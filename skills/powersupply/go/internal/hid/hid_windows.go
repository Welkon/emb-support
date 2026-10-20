//go:build windows

package hid

import (
	"fmt"
	"runtime"
	"strings"
	"unsafe"

	"golang.org/x/sys/windows"
)

const (
	digcfPresent         = 0x00000002
	digcfDeviceInterface = 0x00000010
	genericRead          = 0x80000000
	genericWrite         = 0x40000000
	fileShareRead        = 0x00000001
	fileShareWrite       = 0x00000002
	openExisting         = 3
	fileFlagOverlapped   = 0x40000000
)

var (
	hidGUID = windows.GUID{
		Data1: 0x4D1E55B2, Data2: 0xF16F, Data3: 0x11CF,
		Data4: [8]byte{0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30},
	}
	setupapi           = windows.NewLazySystemDLL("setupapi.dll")
	procGetClassDevs   = setupapi.NewProc("SetupDiGetClassDevsW")
	procEnumInterfaces = setupapi.NewProc("SetupDiEnumDeviceInterfaces")
	procGetDetail      = setupapi.NewProc("SetupDiGetDeviceInterfaceDetailW")
	procDestroy        = setupapi.NewProc("SetupDiDestroyDeviceInfoList")
)

type deviceInterfaceData struct {
	CbSize         uint32
	InterfaceClass windows.GUID
	Flags          uint32
	Reserved       uintptr
}

type winDevice struct {
	h     windows.Handle
	event windows.Handle
	path  string
}

func Open(vid, pid uint16) (Transport, error) {
	hdev, _, err := procGetClassDevs.Call(uintptr(unsafe.Pointer(&hidGUID)), 0, 0,
		digcfPresent|digcfDeviceInterface)
	if windows.Handle(hdev) == windows.InvalidHandle {
		return nil, fmt.Errorf("SetupDiGetClassDevs: %w", err)
	}
	defer procDestroy.Call(hdev)
	want := fmt.Sprintf("vid_%04x&pid_%04x", vid, pid)
	for index := uint32(0); ; index++ {
		var did deviceInterfaceData
		did.CbSize = uint32(unsafe.Sizeof(did))
		r, _, e := procEnumInterfaces.Call(hdev, uintptr(index),
			uintptr(unsafe.Pointer(&hidGUID)), uintptr(unsafe.Pointer(&did)))
		if r == 0 {
			if e == windows.ERROR_NO_MORE_ITEMS {
				break
			}
			return nil, fmt.Errorf("SetupDiEnumDeviceInterfaces: %w", e)
		}
		var required uint32
		procGetDetail.Call(hdev, uintptr(unsafe.Pointer(&did)), 0, 0,
			uintptr(unsafe.Pointer(&required)), 0)
		if required == 0 {
			continue
		}
		buf := make([]byte, required)
		detail := (*struct {
			CbSize     uint32
			DevicePath [1]uint16
		})(unsafe.Pointer(&buf[0]))
		detail.CbSize = uint32(unsafe.Sizeof(*detail))
		r, _, e = procGetDetail.Call(hdev, uintptr(unsafe.Pointer(&did)),
			uintptr(unsafe.Pointer(detail)), uintptr(required), 0, 0)
		if r == 0 {
			continue
		}
		path := windows.UTF16PtrToString((*uint16)(unsafe.Pointer(&buf[4])))
		if !strings.Contains(strings.ToLower(path), want) {
			continue
		}
		handle, err := windows.CreateFile(
			windows.StringToUTF16Ptr(path),
			genericRead|genericWrite,
			fileShareRead|fileShareWrite,
			nil, openExisting, fileFlagOverlapped, 0)
		if err != nil {
			return nil, fmt.Errorf("open %s: %w", path, err)
		}
		event, err := windows.CreateEvent(nil, 1, 0, nil)
		if err != nil {
			windows.CloseHandle(handle)
			return nil, fmt.Errorf("CreateEvent: %w", err)
		}
		return &winDevice{h: handle, event: event, path: path}, nil
	}
	return nil, fmt.Errorf("no HID device with VID %04x PID %04x", vid, pid)
}

func (d *winDevice) Write(p []byte) error {
	// Windows HID requires a report ID prefix. DP100 uses report ID 0.
	if len(p) == 64 {
		p = append([]byte{0}, p...)
	}
	ov := &windows.Overlapped{HEvent: d.event}
	windows.ResetEvent(d.event)
	var done uint32
	err := windows.WriteFile(d.h, p, &done, ov)
	if err == windows.ERROR_IO_PENDING {
		s, _ := windows.WaitForSingleObject(d.event, 1000)
		if s != windows.WAIT_OBJECT_0 {
			windows.CancelIoEx(d.h, ov)
			return fmt.Errorf("HID write timeout")
		}
		err = windows.GetOverlappedResult(d.h, ov, &done, false)
	}
	runtime.KeepAlive(p)
	if err != nil {
		return fmt.Errorf("HID write: %w", err)
	}
	if int(done) != len(p) {
		return fmt.Errorf("short HID write: %d/%d", done, len(p))
	}
	return nil
}

func (d *winDevice) Read(n, timeoutMS int) ([]byte, error) {
	buf := make([]byte, n+1)
	ov := &windows.Overlapped{HEvent: d.event}
	windows.ResetEvent(d.event)
	var done uint32
	err := windows.ReadFile(d.h, buf, &done, ov)
	if err == windows.ERROR_IO_PENDING {
		s, _ := windows.WaitForSingleObject(d.event, uint32(timeoutMS))
		if s != windows.WAIT_OBJECT_0 {
			windows.CancelIoEx(d.h, ov)
			return nil, fmt.Errorf("HID read timeout")
		}
		err = windows.GetOverlappedResult(d.h, ov, &done, false)
	}
	runtime.KeepAlive(buf)
	if err != nil {
		return nil, fmt.Errorf("HID read: %w", err)
	}
	if done == 0 {
		return nil, fmt.Errorf("empty HID report")
	}
	out := buf[:done]
	if len(out) > n && out[0] == 0 {
		out = out[1:]
	}
	return out, nil
}

func (d *winDevice) Close() error {
	if d.event != 0 {
		windows.CloseHandle(d.event)
	}
	return windows.CloseHandle(d.h)
}

func (d *winDevice) Path() string { return d.path }

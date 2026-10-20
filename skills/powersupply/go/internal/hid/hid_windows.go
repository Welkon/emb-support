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
	setupapi           = windows.NewLazySystemDLL("setupapi.dll")
	hidapi             = windows.NewLazySystemDLL("hid.dll")
	procGetHidGuid     = hidapi.NewProc("HidD_GetHidGuid")
	procGetPreparsed   = hidapi.NewProc("HidD_GetPreparsedData")
	procFreePreparsed  = hidapi.NewProc("HidD_FreePreparsedData")
	procGetCaps        = hidapi.NewProc("HidP_GetCaps")
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
	h      windows.Handle
	event  windows.Handle
	path   string
	inLen  int
	outLen int
}

func Paths(vid, pid uint16) ([]string, error) {
	var classGUID windows.GUID
	procGetHidGuid.Call(uintptr(unsafe.Pointer(&classGUID)))
	hdev, _, err := procGetClassDevs.Call(uintptr(unsafe.Pointer(&classGUID)), 0, 0,
		digcfPresent|digcfDeviceInterface)
	if windows.Handle(hdev) == windows.InvalidHandle {
		return nil, fmt.Errorf("SetupDiGetClassDevs: %w", err)
	}
	defer procDestroy.Call(hdev)
	want := fmt.Sprintf("vid_%04x&pid_%04x", vid, pid)
	var paths []string
	for index := uint32(0); ; index++ {
		var did deviceInterfaceData
		did.CbSize = uint32(unsafe.Sizeof(did))
		r, _, e := procEnumInterfaces.Call(hdev, 0,
			uintptr(unsafe.Pointer(&classGUID)), uintptr(index), uintptr(unsafe.Pointer(&did)))
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
		if r, _, _ = procGetDetail.Call(hdev, uintptr(unsafe.Pointer(&did)),
			uintptr(unsafe.Pointer(detail)), uintptr(required), 0, 0); r == 0 {
			continue
		}
		path := windows.UTF16PtrToString((*uint16)(unsafe.Pointer(&buf[4])))
		if strings.Contains(strings.ToLower(path), want) {
			paths = append(paths, path)
		}
	}
	return paths, nil
}

func Open(vid, pid uint16) (Transport, error) {
	paths, err := Paths(vid, pid)
	if err != nil {
		return nil, err
	}
	if len(paths) == 0 {
		return nil, fmt.Errorf("no HID device with VID %04x PID %04x", vid, pid)
	}
	return OpenPath(paths[0])
}

func OpenPath(path string) (Transport, error) {
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
	d := &winDevice{h: handle, event: event, path: path, inLen: 64, outLen: 64}
	var preparsed uintptr
	if r, _, _ := procGetPreparsed.Call(uintptr(handle), uintptr(unsafe.Pointer(&preparsed))); r != 0 {
		var caps [256]byte
		if r, _, _ := procGetCaps.Call(preparsed, uintptr(unsafe.Pointer(&caps[0]))); r != 0 {
			d.inLen = int(uint16(caps[4]) | uint16(caps[5])<<8)
			d.outLen = int(uint16(caps[6]) | uint16(caps[7])<<8)
		}
		procFreePreparsed.Call(preparsed)
	}
	return d, nil
}

func (d *winDevice) Write(p []byte) error {
	if len(p) < 64 {
		p = append(p, make([]byte, 64-len(p))...)
	}
	if d.outLen == len(p)+1 {
		p = append([]byte{0}, p...)
	} else if d.outLen != len(p) {
		return fmt.Errorf("HID output length %d does not match report length %d", len(p), d.outLen)
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
	buf := make([]byte, d.inLen)
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
	if len(out) == n+1 && out[0] == 0 {
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

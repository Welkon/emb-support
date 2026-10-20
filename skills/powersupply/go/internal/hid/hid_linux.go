//go:build linux

package hid

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"golang.org/x/sys/unix"
)

type linuxDevice struct {
	fd   int
	path string
}

// Open finds a hidraw node with the given VID/PID.
func Paths(vid, pid uint16) ([]string, error) {
	matches, _ := filepath.Glob("/sys/class/hidraw/hidraw*/device/uevent")
	var paths []string
	for _, uevent := range matches {
		b, err := os.ReadFile(uevent)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(line, "HID_ID=") {
				continue
			}
			parts := strings.Split(strings.TrimSpace(strings.TrimPrefix(line, "HID_ID=")), ":")
			if len(parts) != 3 {
				continue
			}
			v, err1 := strconv.ParseUint(parts[1], 16, 32)
			p, err2 := strconv.ParseUint(parts[2], 16, 32)
			if err1 != nil || err2 != nil || uint16(v) != vid || uint16(p) != pid {
				continue
			}
			name := filepath.Base(filepath.Dir(filepath.Dir(uevent)))
			paths = append(paths, "/dev/"+name)
			break
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
		return nil, fmt.Errorf("no hidraw device with VID %04x PID %04x", vid, pid)
	}
	return OpenPath(paths[0])
}

func OpenPath(path string) (Transport, error) {
	fd, err := unix.Open(path, unix.O_RDWR|unix.O_CLOEXEC, 0)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", path, err)
	}
	return &linuxDevice{fd: fd, path: path}, nil
}

func (d *linuxDevice) Write(p []byte) error {
	if len(p) < 64 {
		p = append(p, make([]byte, 64-len(p))...)
	}
	n, err := unix.Write(d.fd, p)
	if err != nil {
		return err
	}
	if n != len(p) {
		return fmt.Errorf("short HID write: %d/%d", n, len(p))
	}
	return nil
}

func (d *linuxDevice) Read(n, timeoutMS int) ([]byte, error) {
	fds := []unix.PollFd{{Fd: int32(d.fd), Events: unix.POLLIN}}
	ready, err := unix.Poll(fds, timeoutMS)
	if err != nil {
		return nil, err
	}
	if ready == 0 {
		return nil, fmt.Errorf("HID read timeout")
	}
	buf := make([]byte, n)
	got, err := unix.Read(d.fd, buf)
	if err != nil {
		return nil, err
	}
	if got == 0 {
		return nil, fmt.Errorf("empty HID report")
	}
	return buf[:got], nil
}

func (d *linuxDevice) Close() error { return unix.Close(d.fd) }
func (d *linuxDevice) Path() string { return d.path }

package scpi

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"go.bug.st/serial"
)

type Instrument interface {
	Write(command string) error
	Query(command string) (string, error)
	Close() error
	Resource() string
}

type tcpInstrument struct {
	conn     net.Conn
	resource string
	timeout  time.Duration
}

func (t *tcpInstrument) Write(cmd string) error {
	_, err := io.WriteString(t.conn, cmd+"\n")
	return err
}

func (t *tcpInstrument) Query(cmd string) (string, error) {
	if err := t.Write(cmd); err != nil {
		return "", err
	}
	_ = t.conn.SetReadDeadline(time.Now().Add(t.timeout))
	var b strings.Builder
	buf := make([]byte, 4096)
	for {
		n, err := t.conn.Read(buf)
		if n > 0 {
			b.Write(buf[:n])
			if strings.ContainsRune(b.String(), '\n') {
				break
			}
		}
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() && b.Len() > 0 {
				break
			}
			return strings.TrimSpace(b.String()), err
		}
	}
	return strings.TrimSpace(b.String()), nil
}

func (t *tcpInstrument) Close() error     { return t.conn.Close() }
func (t *tcpInstrument) Resource() string { return t.resource }

type serialInstrument struct {
	port     serial.Port
	resource string
}

func (s *serialInstrument) Write(cmd string) error {
	_, err := s.port.Write([]byte(cmd + "\n"))
	return err
}

func (s *serialInstrument) Query(cmd string) (string, error) {
	if err := s.Write(cmd); err != nil {
		return "", err
	}
	line, err := bufio.NewReader(s.port).ReadString('\n')
	return strings.TrimSpace(line), err
}

func (s *serialInstrument) Close() error     { return s.port.Close() }
func (s *serialInstrument) Resource() string { return s.resource }

type fileInstrument struct {
	f        *os.File
	resource string
}

func (f *fileInstrument) Write(cmd string) error {
	_, err := f.f.Write([]byte(cmd + "\n"))
	return err
}

func (f *fileInstrument) Query(cmd string) (string, error) {
	if err := f.Write(cmd); err != nil {
		return "", err
	}
	line, err := bufio.NewReader(f.f).ReadString('\n')
	return strings.TrimSpace(line), err
}

func (f *fileInstrument) Close() error     { return f.f.Close() }
func (f *fileInstrument) Resource() string { return f.resource }

func parseTCP(resource string) (host string, port int, ok bool) {
	r := strings.TrimSpace(resource)
	if strings.HasPrefix(strings.ToUpper(r), "TCPIP") {
		parts := strings.Split(r, "::")
		if len(parts) >= 3 {
			host = parts[1]
			port, _ = strconv.Atoi(parts[2])
		}
	} else if u, err := url.Parse(r); err == nil && u.Scheme == "tcp" {
		host, port = u.Hostname(), 5025
		if p := u.Port(); p != "" {
			port, _ = strconv.Atoi(p)
		}
	} else if strings.Count(r, ":") == 1 && !strings.HasPrefix(r, "/") {
		host, port = r[:strings.LastIndex(r, ":")], 5025
		if p, err := strconv.Atoi(r[strings.LastIndex(r, ":")+1:]); err == nil {
			port = p
		}
	}
	if port == 0 {
		port = 5025
	}
	return host, port, host != ""
}

func parseSerial(resource string, baud int) (port string, speed int, ok bool) {
	r := strings.TrimSpace(resource)
	if strings.HasPrefix(strings.ToUpper(r), "ASRL") {
		parts := strings.Split(r, "::")
		if len(parts) >= 2 {
			port = parts[1]
			speed = baud
			if len(parts) >= 3 {
				if n, err := strconv.Atoi(parts[2]); err == nil {
					speed = n
				}
			}
			return port, speed, port != ""
		}
	}
	if u, err := url.Parse(r); err == nil && u.Scheme == "serial" {
		port = u.Host
		if q := u.Query().Get("baud"); q != "" {
			speed, _ = strconv.Atoi(q)
		}
		if speed == 0 {
			speed = baud
		}
		return port, speed, port != ""
	}
	if strings.HasPrefix(r, "/dev/tty") || strings.HasPrefix(strings.ToUpper(r), "COM") {
		return r, baud, true
	}
	return "", 0, false
}

// Open opens a TCPIP, ASRL/serial, or Linux USBTMC resource.
func Dial(resource string, timeout time.Duration, baud int) (Instrument, error) {
	if timeout <= 0 {
		timeout = 3 * time.Second
	}
	if baud == 0 {
		baud = 9600
	}
	if host, port, ok := parseTCP(resource); ok {
		conn, err := net.DialTimeout("tcp", net.JoinHostPort(host, strconv.Itoa(port)), timeout)
		if err != nil {
			return nil, fmt.Errorf("connect %s:%d: %w", host, port, err)
		}
		return &tcpInstrument{conn: conn, resource: resource, timeout: timeout}, nil
	}
	if port, speed, ok := parseSerial(resource, baud); ok {
		p, err := serial.Open(port, &serial.Mode{BaudRate: speed})
		if err != nil {
			return nil, fmt.Errorf("open serial %s: %w", port, err)
		}
		_ = p.SetReadTimeout(timeout)
		return &serialInstrument{port: p, resource: resource}, nil
	}
	if strings.HasPrefix(resource, "/dev/usbtmc") {
		f, err := os.OpenFile(resource, os.O_RDWR, 0)
		if err != nil {
			return nil, fmt.Errorf("open %s: %w", resource, err)
		}
		return &fileInstrument{f: f, resource: resource}, nil
	}
	return nil, fmt.Errorf("unsupported resource %q; use TCPIP::host::5025::SOCKET, ASRL::COM3::9600, /dev/usbtmc0, or serial:/dev/ttyUSB0?baud=9600", resource)
}

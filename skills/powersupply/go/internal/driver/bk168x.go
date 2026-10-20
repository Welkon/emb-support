package driver

import (
	"bufio"
	"fmt"
	"strconv"
	"strings"
	"time"

	"go.bug.st/serial"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/config"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/psu"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

type bk168xDevice struct {
	port       serial.Port
	reader     *bufio.Reader
	currentDec int
	ovp, ocp   float64
}

func (d *bk168xDevice) cmd(command string) ([]string, error) {
	_ = d.port.ResetInputBuffer()
	if _, err := d.port.Write([]byte(command + "\r")); err != nil {
		return nil, err
	}
	deadline := time.Now().Add(3 * time.Second)
	var lines []string
	for time.Now().Before(deadline) {
		line, err := d.reader.ReadString('\r')
		line = strings.TrimSpace(line)
		if line == "OK" {
			return lines, nil
		}
		if line != "" {
			lines = append(lines, line)
		}
		if err != nil {
			break
		}
	}
	return nil, fmt.Errorf("no OK from supply for %q", command)
}

func (d *bk168xDevice) set(prefix string, value float64, decimals int) error {
	scale := 1
	for i := 0; i < decimals; i++ {
		scale *= 10
	}
	_, err := d.cmd(fmt.Sprintf("%s%0*d", prefix, 3+decimals, int(value*float64(scale)+0.5)))
	return err
}

func (d *bk168xDevice) settings() (float64, float64) {
	lines, err := d.cmd("GETS")
	if err != nil || len(lines) == 0 || len(lines[0]) < 4 {
		return 0, 0
	}
	v, _ := strconv.Atoi(lines[0][0:3])
	i, _ := strconv.Atoi(lines[0][3:])
	return float64(v) / 10, float64(i) / float64(pow10(d.currentDec))
}

func pow10(n int) int {
	x := 1
	for i := 0; i < n; i++ {
		x *= 10
	}
	return x
}

func (d *bk168xDevice) display() (float64, float64, string) {
	lines, err := d.cmd("GETD")
	if err != nil || len(lines) == 0 || len(lines[0]) < 9 {
		return 0, 0, ""
	}
	raw := lines[0]
	v, _ := strconv.Atoi(raw[0:4])
	i, _ := strconv.Atoi(raw[4:8])
	return float64(v) / 100, float64(i) / 100, raw[8:9]
}

func (d *bk168xDevice) Close() error { return d.port.Close() }
func (d *bk168xDevice) Measurement() (psu.Measurement, error) {
	v, i, _ := d.display()
	return psu.Measurement{Voltage: v, Current: i, Power: v * i}, nil
}
func (d *bk168xDevice) Status() (byte, byte) {
	_, _, state := d.display()
	if state == "1" {
		return 0, 0
	}
	return 2, 0
}
func (d *bk168xDevice) Setpoints() (float64, float64) { return d.settings() }
func (d *bk168xDevice) OutputOn() bool {
	_, _, state := d.display()
	return state == "1"
}
func (d *bk168xDevice) SetVoltage(v float64) error { return d.set("VOLT", v, 1) }
func (d *bk168xDevice) SetCurrent(a float64) error { return d.set("CURR", a, d.currentDec) }
func (d *bk168xDevice) SetOutput(on bool) error {
	if on {
		_, err := d.cmd("SOUT0")
		return err
	}
	_, err := d.cmd("SOUT1")
	return err
}
func (d *bk168xDevice) SetOVP(v float64) error         { d.ovp = v; return d.set("SOVP", v, 1) }
func (d *bk168xDevice) SetOCP(a float64) error         { d.ocp = a; return d.set("SOCP", a, d.currentDec) }
func (d *bk168xDevice) Protection() (float64, float64) { return d.ovp, d.ocp }
func (d *bk168xDevice) Limits() (float64, float64)     { return 30, 5 }

func openBK168x(port string, decimals int) (*server.Unit, error) {
	if decimals <= 0 {
		decimals = 1
	}
	p, err := serial.Open(port, &serial.Mode{BaudRate: 9600})
	if err != nil {
		return nil, err
	}
	_ = p.SetReadTimeout(3 * time.Second)
	d := &bk168xDevice{port: p, reader: bufio.NewReader(p), currentDec: decimals}
	caps := server.Capabilities{OVP: true, OCP: true, OutputState: true}
	return &server.Unit{ID: "bk168x:" + port, Name: "B&K 168x", Family: "bk168x",
		IDN: "B&K,168x," + port + ",serial", Model: "168x", Serial: port, Channels: []int{1},
		Caps: caps, Limits: server.Limits{MaxVoltage: 30, MaxCurrent: 5, MaxOVP: 30, MaxOCP: 5, MaxPower: 150}, Dev: d}, nil
}

type bk168xDriver struct{}

func init()                       { Register(bk168xDriver{}) }
func (bk168xDriver) Name() string { return "bk168x" }
func (bk168xDriver) Discover() ([]Device, error) {
	cfg := config.Load()
	if cfg.Family != "bk168x" || cfg.SerialPort == "" {
		return nil, nil
	}
	return []Device{{Driver: "bk168x", Key: cfg.SerialPort, ID: "bk168x:" + cfg.SerialPort,
		Name: "B&K 168x", Family: "bk168x", Model: "168x", Serial: cfg.SerialPort, Address: cfg.SerialPort}}, nil
}
func (bk168xDriver) Open(dev Device) (*server.Unit, error) {
	return openBK168x(dev.Address, config.Load().CurrentDecimals)
}

// OpenBK168x opens a B&K 168x supply on a serial port.
func OpenBK168x(port string, decimals int) (*server.Unit, error) { return openBK168x(port, decimals) }

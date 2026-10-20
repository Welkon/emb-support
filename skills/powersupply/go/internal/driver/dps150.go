package driver

import (
	"encoding/binary"
	"fmt"
	"math"
	"time"

	"go.bug.st/serial"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/config"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/psu"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

const (
	dpsH2D        = 0xF1
	dpsD2H        = 0xF0
	dpsCmdRead    = 0xA1
	dpsCmdWrite   = 0xB1
	dpsCmdSession = 0xC1
)

type dps150Device struct {
	port     serial.Port
	maxV     float64
	maxI     float64
	ovp, ocp float64
	idn      string
	resource string
}

func checksum(reg byte, data []byte) byte {
	sum := int(reg) + len(data)
	for _, b := range data {
		sum += int(b)
	}
	return byte(sum)
}

func (d *dps150Device) packet(cmd, reg byte, data []byte) (byte, []byte, error) {
	body := []byte{dpsH2D, cmd, reg, byte(len(data))}
	body = append(body, data...)
	body = append(body, checksum(reg, data))
	if _, err := d.port.Write(body); err != nil {
		return 0, nil, err
	}
	header := make([]byte, 4)
	if _, err := readFull(d.port, header); err != nil {
		return 0, nil, err
	}
	if header[0] != dpsD2H {
		return 0, nil, fmt.Errorf("unexpected DPS-150 header 0x%02x", header[0])
	}
	n := int(header[3])
	payload := make([]byte, n+1)
	if _, err := readFull(d.port, payload); err != nil {
		return 0, nil, err
	}
	if checksum(header[2], payload[:n]) != payload[n] {
		return 0, nil, fmt.Errorf("DPS-150 checksum error")
	}
	return header[2], payload[:n], nil
}

func readFull(p serial.Port, b []byte) (int, error) {
	got := 0
	for got < len(b) {
		n, err := p.Read(b[got:])
		got += n
		if err != nil {
			return got, err
		}
		if n == 0 {
			return got, fmt.Errorf("short read")
		}
	}
	return got, nil
}

func (d *dps150Device) writeFloat(reg byte, v float64) error {
	b := make([]byte, 4)
	binary.LittleEndian.PutUint32(b, math.Float32bits(float32(v)))
	_, _, err := d.packet(dpsCmdWrite, reg, b)
	return err
}

func (d *dps150Device) readFloat(reg byte) float64 {
	_, data, err := d.packet(dpsCmdRead, reg, nil)
	if err != nil || len(data) < 4 {
		return 0
	}
	return float64(math.Float32frombits(binary.LittleEndian.Uint32(data[:4])))
}

func (d *dps150Device) readString(reg byte) string {
	_, data, err := d.packet(dpsCmdRead, reg, nil)
	if err != nil {
		return ""
	}
	for i, b := range data {
		if b == 0 {
			return string(data[:i])
		}
	}
	return string(data)
}

func (d *dps150Device) Close() error { return d.port.Close() }

func (d *dps150Device) Measurement() (psu.Measurement, error) {
	_, data, err := d.packet(dpsCmdRead, 0xC3, nil)
	if err != nil {
		return psu.Measurement{}, err
	}
	if len(data) < 12 {
		return psu.Measurement{}, fmt.Errorf("short DPS-150 measurement")
	}
	return psu.Measurement{
		Voltage: float64(math.Float32frombits(binary.LittleEndian.Uint32(data[0:4]))),
		Current: float64(math.Float32frombits(binary.LittleEndian.Uint32(data[4:8]))),
		Power:   float64(math.Float32frombits(binary.LittleEndian.Uint32(data[8:12]))),
	}, nil
}

func (d *dps150Device) Status() (byte, byte) {
	on := d.OutputOn()
	if on {
		return 0, 0
	}
	return 2, 0
}

func (d *dps150Device) Setpoints() (float64, float64) { return d.readFloat(0xC1), d.readFloat(0xC2) }
func (d *dps150Device) OutputOn() bool {
	_, data, err := d.packet(dpsCmdRead, 0xDB, nil)
	return err == nil && len(data) > 0 && data[0] != 0
}
func (d *dps150Device) SetVoltage(v float64) error {
	if v > d.maxV+1e-9 {
		return fmt.Errorf("DPS-150 max voltage is %.2f V", d.maxV)
	}
	return d.writeFloat(0xC1, v)
}
func (d *dps150Device) SetCurrent(a float64) error {
	if a > d.maxI+1e-9 {
		return fmt.Errorf("DPS-150 max current is %.2f A", d.maxI)
	}
	return d.writeFloat(0xC2, a)
}
func (d *dps150Device) SetOutput(on bool) error {
	b := byte(0)
	if on {
		b = 1
	}
	_, _, err := d.packet(dpsCmdWrite, 0xDB, []byte{b})
	return err
}
func (d *dps150Device) SetOVP(v float64) error         { d.ovp = v; return d.writeFloat(0xD1, v) }
func (d *dps150Device) SetOCP(a float64) error         { d.ocp = a; return d.writeFloat(0xD2, a) }
func (d *dps150Device) Protection() (float64, float64) { return d.ovp, d.ocp }
func (d *dps150Device) Limits() (float64, float64)     { return d.maxV, d.maxI }

func openDPS150(port string, baud int) (*server.Unit, error) {
	if baud == 0 {
		baud = 115200
	}
	p, err := serial.Open(port, &serial.Mode{BaudRate: baud})
	if err != nil {
		return nil, err
	}
	_ = p.SetReadTimeout(500 * time.Millisecond)
	_ = p.SetRTS(true)
	d := &dps150Device{port: p, maxV: 30, maxI: 5, resource: port}
	if _, _, err := d.packet(dpsCmdSession, 0x00, []byte{1}); err != nil {
		p.Close()
		return nil, err
	}
	d.idn = fmt.Sprintf("FNIRSI,DPS-150,%s,%s", d.readString(0xDE), d.readString(0xE0))
	d.maxV, d.maxI = d.readFloat(0xE2), d.readFloat(0xE3)
	if d.maxV <= 0 {
		d.maxV = 30
	}
	if d.maxI <= 0 {
		d.maxI = 5
	}
	caps := server.Capabilities{Power: true, OVP: true, OCP: true, OutputState: true}
	return &server.Unit{ID: "dps150:" + port, Name: "FNIRSI DPS-150", Family: "dps150", IDN: d.idn,
		Model: "DPS-150", Serial: port, Channels: []int{1}, Caps: caps,
		Limits: server.Limits{MaxVoltage: d.maxV, MaxCurrent: d.maxI, MaxOVP: d.maxV, MaxOCP: d.maxI, MaxPower: d.maxV * d.maxI},
		Dev:    d}, nil
}

type dps150Driver struct{}

func init()                       { Register(dps150Driver{}) }
func (dps150Driver) Name() string { return "dps150" }
func (dps150Driver) Discover() ([]Device, error) {
	cfg := config.Load()
	if cfg.Family != "dps150" || cfg.SerialPort == "" {
		return nil, nil
	}
	return []Device{{Driver: "dps150", Key: cfg.SerialPort, ID: "dps150:" + cfg.SerialPort,
		Name: "FNIRSI DPS-150", Family: "dps150", Model: "DPS-150", Serial: cfg.SerialPort, Address: cfg.SerialPort}}, nil
}
func (dps150Driver) Open(dev Device) (*server.Unit, error) { return openDPS150(dev.Address, 0) }

// OpenDPS150 opens an FNIRSI DPS-150 on a serial port.
func OpenDPS150(port string, baud int) (*server.Unit, error) { return openDPS150(port, baud) }

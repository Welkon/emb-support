package dp100

import (
	"fmt"
	"sync"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/hid"
)

const (
	MaxVoltage = 30.0
	MaxCurrent = 5.0
	MaxOVP     = 30.5
	MaxOCP     = 5.05
)

type Info struct {
	Model      string  `json:"model"`
	Hardware   float64 `json:"hardware"`
	App        float64 `json:"app"`
	Bootloader float64 `json:"bootloader"`
	SerialHex  string  `json:"serial_hex"`
}

type Status struct {
	OutputMode string `json:"output_mode"`
	WorkState  byte   `json:"work_state"`
}

type Measurement struct {
	Voltage      float64 `json:"voltage"`
	Current      float64 `json:"current"`
	Power        float64 `json:"power"`
	InputVoltage float64 `json:"input_voltage"`
	Temperature  float64 `json:"temperature"`
}

type Snapshot struct {
	Output      string      `json:"output"`
	VSet        float64     `json:"vset"`
	ISet        float64     `json:"iset"`
	Measurement Measurement `json:"measurement"`
	Status      Status      `json:"status"`
	MaxVoltage  float64     `json:"max_voltage"`
}

type Device struct {
	mu       sync.Mutex
	t        hid.Transport
	Info     Info
	V        float64
	I        float64
	OVP      float64
	OCP      float64
	Out      bool
	MaxV     float64
	MaxI     float64
	lastMode byte
	lastWork byte
}

func Open(t hid.Transport) (*Device, error) {
	d := &Device{t: t, MaxV: MaxVoltage, MaxI: MaxCurrent}
	info, err := d.readInfo()
	if err != nil {
		return nil, err
	}
	d.Info = info
	basic, err := d.readBasic()
	if err != nil {
		return nil, err
	}
	if basic.VoMaxMV >= 1000 {
		d.MaxV = float64(basic.VoMaxMV) / 1000
		if d.MaxV > MaxVoltage {
			d.MaxV = MaxVoltage
		}
	}
	s, err := d.readSettings()
	if err != nil {
		return nil, err
	}
	d.V, d.I, d.OVP, d.OCP = s.VSetV, s.ISetA, s.OVPV, s.OCPA
	d.Out = s.State == 1
	d.lastMode, d.lastWork = basic.OutMode, basic.WorkState
	return d, nil
}

func (d *Device) Close() error { return d.t.Close() }

func (d *Device) DeviceInfo() Info              { return d.Info }
func (d *Device) Setpoints() (float64, float64) { return d.V, d.I }
func (d *Device) OutputOn() bool                { return d.Out }
func (d *Device) Limits() (maxV, maxI float64)  { return d.MaxV, d.MaxI }

func (d *Device) Status() (mode, work byte) {
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.lastMode, d.lastWork
}

func (d *Device) exchange(op byte, payload []byte) ([]byte, error) {
	if err := d.t.Write(Encode(op, payload)); err != nil {
		return nil, err
	}
	var last byte
	for attempt := 0; attempt < 4; attempt++ {
		raw, err := d.t.Read(64, 1000)
		if err != nil {
			return nil, err
		}
		f, err := Decode(raw)
		if err != nil {
			return nil, err
		}
		if f.Op == op {
			return f.Payload, nil
		}
		last = f.Op // unsolicited Basic frame, read the next report
	}
	return nil, fmt.Errorf("unexpected opcode 0x%02x, want 0x%02x", last, op)
}

func (d *Device) readInfo() (Info, error) {
	p, err := d.exchange(OpInfo, nil)
	if err != nil {
		return Info{}, err
	}
	if len(p) < 35 {
		return Info{}, fmt.Errorf("info payload too short: %d", len(p))
	}
	return Info{
		Model:      string(trimNul(p[0:15])),
		Hardware:   float64(uint16(p[17])<<8|uint16(p[16])) / 10,
		App:        float64(uint16(p[19])<<8|uint16(p[18])) / 10,
		Bootloader: float64(uint16(p[21])<<8|uint16(p[20])) / 10,
		SerialHex:  fmt.Sprintf("%x", p[24:35]),
	}, nil
}

func trimNul(b []byte) []byte {
	for i, v := range b {
		if v == 0 {
			return b[:i]
		}
	}
	return b
}

func (d *Device) readBasic() (BasicInfo, error) {
	p, err := d.exchange(OpBasic, nil)
	if err != nil {
		return BasicInfo{}, err
	}
	b, err := ParseBasic(p)
	if err != nil {
		return BasicInfo{}, err
	}
	d.lastMode, d.lastWork = b.OutMode, b.WorkState
	return b, nil
}

func (d *Device) readSettings() (Settings, error) {
	p, err := d.exchange(OpSet, []byte{IndexRead})
	if err != nil {
		return Settings{}, err
	}
	return ParseSettings(p)
}

func (d *Device) applyOutput() error {
	if d.V < 0 || d.V > d.MaxV+1e-9 {
		return fmt.Errorf("voltage %.3f V outside 0..%.2f V", d.V, d.MaxV)
	}
	if d.I < 0 || d.I > d.MaxI+1e-9 {
		return fmt.Errorf("current %.3f A outside 0..%.2f A", d.I, d.MaxI)
	}
	state := byte(0)
	if d.Out {
		state = 1
	}
	_, err := d.exchange(OpSet, OutputPayload(state, d.V, d.I))
	return err
}

func (d *Device) applyProtection() error {
	if d.OVP < 0 || d.OVP > MaxOVP+1e-9 {
		return fmt.Errorf("OVP %.3f V outside 0..%.2f V", d.OVP, MaxOVP)
	}
	if d.OCP < 0 || d.OCP > MaxOCP+1e-9 {
		return fmt.Errorf("OCP %.3f A outside 0..%.2f A", d.OCP, MaxOCP)
	}
	state := byte(0)
	if d.Out {
		state = 1
	}
	_, err := d.exchange(OpSet, ProtectPayload(state, d.V, d.I, d.OVP, d.OCP))
	return err
}

func (d *Device) SetVoltage(v float64) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	old := d.V
	d.V = v
	if err := d.applyOutput(); err != nil {
		d.V = old
		return err
	}
	return nil
}

func (d *Device) SetCurrent(a float64) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	old := d.I
	d.I = a
	if err := d.applyOutput(); err != nil {
		d.I = old
		return err
	}
	return nil
}

func (d *Device) SetOutput(on bool) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	old := d.Out
	d.Out = on
	if err := d.applyOutput(); err != nil {
		d.Out = old
		return err
	}
	return nil
}

func (d *Device) SetOVP(v float64) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	old := d.OVP
	d.OVP = v
	if err := d.applyProtection(); err != nil {
		d.OVP = old
		return err
	}
	return nil
}

func (d *Device) SetOCP(a float64) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	old := d.OCP
	d.OCP = a
	if err := d.applyProtection(); err != nil {
		d.OCP = old
		return err
	}
	return nil
}

func (d *Device) Measurement() (Measurement, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	b, err := d.readBasic()
	if err != nil {
		return Measurement{}, err
	}
	return Measurement{
		Voltage:      float64(b.VoutMV) / 1000,
		Current:      float64(b.IoutMA) / 1000,
		Power:        float64(b.VoutMV) * float64(b.IoutMA) / 1e6,
		InputVoltage: float64(b.VinMV) / 1000,
		Temperature:  float64(b.Temp1Deci) / 10,
	}, nil
}

func (d *Device) Snapshot() (Snapshot, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	b, err := d.readBasic()
	if err != nil {
		return Snapshot{}, err
	}
	s, err := d.readSettings()
	if err != nil {
		return Snapshot{}, err
	}
	d.V, d.I, d.OVP, d.OCP = s.VSetV, s.ISetA, s.OVPV, s.OCPA
	d.Out = s.State == 1
	mode := map[byte]string{0: "CC", 1: "CV", 2: "OFF"}[b.OutMode]
	if mode == "" {
		mode = fmt.Sprintf("%d", b.OutMode)
	}
	out := "OFF"
	if s.State == 1 {
		out = "ON"
	}
	return Snapshot{
		Output: out, VSet: s.VSetV, ISet: s.ISetA,
		Measurement: Measurement{
			Voltage:      float64(b.VoutMV) / 1000,
			Current:      float64(b.IoutMA) / 1000,
			Power:        float64(b.VoutMV) * float64(b.IoutMA) / 1e6,
			InputVoltage: float64(b.VinMV) / 1000,
			Temperature:  float64(b.Temp1Deci) / 10,
		},
		Status:     Status{OutputMode: mode, WorkState: b.WorkState},
		MaxVoltage: d.MaxV,
	}, nil
}

// ReadSample reads only the basic frame for a high-rate sample.
func (d *Device) ReadSample() (Measurement, error) {
	return d.Measurement()
}

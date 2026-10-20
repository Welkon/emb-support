package scpi

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/psu"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

type Device struct {
	inst     Instrument
	dialect  *Dialect
	ch       int
	idn      string
	resource string
	limits   server.Limits
	ovp      float64
	ocp      float64
}

func queryFloat(inst Instrument, cmd string) float64 {
	if cmd == "" {
		return 0
	}
	text, err := inst.Query(cmd)
	if err != nil {
		return 0
	}
	v, _ := strconv.ParseFloat(strings.TrimSpace(text), 64)
	return v
}

func (d *Device) selectChannel() error {
	if d.dialect.Select == nil {
		return nil
	}
	return d.inst.Write(d.dialect.Select(d.ch))
}

func (d *Device) Close() error { return d.inst.Close() }

func (d *Device) Measurement() (psu.Measurement, error) {
	if err := d.selectChannel(); err != nil {
		return psu.Measurement{}, err
	}
	m := psu.Measurement{
		Voltage: queryFloat(d.inst, d.dialect.MeasureV(d.ch)),
		Current: queryFloat(d.inst, d.dialect.MeasureI(d.ch)),
	}
	if d.dialect.MeasureP != nil {
		m.Power = queryFloat(d.inst, d.dialect.MeasureP(d.ch))
	}
	if m.Power == 0 {
		m.Power = m.Voltage * m.Current
	}
	return m, nil
}

func (d *Device) Status() (mode, work byte) {
	on, err := d.outputOn()
	if err != nil {
		return 2, 0
	}
	if on {
		return 0, 0
	}
	return 2, 0
}

func (d *Device) Setpoints() (float64, float64) {
	_ = d.selectChannel()
	return queryFloat(d.inst, d.dialect.GetV(d.ch)), queryFloat(d.inst, d.dialect.GetI(d.ch))
}

func (d *Device) OutputOn() bool {
	on, err := d.outputOn()
	return err == nil && on
}

func (d *Device) outputOn() (bool, error) {
	if d.dialect.OutputRead == nil {
		return false, fmt.Errorf("output readback not supported")
	}
	if err := d.selectChannel(); err != nil {
		return false, err
	}
	text, err := d.inst.Query(d.dialect.OutputRead(d.ch))
	if err != nil {
		return false, err
	}
	u := strings.ToUpper(strings.TrimSpace(text))
	return u == "ON" || u == "1" || u == "1.0", nil
}

func (d *Device) SetVoltage(v float64) error {
	if err := d.selectChannel(); err != nil {
		return err
	}
	return d.inst.Write(d.dialect.SetV(d.ch, v))
}

func (d *Device) SetCurrent(a float64) error {
	if err := d.selectChannel(); err != nil {
		return err
	}
	return d.inst.Write(d.dialect.SetI(d.ch, a))
}

func (d *Device) SetOutput(on bool) error {
	if err := d.selectChannel(); err != nil {
		return err
	}
	return d.inst.Write(d.dialect.Output(d.ch, on))
}

func (d *Device) SetOVP(v float64) error {
	if d.dialect.OVP == nil {
		return fmt.Errorf("OVP not supported by %s", d.dialect.Name)
	}
	if err := d.selectChannel(); err != nil {
		return err
	}
	if err := d.inst.Write(d.dialect.OVP(d.ch, v)); err != nil {
		return err
	}
	d.ovp = v
	return nil
}

func (d *Device) SetOCP(a float64) error {
	if d.dialect.OCP == nil {
		return fmt.Errorf("OCP not supported by %s", d.dialect.Name)
	}
	if err := d.selectChannel(); err != nil {
		return err
	}
	if err := d.inst.Write(d.dialect.OCP(d.ch, a)); err != nil {
		return err
	}
	d.ocp = a
	return nil
}

func (d *Device) Protection() (float64, float64) { return d.ovp, d.ocp }
func (d *Device) Limits() (float64, float64)     { return d.limits.MaxVoltage, d.limits.MaxCurrent }
func (d *Device) Resource() string               { return d.resource }
func (d *Device) IDN() string                    { return d.idn }

// RawSCPI exposes raw SCPI for the scpi/query/write commands.
type RawSCPI interface {
	RawQuery(string) (string, error)
	RawWrite(string) error
}

func (d *Device) RawQuery(cmd string) (string, error) { return d.inst.Query(cmd) }
func (d *Device) RawWrite(cmd string) error           { return d.inst.Write(cmd) }

type OpenOptions struct {
	Channel    int
	Family     string
	Timeout    time.Duration
	Baud       int
	MaxVoltage float64
	MaxCurrent float64
}

// Open connects to one SCPI resource and returns one server unit per selected channel.
func Open(resource string, opt OpenOptions) (*server.Unit, error) {
	if opt.Channel == 0 {
		opt.Channel = 1
	}
	if opt.Timeout == 0 {
		opt.Timeout = 3 * time.Second
	}
	if opt.Baud == 0 {
		opt.Baud = 9600
	}
	if opt.MaxVoltage == 0 {
		opt.MaxVoltage = 30
	}
	if opt.MaxCurrent == 0 {
		opt.MaxCurrent = 5
	}
	inst, err := Dial(resource, opt.Timeout, opt.Baud)
	if err != nil {
		return nil, err
	}
	idn, err := inst.Query("*IDN?")
	if err != nil {
		inst.Close()
		return nil, fmt.Errorf("*IDN? failed: %w", err)
	}
	name := opt.Family
	if name == "" {
		name = detectFamily(idn)
	}
	dialect, err := byName(name)
	if err != nil {
		inst.Close()
		return nil, err
	}
	if dialect == nil {
		dialect = genericDialect()
	}
	dialect = normalizeDialect(dialect)
	valid := false
	for _, ch := range dialect.Channels {
		if ch == opt.Channel {
			valid = true
			break
		}
	}
	if !valid {
		inst.Close()
		return nil, fmt.Errorf("channel %d not available; channels are %v", opt.Channel, dialect.Channels)
	}
	id := resource
	if len(dialect.Channels) > 1 {
		id = fmt.Sprintf("%s#%d", resource, opt.Channel)
	}
	parts := strings.Split(idn, ",")
	model := idn
	if len(parts) > 1 && strings.TrimSpace(parts[1]) != "" {
		model = parts[1]
	}
	if len(dialect.Channels) > 1 {
		model = fmt.Sprintf("%s CH%d", model, opt.Channel)
	}
	serial := ""
	if len(parts) > 2 {
		serial = parts[2]
	}
	dev := &Device{inst: inst, dialect: dialect, ch: opt.Channel, idn: idn, resource: resource,
		limits: server.Limits{MaxVoltage: opt.MaxVoltage, MaxCurrent: opt.MaxCurrent,
			MaxOVP: opt.MaxVoltage, MaxOCP: opt.MaxCurrent, MaxPower: opt.MaxVoltage * opt.MaxCurrent}}
	caps := server.Capabilities{
		Power: dialect.MeasureP != nil, OVP: dialect.OVP != nil, OCP: dialect.OCP != nil,
		OutputState: dialect.OutputRead != nil,
	}
	return &server.Unit{
		ID: id, Name: model, Family: dialect.Name, IDN: idn, Model: model, Serial: serial,
		Channels: []int{opt.Channel}, Caps: caps, Limits: dev.limits, Dev: dev,
	}, nil
}

// Channels returns the channel numbers for a resource without keeping it open.
func Channels(resource, family string, timeout time.Duration, baud int) ([]int, string, error) {
	inst, err := Dial(resource, timeout, baud)
	if err != nil {
		return nil, "", err
	}
	defer inst.Close()
	idn, err := inst.Query("*IDN?")
	if err != nil {
		return nil, "", err
	}
	name := family
	if name == "" {
		name = detectFamily(idn)
	}
	d, err := byName(name)
	if err != nil {
		return nil, idn, err
	}
	if d == nil {
		d = genericDialect()
	}
	d = normalizeDialect(d)
	return d.Channels, idn, nil
}

// Probe identifies a resource and returns its dialect, IDN, model, serial, and channels.
func Probe(resource, family string, timeout time.Duration, baud int) (string, string, string, string, []int, error) {
	inst, err := Dial(resource, timeout, baud)
	if err != nil {
		return "", "", "", "", nil, err
	}
	defer inst.Close()
	idn, err := inst.Query("*IDN?")
	if err != nil {
		return "", "", "", "", nil, fmt.Errorf("*IDN? failed: %w", err)
	}
	name := family
	if name == "" {
		name = detectFamily(idn)
	}
	d, err := byName(name)
	if err != nil {
		return "", "", "", "", nil, err
	}
	if d == nil {
		d = genericDialect()
	}
	d = normalizeDialect(d)
	parts := strings.Split(idn, ",")
	model, serial := idn, ""
	if len(parts) > 1 && strings.TrimSpace(parts[1]) != "" {
		model = parts[1]
	}
	if len(parts) > 2 {
		serial = parts[2]
	}
	return d.Name, idn, model, serial, d.Channels, nil
}

package driver

import (
	"fmt"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/dp100"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/hid"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

const (
	dp100VID = 0x2E3C
	dp100PID = 0xAF01
)

type dp100Driver struct{}

func init() { Register(dp100Driver{}) }

func (dp100Driver) Name() string { return "dp100" }

func (dp100Driver) Discover() ([]Device, error) {
	paths, err := hid.Paths(dp100VID, dp100PID)
	if err != nil {
		return nil, err
	}
	var out []Device
	for _, path := range paths {
		t, err := hid.OpenPath(path)
		if err != nil {
			continue
		}
		d, err := dp100.Open(t)
		if err != nil {
			t.Close()
			continue
		}
		info := d.Info
		d.Close()
		id := info.SerialHex
		if id == "" {
			id = path
		}
		out = append(out, Device{
			Driver: "dp100", Key: path, ID: id, Name: info.Model,
			Family: "dp100", Model: info.Model, Serial: info.SerialHex, Address: path,
		})
	}
	return out, nil
}

func (dp100Driver) Open(dev Device) (*server.Unit, error) {
	t, err := hid.OpenPath(dev.Key)
	if err != nil {
		return nil, err
	}
	d, err := dp100.Open(t)
	if err != nil {
		t.Close()
		return nil, err
	}
	info := d.Info
	maxV, maxI := d.Limits()
	id := info.SerialHex
	if id == "" {
		id = dev.Key
	}
	return &server.Unit{
		ID: id, Name: info.Model, Family: "dp100",
		IDN:   fmt.Sprintf("ALIENTEK,DP100,%s,%.1f", info.SerialHex, info.App),
		Model: info.Model, Serial: info.SerialHex,
		Hardware: fmt.Sprintf("%.1f", info.Hardware),
		Firmware: fmt.Sprintf("%.1f", info.App),
		Channels: []int{1},
		Caps: server.Capabilities{
			Power: true, OVP: true, OCP: true,
			OutputState: true, InputVoltage: true, Temperature: true,
		},
		Limits: server.Limits{
			MaxVoltage: maxV, MaxCurrent: maxI,
			MaxOVP: dp100.MaxOVP, MaxOCP: dp100.MaxOCP, MaxPower: 100,
		},
		Dev: d,
	}, nil
}

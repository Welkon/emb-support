// Package driver contains the device-driver registry. Each supported model
// implements Driver once. The server and the UI do not know model details.
package driver

import (
	"errors"
	"fmt"
	"sort"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

// Device is a discovered endpoint before it is opened.
type Device struct {
	Driver  string `json:"driver"`
	Key     string `json:"key"`
	ID      string `json:"id"`
	Name    string `json:"name"`
	Family  string `json:"family"`
	Model   string `json:"model"`
	Serial  string `json:"serial"`
	Address string `json:"address"`
}

// Driver discovers and opens one family of power supplies.
type Driver interface {
	Name() string
	Discover() ([]Device, error)
	Open(Device) (*server.Unit, error)
}

// Found pairs a discovered device with the driver that owns it.
type Found struct {
	Driver Driver
	Device Device
}

var registry []Driver

// Register adds a driver. Drivers register themselves from init.
func Register(d Driver) {
	if d == nil {
		return
	}
	registry = append(registry, d)
	sort.SliceStable(registry, func(i, j int) bool { return registry[i].Name() < registry[j].Name() })
}

// All returns the registered drivers.
func All() []Driver { return append([]Driver(nil), registry...) }

// Discover asks every driver for its devices. A failure in one driver does not
// hide devices from the other drivers.
func Discover() ([]Found, error) {
	var out []Found
	var errs []error
	for _, d := range registry {
		devices, err := d.Discover()
		if err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", d.Name(), err))
			continue
		}
		for _, dev := range devices {
			if dev.Driver == "" {
				dev.Driver = d.Name()
			}
			out = append(out, Found{Driver: d, Device: dev})
		}
	}
	return out, errors.Join(errs...)
}

// Open opens a discovered device.
func Open(f Found) (*server.Unit, error) {
	if f.Driver == nil {
		return nil, fmt.Errorf("device has no driver")
	}
	return f.Driver.Open(f.Device)
}

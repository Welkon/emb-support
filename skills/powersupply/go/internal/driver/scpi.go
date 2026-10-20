package driver

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/config"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/scpi"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

type scpiDriver struct{}

func init() { Register(scpiDriver{}) }

func (scpiDriver) Name() string { return "scpi" }

func (scpiDriver) Discover() ([]Device, error) {
	cfg := config.Load()
	timeout := time.Duration(cfg.Timeout * float64(time.Second))
	var out []Device
	var lastErr error
	for _, resource := range cfg.Endpoints() {
		family, _, model, serial, channels, err := scpi.Probe(resource, cfg.Family, timeout, cfg.Baud)
		if err != nil {
			lastErr = err
			continue
		}
		for _, ch := range channels {
			key := resource
			name := model
			id := resource
			if len(channels) > 1 {
				key = fmt.Sprintf("%s#%d", resource, ch)
				id = key
				name = fmt.Sprintf("%s CH%d", model, ch)
			}
			out = append(out, Device{
				Driver: "scpi", Key: key, ID: id, Name: name,
				Family: family, Model: model, Serial: serial, Address: resource,
			})
		}
	}
	if len(out) == 0 && lastErr != nil {
		return nil, lastErr
	}
	return out, nil
}

func (scpiDriver) Open(dev Device) (*server.Unit, error) {
	cfg := config.Load()
	resource := dev.Address
	if resource == "" {
		resource = dev.Key
	}
	channel := 1
	if i := strings.LastIndex(dev.Key, "#"); i >= 0 {
		if n, err := strconv.Atoi(dev.Key[i+1:]); err == nil {
			channel = n
		}
	}
	return scpi.Open(resource, scpi.OpenOptions{
		Channel: channel, Family: cfg.Family, Timeout: time.Duration(cfg.Timeout * float64(time.Second)),
		Baud: cfg.Baud, MaxVoltage: cfg.MaxVoltage, MaxCurrent: cfg.MaxCurrent,
	})
}

package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

const (
	DefaultPort       = 5025
	DefaultBaud       = 9600
	DefaultTimeout    = 3.0
	DefaultMaxVoltage = 30.0
	DefaultMaxCurrent = 5.0
)

type Config struct {
	Resource        string   `json:"resource,omitempty"`
	Host            string   `json:"host,omitempty"`
	Port            int      `json:"port,omitempty"`
	SerialPort      string   `json:"serial_port,omitempty"`
	Baud            int      `json:"baud,omitempty"`
	Timeout         float64  `json:"timeout,omitempty"`
	Family          string   `json:"family,omitempty"`
	MaxVoltage      float64  `json:"max_voltage,omitempty"`
	MaxCurrent      float64  `json:"max_current,omitempty"`
	SafeOff         bool     `json:"safe_off"`
	CurrentDecimals int      `json:"current_decimals,omitempty"`
	Resources       []string `json:"resources,omitempty"`
}

func Path() string {
	if p := os.Getenv("PSU_CONFIG"); p != "" {
		return p
	}
	dir, err := os.UserConfigDir()
	if err != nil {
		dir = "."
	}
	return filepath.Join(dir, "psu", "config.json")
}

func Load() Config {
	c := Config{
		Port: DefaultPort, Baud: DefaultBaud, Timeout: DefaultTimeout,
		MaxVoltage: DefaultMaxVoltage, MaxCurrent: DefaultMaxCurrent, SafeOff: true, CurrentDecimals: 1,
	}
	if b, err := os.ReadFile(Path()); err == nil {
		_ = json.Unmarshal(b, &c)
	}
	applyEnv(&c)
	if c.Port == 0 {
		c.Port = DefaultPort
	}
	if c.Baud == 0 {
		c.Baud = DefaultBaud
	}
	if c.Timeout == 0 {
		c.Timeout = DefaultTimeout
	}
	if c.MaxVoltage == 0 {
		c.MaxVoltage = DefaultMaxVoltage
	}
	if c.MaxCurrent == 0 {
		c.MaxCurrent = DefaultMaxCurrent
	}
	if c.CurrentDecimals == 0 {
		c.CurrentDecimals = 1
	}
	return c
}

func applyEnv(c *Config) {
	if v := os.Getenv("PSU_RESOURCE"); v != "" {
		c.Resource = v
	}
	if v := os.Getenv("PSU_HOST"); v != "" {
		c.Host = v
	}
	if v := os.Getenv("PSU_PORT"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			c.Port = n
		}
	}
	if v := os.Getenv("PSU_SERIAL_PORT"); v != "" {
		c.SerialPort = v
	}
	if v := os.Getenv("PSU_BAUD"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			c.Baud = n
		}
	}
	if v := os.Getenv("PSU_FAMILY"); v != "" {
		c.Family = v
	}
	if v := os.Getenv("PSU_MAX_VOLTAGE"); v != "" {
		if n, err := strconv.ParseFloat(v, 64); err == nil {
			c.MaxVoltage = n
		}
	}
	if v := os.Getenv("PSU_MAX_CURRENT"); v != "" {
		if n, err := strconv.ParseFloat(v, 64); err == nil {
			c.MaxCurrent = n
		}
	}
	if v := os.Getenv("PSU_RESOURCES"); v != "" {
		c.Resources = append(c.Resources, strings.Split(v, ",")...)
	}
}

func (c Config) Endpoints() []string {
	seen := map[string]bool{}
	var out []string
	base := append([]string{c.Resource}, c.Resources...)
	if c.Host != "" {
		base = append(base, "TCPIP::"+c.Host+"::"+strconv.Itoa(c.Port)+"::SOCKET")
	}
	if c.SerialPort != "" && c.Family != "dps150" && c.Family != "bk168x" && c.Family != "bk" {
		base = append(base, "ASRL::"+c.SerialPort+"::"+strconv.Itoa(c.Baud))
	}
	for _, r := range base {
		r = strings.TrimSpace(r)
		if r == "" || seen[r] {
			continue
		}
		seen[r] = true
		out = append(out, r)
	}
	return out
}

func Save(c Config) error {
	p := Path()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(p, b, 0o644)
}

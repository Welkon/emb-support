// Package psu contains protocol-neutral types shared by drivers and the server.
package psu

// Measurement is one reading from a power supply channel.
type Measurement struct {
	Voltage      float64 `json:"voltage"`
	Current      float64 `json:"current"`
	Power        float64 `json:"power"`
	InputVoltage float64 `json:"input_voltage"`
	Temperature  float64 `json:"temperature"`
}

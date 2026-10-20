package dp100

import (
	"encoding/binary"
	"fmt"
)

const (
	HostToDevice = 0xFB
	DeviceToHost = 0xFA

	OpInfo       = 0x10
	OpBasic      = 0x30
	OpSet        = 0x35
	IndexOutput  = 0x20
	IndexProtect = 0x40
	IndexRead    = 0x80
)

// Frame is one DP100 HID report.
type Frame struct {
	Op      byte
	Seq     byte
	Payload []byte
}

// Encode builds a frame with a CRC-16/MODBUS trailer.
func Encode(op byte, payload []byte) []byte {
	body := make([]byte, 4+len(payload))
	body[0] = HostToDevice
	body[1] = op
	body[2] = 0
	body[3] = byte(len(payload))
	copy(body[4:], payload)
	crc := crc16(body)
	return append(body, byte(crc), byte(crc>>8))
}

// Decode checks the header, length, and CRC. It returns the payload only.
func Decode(raw []byte) (Frame, error) {
	if len(raw) < 6 {
		return Frame{}, fmt.Errorf("short frame: %d bytes", len(raw))
	}
	if raw[0] != DeviceToHost {
		return Frame{}, fmt.Errorf("unexpected header 0x%02x", raw[0])
	}
	n := int(raw[3])
	if len(raw) < 4+n+2 {
		return Frame{}, fmt.Errorf("short payload: need %d, got %d", 4+n+2, len(raw))
	}
	body := raw[:4+n]
	want := binary.LittleEndian.Uint16(raw[4+n : 4+n+2])
	if got := crc16(body); got != want {
		return Frame{}, fmt.Errorf("crc mismatch: got 0x%04x, want 0x%04x", got, want)
	}
	return Frame{Op: raw[1], Seq: raw[2], Payload: raw[4 : 4+n]}, nil
}

func crc16(data []byte) uint16 {
	crc := uint16(0xFFFF)
	for _, b := range data {
		crc ^= uint16(b)
		for i := 0; i < 8; i++ {
			if crc&1 != 0 {
				crc = (crc >> 1) ^ 0xA001
			} else {
				crc >>= 1
			}
		}
	}
	return crc
}

// BasicInfo is the payload of OpBasic.
type BasicInfo struct {
	VinMV     int
	VoutMV    int
	IoutMA    int
	VoMaxMV   int
	Temp1Deci int
	Temp2Deci int
	DC5VMV    int
	OutMode   byte
	WorkState byte
}

func ParseBasic(p []byte) (BasicInfo, error) {
	if len(p) < 16 {
		return BasicInfo{}, fmt.Errorf("basic payload too short: %d", len(p))
	}
	u16 := func(i int) int { return int(binary.LittleEndian.Uint16(p[i : i+2])) }
	return BasicInfo{
		VinMV: u16(0), VoutMV: u16(2), IoutMA: u16(4), VoMaxMV: u16(6),
		Temp1Deci: u16(8), Temp2Deci: u16(10), DC5VMV: u16(12),
		OutMode: p[14], WorkState: p[15],
	}, nil
}

// Settings is the payload of OpSet with IndexRead.
type Settings struct {
	State byte
	VSetV float64
	ISetA float64
	OVPV  float64
	OCPA  float64
}

func ParseSettings(p []byte) (Settings, error) {
	if len(p) < 10 {
		return Settings{}, fmt.Errorf("settings payload too short: %d", len(p))
	}
	u16 := func(i int) int { return int(binary.LittleEndian.Uint16(p[i : i+2])) }
	return Settings{
		State: p[1],
		VSetV: float64(u16(2)) / 1000,
		ISetA: float64(u16(4)) / 1000,
		OVPV:  float64(u16(6)) / 1000,
		OCPA:  float64(u16(8)) / 1000,
	}, nil
}

func le16(v int) (byte, byte) { return byte(v), byte(v >> 8) }

// OutputPayload builds the 0x20 output frame. Protection values are ignored.
func OutputPayload(state byte, voltageV, currentA float64) []byte {
	v, i := int(voltageV*1000+0.5), int(currentA*1000+0.5)
	loV, hiV := le16(v)
	loI, hiI := le16(i)
	return []byte{IndexOutput, state, loV, hiV, loI, hiI, 0, 0, 0, 0}
}

// ProtectPayload builds the 0x40 protection frame. It preserves the setpoints.
func ProtectPayload(state byte, voltageV, currentA, ovpV, ocpA float64) []byte {
	v, i := int(voltageV*1000+0.5), int(currentA*1000+0.5)
	ovp, ocp := int(ovpV*1000+0.5), int(ocpA*1000+0.5)
	loV, hiV := le16(v)
	loI, hiI := le16(i)
	loO, hiO := le16(ovp)
	loC, hiC := le16(ocp)
	return []byte{IndexProtect, state, loV, hiV, loI, hiI, loO, hiO, loC, hiC}
}

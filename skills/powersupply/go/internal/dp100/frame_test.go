package dp100

import (
	"encoding/binary"
	"encoding/hex"
	"testing"
)

func response(op byte, payload []byte) []byte {
	body := make([]byte, 4+len(payload))
	body[0] = DeviceToHost
	body[1] = op
	body[3] = byte(len(payload))
	copy(body[4:], payload)
	crc := crc16(body)
	return append(body, byte(crc), byte(crc>>8))
}

func basicPayload() []byte {
	p := make([]byte, 16)
	binary.LittleEndian.PutUint16(p[0:], 9254) // input 9.254 V
	binary.LittleEndian.PutUint16(p[2:], 2824) // output 2.824 V
	binary.LittleEndian.PutUint16(p[4:], 467)  // current 0.467 A
	binary.LittleEndian.PutUint16(p[6:], 8970) // max output 8.970 V
	binary.LittleEndian.PutUint16(p[8:], 318)  // temperature 31.8 C
	binary.LittleEndian.PutUint16(p[10:], 315)
	binary.LittleEndian.PutUint16(p[12:], 5061)
	p[14], p[15] = 0, 0
	return p
}

func settingsPayload(state byte) []byte {
	p := make([]byte, 10)
	p[1] = state
	binary.LittleEndian.PutUint16(p[2:], 3260)
	binary.LittleEndian.PutUint16(p[4:], 470)
	binary.LittleEndian.PutUint16(p[6:], 30500)
	binary.LittleEndian.PutUint16(p[8:], 5050)
	return p
}

func infoPayload() []byte {
	p := make([]byte, 40)
	copy(p[0:15], []byte("ATK-DP100\x00"))
	binary.LittleEndian.PutUint16(p[16:], 12)
	binary.LittleEndian.PutUint16(p[18:], 14)
	binary.LittleEndian.PutUint16(p[20:], 11)
	copy(p[24:35], []byte("SN123456789"))
	return p
}

func TestGoldenInfoFrame(t *testing.T) {
	if got := hex.EncodeToString(Encode(OpInfo, nil)); got != "fb10000030c5" {
		t.Fatalf("info frame = %s", got)
	}
}

func TestDecodeRejectsBadCRC(t *testing.T) {
	raw := response(OpBasic, basicPayload())
	raw[len(raw)-1] ^= 0xFF
	if _, err := Decode(raw); err == nil {
		t.Fatal("expected CRC error")
	}
}

func TestParseBasicOffsets(t *testing.T) {
	b, err := ParseBasic(basicPayload())
	if err != nil {
		t.Fatal(err)
	}
	if b.VinMV != 9254 || b.VoutMV != 2824 || b.IoutMA != 467 {
		t.Fatalf("unexpected basic: %+v", b)
	}
	if b.VoMaxMV != 8970 || b.Temp1Deci != 318 || b.OutMode != 0 {
		t.Fatalf("unexpected basic fields: %+v", b)
	}
}

func TestProtectionPayloadPreservesSetpoints(t *testing.T) {
	p := ProtectPayload(0, 3.26, 0.47, 2.5, 0.2)
	if p[0] != IndexProtect {
		t.Fatalf("index = 0x%02x", p[0])
	}
	if got := binary.LittleEndian.Uint16(p[2:4]); got != 3260 {
		t.Fatalf("vset = %d", got)
	}
	if got := binary.LittleEndian.Uint16(p[4:6]); got != 470 {
		t.Fatalf("iset = %d", got)
	}
	if got := binary.LittleEndian.Uint16(p[6:8]); got != 2500 {
		t.Fatalf("ovp = %d", got)
	}
	if got := binary.LittleEndian.Uint16(p[8:10]); got != 200 {
		t.Fatalf("ocp = %d", got)
	}
}

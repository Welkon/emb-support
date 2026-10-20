package dp100

import (
	"encoding/binary"
	"fmt"
	"testing"
)

type fakeTransport struct {
	queue  [][]byte
	writes [][]byte
}

func (f *fakeTransport) Write(p []byte) error {
	f.writes = append(f.writes, append([]byte(nil), p...))
	return nil
}
func (f *fakeTransport) Read(n, timeout int) ([]byte, error) {
	if len(f.queue) == 0 {
		return nil, fmt.Errorf("no response")
	}
	r := f.queue[0]
	f.queue = f.queue[1:]
	return r, nil
}
func (f *fakeTransport) Close() error { return nil }
func (f *fakeTransport) Path() string { return "fake" }

func newDevice(t *testing.T) (*Device, *fakeTransport) {
	t.Helper()
	f := &fakeTransport{queue: [][]byte{
		response(OpInfo, infoPayload()),
		response(OpBasic, basicPayload()),
		response(OpSet, settingsPayload(0)),
	}}
	d, err := Open(f)
	if err != nil {
		t.Fatal(err)
	}
	return d, f
}

func TestOpenAndSnapshot(t *testing.T) {
	d, f := newDevice(t)
	if d.Info.Model != "ATK-DP100" || d.Info.App != 1.4 {
		t.Fatalf("info = %+v", d.Info)
	}
	if d.V != 3.26 || d.I != 0.47 || d.Out {
		t.Fatalf("settings = v %.2f i %.2f out %v", d.V, d.I, d.Out)
	}
	if d.MaxV != 8.97 {
		t.Fatalf("max voltage = %.2f", d.MaxV)
	}
	f.queue = [][]byte{response(OpBasic, basicPayload()), response(OpSet, settingsPayload(1))}
	s, err := d.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	if s.Output != "ON" || s.Status.OutputMode != "CC" || s.Measurement.InputVoltage != 9.254 {
		t.Fatalf("snapshot = %+v", s)
	}
}

func TestSetVoltageAndProtectionFrames(t *testing.T) {
	d, f := newDevice(t)
	f.queue = [][]byte{response(OpSet, []byte{1})}
	if err := d.SetVoltage(3.3); err != nil {
		t.Fatal(err)
	}
	frame := f.writes[len(f.writes)-1]
	if frame[4] != IndexOutput {
		t.Fatalf("output index = 0x%02x", frame[4])
	}
	if got := binary.LittleEndian.Uint16(frame[6:8]); got != 3300 {
		t.Fatalf("vset frame = %d", got)
	}

	f.queue = [][]byte{response(OpSet, []byte{1})}
	if err := d.SetOVP(2.5); err != nil {
		t.Fatal(err)
	}
	frame = f.writes[len(f.writes)-1]
	if frame[4] != IndexProtect {
		t.Fatalf("protection index = 0x%02x", frame[4])
	}
	if got := binary.LittleEndian.Uint16(frame[6:8]); got != 3300 {
		t.Fatalf("protection lost vset: %d", got)
	}
	if got := binary.LittleEndian.Uint16(frame[10:12]); got != 2500 {
		t.Fatalf("ovp frame = %d", got)
	}
}

func TestLimits(t *testing.T) {
	d, _ := newDevice(t)
	if err := d.SetVoltage(40); err == nil {
		t.Fatal("expected voltage limit error")
	}
	if err := d.SetCurrent(6); err == nil {
		t.Fatal("expected current limit error")
	}
	if err := d.SetOVP(31); err == nil {
		t.Fatal("expected OVP limit error")
	}
}

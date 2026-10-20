package server

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"testing/fstest"
	"time"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/dp100"
)

type fakeDev struct {
	mu   sync.Mutex
	v    float64
	i    float64
	out  bool
	ovp  float64
	ocp  float64
	mode byte
	work byte
}

func (f *fakeDev) Status() (byte, byte) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.out {
		return 2, f.work
	}
	if f.mode == 0 {
		return 0, f.work
	}
	return 1, f.work
}

func (f *fakeDev) Snapshot() (dp100.Snapshot, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	mode := "CC"
	if f.out {
		mode = "CV"
	} else {
		mode = "OFF"
	}
	return dp100.Snapshot{
		Output: map[bool]string{false: "OFF", true: "ON"}[f.out],
		VSet:   f.v, ISet: f.i, MaxVoltage: 30,
		Measurement: dp100.Measurement{Voltage: f.v, Current: f.i, InputVoltage: 12, Temperature: 30},
		Status:      dp100.Status{OutputMode: mode},
	}, nil
}
func (f *fakeDev) Measurement() (dp100.Measurement, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return dp100.Measurement{Voltage: f.v, Current: f.i, Power: f.v * f.i, InputVoltage: 12, Temperature: 30}, nil
}
func (f *fakeDev) SetVoltage(v float64) error { f.mu.Lock(); f.v = v; f.mu.Unlock(); return nil }
func (f *fakeDev) SetCurrent(a float64) error { f.mu.Lock(); f.i = a; f.mu.Unlock(); return nil }
func (f *fakeDev) SetOutput(on bool) error    { f.mu.Lock(); f.out = on; f.mu.Unlock(); return nil }
func (f *fakeDev) SetOVP(v float64) error     { f.mu.Lock(); f.ovp = v; f.mu.Unlock(); return nil }
func (f *fakeDev) SetOCP(a float64) error     { f.mu.Lock(); f.ocp = a; f.mu.Unlock(); return nil }
func (f *fakeDev) DeviceInfo() dp100.Info {
	return dp100.Info{Model: "FAKE", App: 1.4, SerialHex: "SN"}
}
func (f *fakeDev) Setpoints() (float64, float64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.v, f.i
}
func (f *fakeDev) OutputOn() bool             { f.mu.Lock(); defer f.mu.Unlock(); return f.out }
func (f *fakeDev) Limits() (float64, float64) { return 30, 5 }
func (f *fakeDev) Close() error               { return nil }

func newTestServer(t *testing.T) (*Server, *fakeDev, *httptest.Server) {
	t.Helper()
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "index.html"), []byte("<title>Power Supply</title>"), 0o644)
	f := &fakeDev{v: 3, i: 0.5}
	s := New(f, Options{SampleHz: 100, DistDir: dir})
	ts := httptest.NewServer(s.Handler())
	t.Cleanup(func() { s.Close(); ts.Close() })
	return s, f, ts
}

func getJSON(t *testing.T, url string) map[string]any {
	t.Helper()
	res, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	var out map[string]any
	if err := json.NewDecoder(res.Body).Decode(&out); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestStateAndStatic(t *testing.T) {
	_, _, ts := newTestServer(t)
	s := getJSON(t, ts.URL+"/api/state?ch=1")
	if s["family"] != "dp100" || s["ok"] != true {
		t.Fatalf("state = %+v", s)
	}
	res, err := http.Get(ts.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.Header.Get("Cache-Control") != "no-cache" {
		t.Fatal("missing index cache header")
	}
}

func TestSetOutputHistoryStream(t *testing.T) {
	_, f, ts := newTestServer(t)
	body := strings.NewReader(`{"ch":1,"voltage":5,"current":1}`)
	res, err := http.Post(ts.URL+"/api/set", "application/json", body)
	if err != nil || res.StatusCode != 200 {
		t.Fatalf("set: %v %v", err, res.StatusCode)
	}
	res.Body.Close()
	if f.v != 5 || f.i != 1 {
		t.Fatalf("setpoint = %.2f %.2f", f.v, f.i)
	}
	res, _ = http.Post(ts.URL+"/api/output", "application/json", strings.NewReader(`{"ch":1,"on":true}`))
	if res.StatusCode != 400 {
		t.Fatal("ON without confirm must fail")
	}
	res.Body.Close()
	res, _ = http.Post(ts.URL+"/api/output", "application/json", strings.NewReader(`{"ch":1,"on":true,"confirm":true}`))
	if res.StatusCode != 200 {
		t.Fatal("ON with confirm failed")
	}
	res.Body.Close()
	time.Sleep(60 * time.Millisecond)
	h := getJSON(t, ts.URL+"/api/history?ch=1&seconds=2")
	if n := len(h["samples"].([]any)); n == 0 {
		t.Fatal("history is empty")
	}
	client := &http.Client{Timeout: 2 * time.Second}
	sres, err := client.Get(ts.URL + "/api/stream?ch=1&hz=50")
	if err != nil {
		t.Fatal(err)
	}
	defer sres.Body.Close()
	line, err := bufio.NewReader(sres.Body).ReadString('\n')
	if err != nil || !strings.HasPrefix(line, "data:") {
		t.Fatalf("stream line = %q, %v", line, err)
	}
	var sample map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(strings.TrimPrefix(line, "data:"))), &sample); err != nil {
		t.Fatal(err)
	}
	if sample["t"] == nil {
		t.Fatalf("stream sample = %+v", sample)
	}
}

func TestDesktopRuntimeInjection(t *testing.T) {
	f := &fakeDev{v: 3, i: 0.5}
	s := New(f, Options{DistFS: fstest.MapFS{
		"index.html": &fstest.MapFile{Data: []byte("<html><head></head><body></body></html>")},
	}})
	defer s.Close()
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	res, err := http.Get(ts.URL + "/?desktop=1")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(res.Body)
	res.Body.Close()
	if !strings.Contains(string(body), "/wails/runtime.js") {
		t.Fatal("desktop index does not inject the Wails runtime")
	}

	res, err = http.Get(ts.URL + "/")
	if err != nil {
		t.Fatal(err)
	}
	body, _ = io.ReadAll(res.Body)
	res.Body.Close()
	if strings.Contains(string(body), "/wails/runtime.js") {
		t.Fatal("browser index must not inject the Wails runtime")
	}
}

func TestMultipleDevices(t *testing.T) {
	a := &fakeDev{v: 1, i: 0.1}
	b := &fakeDev{v: 2, i: 0.2}
	s := NewMulti([]Unit{{ID: "a", Name: "A", Dev: a}, {ID: "b", Name: "B", Dev: b}}, Options{SampleHz: 100})
	defer s.Close()
	ts := httptest.NewServer(s.Handler())
	defer ts.Close()

	res, err := http.Get(ts.URL + "/api/devices")
	if err != nil {
		t.Fatal(err)
	}
	var list struct {
		Devices []struct {
			ID string `json:"id"`
		} `json:"devices"`
	}
	if err := json.NewDecoder(res.Body).Decode(&list); err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	if len(list.Devices) != 2 || list.Devices[0].ID != "a" || list.Devices[1].ID != "b" {
		t.Fatalf("devices = %+v", list.Devices)
	}

	body := strings.NewReader(`{"device":"b","voltage":5,"current":1}`)
	res, err = http.Post(ts.URL+"/api/set", "application/json", body)
	if err != nil || res.StatusCode != 200 {
		t.Fatalf("set b: %v %v", err, res.StatusCode)
	}
	res.Body.Close()
	if a.v != 1 || b.v != 5 {
		t.Fatalf("setpoints crossed: a=%.2f b=%.2f", a.v, b.v)
	}

	res, err = http.Get(ts.URL + "/api/state?device=a")
	if err != nil {
		t.Fatal(err)
	}
	var state struct {
		Device string `json:"device"`
	}
	json.NewDecoder(res.Body).Decode(&state)
	res.Body.Close()
	if state.Device != "a" {
		t.Fatalf("state device = %q", state.Device)
	}

	res, err = http.Get(ts.URL + "/api/state?device=missing")
	if err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	if res.StatusCode != 404 {
		t.Fatalf("unknown device status = %d", res.StatusCode)
	}

	res, err = http.Post(ts.URL+"/api/all-off", "application/json", strings.NewReader(`{}`))
	if err != nil || res.StatusCode != 200 {
		t.Fatalf("all off: %v %v", err, res.StatusCode)
	}
	res.Body.Close()
	if a.out || b.out {
		t.Fatal("all-off did not turn off both devices")
	}
}

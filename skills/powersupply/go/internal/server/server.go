package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io/fs"
	"mime"
	"net"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/psu"
)

type Backend interface {
	Status() (mode, work byte)
	Measurement() (psu.Measurement, error)
	SetVoltage(float64) error
	SetCurrent(float64) error
	SetOutput(bool) error
	SetOVP(float64) error
	SetOCP(float64) error
	Protection() (ovp, ocp float64)
	Setpoints() (voltage, current float64)
	OutputOn() bool
	Limits() (maxV, maxI float64)
	Close() error
}

type Sample struct {
	T            int64    `json:"t"`
	Voltage      float64  `json:"voltage"`
	Current      float64  `json:"current"`
	Power        float64  `json:"power"`
	InputVoltage *float64 `json:"input_voltage,omitempty"`
	Temperature  *float64 `json:"temperature,omitempty"`
}

type Options struct {
	MaxVoltage  float64
	MaxCurrent  float64
	SampleHz    int
	DistDir     string
	DistFS      fs.FS
	AllowOrigin string
}

// Unit is one connected power supply. ID must be stable for the lifetime of the
// process; the DP100 serial number is the natural choice.
type Capabilities struct {
	Power        bool `json:"power"`
	OVP          bool `json:"ovp"`
	OCP          bool `json:"ocp"`
	OutputState  bool `json:"output_state"`
	InputVoltage bool `json:"input_voltage"`
	Temperature  bool `json:"temperature"`
}

type Limits struct {
	MaxVoltage float64 `json:"max_voltage"`
	MaxCurrent float64 `json:"max_current"`
	MaxOVP     float64 `json:"max_ovp"`
	MaxOCP     float64 `json:"max_ocp"`
	MaxPower   float64 `json:"max_power"`
}

// Unit is one connected power supply. A unit may come from any driver.
// ID must be stable for the lifetime of the process. Metadata is optional;
// when it is zero, the server falls back to the DP100 defaults.
type Unit struct {
	ID       string
	Name     string
	Family   string
	IDN      string
	Model    string
	Serial   string
	Hardware string
	Firmware string
	Channels []int
	Caps     Capabilities
	Limits   Limits
	Dev      Backend
}

type deviceState struct {
	id       string
	name     string
	family   string
	idn      string
	model    string
	serial   string
	hardware string
	firmware string
	channels []int
	caps     Capabilities
	limits   Limits
	dev      Backend
	mu       sync.RWMutex
	devMu    sync.Mutex
	hist     []Sample
	stop     chan struct{}
}

type Server struct {
	opt       Options
	units     []*deviceState
	byID      map[string]*deviceState
	defaultID string
	wg        sync.WaitGroup
}

func normalizeOptions(opt Options) Options {
	if opt.MaxVoltage == 0 {
		opt.MaxVoltage = 30.0
	}
	if opt.MaxCurrent == 0 {
		opt.MaxCurrent = 5.0
	}
	if opt.SampleHz == 0 {
		opt.SampleHz = 20
	}
	return opt
}

// New keeps the single-device API. Multiple devices use NewMulti.
func New(dev Backend, opt Options) *Server {
	return NewMulti([]Unit{{ID: "default", Family: "dp100", Dev: dev}}, opt)
}

func NewMulti(units []Unit, opt Options) *Server {
	s := &Server{opt: normalizeOptions(opt), byID: make(map[string]*deviceState)}
	for i, unit := range units {
		if unit.Dev == nil {
			continue
		}
		id := strings.TrimSpace(unit.ID)
		if id == "" {
			id = fmt.Sprintf("device-%d", i+1)
		}
		base := id
		for n := 2; s.byID[id] != nil; n++ {
			id = fmt.Sprintf("%s-%d", base, n)
		}
		name := strings.TrimSpace(unit.Name)
		if name == "" {
			name = id
		}
		family := unit.Family
		if family == "" {
			family = "unknown"
		}
		channels := unit.Channels
		if len(channels) == 0 {
			channels = []int{1}
		}
		caps := unit.Caps
		if family == "dp100" && caps == (Capabilities{}) {
			caps = Capabilities{Power: true, OVP: true, OCP: true, OutputState: true, InputVoltage: true, Temperature: true}
		}
		limits := unit.Limits
		if limits.MaxVoltage == 0 {
			limits.MaxVoltage = 30.0
		}
		if limits.MaxCurrent == 0 {
			limits.MaxCurrent = 5.0
		}
		if limits.MaxOVP == 0 {
			limits.MaxOVP = 30.5
		}
		if limits.MaxOCP == 0 {
			limits.MaxOCP = 5.05
		}
		if limits.MaxPower == 0 {
			limits.MaxPower = 100
		}
		u := &deviceState{
			id: id, name: name, family: family, idn: unit.IDN, model: unit.Model,
			serial: unit.Serial, hardware: unit.Hardware, firmware: unit.Firmware,
			channels: channels, caps: caps, limits: limits,
			dev: unit.Dev, stop: make(chan struct{}),
		}
		s.units = append(s.units, u)
		s.byID[id] = u
		if s.defaultID == "" {
			s.defaultID = id
		}
		s.wg.Add(1)
		go s.sampleLoop(u)
	}
	return s
}

func (s *Server) Close() {
	for _, u := range s.units {
		select {
		case <-u.stop:
		default:
			close(u.stop)
		}
	}
	s.wg.Wait()
}

func (s *Server) Stop() { s.Close() }

func (s *Server) sampleLoop(u *deviceState) {
	defer s.wg.Done()
	period := time.Second / time.Duration(s.opt.SampleHz)
	for {
		start := time.Now()
		u.devMu.Lock()
		m, err := u.dev.Measurement()
		u.devMu.Unlock()
		if err == nil {
			iv, tv := m.InputVoltage, m.Temperature
			u.mu.Lock()
			u.hist = append(u.hist, Sample{
				T: time.Now().UnixMilli(), Voltage: m.Voltage, Current: m.Current,
				Power: m.Power, InputVoltage: &iv, Temperature: &tv,
			})
			limit := s.opt.SampleHz * 240
			if len(u.hist) > limit {
				u.hist = u.hist[len(u.hist)-limit:]
			}
			u.mu.Unlock()
		}
		if d := period - time.Since(start); d > 0 {
			select {
			case <-time.After(d):
			case <-u.stop:
				return
			}
		}
	}
}

func (s *Server) unit(r *http.Request, requested string) (*deviceState, error) {
	id := strings.TrimSpace(requested)
	if id == "" {
		id = strings.TrimSpace(r.URL.Query().Get("device"))
	}
	if id == "" {
		id = s.defaultID
	}
	u := s.byID[id]
	if u == nil {
		return nil, fmt.Errorf("unknown device %q", id)
	}
	return u, nil
}

func (s *Server) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/devices", s.devices)
	mux.HandleFunc("/api/state", s.state)
	mux.HandleFunc("/api/history", s.history)
	mux.HandleFunc("/api/stream", s.stream)
	mux.HandleFunc("/api/set", s.set)
	mux.HandleFunc("/api/output", s.output)
	mux.HandleFunc("/api/protect", s.protect)
	mux.HandleFunc("/api/all-off", s.allOff)
	mux.HandleFunc("/", s.static)
	return s.cors(mux)
}

func (s *Server) Handler() http.Handler { return s.handler() }

func (s *Server) cors(next http.Handler) http.Handler {
	if s.opt.AllowOrigin == "" {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", s.opt.AllowOrigin)
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) devices(w http.ResponseWriter, r *http.Request) {
	out := make([]map[string]any, 0, len(s.units))
	for _, u := range s.units {
		out = append(out, s.deviceJSON(u))
	}
	writeJSON(w, 200, map[string]any{"ok": true, "devices": out, "default": s.defaultID})
}

func (s *Server) state(w http.ResponseWriter, r *http.Request) {
	u, err := s.unit(r, "")
	if err != nil {
		writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.writeState(w, u)
}

func (s *Server) deviceJSON(u *deviceState) map[string]any {
	idn := u.idn
	if idn == "" {
		idn = fmt.Sprintf("%s,%s", u.name, u.serial)
	}
	return map[string]any{
		"id": u.id, "name": u.name, "family": u.family, "idn": idn,
		"model": u.model, "serial_number_hex": u.serial,
		"firmware_version": u.firmware, "hardware": u.hardware,
		"channels": u.channels, "capabilities": u.caps, "limits": u.limits,
		"output": map[bool]string{false: "OFF", true: "ON"}[u.dev.OutputOn()],
	}
}

func (s *Server) writeState(w http.ResponseWriter, u *deviceState) {
	ch := u.channels[0]
	u.mu.RLock()
	var last Sample
	have := len(u.hist) > 0
	if have {
		last = u.hist[len(u.hist)-1]
	}
	u.mu.RUnlock()

	u.devMu.Lock()
	vset, iset := u.dev.Setpoints()
	out := u.dev.OutputOn()
	maxV, _ := u.dev.Limits()
	mode, work := u.dev.Status()
	if !have {
		if m, err := u.dev.Measurement(); err == nil {
			last = Sample{Voltage: m.Voltage, Current: m.Current, Power: m.Power,
				InputVoltage: &m.InputVoltage, Temperature: &m.Temperature}
			have = true
		}
	}
	u.devMu.Unlock()

	measurement := map[string]any{"voltage": 0.0, "current": 0.0, "power": 0.0}
	if have {
		measurement = map[string]any{
			"voltage": last.Voltage, "current": last.Current, "power": last.Power,
			"input_voltage": last.InputVoltage, "temperature": last.Temperature,
		}
	}
	output := "OFF"
	if out {
		output = "ON"
	}
	modeName := map[byte]string{0: "CC", 1: "CV", 2: "OFF"}[mode]
	if modeName == "" {
		modeName = "OFF"
	}
	status := map[string]any{"output_mode": modeName, "work_state": work}
	idn := u.idn
	if idn == "" {
		idn = fmt.Sprintf("%s,%s", u.name, u.serial)
	}
	limits := u.limits
	if maxV > 0 {
		limits.MaxVoltage = maxV
	}
	writeJSON(w, 200, map[string]any{
		"ok": true, "device": u.id, "device_name": u.name, "family": u.family,
		"idn": idn, "device_info": map[string]any{
			"model": u.model, "firmware_version": u.firmware, "hardware": u.hardware,
			"serial_number_hex": u.serial,
		},
		"channels": u.channels, "ch": ch, "output": output,
		"setpoint":    map[string]any{"voltage": vset, "current": iset},
		"measurement": measurement, "status": status,
		"capabilities": u.caps, "limits": limits,
	})
}

func (s *Server) history(w http.ResponseWriter, r *http.Request) {
	u, err := s.unit(r, "")
	if err != nil {
		writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	seconds := 62.0
	if v := r.URL.Query().Get("seconds"); v != "" {
		fmt.Sscanf(v, "%f", &seconds)
	}
	if seconds < 1 || seconds > 120 {
		seconds = 62
	}
	cutoff := time.Now().Add(-time.Duration(seconds * float64(time.Second))).UnixMilli()
	u.mu.RLock()
	out := make([]Sample, 0, len(u.hist))
	for _, sample := range u.hist {
		if sample.T >= cutoff {
			out = append(out, sample)
		}
	}
	u.mu.RUnlock()
	writeJSON(w, 200, map[string]any{"ok": true, "device": u.id, "ch": 1, "samples": out})
}

func (s *Server) stream(w http.ResponseWriter, r *http.Request) {
	u, err := s.unit(r, "")
	if err != nil {
		writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	hz := 20.0
	if v := r.URL.Query().Get("hz"); v != "" {
		fmt.Sscanf(v, "%f", &hz)
	}
	if hz < 1 || hz > 60 {
		hz = 20
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeJSON(w, 500, map[string]any{"ok": false, "error": "stream unsupported"})
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(200)
	flusher.Flush()
	period := time.Duration(float64(time.Second) / hz)
	var last int64
	for {
		select {
		case <-r.Context().Done():
			return
		case <-u.stop:
			return
		default:
		}
		u.mu.RLock()
		var latest *Sample
		if len(u.hist) > 0 {
			x := u.hist[len(u.hist)-1]
			if x.T > last {
				latest = &x
			}
		}
		u.mu.RUnlock()
		if latest != nil {
			last = latest.T
			b, _ := json.Marshal(latest)
			fmt.Fprintf(w, "data: %s\n\n", b)
			flusher.Flush()
		}
		select {
		case <-r.Context().Done():
			return
		case <-time.After(period):
		}
	}
}

func (s *Server) set(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Device  string   `json:"device"`
		Ch      int      `json:"ch"`
		Voltage *float64 `json:"voltage"`
		Current *float64 `json:"current"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	u, err := s.unit(r, body.Device)
	if err != nil {
		writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	maxV, maxI := u.limits.MaxVoltage, u.limits.MaxCurrent
	if maxV <= 0 {
		maxV = s.opt.MaxVoltage
	}
	if maxI <= 0 {
		maxI = s.opt.MaxCurrent
	}
	if body.Voltage != nil && (*body.Voltage < 0 || *body.Voltage > maxV) {
		writeJSON(w, 400, map[string]any{"ok": false, "error": "voltage limit"})
		return
	}
	if body.Current != nil && (*body.Current < 0 || *body.Current > maxI) {
		writeJSON(w, 400, map[string]any{"ok": false, "error": "current limit"})
		return
	}
	u.devMu.Lock()
	if body.Voltage != nil {
		err = u.dev.SetVoltage(*body.Voltage)
	}
	if err == nil && body.Current != nil {
		err = u.dev.SetCurrent(*body.Current)
	}
	u.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.writeState(w, u)
}

func (s *Server) output(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Device  string `json:"device"`
		Ch      int    `json:"ch"`
		On      bool   `json:"on"`
		Confirm bool   `json:"confirm"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	u, err := s.unit(r, body.Device)
	if err != nil {
		writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	if body.On && !body.Confirm {
		writeJSON(w, 400, map[string]any{"ok": false, "error": "output ON requires confirm=true"})
		return
	}
	u.devMu.Lock()
	err = u.dev.SetOutput(body.On)
	u.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.writeState(w, u)
}

func (s *Server) protect(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Device string   `json:"device"`
		Ch     int      `json:"ch"`
		OVP    *float64 `json:"ovp"`
		OCP    *float64 `json:"ocp"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	u, err := s.unit(r, body.Device)
	if err != nil {
		writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	u.devMu.Lock()
	if body.OVP != nil {
		err = u.dev.SetOVP(*body.OVP)
	}
	if err == nil && body.OCP != nil {
		err = u.dev.SetOCP(*body.OCP)
	}
	u.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.writeState(w, u)
}

func (s *Server) allOff(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Device string `json:"device"`
	}
	if r.Body != nil {
		json.NewDecoder(r.Body).Decode(&body)
	}
	targets := s.units
	if body.Device != "" || r.URL.Query().Get("device") != "" {
		u, err := s.unit(r, body.Device)
		if err != nil {
			writeJSON(w, 404, map[string]any{"ok": false, "error": err.Error()})
			return
		}
		targets = []*deviceState{u}
	}
	off := make([]string, 0, len(targets))
	for _, u := range targets {
		u.devMu.Lock()
		err := u.dev.SetOutput(false)
		u.devMu.Unlock()
		if err != nil {
			writeJSON(w, 500, map[string]any{"ok": false, "device": u.id, "error": err.Error()})
			return
		}
		off = append(off, u.id)
	}
	writeJSON(w, 200, map[string]any{"ok": true, "outputs_off": off})
}

func (s *Server) static(w http.ResponseWriter, r *http.Request) {
	if s.opt.DistFS != nil {
		rel := strings.TrimPrefix(path.Clean(r.URL.Path), "/")
		if rel == "" || rel == "." {
			rel = "index.html"
		}
		data, err := fs.ReadFile(s.opt.DistFS, rel)
		if err != nil {
			if strings.HasPrefix(rel, "assets/") {
				writeJSON(w, 404, map[string]any{"ok": false, "error": "not found"})
				return
			}
			rel = "index.html"
			data, err = fs.ReadFile(s.opt.DistFS, rel)
			if err != nil {
				writeJSON(w, 404, map[string]any{"ok": false, "error": "not found"})
				return
			}
		}
		if rel == "index.html" {
			w.Header().Set("Cache-Control", "no-cache")
			if r.URL.Query().Get("desktop") == "1" {
				data = bytes.Replace(data, []byte("</head>"),
					[]byte(`<script type="module" src="/wails/runtime.js"></script></head>`), 1)
			}
		}
		w.Header().Set("Content-Type", mime.TypeByExtension(path.Ext(rel)))
		w.WriteHeader(200)
		w.Write(data)
		return
	}
	if s.opt.DistDir == "" {
		writeJSON(w, 404, map[string]any{"ok": false, "error": "not found"})
		return
	}
	rel := strings.TrimPrefix(path.Clean(r.URL.Path), "/")
	if rel == "" || rel == "." {
		rel = "index.html"
	}
	full := filepath.Join(s.opt.DistDir, filepath.FromSlash(rel))
	root := filepath.Clean(s.opt.DistDir) + string(os.PathSeparator)
	if !strings.HasPrefix(full, root) {
		writeJSON(w, 404, map[string]any{"ok": false, "error": "not found"})
		return
	}
	if info, err := os.Stat(full); err != nil || info.IsDir() {
		if strings.HasPrefix(rel, "assets/") {
			writeJSON(w, 404, map[string]any{"ok": false, "error": "not found"})
			return
		}
		rel = "index.html"
		full = filepath.Join(s.opt.DistDir, rel)
	}
	if rel == "index.html" {
		w.Header().Set("Cache-Control", "no-cache")
	}
	http.ServeFile(w, r, full)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func ListenAndServe(dev Backend, opt Options) error {
	s := New(dev, opt)
	defer s.Close()
	addr := net.JoinHostPort("127.0.0.1", "8765")
	return http.ListenAndServe(addr, s.Handler())
}

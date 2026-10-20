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

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/dp100"
)

type Backend interface {
	Snapshot() (dp100.Snapshot, error)
	Status() (mode, work byte)
	Measurement() (dp100.Measurement, error)
	SetVoltage(float64) error
	SetCurrent(float64) error
	SetOutput(bool) error
	SetOVP(float64) error
	SetOCP(float64) error
	DeviceInfo() dp100.Info
	Setpoints() (float64, float64)
	OutputOn() bool
	Limits() (float64, float64)
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

type Server struct {
	dev   Backend
	opt   Options
	mu    sync.RWMutex
	devMu sync.Mutex
	hist  []Sample
	stop  chan struct{}
}

func New(dev Backend, opt Options) *Server {
	if opt.MaxVoltage == 0 {
		opt.MaxVoltage = dp100.MaxVoltage
	}
	if opt.MaxCurrent == 0 {
		opt.MaxCurrent = dp100.MaxCurrent
	}
	if opt.SampleHz == 0 {
		opt.SampleHz = 20
	}
	s := &Server{dev: dev, opt: opt, stop: make(chan struct{})}
	go s.sampleLoop()
	return s
}

func (s *Server) Close() {
	select {
	case <-s.stop:
	default:
		close(s.stop)
	}
}

func (s *Server) Stop() { s.Close() }

func (s *Server) sampleLoop() {
	period := time.Second / time.Duration(s.opt.SampleHz)
	for {
		start := time.Now()
		s.devMu.Lock()
		m, err := s.dev.Measurement()
		s.devMu.Unlock()
		if err == nil {
			iv, tv := m.InputVoltage, m.Temperature
			s.mu.Lock()
			s.hist = append(s.hist, Sample{
				T: time.Now().UnixMilli(), Voltage: m.Voltage, Current: m.Current,
				Power: m.Power, InputVoltage: &iv, Temperature: &tv,
			})
			if len(s.hist) > s.opt.SampleHz*240 {
				s.hist = s.hist[len(s.hist)-s.opt.SampleHz*240:]
			}
			s.mu.Unlock()
		}
		if d := period - time.Since(start); d > 0 {
			select {
			case <-time.After(d):
			case <-s.stop:
				return
			}
		}
	}
}

func (s *Server) handler() http.Handler {
	mux := http.NewServeMux()
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

func (s *Server) state(w http.ResponseWriter, r *http.Request) {
	ch := 1
	s.mu.RLock()
	var last Sample
	have := len(s.hist) > 0
	if have {
		last = s.hist[len(s.hist)-1]
	}
	s.mu.RUnlock()

	s.devMu.Lock()
	info := s.dev.DeviceInfo()
	vset, iset := s.dev.Setpoints()
	out := s.dev.OutputOn()
	maxV, _ := s.dev.Limits()
	mode, work := s.dev.Status()
	if !have {
		if m, err := s.dev.Measurement(); err == nil {
			last = Sample{Voltage: m.Voltage, Current: m.Current, Power: m.Power,
				InputVoltage: &m.InputVoltage, Temperature: &m.Temperature}
			have = true
		}
	}
	s.devMu.Unlock()

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
	writeJSON(w, 200, map[string]any{
		"ok": true, "idn": fmt.Sprintf("ALIENTEK,DP100,%s,%.1f", info.SerialHex, info.App),
		"family": "dp100", "device_info": map[string]any{
			"model": info.Model, "hardware_version": info.Hardware, "app_version": info.App,
			"bootloader_version": info.Bootloader, "serial_number_hex": info.SerialHex,
		},
		"channels": []int{ch}, "ch": ch, "output": output,
		"setpoint":    map[string]any{"voltage": vset, "current": iset},
		"measurement": measurement, "status": status,
		"capabilities": map[string]bool{"power": true, "ovp": true, "ocp": true,
			"output_state": true, "input_voltage": true, "temperature": true},
		"limits": map[string]any{"max_voltage": maxV, "max_current": dp100.MaxCurrent,
			"max_ovp": dp100.MaxOVP, "max_ocp": dp100.MaxOCP, "max_power": 100.0},
	})
}

func (s *Server) history(w http.ResponseWriter, r *http.Request) {
	seconds := 62.0
	if v := r.URL.Query().Get("seconds"); v != "" {
		fmt.Sscanf(v, "%f", &seconds)
	}
	if seconds < 1 || seconds > 120 {
		seconds = 62
	}
	cutoff := time.Now().Add(-time.Duration(seconds * float64(time.Second))).UnixMilli()
	s.mu.RLock()
	out := make([]Sample, 0, len(s.hist))
	for _, sample := range s.hist {
		if sample.T >= cutoff {
			out = append(out, sample)
		}
	}
	s.mu.RUnlock()
	writeJSON(w, 200, map[string]any{"ok": true, "ch": 1, "samples": out})
}

func (s *Server) stream(w http.ResponseWriter, r *http.Request) {
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
		case <-s.stop:
			return
		default:
		}
		s.mu.RLock()
		var latest *Sample
		if len(s.hist) > 0 {
			x := s.hist[len(s.hist)-1]
			if x.T > last {
				latest = &x
			}
		}
		s.mu.RUnlock()
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
		Ch      int      `json:"ch"`
		Voltage *float64 `json:"voltage"`
		Current *float64 `json:"current"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	if body.Voltage != nil && (*body.Voltage < 0 || *body.Voltage > s.opt.MaxVoltage) {
		writeJSON(w, 400, map[string]any{"ok": false, "error": "voltage limit"})
		return
	}
	if body.Current != nil && (*body.Current < 0 || *body.Current > s.opt.MaxCurrent) {
		writeJSON(w, 400, map[string]any{"ok": false, "error": "current limit"})
		return
	}
	s.devMu.Lock()
	var err error
	if body.Voltage != nil {
		err = s.dev.SetVoltage(*body.Voltage)
	}
	if err == nil && body.Current != nil {
		err = s.dev.SetCurrent(*body.Current)
	}
	s.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.state(w, r)
}

func (s *Server) output(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Ch      int  `json:"ch"`
		On      bool `json:"on"`
		Confirm bool `json:"confirm"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	if body.On && !body.Confirm {
		writeJSON(w, 400, map[string]any{"ok": false, "error": "output ON requires confirm=true"})
		return
	}
	s.devMu.Lock()
	err := s.dev.SetOutput(body.On)
	s.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.state(w, r)
}

func (s *Server) protect(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Ch  int      `json:"ch"`
		OVP *float64 `json:"ovp"`
		OCP *float64 `json:"ocp"`
	}
	json.NewDecoder(r.Body).Decode(&body)
	s.devMu.Lock()
	var err error
	if body.OVP != nil {
		err = s.dev.SetOVP(*body.OVP)
	}
	if err == nil && body.OCP != nil {
		err = s.dev.SetOCP(*body.OCP)
	}
	s.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	s.state(w, r)
}

func (s *Server) allOff(w http.ResponseWriter, r *http.Request) {
	s.devMu.Lock()
	err := s.dev.SetOutput(false)
	s.devMu.Unlock()
	if err != nil {
		writeJSON(w, 400, map[string]any{"ok": false, "error": err.Error()})
		return
	}
	writeJSON(w, 200, map[string]any{"ok": true, "outputs_off": []int{1}})
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

package main

import (
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"math"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/config"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/driver"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/hid"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/scpi"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

func main() {
	if len(os.Args) < 2 {
		usage()
	}
	var err error
	switch os.Args[1] {
	case "setup":
		err = cmdSetup(os.Args[2:])
	case "test":
		err = cmdTest(os.Args[2:])
	case "list":
		err = cmdList(os.Args[2:])
	case "discover":
		err = cmdDiscover(os.Args[2:])
	case "doctor":
		err = cmdDoctor(os.Args[2:])
	case "config":
		err = cmdConfig(os.Args[2:])
	case "channels":
		err = cmdChannels(os.Args[2:])
	case "all-off":
		err = cmdAllOff(os.Args[2:])
	case "ramp":
		err = cmdRamp(os.Args[2:])
	case "sequence":
		err = cmdSequence(os.Args[2:])
	case "log":
		err = cmdLog(os.Args[2:])
	case "scpi":
		err = cmdRaw(os.Args[2:], false)
	case "query":
		err = cmdRaw(os.Args[2:], true)
	case "write":
		err = cmdRaw(os.Args[2:], false)
	case "idn":
		err = cmdIDN(os.Args[2:])
	case "get":
		err = cmdGet(os.Args[2:])
	case "measure":
		err = cmdMeasure(os.Args[2:])
	case "snapshot":
		err = cmdSnapshot(os.Args[2:])
	case "set":
		err = cmdSet(os.Args[2:])
	case "output":
		err = cmdOutput(os.Args[2:])
	case "protect":
		err = cmdProtect(os.Args[2:])
	case "web":
		err = cmdWeb(os.Args[2:])
	default:
		usage()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: psu <setup|test|list|discover|doctor|config|channels|idn|get|measure|snapshot|set|output|all-off|protect|ramp|sequence|log|web|scpi|query|write> [connection options]")
	os.Exit(2)
}

type selector struct {
	serial          string
	path            string
	host            string
	port            int
	resource        string
	serialPort      string
	baud            int
	family          string
	ch              int
	currentDecimals int
	timeout         float64
	maxVoltage      float64
	maxCurrent      float64
}

func addSelector(fs *flag.FlagSet) *selector {
	sel := &selector{}
	fs.StringVar(&sel.serial, "serial", "", "device serial number or serial port")
	fs.StringVar(&sel.path, "path", "", "driver-specific path")
	fs.StringVar(&sel.host, "host", "", "SCPI LAN host")
	fs.IntVar(&sel.port, "port", 5025, "SCPI LAN port")
	fs.StringVar(&sel.resource, "resource", "", "SCPI resource string")
	fs.StringVar(&sel.serialPort, "serial-port", "", "serial port, for example COM5")
	fs.IntVar(&sel.baud, "baud", 9600, "serial baud")
	fs.StringVar(&sel.family, "family", "", "SCPI family")
	fs.IntVar(&sel.ch, "ch", 1, "channel")
	fs.IntVar(&sel.currentDecimals, "current-decimals", 0, "B&K 168x current decimals")
	fs.Float64Var(&sel.timeout, "timeout", 3, "connection timeout in seconds")
	fs.Float64Var(&sel.maxVoltage, "max-voltage", 0, "safety voltage limit")
	fs.Float64Var(&sel.maxCurrent, "max-current", 0, "safety current limit")
	return sel
}

func (s *selector) endpoint() string {
	if s.resource != "" {
		return s.resource
	}
	if s.host != "" {
		return fmt.Sprintf("TCPIP::%s::%d::SOCKET", s.host, s.port)
	}
	if s.serialPort != "" {
		return fmt.Sprintf("ASRL::%s::%d", s.serialPort, s.baud)
	}
	if s.serial != "" && (strings.HasPrefix(strings.ToUpper(s.serial), "COM") || strings.HasPrefix(s.serial, "/dev/tty")) {
		return fmt.Sprintf("ASRL::%s::%d", s.serial, s.baud)
	}
	return ""
}

func (s *selector) scpiUnit() (*server.Unit, error) {
	resource := s.endpoint()
	if resource == "" {
		return nil, fmt.Errorf("no SCPI endpoint")
	}
	cfg := config.Load()
	maxV, maxI := s.maxVoltage, s.maxCurrent
	if maxV == 0 {
		maxV = cfg.MaxVoltage
	}
	if maxI == 0 {
		maxI = cfg.MaxCurrent
	}
	family := s.family
	if family == "" {
		family = cfg.Family
	}
	return scpi.Open(resource, scpi.OpenOptions{
		Channel: s.ch, Family: family, Timeout: time.Duration(s.timeout * float64(time.Second)),
		Baud: s.baud, MaxVoltage: maxV, MaxCurrent: maxI,
	})
}

func describe(f driver.Found) string {
	d := f.Device
	addr := d.Address
	if addr == "" {
		addr = d.Key
	}
	return fmt.Sprintf("%s\t%s\t%s\t%s", d.ID, d.Model, d.Family, addr)
}

func (s *selector) find() (driver.Found, error) {
	found, err := driver.Discover()
	if err != nil && len(found) == 0 {
		return driver.Found{}, err
	}
	var matches []driver.Found
	for _, f := range found {
		if s.path != "" && f.Device.Key != s.path && f.Device.Address != s.path {
			continue
		}
		if s.serial != "" && !strings.EqualFold(f.Device.ID, s.serial) && !strings.EqualFold(f.Device.Serial, s.serial) {
			continue
		}
		matches = append(matches, f)
	}
	if s.path == "" && s.serial == "" && len(matches) > 1 {
		var names []string
		for _, f := range matches {
			names = append(names, describe(f))
		}
		return driver.Found{}, fmt.Errorf("multiple devices found:\n%s\nuse --serial or --path", strings.Join(names, "\n"))
	}
	if len(matches) == 0 {
		return driver.Found{}, fmt.Errorf("no matching device")
	}
	return matches[0], nil
}

func (s *selector) open() (*server.Unit, error) {
	port := s.serialPort
	if port == "" && (strings.HasPrefix(strings.ToUpper(s.serial), "COM") || strings.HasPrefix(s.serial, "/dev/tty")) {
		port = s.serial
	}
	if s.family == "dps150" {
		if port == "" {
			return nil, fmt.Errorf("dps150 needs --serial-port")
		}
		return driver.OpenDPS150(port, s.baud)
	}
	if s.family == "bk168x" || s.family == "bk" {
		if port == "" {
			return nil, fmt.Errorf("bk168x needs --serial-port")
		}
		decimals := s.currentDecimals
		if decimals == 0 {
			decimals = config.Load().CurrentDecimals
		}
		return driver.OpenBK168x(port, decimals)
	}
	if s.endpoint() != "" || s.family != "" {
		return s.scpiUnit()
	}
	f, err := s.find()
	if err != nil {
		return nil, err
	}
	return driver.Open(f)
}

func (s *selector) openAll() ([]server.Unit, error) {
	if s.endpoint() != "" || s.family != "" || s.serial != "" || s.path != "" {
		u, err := s.open()
		if err != nil {
			return nil, err
		}
		return []server.Unit{*u}, nil
	}
	found, err := driver.Discover()
	if err != nil && len(found) == 0 {
		return nil, err
	}
	var units []server.Unit
	seen := make(map[string]bool)
	for _, f := range found {
		u, err := driver.Open(f)
		if err != nil {
			continue
		}
		id := u.ID
		if seen[id] {
			u.Dev.Close()
			continue
		}
		seen[id] = true
		units = append(units, *u)
	}
	if len(units) == 0 {
		return nil, fmt.Errorf("no devices found")
	}
	return units, nil
}

func closeAll(units []server.Unit) {
	for _, u := range units {
		u.Dev.Close()
	}
}

func emit(v any, asJSON *bool) {
	if *asJSON {
		b, _ := json.MarshalIndent(v, "", "  ")
		fmt.Println(string(b))
		return
	}
	switch x := v.(type) {
	case map[string]any:
		for k, val := range x {
			fmt.Printf("%s=%v ", k, val)
		}
		fmt.Println()
	default:
		fmt.Println(v)
	}
}

func cmdList(args []string) error {
	fs := flag.NewFlagSet("list", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	fs.Parse(args)
	found, err := driver.Discover()
	if err != nil && len(found) == 0 {
		return err
	}
	if *asJSON {
		out := make([]driver.Device, 0, len(found))
		for _, f := range found {
			out = append(out, f.Device)
		}
		b, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(b))
		return nil
	}
	for _, f := range found {
		fmt.Println(describe(f))
	}
	if len(found) == 0 {
		fmt.Println("no devices found")
	}
	return nil
}

func cmdIDN(args []string) error {
	fs := flag.NewFlagSet("idn", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	emit(map[string]any{
		"id": u.ID, "idn": u.IDN, "family": u.Family, "model": u.Model,
		"serial": u.Serial, "hardware": u.Hardware, "firmware": u.Firmware,
	}, asJSON)
	return nil
}

func cmdGet(args []string) error {
	fs := flag.NewFlagSet("get", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	v, i := u.Dev.Setpoints()
	emit(map[string]any{"voltage": v, "current": i, "output": u.Dev.OutputOn()}, asJSON)
	return nil
}

func cmdMeasure(args []string) error {
	fs := flag.NewFlagSet("measure", flag.ExitOnError)
	items := fs.String("items", "voltage,current,power", "comma-separated measurements")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	m, err := u.Dev.Measurement()
	if err != nil {
		return err
	}
	values := map[string]any{}
	for _, item := range strings.Split(*items, ",") {
		switch strings.TrimSpace(strings.ToLower(item)) {
		case "voltage":
			values["voltage"] = m.Voltage
		case "current":
			values["current"] = m.Current
		case "power":
			values["power"] = m.Power
		case "input_voltage", "input":
			values["input_voltage"] = m.InputVoltage
		case "temperature", "temp":
			values["temperature"] = m.Temperature
		}
	}
	emit(values, asJSON)
	return nil
}

func cmdSnapshot(args []string) error {
	fs := flag.NewFlagSet("snapshot", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	m, err := u.Dev.Measurement()
	if err != nil {
		return err
	}
	v, i := u.Dev.Setpoints()
	mode, work := u.Dev.Status()
	limitV, limitI := u.Dev.Limits()
	emit(map[string]any{
		"device": u.ID, "family": u.Family, "model": u.Model, "serial": u.Serial,
		"output": map[bool]string{false: "OFF", true: "ON"}[u.Dev.OutputOn()],
		"vset":   v, "iset": i,
		"measurement": map[string]any{"voltage": m.Voltage, "current": m.Current,
			"power": m.Power, "input_voltage": m.InputVoltage, "temperature": m.Temperature},
		"status":      map[string]any{"output_mode": map[byte]string{0: "CC", 1: "CV", 2: "OFF"}[mode], "work_state": work},
		"max_voltage": limitV, "max_current": limitI,
		"limits": u.Limits,
	}, asJSON)
	return nil
}

func cmdSet(args []string) error {
	fs := flag.NewFlagSet("set", flag.ExitOnError)
	voltage := fs.Float64("voltage", -1, "voltage setpoint")
	current := fs.Float64("current", -1, "current setpoint")
	verify := fs.Bool("verify", false, "read back the setpoints")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	var vp, ip *float64
	if *voltage >= 0 {
		vp = voltage
	}
	if *current >= 0 {
		ip = current
	}
	if err := checkUnitLimits(u, vp, ip); err != nil {
		return err
	}
	if *voltage >= 0 {
		if err := u.Dev.SetVoltage(*voltage); err != nil {
			return err
		}
	}
	if *current >= 0 {
		if err := u.Dev.SetCurrent(*current); err != nil {
			return err
		}
	}
	v, i := u.Dev.Setpoints()
	out := map[string]any{"voltage": v, "current": i}
	if *verify {
		out["readback"] = map[string]any{"voltage": v, "current": i}
	}
	emit(out, asJSON)
	return nil
}

func cmdOutput(args []string) error {
	yes, asJSON, on := false, false, false
	found := false
	sel := &selector{}
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch a {
		case "on":
			on, found = true, true
		case "off":
			on, found = false, true
		case "--yes", "-yes":
			yes = true
		case "--json", "-json":
			asJSON = true
		case "--serial", "-serial":
			if i+1 >= len(args) {
				return fmt.Errorf("--serial needs a value")
			}
			i++
			sel.serial = args[i]
		case "--path", "-path":
			if i+1 >= len(args) {
				return fmt.Errorf("--path needs a value")
			}
			i++
			sel.path = args[i]
		case "--host":
			if i+1 >= len(args) {
				return fmt.Errorf("--host needs a value")
			}
			i++
			sel.host = args[i]
		case "--port":
			if i+1 >= len(args) {
				return fmt.Errorf("--port needs a value")
			}
			i++
			sel.port, _ = strconv.Atoi(args[i])
		case "--resource":
			if i+1 >= len(args) {
				return fmt.Errorf("--resource needs a value")
			}
			i++
			sel.resource = args[i]
		case "--serial-port":
			if i+1 >= len(args) {
				return fmt.Errorf("--serial-port needs a value")
			}
			i++
			sel.serialPort = args[i]
		case "--baud":
			if i+1 >= len(args) {
				return fmt.Errorf("--baud needs a value")
			}
			i++
			sel.baud, _ = strconv.Atoi(args[i])
		case "--family":
			if i+1 >= len(args) {
				return fmt.Errorf("--family needs a value")
			}
			i++
			sel.family = args[i]
		case "--ch":
			if i+1 >= len(args) {
				return fmt.Errorf("--ch needs a value")
			}
			i++
			sel.ch, _ = strconv.Atoi(args[i])
		default:
			return fmt.Errorf("usage: psu output on|off --yes")
		}
	}
	if !found {
		return fmt.Errorf("usage: psu output on|off --yes")
	}
	if on && !yes {
		return fmt.Errorf("output ON requires --yes")
	}
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	if err := u.Dev.SetOutput(on); err != nil {
		return err
	}
	state := "off"
	if u.Dev.OutputOn() {
		state = "on"
	}
	emit(map[string]any{"state": state}, &asJSON)
	return nil
}

func cmdProtect(args []string) error {
	fs := flag.NewFlagSet("protect", flag.ExitOnError)
	ovp := fs.Float64("ovp", -1, "OVP")
	ocp := fs.Float64("ocp", -1, "OCP")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	if *ovp >= 0 {
		if err := u.Dev.SetOVP(*ovp); err != nil {
			return err
		}
	}
	if *ocp >= 0 {
		if err := u.Dev.SetOCP(*ocp); err != nil {
			return err
		}
	}
	ov, oc := u.Dev.Protection()
	emit(map[string]any{"ovp": ov, "ocp": oc}, asJSON)
	return nil
}

func cmdSetup(args []string) error {
	fs := flag.NewFlagSet("setup", flag.ExitOnError)
	asJSON := fs.Bool("json", true, "")
	fs.Parse(args)
	emit(map[string]any{
		"ok": true, "runtime": "go", "message": "The Go binary has no Python venv. USB HID works out of the box; SCPI uses TCP/serial resources.",
	}, asJSON)
	return nil
}

func cmdTest(args []string) error {
	dir, err := os.Getwd()
	if err != nil {
		return err
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "go.mod")); err == nil {
			break
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return fmt.Errorf("go.mod not found; run from the Go module")
		}
		dir = parent
	}
	cmd := exec.Command("go", "test", "./...")
	cmd.Dir = dir
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	return cmd.Run()
}

func cmdDiscover(args []string) error {
	fs := flag.NewFlagSet("discover", flag.ExitOnError)
	scan := fs.String("scan", "", "subnet to scan, for example 192.168.1.0/24")
	port := fs.Int("port", 5025, "SCPI port")
	asJSON := fs.Bool("json", false, "")
	fs.Parse(args)
	found, err := driver.Discover()
	if err != nil && len(found) == 0 {
		return err
	}
	items := make([]map[string]any, 0, len(found))
	for _, f := range found {
		items = append(items, map[string]any{
			"driver": f.Device.Driver, "id": f.Device.ID, "model": f.Device.Model,
			"family": f.Device.Family, "serial": f.Device.Serial, "address": f.Device.Address,
		})
	}
	if *scan != "" {
		items = append(items, scanSubnet(*scan, *port)...)
	}
	if *asJSON {
		b, _ := json.MarshalIndent(map[string]any{"ok": true, "instruments": items}, "", "  ")
		fmt.Println(string(b))
	} else {
		for _, item := range items {
			fmt.Printf("%v\t%v\t%v\t%v\n", item["id"], item["model"], item["family"], item["address"])
		}
	}
	return nil
}

func scanSubnet(cidr string, port int) []map[string]any {
	ip := net.ParseIP(strings.TrimSpace(cidr))
	if ip == nil {
		parts := strings.Split(cidr, ".")
		if len(parts) >= 3 {
			ip = net.ParseIP(strings.Join(parts[:3], ".") + ".0")
		}
	}
	if ip == nil {
		return nil
	}
	base := ip.To4()
	if base == nil {
		return nil
	}
	var out []map[string]any
	var mu sync.Mutex
	var wg sync.WaitGroup
	sem := make(chan struct{}, 64)
	for i := 1; i < 255; i++ {
		host := net.IPv4(base[0], base[1], base[2], byte(i)).String()
		wg.Add(1)
		go func(host string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()
			conn, err := net.DialTimeout("tcp", net.JoinHostPort(host, strconv.Itoa(port)), 300*time.Millisecond)
			if err != nil {
				return
			}
			defer conn.Close()
			_ = conn.SetDeadline(time.Now().Add(700 * time.Millisecond))
			_, _ = conn.Write([]byte("*IDN?\n"))
			buf := make([]byte, 512)
			n, _ := conn.Read(buf)
			if n > 0 {
				mu.Lock()
				out = append(out, map[string]any{"host": host, "idn": strings.TrimSpace(string(buf[:n]))})
				mu.Unlock()
			}
		}(host)
	}
	wg.Wait()
	return out
}

func cmdDoctor(args []string) error {
	fs := flag.NewFlagSet("doctor", flag.ExitOnError)
	fs.Parse(args)
	cfg := config.Load()
	info := map[string]any{
		"ok": true, "config_path": config.Path(), "config": cfg,
		"resources": cfg.Endpoints(),
	}
	if paths, err := hid.Paths(0x2E3C, 0xAF01); err == nil {
		info["hid"] = paths
	}
	var usbtmc, serials []string
	for _, pattern := range []string{"/dev/usbtmc*"} {
		if m, _ := filepath.Glob(pattern); len(m) > 0 {
			usbtmc = append(usbtmc, m...)
		}
	}
	for _, pattern := range []string{"/dev/ttyUSB*", "/dev/ttyACM*"} {
		if m, _ := filepath.Glob(pattern); len(m) > 0 {
			serials = append(serials, m...)
		}
	}
	info["usbtmc"], info["serial"] = usbtmc, serials
	b, _ := json.MarshalIndent(info, "", "  ")
	fmt.Println(string(b))
	return nil
}

func cmdConfig(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: psu config <list|get|set|unset> [key] [value]")
	}
	cfg := config.Load()
	switch args[0] {
	case "list":
		emit(map[string]any{"ok": true, "path": config.Path(), "config": cfg}, boolPtr(true))
	case "get":
		if len(args) < 2 {
			return fmt.Errorf("config get needs a key")
		}
		emit(map[string]any{"ok": true, "key": args[1], "value": configValue(cfg, args[1])}, boolPtr(true))
	case "set":
		if len(args) < 3 {
			return fmt.Errorf("config set needs a key and value")
		}
		if err := setConfigValue(&cfg, args[1], args[2]); err != nil {
			return err
		}
		if err := config.Save(cfg); err != nil {
			return err
		}
		emit(map[string]any{"ok": true, "set": map[string]any{args[1]: args[2]}}, boolPtr(true))
	case "unset":
		if len(args) < 2 {
			return fmt.Errorf("config unset needs a key")
		}
		if err := unsetConfigValue(&cfg, args[1]); err != nil {
			return err
		}
		if err := config.Save(cfg); err != nil {
			return err
		}
		emit(map[string]any{"ok": true, "removed": args[1]}, boolPtr(true))
	default:
		return fmt.Errorf("unknown config command %q", args[0])
	}
	return nil
}

func boolPtr(v bool) *bool { return &v }

func configValue(c config.Config, key string) any {
	switch key {
	case "resource":
		return c.Resource
	case "host":
		return c.Host
	case "port":
		return c.Port
	case "serial_port", "serial":
		return c.SerialPort
	case "baud":
		return c.Baud
	case "timeout":
		return c.Timeout
	case "family":
		return c.Family
	case "max_voltage":
		return c.MaxVoltage
	case "max_current":
		return c.MaxCurrent
	case "safe_off":
		return c.SafeOff
	case "current_decimals":
		return c.CurrentDecimals
	case "resources":
		return c.Resources
	}
	return nil
}

func setConfigValue(c *config.Config, key, value string) error {
	switch key {
	case "resource":
		c.Resource = value
	case "host":
		c.Host = value
	case "serial_port", "serial":
		c.SerialPort = value
	case "family":
		c.Family = value
	case "port", "baud":
		n, err := strconv.Atoi(value)
		if err != nil {
			return err
		}
		if key == "port" {
			c.Port = n
		} else {
			c.Baud = n
		}
	case "timeout", "max_voltage", "max_current":
		f, err := strconv.ParseFloat(value, 64)
		if err != nil {
			return err
		}
		switch key {
		case "timeout":
			c.Timeout = f
		case "max_voltage":
			c.MaxVoltage = f
		default:
			c.MaxCurrent = f
		}
	case "current_decimals":
		n, err := strconv.Atoi(value)
		if err != nil {
			return err
		}
		c.CurrentDecimals = n
	case "safe_off":
		c.SafeOff = value == "1" || strings.EqualFold(value, "true") || strings.EqualFold(value, "yes") || strings.EqualFold(value, "on")
	case "resources":
		c.Resources = nil
		for _, r := range strings.Split(value, ",") {
			if r = strings.TrimSpace(r); r != "" {
				c.Resources = append(c.Resources, r)
			}
		}
	default:
		return fmt.Errorf("unknown config key %q", key)
	}
	return nil
}

func unsetConfigValue(c *config.Config, key string) error {
	switch key {
	case "resource":
		c.Resource = ""
	case "host":
		c.Host = ""
	case "serial_port", "serial":
		c.SerialPort = ""
	case "family":
		c.Family = ""
	case "resources":
		c.Resources = nil
	default:
		return fmt.Errorf("unknown config key %q", key)
	}
	return nil
}

func cmdChannels(args []string) error {
	fs := flag.NewFlagSet("channels", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	emit(map[string]any{
		"ok": true, "id": u.ID, "idn": u.IDN, "family": u.Family,
		"name": u.Name, "channels": u.Channels, "capabilities": u.Caps, "limits": u.Limits,
	}, asJSON)
	return nil
}

func cmdAllOff(args []string) error {
	fs := flag.NewFlagSet("all-off", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	units, err := sel.openAll()
	if err != nil {
		return err
	}
	defer closeAll(units)
	var done []string
	for _, u := range units {
		if err := u.Dev.SetOutput(false); err == nil {
			done = append(done, u.ID)
		}
	}
	emit(map[string]any{"ok": true, "outputs_off": done}, asJSON)
	return nil
}

func checkUnitLimits(u *server.Unit, v, i *float64) error {
	if v != nil && u.Limits.MaxVoltage > 0 && *v > u.Limits.MaxVoltage {
		return fmt.Errorf("voltage %.3f exceeds device limit %.3f", *v, u.Limits.MaxVoltage)
	}
	if i != nil && u.Limits.MaxCurrent > 0 && *i > u.Limits.MaxCurrent {
		return fmt.Errorf("current %.3f exceeds device limit %.3f", *i, u.Limits.MaxCurrent)
	}
	return nil
}

func cmdRamp(args []string) error {
	fs := flag.NewFlagSet("ramp", flag.ExitOnError)
	to := fs.Float64("to", math.NaN(), "target voltage")
	start := fs.Float64("start", math.NaN(), "start voltage")
	step := fs.Float64("step", 0.1, "step voltage")
	delay := fs.Float64("delay", 0.2, "delay between steps")
	yes := fs.Bool("yes", false, "confirm the ramp")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	if !*yes {
		return fmt.Errorf("ramp changes the output; pass --yes")
	}
	if math.IsNaN(*to) {
		return fmt.Errorf("ramp requires --to")
	}
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	if err := checkUnitLimits(u, to, nil); err != nil {
		return err
	}
	cfg := config.Load()
	v0, _ := u.Dev.Setpoints()
	if !math.IsNaN(*start) {
		v0 = *start
	}
	st := math.Abs(*step)
	if st == 0 {
		st = 0.1
	}
	v := v0
	steps := 0
	dir := 1.0
	if *to < v0 {
		dir = -1
	}
	fail := func(err error) error {
		if cfg.SafeOff {
			_ = u.Dev.SetOutput(false)
		}
		return err
	}
	for (dir > 0 && v < *to) || (dir < 0 && v > *to) {
		if dir > 0 {
			v = math.Min(*to, v+st)
		} else {
			v = math.Max(*to, v-st)
		}
		if err := checkUnitLimits(u, &v, nil); err != nil {
			return fail(err)
		}
		if err := u.Dev.SetVoltage(math.Round(v*10000) / 10000); err != nil {
			return fail(err)
		}
		steps++
		time.Sleep(time.Duration(math.Max(0, *delay) * float64(time.Second)))
	}
	emit(map[string]any{"ok": true, "id": u.ID, "from": v0, "to": *to, "steps": steps, "safe_off": cfg.SafeOff}, asJSON)
	return nil
}

func cmdSequence(args []string) error {
	fs := flag.NewFlagSet("sequence", flag.ExitOnError)
	yes := fs.Bool("yes", false, "confirm the sequence")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	flags, file := splitFlagsAndCommand(args)
	fs.Parse(flags)
	if !*yes {
		return fmt.Errorf("sequence changes the output; pass --yes")
	}
	if file == "" {
		return fmt.Errorf("sequence needs a JSON file")
	}
	b, err := os.ReadFile(file)
	if err != nil {
		return err
	}
	var raw json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	var steps []struct {
		Voltage *float64 `json:"voltage"`
		Current *float64 `json:"current"`
		Delay   float64  `json:"delay"`
	}
	if err := json.Unmarshal(raw, &steps); err != nil {
		var wrap struct {
			Steps []struct {
				Voltage *float64 `json:"voltage"`
				Current *float64 `json:"current"`
				Delay   float64  `json:"delay"`
			} `json:"steps"`
		}
		if err2 := json.Unmarshal(raw, &wrap); err2 != nil {
			return fmt.Errorf("sequence must be a list or an object with steps: %w", err)
		}
		steps = wrap.Steps
	}
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	cfg := config.Load()
	applied := make([]map[string]any, 0, len(steps))
	for i, step := range steps {
		if err := checkUnitLimits(u, step.Voltage, step.Current); err != nil {
			if cfg.SafeOff {
				_ = u.Dev.SetOutput(false)
			}
			return err
		}
		if step.Voltage != nil {
			if err := u.Dev.SetVoltage(*step.Voltage); err != nil {
				return err
			}
		}
		if step.Current != nil {
			if err := u.Dev.SetCurrent(*step.Current); err != nil {
				return err
			}
		}
		applied = append(applied, map[string]any{"step": i + 1, "voltage": step.Voltage, "current": step.Current})
		time.Sleep(time.Duration(math.Max(0, step.Delay) * float64(time.Second)))
	}
	emit(map[string]any{"ok": true, "id": u.ID, "steps": applied, "safe_off": cfg.SafeOff}, asJSON)
	return nil
}

func cmdLog(args []string) error {
	fs := flag.NewFlagSet("log", flag.ExitOnError)
	duration := fs.Float64("duration", 10, "seconds")
	interval := fs.Float64("interval", 0.5, "seconds")
	out := fs.String("out", "psu-log.csv", "CSV output")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	f, err := os.Create(*out)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	_ = w.Write([]string{"time", "voltage", "current", "power"})
	deadline := time.Now().Add(time.Duration(*duration * float64(time.Second)))
	rows := 0
	for time.Now().Before(deadline) {
		m, err := u.Dev.Measurement()
		if err != nil {
			return err
		}
		_ = w.Write([]string{time.Now().Format(time.RFC3339Nano), fmt.Sprint(m.Voltage), fmt.Sprint(m.Current), fmt.Sprint(m.Power)})
		rows++
		time.Sleep(time.Duration(math.Max(0, *interval) * float64(time.Second)))
	}
	w.Flush()
	if err := w.Error(); err != nil {
		return err
	}
	state := "OFF"
	if u.Dev.OutputOn() {
		state = "ON"
		fmt.Fprintln(os.Stderr, "[warn] output is still ON")
	}
	emit(map[string]any{"ok": true, "id": u.ID, "samples": rows, "out": *out, "output": state}, asJSON)
	return nil
}

func splitFlagsAndCommand(args []string) ([]string, string) {
	valueFlags := map[string]bool{"--host": true, "--port": true, "--resource": true,
		"--serial": true, "--serial-port": true, "--baud": true, "--family": true,
		"--ch": true, "--timeout": true, "--max-voltage": true, "--max-current": true,
		"--path": true}
	var flags []string
	var command string
	for i := 0; i < len(args); i++ {
		a := args[i]
		if strings.HasPrefix(a, "-") {
			flags = append(flags, a)
			if valueFlags[a] && i+1 < len(args) {
				i++
				flags = append(flags, args[i])
			}
			continue
		}
		if command == "" {
			command = a
		} else {
			command += " " + a
		}
	}
	return flags, command
}

func cmdRaw(args []string, forceQuery bool) error {
	fs := flag.NewFlagSet("scpi", flag.ExitOnError)
	query := fs.Bool("query", forceQuery, "send a query")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	flags, command := splitFlagsAndCommand(args)
	fs.Parse(flags)
	if command == "" {
		return fmt.Errorf("raw SCPI needs a command")
	}
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
	raw, ok := u.Dev.(scpi.RawSCPI)
	if !ok {
		return fmt.Errorf("raw SCPI is not available on %s", u.Family)
	}
	cmd := command
	if *query {
		resp, err := raw.RawQuery(cmd)
		if err != nil {
			return err
		}
		emit(map[string]any{"ok": true, "command": cmd, "response": resp}, asJSON)
	} else {
		if err := raw.RawWrite(cmd); err != nil {
			return err
		}
		emit(map[string]any{"ok": true, "command": cmd, "response": nil}, asJSON)
	}
	return nil
}

func cmdWeb(args []string) error {
	fs := flag.NewFlagSet("web", flag.ExitOnError)
	bind := fs.String("bind", "127.0.0.1", "bind address")
	port := fs.Int("web-port", 8765, "HTTP port")
	openFlag := fs.Bool("open", false, "open the default browser")
	allowOrigin := fs.String("allow-origin", "", "CORS origin, for example * or null")
	dist := fs.String("webapp", "", "path to webapp/dist")
	sel := addSelector(fs)
	fs.Parse(args)

	root := *dist
	if root == "" {
		root = findWebapp()
	}
	units, err := sel.openAll()
	if err != nil {
		return err
	}
	defer closeAll(units)
	srv := server.NewMulti(units, server.Options{DistDir: root, AllowOrigin: *allowOrigin})
	defer srv.Close()
	addr := net.JoinHostPort(*bind, fmt.Sprint(*port))
	url := fmt.Sprintf("http://localhost:%d/", *port)
	fmt.Println("web UI:", url)
	if root == "" {
		fmt.Println("warning: webapp/dist not found; API only")
	}
	if *openFlag {
		openBrowser(url)
	}
	return http.ListenAndServe(addr, srv.Handler())
}

func findWebapp() string {
	candidates := []string{"webapp/dist", "../webapp/dist", "../../webapp/dist"}
	if exe, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Join(filepath.Dir(exe), "webapp", "dist"))
	}
	for _, c := range candidates {
		if info, err := os.Stat(filepath.Join(c, "index.html")); err == nil && !info.IsDir() {
			abs, _ := filepath.Abs(c)
			return abs
		}
	}
	return ""
}

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		if os.Getenv("WSL_DISTRO_NAME") != "" {
			cmd = exec.Command("cmd.exe", "/c", "start", "", url)
		} else {
			cmd = exec.Command("xdg-open", url)
		}
	}
	_ = cmd.Start()
}

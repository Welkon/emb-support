package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/driver"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
)

func main() {
	if len(os.Args) < 2 {
		usage()
	}
	var err error
	switch os.Args[1] {
	case "list":
		err = cmdList(os.Args[2:])
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
	fmt.Fprintln(os.Stderr, "usage: psu <list|idn|get|measure|snapshot|set|output|protect|web> [--serial <id>] [options]")
	os.Exit(2)
}

type selector struct {
	serial string
	path   string
}

func addSelector(fs *flag.FlagSet) *selector {
	sel := &selector{}
	fs.StringVar(&sel.serial, "serial", "", "device serial number")
	fs.StringVar(&sel.path, "path", "", "driver-specific address or path")
	return sel
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
	f, err := s.find()
	if err != nil {
		return nil, err
	}
	return driver.Open(f)
}

func (s *selector) openAll() ([]server.Unit, error) {
	if s.serial != "" || s.path != "" {
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
	emit(map[string]any{"voltage": m.Voltage, "current": m.Current, "power": m.Power,
		"input_voltage": m.InputVoltage, "temperature": m.Temperature}, asJSON)
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
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	u, err := sel.open()
	if err != nil {
		return err
	}
	defer u.Dev.Close()
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
	emit(map[string]any{"voltage": v, "current": i}, asJSON)
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

func cmdWeb(args []string) error {
	fs := flag.NewFlagSet("web", flag.ExitOnError)
	bind := fs.String("bind", "127.0.0.1", "bind address")
	port := fs.Int("port", 8765, "HTTP port")
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

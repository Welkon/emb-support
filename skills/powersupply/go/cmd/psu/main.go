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

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/dp100"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/hid"
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
	fs.StringVar(&sel.serial, "serial", "", "DP100 serial number")
	fs.StringVar(&sel.path, "path", "", "HID device path")
	return sel
}

func (s *selector) open() (*dp100.Device, error) {
	paths, err := hid.Paths(0x2E3C, 0xAF01)
	if err != nil {
		return nil, err
	}
	if s.path != "" {
		return openPath(s.path)
	}
	if s.serial != "" {
		for _, path := range paths {
			d, err := openPath(path)
			if err != nil {
				continue
			}
			if strings.EqualFold(d.Info.SerialHex, s.serial) {
				return d, nil
			}
			d.Close()
		}
		return nil, fmt.Errorf("no DP100 with serial %q", s.serial)
	}
	if len(paths) == 0 {
		return nil, fmt.Errorf("no DP100 found")
	}
	if len(paths) > 1 {
		var found []string
		for _, path := range paths {
			d, err := openPath(path)
			if err != nil {
				continue
			}
			found = append(found, d.Info.SerialHex)
			d.Close()
		}
		return nil, fmt.Errorf("multiple DP100 devices found (%s); use --serial", strings.Join(found, ", "))
	}
	return openPath(paths[0])
}

func (s *selector) openAll() ([]server.Unit, []*dp100.Device, error) {
	if s.serial != "" || s.path != "" {
		d, err := s.open()
		if err != nil {
			return nil, nil, err
		}
		return []server.Unit{{ID: d.Info.SerialHex, Name: d.Info.Model, Dev: d}}, []*dp100.Device{d}, nil
	}
	paths, err := hid.Paths(0x2E3C, 0xAF01)
	if err != nil {
		return nil, nil, err
	}
	var units []server.Unit
	var devices []*dp100.Device
	seen := make(map[string]bool)
	for _, path := range paths {
		d, err := openPath(path)
		if err != nil {
			continue
		}
		id := d.Info.SerialHex
		if id == "" {
			id = path
		}
		if seen[id] {
			d.Close()
			continue
		}
		seen[id] = true
		units = append(units, server.Unit{ID: id, Name: d.Info.Model, Dev: d})
		devices = append(devices, d)
	}
	if len(units) == 0 {
		return nil, nil, fmt.Errorf("no DP100 found")
	}
	return units, devices, nil
}

func openPath(path string) (*dp100.Device, error) {
	t, err := hid.OpenPath(path)
	if err != nil {
		return nil, err
	}
	d, err := dp100.Open(t)
	if err != nil {
		t.Close()
		return nil, err
	}
	return d, nil
}

func closeAll(devices []*dp100.Device) {
	for _, d := range devices {
		d.Close()
	}
}

func emit(v any, asJSON *bool) {
	if *asJSON {
		b, _ := json.MarshalIndent(v, "", "  ")
		fmt.Println(string(b))
		return
	}
	switch x := v.(type) {
	case dp100.Info:
		fmt.Printf("%s fw=%.1f hw=%.1f serial=%s\n", x.Model, x.App, x.Hardware, x.SerialHex)
	case dp100.Snapshot:
		fmt.Printf("%s V=%.3f I=%.3f P=%.3f Vin=%.3f T=%.1f VSet=%.3f ISet=%.3f\n",
			x.Output, x.Measurement.Voltage, x.Measurement.Current, x.Measurement.Power,
			x.Measurement.InputVoltage, x.Measurement.Temperature, x.VSet, x.ISet)
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
	paths, err := hid.Paths(0x2E3C, 0xAF01)
	if err != nil {
		return err
	}
	var out []dp100.Info
	for _, path := range paths {
		d, err := openPath(path)
		if err != nil {
			continue
		}
		out = append(out, d.Info)
		d.Close()
	}
	if *asJSON {
		b, _ := json.MarshalIndent(out, "", "  ")
		fmt.Println(string(b))
		return nil
	}
	for _, info := range out {
		fmt.Printf("%s %s fw=%.1f hw=%.1f\n", info.SerialHex, info.Model, info.App, info.Hardware)
	}
	if len(out) == 0 {
		fmt.Println("no DP100 found")
	}
	return nil
}

func cmdIDN(args []string) error {
	fs := flag.NewFlagSet("idn", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	emit(d.Info, asJSON)
	return nil
}

func cmdGet(args []string) error {
	fs := flag.NewFlagSet("get", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	emit(map[string]any{"voltage": d.V, "current": d.I, "output": d.Out}, asJSON)
	return nil
}

func cmdMeasure(args []string) error {
	fs := flag.NewFlagSet("measure", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	m, err := d.Measurement()
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
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	s, err := d.Snapshot()
	if err != nil {
		return err
	}
	emit(s, asJSON)
	return nil
}

func cmdSet(args []string) error {
	fs := flag.NewFlagSet("set", flag.ExitOnError)
	voltage := fs.Float64("voltage", -1, "voltage setpoint")
	current := fs.Float64("current", -1, "current setpoint")
	asJSON := fs.Bool("json", false, "")
	sel := addSelector(fs)
	fs.Parse(args)
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	if *voltage >= 0 {
		if err := d.SetVoltage(*voltage); err != nil {
			return err
		}
	}
	if *current >= 0 {
		if err := d.SetCurrent(*current); err != nil {
			return err
		}
	}
	emit(map[string]any{"voltage": d.V, "current": d.I}, asJSON)
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
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	if err := d.SetOutput(on); err != nil {
		return err
	}
	state := "off"
	if d.Out {
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
	d, err := sel.open()
	if err != nil {
		return err
	}
	defer d.Close()
	if *ovp >= 0 {
		if err := d.SetOVP(*ovp); err != nil {
			return err
		}
	}
	if *ocp >= 0 {
		if err := d.SetOCP(*ocp); err != nil {
			return err
		}
	}
	emit(map[string]any{"ovp": d.OVP, "ocp": d.OCP}, asJSON)
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
	units, devices, err := sel.openAll()
	if err != nil {
		return err
	}
	defer closeAll(devices)
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

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
	fmt.Fprintln(os.Stderr, "usage: psu <idn|get|measure|snapshot|set|output|protect|web> [options]")
	os.Exit(2)
}

func open() (*dp100.Device, error) {
	t, err := hid.Open(0x2E3C, 0xAF01)
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

func cmdIDN(args []string) error {
	fs := flag.NewFlagSet("idn", flag.ExitOnError)
	asJSON := fs.Bool("json", false, "")
	fs.Parse(args)
	d, err := open()
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
	fs.Parse(args)
	d, err := open()
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
	fs.Parse(args)
	d, err := open()
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
	fs.Parse(args)
	d, err := open()
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
	fs.Parse(args)
	d, err := open()
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
	for _, a := range args {
		switch a {
		case "on":
			on, found = true, true
		case "off":
			on, found = false, true
		case "--yes", "-yes":
			yes = true
		case "--json", "-json":
			asJSON = true
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
	d, err := open()
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
	fs.Parse(args)
	d, err := open()
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
	fs.Parse(args)

	root := *dist
	if root == "" {
		root = findWebapp()
	}
	d, err := open()
	if err != nil {
		return err
	}
	defer d.Close()
	srv := server.New(d, server.Options{DistDir: root, AllowOrigin: *allowOrigin})
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

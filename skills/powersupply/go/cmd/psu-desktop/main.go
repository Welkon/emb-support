//go:build windows

package main

import (
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/dp100"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/hid"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/server"
	"github.com/Welkon/emb-support/skills/powersupply/go/internal/webassets"
	"github.com/wailsapp/wails/v3/pkg/application"
)

func externalWebDir() string {
	if dir := os.Getenv("PSU_WEB_DIR"); dir != "" {
		if _, err := os.Stat(filepath.Join(dir, "index.html")); err == nil {
			return dir
		}
	}
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	dir := filepath.Join(filepath.Dir(exe), "web", "current")
	if _, err := os.Stat(filepath.Join(dir, "index.html")); err == nil {
		return dir
	}
	return ""
}

func openAll() ([]server.Unit, []*dp100.Device, error) {
	paths, err := hid.Paths(0x2E3C, 0xAF01)
	if err != nil {
		return nil, nil, err
	}
	var units []server.Unit
	var devices []*dp100.Device
	seen := make(map[string]bool)
	for _, path := range paths {
		t, err := hid.OpenPath(path)
		if err != nil {
			log.Printf("skip %s: %v", path, err)
			continue
		}
		dev, err := dp100.Open(t)
		if err != nil {
			t.Close()
			log.Printf("skip %s: %v", path, err)
			continue
		}
		info := dev.DeviceInfo()
		id := info.SerialHex
		if id == "" {
			id = path
		}
		if seen[id] {
			dev.Close()
			continue
		}
		seen[id] = true
		units = append(units, server.Unit{ID: id, Name: info.Model, Dev: dev})
		devices = append(devices, dev)
	}
	if len(units) == 0 {
		return nil, nil, fmt.Errorf("no DP100 found on %d HID path(s)", len(paths))
	}
	return units, devices, nil
}

func main() {
	units, devices, err := openAll()
	if err != nil {
		log.Fatal("DP100: ", err)
	}
	defer func() {
		for _, dev := range devices {
			dev.Close()
		}
	}()

	assets, err := fs.Sub(webassets.FS, "dist")
	if err != nil {
		log.Fatal(err)
	}
	// A writable web/current directory next to the executable overrides the
	// embedded UI. This lets the app update its frontend without a new binary.
	if dir := externalWebDir(); dir != "" {
		assets = os.DirFS(dir)
	}
	srv := server.NewMulti(units, server.Options{DistFS: assets})
	defer srv.Close()

	app := application.New(application.Options{
		Name:        "Power Supply",
		Description: "Programmable power supply control",
		Assets: application.AssetOptions{
			Handler: srv.Handler(),
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: true,
		},
	})
	app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:      "Power Supply - DP100",
		Width:      1280,
		Height:     900,
		MinWidth:   980,
		MinHeight:  720,
		Frameless:  true,
		StartState: application.WindowStateMaximised,
		URL:        "/?desktop=1",
	})
	if err := app.Run(); err != nil {
		log.Fatal(err)
	}
}

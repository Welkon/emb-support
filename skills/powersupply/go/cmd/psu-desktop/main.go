//go:build windows

package main

import (
	"fmt"
	"io/fs"
	"log"
	"os"
	"path/filepath"

	"github.com/Welkon/emb-support/skills/powersupply/go/internal/driver"
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

func openAll() ([]server.Unit, error) {
	found, err := driver.Discover()
	if err != nil && len(found) == 0 {
		return nil, err
	}
	var units []server.Unit
	seen := make(map[string]bool)
	for _, f := range found {
		u, err := driver.Open(f)
		if err != nil {
			log.Printf("skip %s: %v", f.Device.Address, err)
			continue
		}
		if seen[u.ID] {
			u.Dev.Close()
			continue
		}
		seen[u.ID] = true
		units = append(units, *u)
	}
	if len(units) == 0 {
		return nil, fmt.Errorf("no power supply found")
	}
	return units, nil
}

func main() {
	units, err := openAll()
	if err != nil {
		log.Fatal("PSU: ", err)
	}
	defer func() {
		for _, u := range units {
			u.Dev.Close()
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

//go:build windows

package main

import (
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

func main() {
	t, err := hid.Open(0x2E3C, 0xAF01)
	if err != nil {
		log.Fatal("DP100: ", err)
	}
	dev, err := dp100.Open(t)
	if err != nil {
		t.Close()
		log.Fatal("DP100: ", err)
	}
	defer dev.Close()

	assets, err := fs.Sub(webassets.FS, "dist")
	if err != nil {
		log.Fatal(err)
	}
	// A writable web/current directory next to the executable overrides the
	// embedded UI. This lets the app update its frontend without a new binary.
	if dir := externalWebDir(); dir != "" {
		assets = os.DirFS(dir)
	}
	srv := server.New(dev, server.Options{DistFS: assets})
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

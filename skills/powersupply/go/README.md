# PSU Go Core

Prototype of the Go power-supply core.

## Implemented

- DP100 frame encode/decode with CRC-16/MODBUS.
- DP100 info, basic, settings, output, and protection parsing.
- OVP/OCP writes with index `0x40` and setpoint preservation.
- Limits: 30 V, 5 A, OVP 30.5 V, OCP 5.05 A.
- Pure-Go Windows HID transport (SetupAPI + overlapped I/O).
- Linux hidraw transport.
- CLI: `idn`, `get`, `measure`, `snapshot`, `set`, `output`, `protect`, `web`.
- HTTP API: `/api/state`, `/api/history`, `/api/stream` (SSE), `/api/set`,
  `/api/output`, `/api/protect`, `/api/all-off`.
- Background 20 Hz sampler with a 4-minute ring buffer.
- Static React UI and optional CORS for a standalone single-file build.
- Wails v3 frameless desktop window with custom drag, minimise, maximise, and close.
- Desktop chart polling through `/api/history`; the browser keeps SSE.
- React UI embedded in the executable.
- External `web/current` or `PSU_WEB_DIR` overrides the embedded UI.
- Golden-frame, fake-transport, and server tests.

## Verified on hardware

Windows, pure Go HID, CGO disabled:

- Device info and snapshot.
- Setpoint and output ON/OFF.
- Protection write with index `0x40`.
- OVP trip: output turned off and `work_state` became 1.

## Not yet

- Config, logging, sequences, scans, presets.
- Tray icon and signed updater.
- Windows signing and updater.

## Build

```sh
go test ./...
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o psu.exe ./cmd/psu
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o psu ./cmd/psu
```

Desktop build. Run it on Windows with WebView2 installed:

```sh
./scripts/build_windows.sh
```

The desktop window starts maximised. `scripts/sync_web.sh` copies
`webapp/dist` into `internal/webassets/dist` before the desktop build. To update only the UI, put a build in
`web/current` next to the executable. The desktop app uses it instead of the
embedded copy.

Run only with the DP100 on the same OS:

```sh
psu idn --json
psu get
psu measure
psu set --voltage 3.3 --current 0.5
psu output on --yes
psu output off
psu protect --ovp 30.5 --ocp 5.05
psu web --open
```

The `web` command uses `webapp/dist` and binds to `127.0.0.1:8765` by default.

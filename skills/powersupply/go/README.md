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
- Golden-frame, fake-transport, and server tests.

## Verified on hardware

Windows, pure Go HID, CGO disabled:

- Device info and snapshot.
- Setpoint and output ON/OFF.
- Protection write with index `0x40`.
- OVP trip: output turned off and `work_state` became 1.

## Not yet

- Wails v3 desktop shell.
- Config, logging, sequences, scans, presets.
- Windows signing and updater.

## Build

```sh
go test ./...
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o psu.exe ./cmd/psu
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o psu ./cmd/psu
```

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

# PSU Go Core

Go implementation of the programmable power-supply skill.

## Implemented

- DP100 USB HID driver, including OVP/OCP index `0x40`.
- FNIRSI DPS-150 serial driver.
- B&K 168x serial driver.
- Generic SCPI driver over:
  - `TCPIP::host::5025::SOCKET`
  - `ASRL::COM3::9600`
  - `serial:///dev/ttyUSB0?baud=9600`
  - Linux `/dev/usbtmc*`
- SCPI dialects: Rigol, Keysight/Agilent, Siglent, Rohde & Schwarz,
  Korad, GW Instek, B&K Precision, Owon, Itech, Aim-TTi, Generic.
- Driver registry. One driver can be added without changing the server or UI.
- Mixed devices. Each unit is sampled independently at 20 Hz and keeps its own
  history. API requests use `device=<id>`.
- Frameless Wails v3 desktop app with device tabs and `All off`.
- HTTP API: `/api/devices`, `/api/state`, `/api/history`, `/api/stream`,
  `/api/set`, `/api/output`, `/api/protect`, `/api/all-off`.
- CLI:
  `setup`, `test`, `list`, `discover`, `doctor`, `config`, `channels`,
  `idn`, `get`, `measure`, `status` (alias of `snapshot`), `set`, `output`, `all-off`, `protect`,
  `ramp`, `sequence`, `log`, `web`, `scpi`, `query`, `write`.
- Per-unit capabilities and limits. The UI hides unsupported fields.
- Golden-frame, fake-transport, SCPI dialect, TCP transport, and server tests.

## Limit of the current port

Windows USB-TMC/VISA resources are not implemented. Use LAN SCPI, serial SCPI,
or Linux `/dev/usbtmc*`. The DP100 uses pure-Go HID on Windows and Linux.

## Drivers

The server and UI do not know model details. A driver discovers devices and
returns a `server.Unit` with:

- `family`
- channels
- capabilities
- limits

Current registry:

- `dp100`
- `dps150`
- `bk168x`
- `scpi`

To add a model:

1. Implement `driver.Driver` with `Discover` and `Open`.
2. Return a `server.Unit` with the correct metadata.
3. Register the driver from `init`.
4. Add a driver test.

## Configuration

The config file is `$PSU_HOME/config.json`. Without `PSU_HOME` it follows the
same order as the Python CLI (`scripts/psuscpi/common.py:data_home`): an existing
`.emb-agent/bench/psu` inside the project, then that path for a project with a
`.emb-agent` marker and no legacy dir, then `~/.local/share/psu`. `PSU_CONFIG`
overrides the file itself. Both CLIs therefore read one file, and a sandbox that
only allows workspace writes needs no approval. The most useful keys are:

```sh
psu config set host 192.168.1.50
psu config set port 5025
psu config set family generic
psu config set resource 'ASRL::COM5::9600'
psu config set serial_port COM5
psu config set family dps150
psu config set resources 'TCPIP::192.168.1.51::5025::SOCKET,TCPIP::192.168.1.52::5025::SOCKET'
psu config set max_voltage 60
psu config set max_current 5
psu config set safe_off true
psu config list
```

Environment overrides: `PSU_RESOURCE`, `PSU_RESOURCES`, `PSU_HOST`, `PSU_PORT`,
`PSU_SERIAL_PORT`, `PSU_BAUD`, `PSU_FAMILY`, `PSU_MAX_VOLTAGE`,
`PSU_MAX_CURRENT`.

## Build

```sh
go test ./...
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o psu.exe ./cmd/psu
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o psu ./cmd/psu
```

Desktop build on Windows with WebView2:

```sh
./scripts/build_windows.sh
```

`scripts/sync_web.sh` copies `webapp/dist` into `internal/webassets/dist`.
The desktop window starts maximised. Put a frontend build in `web/current`
next to the executable, or set `PSU_WEB_DIR`, to override the embedded UI.

## Examples

```sh
psu list
psu idn --serial 86759d000040041622272d --json
psu channels --host 192.168.1.50 --json
psu set --host 192.168.1.50 --voltage 5 --current 1 --verify
psu output on --host 192.168.1.50 --yes
psu measure --host 192.168.1.50 --items voltage,current
psu ramp --host 192.168.1.50 --to 12 --step 0.5 --delay 0.2 --yes
psu sequence steps.json --host 192.168.1.50 --yes
psu log --host 192.168.1.50 --duration 30 --interval 0.2 --out run.csv
psu scpi ':VOLTage?' --query --host 192.168.1.50
psu web --host 192.168.1.50 --web-port 8765
```

## Safety

`output on` requires `--yes`. `ramp` and `sequence` require `--yes`. Server-side
setpoint limits come from each unit, not only from the page. `safe_off` turns
the output off when a ramp or sequence fails.

## Not yet

- Windows USB-TMC/VISA resources.
- WSL `usbipd` auto-attach.
- Hot-plug detection after the app starts.
- Signed updater.

# Troubleshooting

## The tool cannot find the instrument

1. LAN: run `ping <ip>`. The default port is 5025. Make sure the supply has LAN and SCPI enabled. Open the firewall.
   ```bash
   scripts/psu.py scpi --host <ip> "*IDN?" --query
   ```
2. USB: run `lsusb` and `ls /dev/usbtmc*`. On Linux, run `scripts/install_udev.sh`. On WSL, run `usbipd attach --wsl` first.
3. Serial (Korad): check `/dev/ttyUSB0` or `COM3`. Use 9600 baud. Some clone chips need `--baud 9600` and no flow control.
4. VISA resource: run `scripts/psu.py discover`. Use `--resource` when more than one instrument is present.

## DP100 on Linux or WSL

- Check the device: `lsusb | grep 2e3c`. The expected ID is `2e3c:af01`.
- Check the node: `ls -l /dev/hidraw*`. If the node is absent, the kernel did not bind the HID device, or the cable is loose.
- Permissions: run `scripts/install_udev.sh`. It includes a hidraw rule for the DP100. Replug the device.
- Python dependency: `psu.py setup` installs `hidapi`. If the source build fails, install `libhidapi-dev` and `libusb-1.0-0-dev` first.
- WSL: run `usbipd attach --wsl --busid X` first. If you cannot attach the HID device, use a native Linux host.
- Exclusive access: the official ATK-DP100 PC tool can hold the HID device. Close it before you run this skill.
- If the device does not respond, the driver returns a HID timeout error. It does not hang. Check the cable, permissions, and exclusive access.

## The tool connects but reads zero

- The output is off. Run `output on --yes`.
- The channel is wrong. Run `channels` on a multi-output model, then select the channel with `--ch`.
- Remote sense or local sense is connected incorrectly. The reading can be low or zero.
- Korad clone firmware is case-sensitive. Use `VOUT1?`, not `VOUT1 ?`.

## set succeeds but the actual voltage is wrong

- The supply uses remote sense. Cable loss compensation can make the terminal voltage differ from the display.
- The current limit is too low. The supply enters CC mode and pulls the voltage down.
- `--verify` reads the setpoint back. If the readback differs, check the dialect with `--family`.
- Some models load the setpoint only after `:OUTPut ON`.

## The output does not turn on

- OVP or OCP has tripped. Clear the protection with the model command, or power-cycle the supply.
- Over-temperature or overload protection is active.
- A tracking or parallel mode owns the channel.
- A multi-output Keysight model needs `:INSTrument:NSELect` first. This skill does this automatically.

## The ramp or sequence stops

- A limit violation stops the run immediately. Read the JSON error.
- On an error, `safe_off` (on by default) turns the output off.
- To keep the output on, run `config set safe_off false`. This is not recommended.

## The reading is noisy or jumps

- A shorter sample interval adds noise. Use `log --interval` of 0.2 s or more.
- With an electronic load or a pulsed load, the supply display and a DMM can differ by a large amount. Use the raw `measure` value first.
- For more precision, use `scpi` and the high-resolution measurement command for the model.

## WSL detection

- `psu.py` detects WSL at start. If you do not give a connection option, it tries `usbipd attach` on a shared Windows supply.
- `psu.py doctor` lists Windows USB devices, the VID brand, and the bind/attach commands. `--attach-usb` runs attach directly.
- On WSL, `psu.py web --open` starts a Windows browser. If the browser does not open, open the printed `http://localhost:<port>/` URL manually.

## The Web UI does not open, or the port is in use

- The default is `127.0.0.1:8765`. If the port is busy, use `--web-port 8766`.
- To open the UI from another machine, use `--bind 0.0.0.0` and open the firewall. The UI has no login.
- If the page shows disconnected, read the device error in the terminal. Exclusive access by another program also causes this state.

## Safety

- Set voltage and current first. Then enable the output. Before you disconnect a load, run `output off`.
- A battery or a large capacitor can keep the terminals live after output OFF.
- OVP and OCP are software functions. They do not replace a hardware current limit, a fuse, or the correct wire size.
- Do not run an unattended ramp or sequence above the rating of the supply or the load.

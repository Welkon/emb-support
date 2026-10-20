# Troubleshooting

Find the symptom first. Each section starts with the fastest check, then gives the cause.

## Probe not visible

`doctor` shows an empty `probes` array, or `pyocd list` prints "No available debug probes are connected".

1. **Check the physical layer first**
   ```bash
   lsusb | grep -i -E "dap|mbed|0d28|1209"
   ```
   No device: check the cable, the power and the USB port. DAPLink can be powered by the target board or by USB. Test both.
2. **WSL** (`doctor` shows `wsl: true`)
   USB does not enter WSL automatically. After a failed connect, the skill calls the Windows-side `usbipd.exe` and attaches known probes that are already shared. Disable this with `--no-wsl-auto-attach` or `DAP_WSL_AUTO_ATTACH=0`.
   ```bash
   dap.py wsl status                 # Windows devices, known probes, busid and state
   dap.py wsl attach --busid 2-3     # Attach to WSL. If not shared, bind first.
   dap.py doctor --attach            # Attach the first known probe that is not attached.
   ```
   For a new port, run `usbipd bind --busid 2-3` once in an elevated PowerShell. Run `attach` again after each replug or reboot. The device `/dev/bus/usb/...` appears in WSL only after a successful attach.
   Common probe VIDs: `0d28` DAPLink, `0483` ST-Link, `1366` J-Link, `1209` pid.codes.
3. **Linux permissions**
   ```bash
   ls -l /dev/bus/usb/*/* | head
   ```
   `LIBUSB_ERROR_ACCESS` or "Permission denied": install the udev rule below. Then unplug and replug the probe.
4. **Probe is busy**
   ```bash
   pgrep -a -f "pyocd|openocd|JLinkGDBServer|gdb"
   ```
   Two GDB servers cannot use one probe. Stop the old `dap.py gdb --detach` process first.

### udev rule (Linux)

```bash
sudo tee /etc/udev/rules.d/60-daplink.rules >/dev/null <<'EOF'
# DAPLink / mbed CMSIS-DAP (HID + v2 bulk)
ATTRS{idVendor}=="0d28", ATTRS{idProduct}=="0204", MODE="0666", GROUP="plugdev"
# Open-source probes under pid.codes
ATTRS{idVendor}=="1209", ATTRS{idProduct}=="c0de", MODE="0666", GROUP="plugdev"
# ST-Link, often used as CMSIS-DAP
ATTRS{idVendor}=="0483", ATTRS{idProduct}=="3748", MODE="0666", GROUP="plugdev"
ATTRS{idVendor}=="0483", ATTRS{idProduct}=="374b", MODE="0666", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Unplug and replug the probe. Make sure the user is in the `plugdev` group (`groups`).

## target not found

`-t stm32f103rc` returns `TARGET_NOT_FOUND` or "target type not found".

1. The name must match `dap.py targets` exactly. Case and suffix (`xE`, `xG`, `_XXAA`) differ by chip.
   ```bash
   dap.py targets --search gd32
   ```
2. The device pack is missing.
   ```bash
   dap.py pack search <part>     # for example GD32F303CC or HC32F460KETA
   dap.py pack install <part>
   ```
   Pack names and chip names are not always the same. `pack search` accepts partial names.
3. The pack is installed but the target is still unknown. Pass the pack file directly and bypass the index:
   `--pack /path/to/vendor.pack`.
4. The vendor has no pack (some small vendors). Use an OpenOCD `target/*.cfg`. See `engines.md`.

## Flash fails

Typical output: `Failed to erase/program`, `flash programming failed`, `Timeout while waiting for flash operation`.

Try these steps in order. Start with the lowest cost.

1. **Lower the clock.** Use `--frequency 1000000`. The default can be 4 to 12 MHz, which is unstable on long wires. If it still fails, try `500000`.
2. **Change the reset or connect mode.** `mem` and `regs` accept `--connect under-reset`. For flash, run `reset --halt` first.
3. **Erase the whole chip.** Use `erase --chip-erase`. This removes the bootloader. Get confirmation from the user first.
4. **Read protection.** If read protection (RDP) locks the chip, pyOCD reports erase failure or cannot connect. STM32 needs an RDP unlock, which erases the whole chip. Ask the user to use STM32CubeProgrammer, or get explicit approval before you change option bytes.
5. **Low power or watchdog.** The target may sleep at power-on or reset in a loop. Use `--connect under-reset`. If needed, flash while the target is held in reset.
6. **Firmware reuses the SWD pins.** If the firmware changes PA13/PA14 to GPIO, a normal attach fails. Use `under-reset`.

## Unstable SWD

Symptoms: `WAIT` or `FAULT` responses, random `transfer error`, or a flash that stops halfway.

- Ground: connect probe GND to target GND directly. Do not rely on the USB ground.
- Wire length: keep SWDIO and SWCLK shorter than 10 cm. Below 1 MHz is safer on long wires.
- Pull-up: some boards need a 10k pull-up on SWDIO.
- Voltage: match the probe IO level to the target. A 1.8 V target with a 3.3 V probe is unstable.
- Multiple probes: use `-u <serial>` to select one probe and avoid the wrong board.

## RTT shows no output

`dap.py rtt` prints nothing, or reports "RTT control block not found".

1. **The firmware must include SEGGER RTT.** It needs `SEGGER_RTT.c` and `SEGGER_RTT_printf`, and the linker must keep `_SEGGER_RTT`. Firmware that only redirects `printf` to UART has no RTT control block.
2. The control block is usually at the start of RAM. Scanning takes time. Increase `--duration`, or set the start address with `-a 0x20000000`.
3. The control block is not ready right after reset. Use `--duration 20`, or `-M attach` to attach to an existing control block without a rescan.
4. RTT stops in low-power modes. Confirm that the firmware runs and does not enter STOP or STANDBY.
5. A small RTT buffer drops logs. Check `BUFFER_SIZE_UP`.

RTT uses target writes and probe reads. It does not need UART. If the firmware also uses SWO/ITM, do not share the same pin.

## GDB cannot connect

- Port in use: run `ss -ltnp | grep 3333`, then use `-p 3334`.
- The `--detach` process exited: read `gdbserver.log` in the data directory. `dap.py env` shows that directory.
- GDB must load an ELF with symbols: `arm-none-eabi-gdb build/fw.elf -ex 'target extended-remote :3333'`. Without symbols, breakpoints work only by address.
- Breakpoints are lost after reset: the pyOCD GDB server reloads software breakpoints. If `--persist` still fails, use hardware breakpoints.

## Error messages

| Message | Meaning | First action |
|---|---|---|
| `No available debug probes are connected` | Probe not visible | `lsusb`, `usbipd attach`, udev |
| `LIBUSB_ERROR_ACCESS` | Permission | udev rule, then replug |
| `TARGET_NOT_FOUND` | Wrong target name | `targets --search`, `pack install` |
| `no memory region` | Address not in the map | Check the linker script or `--base` |
| `Failed to erase` | Read protection, low power, clock | Lower the clock, `--connect under-reset`, unlock |
| `transfer error` / `WAIT` | SWD signal quality | Ground, short wires, lower clock |
| `RTT control block not found` | RTT not enabled | Check `SEGGER_RTT.c`, set `-a` |
| `Address already in use` | GDB server port conflict | Change the port or stop the old process |

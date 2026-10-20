# Troubleshooting

## No LAN connection

1. Run `ping <ip>`. Make sure that the instrument and the computer are on the same subnet.
2. Check the port. Most instruments use port **5025** (Rigol, Siglent, Keysight, and Rohde & Schwarz). VXI-11 uses port 111 for port mapping.
3. Enable the remote, SCPI, or LAN option on the instrument. The menu name is different for each brand.
4. Remove firewall and router isolation. Use a wired connection on the same subnet. This step excludes access-point isolation.
5. Try a raw connection:

```bash
scripts/scope.py scpi --host <ip> "*IDN?" --query
scripts/scope.py doctor --host <ip>
```

6. Some Keysight models do not use port 5025 for the socket. Read the manual, or use the VXI-11 resource from the `list` command.

## No USB connection

```bash
lsusb | grep -iE "0699|1ab1|f4ec|0957|05ff|0aad"    # Tek, Rigol, Siglent, Keysight, LeCroy, R&S
ls /dev/usbtmc*
```

- If `/dev/usbtmc*` is absent, run `sudo modprobe usbtmc`. Make sure that the instrument is a USBTMC device.
- If the device is present but you have no permission, run `scripts/install_udev.sh`. Then disconnect and connect the instrument.
- WSL: the program detects WSL at startup. If no local device is present, it runs `usbipd attach` for a shared Windows-side oscilloscope. Use `--no-auto-attach` to disable this action. The `doctor` command finds `usbipd.exe` on the Windows side, lists the oscilloscope vendor IDs (Tek, Rigol, Siglent, Keysight, LeCroy, R&S, Yokogawa, GW Instek, Hantek, Owon, and Micsig), and writes the attach commands. Add `--attach-usb` to run the attach commands.
  A device in state `Not shared` needs `usbipd bind --busid X` as Administrator. Then run `usbipd attach --wsl --busid X`.
- Windows: install a VISA runtime (TekVISA or NI-VISA) or a libusb driver. Read the bitness section in `tektronix.md`.
- Resource string format: `USB0::0x0699::0x0368::<serial>::INSTR`. A wrong serial number prevents a connection.

## Timeout

- The default timeout is 5 seconds. A deep-memory transfer can need more time. Use `--timeout 30`.
- Make sure that the instrument completed the last operation. Send `*OPC?` before the next query when necessary.
- For a large capture, first decrease `--points`. Increase the value after the link is stable.

## Truncated or invalid binary block

- The SCPI block format is `#<n><length><payload>`. The form `#0` has no length. Read until the terminator.
- If the reply starts with `#` but the length is wrong, find out whether the instrument sent a block or text. Use `--json` to see the bytes.
- Some instruments add `\n` after a block. The parser uses the length field, so this suffix has no effect.
- ASCII mode (Tektronix) has no block header. The values are separated by commas or spaces.

## Measurement not supported

The `measure` command first tries the instrument command `:MEASure:*?`. If the instrument does not support the item or returns an error, the command calculates the value from the waveform. The fallback covers Vpp, Vmin, Vmax, mean, RMS, frequency, period, duty, rise, and fall. If the instrument has no deep memory, limit the length with `capture --points`.

## Screenshot not supported

The `shot` command accepts only PNG, JPEG, or BMP data. A failure usually has one of these causes:

- The model has no screen download command. This is common on a TBS 1102B.
- The instrument needs `:HARDcopy:SETUP` first.
- The firmware returns BMP. Use `scpi` to read the raw block, then convert the image.

When no screen dump is available, the skill captures CH1 and writes an SVG waveform plot. The JSON output has `fallback: waveform-plot`.

## Trigger does not fire

- The trigger level is outside the signal range.
- The timebase is too slow. The waveform is compressed.
- The trigger source channel is off or hidden.
- The sweep mode is AUTO. AUTO triggers without a signal. Use NORMAL or SINGLE.
- The probe attenuation setting does not match the probe.

If `monitor` does not find an event, first use `--dry-run`. Check the commands. Then read back `:TRIGger:STATe?` and `:TRIGger:EDGE:LEVel?` with `scpi`.

## Windows problems

- `VI_ERROR_INV_OBJECT`: the Python bitness does not match the VISA DLL bitness. Read `tektronix.md`.
- `--backend @py` cannot find a USB device: pyvisa-py needs a libusb driver. Use the vendor VISA runtime, or install libusb.
- A serial (ASRL) resource can need an extra driver on some USB-to-serial chips.

## Safety

- For a high-voltage or floating measurement, first check the differential probe and the isolation.
- Do not use a standard passive probe on the mains voltage.
- Read the old value before you change the trigger, the timebase, or a channel. Restore the old value at the end.

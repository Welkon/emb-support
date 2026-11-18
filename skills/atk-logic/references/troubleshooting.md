# Troubleshooting

Start with the symptom. Every command ends in one JSON object; read
`error.code` and act on that, not on the message text.

## "It does not capture" / my capture never finishes

The usual cause is a trigger that never fires, not a broken analyzer.

- `--ch N:rising|falling|high|low|both` waits until the line reaches that
  condition. With no probe attached, or a probe on a line that stays low, it
  waits forever.
- This skill stops such a run after `--trigger-timeout` seconds of silence
  (default 20) and reports `trigger_not_found` with the buffer position it
  reached. Partial data is copied to `--out` when the vendor wrote any.
- Check the probe, its ground, and `--threshold` (1.8 V for 3.3 V logic, 1.65 V
  for a 3.3 V midpoint is also common; 0.9 V for 1.8 V logic).
- For "what is on the line right now" use `--ch N:none`; the capture starts
  immediately.
- A legitimate long wait ("press the button after I start") uses
  `--trigger-timeout 0`.

## doctor says no device

1. `scripts/atkla.py doctor` — does the CLI run at all (`cli.version`)?
2. `scripts/atkla.py list` — is `devices` empty?
3. Check cable and power, then replug. `profileComplete:false` right after
   enumeration is normal; `info` gets the full profile.
4. `bootloader: true` means the analyzer is in upgrade mode; it cannot capture.

On WSL the device must be attached to **Windows**. If it was handed to the
distro with `usbipd attach`, detach it (`usbipd detach --busid X`) so the
Windows CLI can open it again.

## device_busy

Another program holds the analyzer: the ATK-Logic GUI, another CLI process, or
a previous capture that has not finished unwinding. Wait for `idle` (the skill
does), close the GUI, or wait ~15 s after a stopped capture. The vendor CLI
cannot report the occupying PID.

## The capture stops at some percentage and the file is .bin.partial

A stop was requested — trigger timeout, Ctrl+C, unplug, or a stop from another
process. `capture.json` says why (`status`, `actualStopMode`, `reason`) and
`validBits` tells how much data is real. Read it with
`scripts/atkla.py read <dir>`; do not rename `.partial`.

## output_too_slow / output_write_failed

The writer cannot keep up or cannot write: a network drive, a sync client, a
nearly full disk, or a Linux path crossing the WSL 9p share at high rate.
Capture into `/mnt/c/...` (native Windows path) or lower `--freq`, `--time`, or
the channel count. `--out` inside the Linux filesystem is already staged on the
Windows side and copied once, so a slow first write means the copy itself is
the problem — check free space.

## atkdl_save_failed

The BIN is complete; only the GUI project failed to save. Keep the BIN, fix the
target directory, and re-run with `--format atkdl` or open the BIN directly.

## A capture ran, but the numbers look wrong

- `stuck: true` with `edges: 0` — the line never moved: wrong channel, probe
  not connected, wrong threshold, or a channel outside `usableChannels`.
- Aliasing: the rate must be at least 2× (preferably 10×) the fastest edge you
  care about. 1 MHz on a 1 MHz clock yields a plausible but meaningless
  square wave.
- Duty and cycle rate from a noisy floating input look like a random 5–10 %
  high level with thousands of 1-bit pulses. Connect a ground.
- `minRunBits: 1` on a "clean" clock means the edge is being sampled at the
  transition; raise `--freq`.

## Reading a GUI project gives odd lengths

`.atkdl` chunks are padded to 1 MiB. `read` uses `channel.ini` and
`SamplingDepth` to trim, so trust `validBits` in the output, not the extracted
file size. See `references/atkdl-format.md`.

## After a forced kill

If something killed the CLI during a capture, the analyzer can be left in the
last state. Replug it once, run `doctor`, then capture again. Do not loop
`device connect` against a device that has not been replugged.

## Harmless log lines

`CYUSB synchronous read failed. LastError=997` is a 100 ms poll timeout
(`ERROR_IO_PENDING`) and is retried automatically; it only appears in the CLI's
`log` directory. Chinese text in stderr from the vendor binary is normal
diagnostics, not a failure.

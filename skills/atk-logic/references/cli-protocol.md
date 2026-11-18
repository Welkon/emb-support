# Vendor CLI contract, as observed

Source: the two manuals shipped with ATK-Logic (`docs/ATK CLI AI manual.md`,
`docs/ATK CLI User manual.md`) plus probing on a DL32 Plus (v1.1.2.2, USB 3,
MCU 10 / FPGA 134, Windows-side device, WSL host). Where observation and the
manual disagree, the observation is noted.

## One-shot commands

```
atk-logic-cli --version
atk-logic-cli device list [--json]
atk-logic-cli device connect [--device-id ID] [--json]
atk-logic-cli device status [--json]
atk-logic-cli device disconnect [--json]
atk-logic-cli device capabilities --mode buffer|stream --channels 0,1 \
    [--frequency HZ | --time MS] [--json]
atk-logic-cli capture validate --config FILE [OPTIONS] [--json]
atk-logic-cli capture run [--device-id ID] --config FILE [OPTIONS] [--json]
atk-logic-cli session --stdio [--mode user|ai]
```

`--json` keeps stdout to one JSON object (except `capture run`, which streams
event objects). Ordinary logs, including USB chatter, go to stderr. Failure exit
code observed: `4`. Success: `0`.

`capture` options: `--mode`, `--frequency`, `--time`, `--threshold`,
`--trigger-position`, `--channel ID:none|rising|high|falling|low|both`
(repeatable), `--format bin|atkdl|both`, `--output-dir`, `--no-timestamp`.
Options override `--config`; repeated `--channel` *replaces* the config list.

Each process holds at most one connection. One-shot commands therefore connect,
act and disconnect; that is why a one-shot `device status` reports
`connected:false` even directly after an earlier `device connect`.

## Capability answers

Full table:

```json
{"ok":true,"device":{...},"options":[{"frequencyHz":1000000,"hardwareIndex":1,
  "timings":[{"durationMs":1,"rle":false}, ...]}]}
```

Single query (`--frequency HZ` **xor** `--time MS`, they are mutually exclusive):

```json
{"ok":true,"query":"durationOptions","frequencyHz":1000000,
 "durationOptionsMs":[350000000,180000000,...,1],"maxDurationMs":350000000}
{"ok":true,"query":"frequencyOptions","durationMs":1000,
 "frequencyOptionsHz":[1000000000,...,1000000],"maxFrequencyHz":1000000000}
```

Lists are sorted descending. Legality depends on series, high/low
configuration, enabled channel count and USB speed, so the same request can be
legal on one profile and not on another. `rle:true` marks durations where the
device compresses automatically; the output BIN layout does not change.

Observed on this bench (DL32 Plus, 2 channels, buffer):
1 MHz allows 1 ms … 350 s; 1 GHz allows 1 ms … 175 s with RLE from 2 s; 32
channels shrink the set. `stream` allows longer durations (180 000 s at 1 MHz)
because it is bounded by USB throughput rather than memory.

## Session JSONL

```
atk-logic-cli session --stdio --mode ai
```

One request per line on stdin, one JSON object per line on stdout, flushed
immediately. Human logs on stderr only. `--mode ai` is mandatory for JSONL;
without it the session speaks space-separated user commands and prints a
`atk-cli>` prompt.

Methods: `device.list`, `device.connect`, `device.status`,
`device.capabilities`, `device.disconnect`, `capture.validate`, `capture.run`,
`capture.status`, `capture.stop`, `session.close`.

Observed response to `capture.run` (the manual calls it "accepted"):

```json
{"id":"r","ok":true,"accepted":true,"captureId":"capture-20261117T080046805"}
```

Events follow, tagged with `requestId` (not `id`), then `idle`:

```json
{"captureId":"...","requestId":"r","event":"capture.started","directory":"C:/out/20261117_160046_805","rle":false}
{"captureId":"...","event":"capture.progress","percent":50,"state":1,"type":2}
{"captureId":"...","event":"output.progress","format":"atkdl","percent":95,"state":1}
{"captureId":"...","requestId":"r","event":"capture.finished"}
{"captureId":"...","event":"idle"}
```

`capture.status` answers `{"state":"idle"|...}` and is the fallback when the
`idle` event is not seen. `capture.stop` takes `{"immediate":true|false}` and
the capture then ends with a `capture.finished` whose `capture.json` records
`requestedStopMode`/`actualStopMode`.

Close with `session.close` and wait for the process to exit. Do not close stdin
or kill the process: the device needs the shutdown sequence (wake, stop PWM,
device exit, sleep, release USB).

## Quirks worth knowing

- **`output.progress` floods.** One 10 ms capture with `--format both` printed
  204 803 `output.progress` lines, nearly all at 95 %, before finishing. Any
  reader must stream and decimate; buffering the whole stdout is wasteful and
  printing it is unreadable. This skill counts events and only reports a
  percentage when it moves.
- **One-shot `capture run` has no `accepted` line**; stdout starts with
  `capture.started`. Only the session form acknowledges the request.
- **`capture.json` stores the trigger as a device enum string**, not the
  protocol name: `0 none, 1 rising, 2 high, 3 falling, 4 low, 5 both`. The
  JSONL request and `--channel` use the names.
- **Default trigger position is 0, not 50**, when the flag is omitted in a
  one-shot call. This skill always sends `--position` explicitly.
- **A waiting trigger produces silence.** With `high` on a line that stays low,
  progress stops at the trigger position (50 % in the observed run) and nothing
  else happens for as long as you wait. The manual documents no trigger timeout;
  a caller has to impose one and stop politely.
- **`capture validate` creates no files** but does resolve a timestamped output
  directory; the same path is not reused by the following run.
- **Paths are Windows paths** for the CLI process. From WSL a Linux directory
  has to be passed as `\\wsl.localhost\<distro>\...`; it works, and it is slow
  for large writes, which is why the skill stages on the Windows side.
- **`CYUSB synchronous read failed. LastError=997`** is a 100 ms poll timeout
  (`ERROR_IO_PENDING`), logged to the `log` directory and harmless.
- **Service of `capture stop`**: after stopping, the device uploads what it has
  and unwinds; expect ~15 s before the process is ready again.

## Output directory and files

Without `--output-dir`, captures go under the CLI's own working directory
(`capture/<timestamp>/`); that is why this skill always passes an absolute one.
The timestamp format is `yyyyMMdd_HHmmss_zzz`. An existing directory is never
overwritten (`output_conflict`).

Per capture: `capture.json`, one `channel_<id>.bin` per channel (written as
`.bin.partial` until complete), optionally `capture.atkdl`, and a `save/`
directory for the GUI project. `capture.json` carries the request, the device
profile, `validBits` and byte size per channel, start/finish times, RLE, and
`status: complete|incomplete` with a stop mode and failure reason.

## BIN packing

One sample per bit, LSB first inside each byte, channels in separate files:

```python
data = Path("channel_0.bin").read_bytes()
valid_bits = 10000                    # from capture.json
samples = [(data[i // 8] >> (i % 8)) & 1 for i in range(valid_bits)]
```

The unused high bits of the last byte are zero; `validBits`, not the file size,
decides how many samples are real.

## How this skill follows the manual

Every rule from `docs/ATK CLI AI manual.md` / `docs/ATK CLI User manual.md`
mapped to the place that enforces it. A reviewer can check these one by one.

| manual rule | where it lives |
|---|---|
| order `list → connect → capabilities → validate → run` | `capture.run`: `device.list`, `_choose_device`, `device.connect`, `device.capabilities`, `capture.validate`, `capture.run` |
| never guess frequency/duration; use the device list | `capabilities.resolve`; `--strict` refuses instead of adjusting |
| `--frequency` xor `--time` in capability queries | `query_one_shot` sends at most one; `caps` rejects both |
| at least one channel, ids inside the real range | `parse_channels` (non-empty, unique), `capture._check_channels` (device profile) |
| threshold `[-5, 5]` V | `parse_volts` |
| output dir never overwritten, `.bin.partial` kept | `_plan_output` (`output_conflict`), no rename/delete anywhere |
| `validBits` is the only length truth | `decode.analyse_capture` reads `capture.json`, not the file size |
| LSB-first bit packing, channels separate | `decode._read_bits` / `_fast_counts` |
| wait for `capture.finished` then `idle` before the next run | `Session.capture` (+ `capture.status`), `run_events` |
| branch on `error.code`, not on `message` | `vendor_error`, `SkillError.code`, all suggestions keyed by code |
| `capture.stop` (default, keeps data) before any hard end | trigger timeout and capture timeout call `capture.stop`; SIGINT only as the documented Ctrl+C equivalent |
| `session --stdio --mode ai`, `session.close`, wait for exit | `protocol.Session` |
| do not kill the process mid-capture | `Session.close` sends `session.close` and waits 60 s; `run_events` SIGINTs, then `terminate()` after a grace period, `kill()` only if that is ignored |
| `device list` first when the device is not named | `_choose_device`: one device is taken, several raise `multiple_devices`, none raises `device_not_found` |
| AI mode rejects bare text | the skill only writes JSON lines to the session |
| keep diagnostic material | `request.json` per capture, `stderr_tail` and event counts in errors |

Protocol decoding is **not** part of the vendor CLI. `decode` runs the GUI's own
decoder modules locally on the captured BIN (see `references/decoders.md`), so
the CLI contract above is unaffected: a capture is still one BIN per channel
with `validBits` as the only length.

### Deliberate differences

1. **`--out` is the evidence directory.** The vendor always nests
   `<PATH>/<timestamp>/`; with staging the skill copies that directory to
   `--out` itself and reports where the CLI really wrote as
   `capture.vendorDirectory`. Native `/mnt/c/...` destinations keep the
   vendor's timestamped child.
2. **`--freq`/`--time` have defaults** (`1m`, `10ms`). They are requests, not
   guesses: they are resolved against `device.capabilities` and every change is
   returned in `adjustments`, with `--strict` available to refuse instead.
3. **A trigger timeout exists.** The manual documents none, but a waiting
   trigger produces no events, so the skill stops after `--trigger-timeout`
   seconds of silence (default 20, `0` disables), keeps partial data and raises
   `trigger_not_found`.
4. **`--config` is always written.** The documented invocation takes a config
   file; the skill writes the resolved request to a temp config and passes it
   together with the same values as flags, so both paths agree and the request
   is auditable.
5. **`device.list` is called even when `--device-id` is given**, so a wrong id
   fails with the available ids in the error instead of a device-level failure.

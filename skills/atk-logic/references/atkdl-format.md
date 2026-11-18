# ATKDL project format

`.atkdl` is a zip. A GUI-saved project and a CLI `--format atkdl` capture use
the same container; the metadata inside differs slightly.

```
set.ini                  session settings
channel.ini              top-level channel list/session name (small)
0/channel.ini            per-channel facts
0/0-0.bin, 0/0-1.bin…    consecutive chunks of channel 0
1/channel.ini            (a disabled channel has an ini and no data)
set.ini, save/           extra files written by the CLI capture path
```

## Chunks

Chunk files are 1 MiB (1 048 576 bytes) each and **the last chunk is padded**.
Chunks are byte-aligned, so concatenating them preserves the LSB-first packing
of the plain BIN output. Never infer the sample count from the file size — 24
chunks of a 10 s / 20 MHz capture look like 201 326 592 samples while the real
figure is 200 003 328.

## set.ini

CLI captures add explicit base units:

```ini
SessionName=CLI Capture
CaptureMode=buffer
SamplingFrequency=1000            # legacy, unitless
SamplingFrequencyHz=1000000
SamplingTimeMs=10
SamplingDepth=10000
TriggerSamplingDepth=5000
TriggerPositionPercent=50
TriggerPositionLabel=50%
ThresholdVolts=1.8
CollectType=0
```

GUI projects keep one JSON blob instead:

```ini
[DL32 Plus]
settingData={"RLE":false,"isBuffer":false,"setHz":20000000,"setTime":10000,
             "thresholdLevel":1.6,"triggerPosition":1,...}
channelsSet=[{"id":0,"enable":true,"triggerType":1,"name":"Channel 0"},...]
```

`settingData.isBuffer:false` corresponds to stream mode. `triggerType` uses the
same enum as `capture.json` (`0 none … 5 both`).

## <channel>/channel.ini

Plain text, one value per line:

```
Channel 0
0
200003328
0,0
0,0
```

Line 1 is the display name, line 3 the stored sample count. A CLI capture writes
a large, repeated header block here (about 32 kB) and a smaller number on line 3
(`10112` for a 10 000-sample run); that is why the skill takes the **minimum** of
the available limits.

## How `read` derives validBits

```
storedBits   = sum(chunk file sizes) * 8
sampleCount  = channel.ini line 3, when it is positive
depth        = set.ini SamplingDepth, when present
validBits    = min(storedBits, sampleCount, depth)
```

- GUI project: `min(201 326 592, 200 003 328) = 200 003 328` ✔
- CLI capture: `min(8 388 608, 10 112, 10 000) = 10 000` ✔

If none of the numbers exist, `read` falls back to `frequencyHz × durationMs`.

## Enabled channels

`channelsSet` names the enabled channels. When it is absent (CLI captures) the
channels that have chunk files are the captured ones. `read --ch` selects a
subset; `--extract DIR` keeps the concatenated `channel_<id>.bin` files so they
can be fed to other tools.

## decodeJson: configuration, not results

A GUI project that has protocol decoders configured stores one JSON blob:

```ini
decodeJson=[{"decodeID":"1754270102648","decodeJson":{
  "PWM":{"main":{"id":"pwm","name":"PWM"},
         "channels":[{"id":"data","name":"Data","value":"0"}],
         "annotation_rows":[{"desc":"Duty cycles"},{"desc":"Periods"},
                            {"desc":"Frequencies"}],
         "options":[{"id":"polarity","value":"active-high"}]},
  "main":{"channelList":["0"],"decodeID":"1754270102648","first":"PWM"}}}]
```

It names the decoder, its input channel, its options and which annotation rows
it would show — **the decoded rows themselves are not in the project**. They
exist only in the GUI session or in the CSV the GUI exports. Verified on a real
project (`BH-TS0013-09.atkdl`, PWM on channel 0, active-high) whose exported
CSV has 120 027 annotation rows while the project is 180 kB.

`read` reports the configuration (`project.decoders`) so a project can be
described without the GUI, and `--gui-csv FILE` reads an exported CSV.

## Cursors live in vernier.ini

`vernier.ini` holds marker positions (Trigger, T1, T2, T3), not measurements:

```ini
Trigger,ff26a3d9,200000,
T1,ffed5756,6604258800000,到最大值
```

`read` does not interpret these.

## Reading a GUI decode export

`--gui-csv` accepts the file the GUI writes from a decode ("Export CSV"), in
the Windows code page (read as UTF-8, then GB18030):

```
序号,开始,时间,名称,数值,
0,150 ns,249.950000 µs,Duty cycles,1.200240%,
```

The summary reports one entry per annotation name with count, unit
(`percent`, `ns`, `hz`, `bit`, `number`) and min/max/mean; values without a
recognised unit are kept as text samples. Cross-checking the own decoder
against such a file is the cheapest way to validate a capture: on the reference
project the GUI reports mean duty 60.45 % and 249.9 µs periods, and `read`
reports 60.47 % duty with 4 001 cycles/s — the same signal.

# Dialects and Command Differences

`idn` detects the brand automatically. Use `--family` to override the result.
All commands can bypass the dialect layer with `psu.py scpi "<command>" --query`.

## Rigol DP800 (`rigol`)

```
:CHANnel<n>:VOLTage <v>        :CHANnel<n>:VOLTage?
:CHANnel<n>:CURRent <a>        :CHANnel<n>:CURRent?
:OUTPut CHANnel<n>,ON|OFF     :OUTPut? CHANnel<n>
:MEASure:VOLTage? CHANnel<n>
:MEASure:CURRent? CHANnel<n>
:MEASure:POWEr? CHANnel<n>
:CHANnel<n>:OVP <v>            :CHANnel<n>:OCP <a>
```

Channels 1 to 3. CH3 on the DP832 is usually the low-current channel.

## Keysight E36xx (`keysight`)

```
:INSTrument:NSELect <n>        # Select an output.
:VOLTage <v>                   :VOLTage?
:CURRent <a>                   :CURRent?
:OUTPut ON|OFF                 :OUTPut?
:MEASure:VOLTage?              :MEASure:CURRent?
:OUTPut:OVP:VOLTage <v>
```

The E36312A has three outputs. The E3631A and E364xA are similar.
OCP depends on the model. This skill maps OVP only for Keysight supplies.

## Siglent SPD3303X (`siglent`)

```
:CH<n>:VOLT <v>                :CH<n>:VOLT?
:CH<n>:CURR <a>                :CH<n>:CURR?
:OUTP CH<n>,ON|OFF             :OUTP? CH<n>
:MEAS:VOLT? CH<n>              :MEAS:CURR? CH<n>
:MEAS:POW? CH<n>
```

Channels 1 and 2. The third tracking channel usually follows CH1 or CH2.

## R&S HMC804x (`rns`)

```
:INSTrument:NSELect <n>
:VOLTage / :CURRent
:OUTPut:CHANnel<n>:STATe ON|OFF   :OUTPut:CHANnel<n>:STATe?
:MEASure:VOLTage? / :MEASure:CURRent?
```

The HMC8041, HMC8042, and HMC8043 have 1, 2, and 3 channels.
This skill lists channels 1 to 4 by default. An invalid channel returns an error.

## Korad and Tenma (`korad`, serial)

```
VSET<n>:<v>     ISET<n>:<a>
VSET<n>?        ISET<n>?
VOUT<n>?        IOUT<n>?
OUT<n>          # 1 = on, 0 = off
```

Use 9600 8N1. The supply does not support OVP, OCP, or power queries.
The tool calculates power as V x I.
Use `psu.py ... --serial /dev/ttyUSB0 --baud 9600`.

## GW Instek, BK Precision, Aim-TTi, and Owon

The channel selection command depends on the series. The current implementation uses:

- `gwinstek` and `bkprecision`: `:INSTrument:NSELect` plus `:VOLT`, `:CURR`, and `:OUTP`.
- `owon`: `:CH<n>:VOLT` and `:OUTP CH<n>,ON`.
- `aimtti`: `:VOLT`, `:CURR`, and `:OUTP`.

For the first use, run `idn` and `channels`. Then use `scpi` to check the key commands.

## Add a new brand

Create a subclass of `Dialect` in `scripts/psuscpi/dialects.py`. Override these methods:

- `channels`
- `set_voltage`, `set_current`, `get_voltage`, and `get_current`
- `measure_voltage`, `measure_current`, and `measure_power`. Return `None` if a value is not available.
- `output` and `output_state`. Return `None` if the state is not available.
- `ovp` and `ocp`. Return `None` if the function is not supported.
- For a multi-output model that needs selection, set `selected = True` and define `select(n)`.

Register the class in `FAMILIES` and `detect_family()`. Add one command-generation test.

## Sources

- Rigol DP800 Programming Guide
- Keysight E36312A, E3631A, and E364xA programming guides
- Siglent SPD3303X programming guide
- R&S HMC804x SCPI reference
- Korad KA3005P serial protocol
- The Keysight E36xx driver in `pymeasure` for cross-checking

## Non-SCPI drivers

### ALIENTEK DP100 (`dp100`, USB HID)

Use `--hid dp100`. The driver uses `hidapi` directly.
The device manual and public implementations define the device enumeration,
frame format, and command set. This document does not repeat them.

### FNIRSI DPS-150 (`dps150`, USB CDC)

The protocol follows `PROTOCOL.md` from `nasheed-x/dps150_api`.

- USB CDC, 115200 8N1, RTS asserted.
- Frame: `F1/F0 | cmd | reg | len | data | checksum`. `checksum = (reg + len + sum(data)) & 0xFF`.
- Commands: `0xC1` session, `0xB1` write register, and `0xA1` read register.
- Key registers:
  - `0xC1` voltage setpoint (float32 LE).
  - `0xC2` current setpoint (float32 LE).
  - `0xC3` measured V, I, and P (three float32 values).
  - `0xD1` and `0xD2` OVP and OCP.
  - `0xDB` output switch (uint8).
  - `0xDE` and `0xE0` model and firmware strings.
  - `0xE2` and `0xE3` maximum voltage and current.
- Send the session frame `F1 C1 00 01 01 02` after you open the port.

### B&K 168x and Manson HCS-3xxx (`bk168x`, serial)

The protocol follows `JacobBeningo/devpsu` (MIT).

- 9600 8N1. End each command with CR. Each response ends with an `OK` line.
- `VOLT123` sets 12.3 V. Use three digits and one decimal place.
- `CURR050` sets 5.0 A. The 1685B uses two decimal places. Add `--current-decimals 2`.
- `GETS` reads setpoints. `GETD` reads measurements and the CV/CC flag.
- `SOUT0` enables the output. `SOUT1` disables the output. The logic is inverted.
- `SOVP` and `SOCP` set protection. `GMAX` reads the model range.

### ITECH (`itech`, SCPI)

The commands follow the ITECH IT6300 Programming Guide.

```
:INSTrument:NSELect <n>
:VOLTage / :CURRent
:OUTPut ON|OFF
:MEASure:VOLTage? / :CURRent? / :POWer?
:VOLTage:PROTection <v>;:VOLTage:PROTection:STATe ON
```

Channels 1 to 3. The IT6900 series uses the same command family.

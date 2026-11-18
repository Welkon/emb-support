"""Native USB transport for the ATK-Logic analyzer.

The vendor CLI is the default path; this module exists for the acquisition
features the CLI does not expose (stage/serial triggers, PWM, rolling mode).
The wire format comes from two independent public sources:

* `apiwat59/atk-dl32-mcp` — `DL32_PROTOCOL.md`, static analysis of the GUI with
  Ghidra, including the framing, CRC and payload layouts.
* `LHX369963/dl16-cli` — a working Python driver for the same commands.

Frame (host -> device, command path)::

    00 x 8 | 0A | cmd | len+1 | payload | 0B | CRC32 (LE, over cmd..payload+0B) | 00

Raw system packets (handshake, reset) use ``0A cmd payload 0B`` padded to 510
bytes. The analyzer answers on the bulk IN endpoint with packets that start with
``0A`` and end with ``0B``.

Safety: nothing here runs unless asked. `usb info` only performs the read-only
handshake (hello, reset, device data) and is the first thing to try on hardware.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

from .common import SkillError

VID_PID = ((0x04B4, 0x6A6A), (0x1A86, 0x6A6B), (0x1A86, 0xFFCC))
RAW_SIZE = 510
RAW_START = 0x0A
RAW_END = 0x0B

# Command ids recovered from the vendor binary.
CMD_DEVICE_DATA = 0x10
CMD_PARAMETERS = 0x11
CMD_TRIGGER_SIMPLE = 0x12
CMD_TRIGGER_STAGE = 0x13
CMD_TRIGGER_SERIAL = 0x14
CMD_STOP = 0x15
CMD_PWM = 0x17
CMD_EXIT = 0x18
CMD_HELLO = 0x81
CMD_RESET = 0x87

# Sample-rate index used by the 0x11 parameter payload.
HZ_INDEX = {
    1_000_000: 1, 2_000_000: 2, 4_000_000: 3, 5_000_000: 4, 10_000_000: 5,
    20_000_000: 6, 25_000_000: 7, 40_000_000: 8, 50_000_000: 9, 100_000_000: 10,
    200_000_000: 11, 250_000_000: 12, 500_000_000: 13, 1_000_000_000: 14,
    400_000_000: 15, 800_000_000: 16,
}
HZ_INDEX_REVERSE = {value: key for key, value in HZ_INDEX.items()}

# Simple trigger codes: 0x8 marks "channel enabled", 0x7 means "do not care".
TRIGGER_NIBBLE = {
    "none": 0x7, "x": 0x7,
    "rising": 0x1, "r": 0x1,
    "high": 0x4, "1": 0x4,
    "falling": 0x2, "f": 0x2,
    "low": 0x0, "0": 0x0,
    "both": 0x3, "either": 0x3,
}


def crc32_atk(data: bytes) -> int:
    """Reflected CRC-32 with seed 0 and final NOT (the vendor's gCRC32)."""
    return zlib.crc32(data, 0xFFFFFFFF) & 0xFFFFFFFF


def frame(command: int, payload: bytes = b"") -> bytes:
    """Host -> device command frame."""
    if len(payload) + 1 > 0xFF:
        raise SkillError(
            "usb_payload_too_long", f"{len(payload)} bytes does not fit one length byte"
        )
    body = bytes((command, len(payload) + 1)) + payload
    crc = crc32_atk(body).to_bytes(4, "little")
    return bytes(8) + bytes((RAW_START,)) + body + bytes((RAW_END,)) + crc + bytes(1)


def raw_packet(command: int, payload: bytes = b"", size: int = RAW_SIZE) -> bytes:
    """System packet: ``0A cmd payload 0B`` padded with zeros."""
    packet = bytes((RAW_START, command)) + payload + bytes((RAW_END,))
    if len(packet) > size:
        raise SkillError("usb_payload_too_long", f"{len(packet)} bytes exceeds {size}")
    return packet + bytes(size - len(packet))


# ---------------------------------------------------------------- payloads

def parameter_payload(frequency_hz: int, duration_ms: int, threshold_volts: float,
                      trigger_position_percent: float = 50.0, *,
                      buffer_mode: bool = True, rle: bool = False,
                      channels: int = 1) -> bytes:
    """13-byte 0x11 payload: flags, threshold, rate index, depth, trigger depth."""
    index = HZ_INDEX.get(int(frequency_hz))
    if index is None:
        raise SkillError(
            "usb_unsupported_rate",
            f"{frequency_hz} Hz has no protocol index",
            [f"legal rates: {', '.join(f'{hz}' for hz in sorted(HZ_INDEX))}"],
        )
    flags = 0
    if buffer_mode:
        flags |= 0x80
    if rle:
        flags |= 0x40
    threshold = round(abs(float(threshold_volts)) * 10)
    if threshold > 0x7F:
        raise SkillError("usb_threshold_range", f"threshold {threshold_volts} V is too large")
    if float(threshold_volts) < 0:
        threshold |= 0x80
    samples = int(int(frequency_hz) * int(duration_ms) // 1000)
    position = int(samples * float(trigger_position_percent) / 100.0)
    channels = max(1, int(channels))
    return (
        bytes((flags, threshold & 0xFF, index))
        + samples.to_bytes(5, "little")
        + position.to_bytes(5, "little")
    )


TRIGGER_CODES = {"none": 0x7, "rising": 0x1, "falling": 0x2,
                 "high": 0x4, "low": 0x0, "both": 0x3}
ENABLE = 0x8


def simple_trigger_payload(states: dict[int, str], channel_offset: int = 0,
                           collect_type: int = 0) -> bytes:
    """0x12 payload in the vendor layout: one byte per channel pair, then a flag.

    Even channel -> high nibble, odd channel -> low nibble; a nibble is
    ``0x8 | code`` when the channel is enabled and ``0x7`` (don't care) when it
    is not. The trailing byte is 1 when capture starts immediately (no trigger
    condition armed) and 0 otherwise.
    """
    pairs = bytearray(16)
    armed = False
    for channel, state in states.items():
        index = channel - channel_offset
        if not 0 <= index < 32:
            raise SkillError("invalid_trigger_channel",
                             f"channel {channel} is outside this bank")
        if state not in TRIGGER_CODES:
            raise SkillError("invalid_trigger_state",
                             f"unknown trigger {state!r}",
                             ["use none, rising, falling, high, low or both"])
        nibble = ENABLE | TRIGGER_CODES[state]
        if state != "none":
            armed = True
        if index % 2 == 0:
            pairs[index // 2] |= nibble << 4
        else:
            pairs[index // 2] |= nibble
    return bytes(pairs) + bytes([0 if armed else 1])


def pack_channel_pairs(states: dict[int, str], channel_offset: int = 0) -> bytes:
    """One byte per channel pair, as used by the 0x12/0x13/0x14 payloads."""
    pairs = bytearray(16)
    for channel, state in states.items():
        index = channel - channel_offset
        if not 0 <= index < 32:
            raise SkillError("invalid_trigger_channel",
                             f"channel {channel} is outside this bank")
        if state not in TRIGGER_CODES:
            raise SkillError("invalid_trigger_state", f"unknown trigger {state!r}",
                             ["use none, rising, falling, high, low or both"])
        nibble = ENABLE | TRIGGER_CODES[state]
        if index % 2 == 0:
            pairs[index // 2] |= nibble << 4
        else:
            pairs[index // 2] |= nibble
    return bytes(pairs)


def stage_trigger_payload(stages: list[dict], trigger_level: int = 0,
                          channel_offset: int = 0) -> bytes:
    """0x13 payload: per stage ``index | level | counter(2 LE) | flag | pairs``."""
    if not stages:
        raise SkillError("invalid_stage_trigger", "at least one stage is required")
    if len(stages) > 0xFF:
        raise SkillError("invalid_stage_trigger", "too many stages")
    output = bytearray()
    for number, stage in enumerate(stages, start=1):
        counter = int(stage.get("counter", 1))
        if not 0 <= counter <= 0xFFFF:
            raise SkillError("invalid_stage_trigger", f"counter {counter} does not fit")
        output.extend((number, trigger_level))
        output.extend(counter.to_bytes(2, "little"))
        output.append(0x00 if stage.get("contiguous", True) else 0x40)
        output.extend(pack_channel_pairs(stage.get("states", {}), channel_offset))
    return bytes(output)


def serial_trigger_payload(value_channel: int, value_width: int, value_data: int,
                           time_channel: int, time_edge: int,
                           start_states: dict[int, str], stop_states: dict[int, str],
                           channel_offset: int = 0) -> bytes:
    """0x14 payload: value channel/width/data, time channel/edge, start and stop."""
    return (bytes((value_channel + channel_offset, value_width))
            + value_data.to_bytes(2, "little")
            + bytes((time_channel + channel_offset, time_edge))
            + pack_channel_pairs(start_states, channel_offset)
            + pack_channel_pairs(stop_states, channel_offset))


def pwm_close_payload() -> bytes:
    """0x17 close-all, as sent by the GUI when it disconnects."""
    return bytes((0x20, 0x10))


# ---------------------------------------------------------------- parsing

def _packets(data: bytes) -> list[bytes]:
    """Split a bulk read into ``0A .. 0B`` packets."""
    packets = []
    index = 0
    while index < len(data):
        if data[index] != RAW_START:
            index += 1
            continue
        end = data.find(bytes((RAW_END,)), index + 1)
        if end < 0:
            break
        packets.append(data[index:end + 1])
        index = end + 1
    return packets


@dataclass
class Hello:
    mode: str
    mcu_version: str
    variant: int
    plus: bool
    raw: bytes


def parse_hello(data: bytes) -> Hello | None:
    """``0A 81 01 <mode> <major> <minor> <variant> 00 00 <plus> 0B``"""
    packet = next((p for p in _packets(data) if len(p) >= 11 and p[1] == CMD_HELLO), None)
    if packet is None:
        return None
    mode = chr(packet[3]) if 0x20 <= packet[3] < 0x7F else "?"
    return Hello(
        mode=mode,
        mcu_version=f"{packet[4]}.{packet[5]}",
        variant=packet[6],
        plus=bool(packet[8]) if len(packet) > 8 else False,
        raw=packet,
    )


def parse_device_data(data: bytes) -> dict:
    """Best effort: the GUI's record parser is not fully documented."""
    name = ""
    for packet in _packets(data):
        for run in re.findall(rb"[A-Za-z0-9][A-Za-z0-9_.-]{2,}", packet):
            token = run.decode("ascii", "ignore")
            if "DL" in token.upper() and " " not in token:
                name = token
    return {"name": name, "bytes": len(data), "packets": len(_packets(data))}


# --------------------------------------------------------------- transport

class Transport:
    """pyusb bulk transport. Imported lazily so the skill works without pyusb."""

    def __init__(self, timeout_ms: int = 300) -> None:
        try:
            import usb.core  # noqa: F401
            import usb.util  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the host
            raise SkillError(
                "usb_backend_missing",
                "pyusb is not installed, so the native transport is unavailable",
                ["pip install pyusb", "or keep using the vendor CLI (default)"],
            ) from exc
        self.timeout_ms = timeout_ms
        self.device = None
        self.ep_in = None
        self.ep_out = None

    def _backend(self):
        """pyusb backend, optionally pinned to a library outside the loader path.

        ``ATK_LOGIC_LIBUSB`` may point at a ``libusb-1.0.so.0`` extracted from a
        .deb, which lets an unprivileged user use the pipeline without installing
        the package system-wide.
        """
        import os

        import usb.backend.libusb1

        override = os.environ.get("ATK_LOGIC_LIBUSB")
        if override:
            return usb.backend.libusb1.get_backend(
                find_library=lambda name, *a, **k: override)
        return usb.backend.libusb1.get_backend()

    def open(self) -> "Transport":
        import usb.core
        import usb.util

        for vid, pid in VID_PID:
            device = usb.core.find(idVendor=vid, idProduct=pid, backend=self._backend())
            if device is not None:
                break
        else:
            raise SkillError(
                "usb_device_not_found",
                "no ATK-Logic analyzer is visible to this process",
                [
                    "on WSL attach it first: usbipd attach --wsl --busid <id>",
                    "check the WinUSB/libusbK driver is bound to the device",
                ],
            )
        cfg = device.get_active_configuration()
        interface = cfg[(0, 0)]
        self.ep_in = usb.util.find_descriptor(
            interface, custom_match=lambda e: usb.util.endpoint_direction(
                e.bEndpointAddress) == usb.util.ENDPOINT_IN)
        self.ep_out = usb.util.find_descriptor(
            interface, custom_match=lambda e: usb.util.endpoint_direction(
                e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        if self.ep_in is None or self.ep_out is None:
            raise SkillError("usb_endpoints_missing", "the device has no bulk in/out pair")
        self.device = device
        return self

    def write(self, data: bytes) -> int:
        return self.ep_out.write(data, timeout=self.timeout_ms)

    def read(self, size: int = 512) -> bytes:
        import usb.core

        try:
            return bytes(self.ep_in.read(size, timeout=self.timeout_ms))
        except usb.core.USBTimeoutError:
            return b""

    def drain(self, limit: int = 64) -> bytes:
        data = b""
        for _ in range(limit):
            chunk = self.read()
            if not chunk:
                break
            data += chunk
        return data

    def close(self) -> None:
        import usb.util

        if self.device is not None:
            usb.util.dispose_resources(self.device)
            self.device = None


# ------------------------------------------------- libusb-free fallback

class UsbfsTransport:
    """Bulk transport through /dev/bus/usb ioctls: no libusb, no download.

    Used when pyusb has no backend. Needs write access to the device node —
    the udev rule from ``scripts/install_udev.sh`` provides it.
    """

    USBDEVFS_CLAIMINTERFACE = 0x8004550F
    USBDEVFS_RELEASEINTERFACE = 0x80045510
    USBDEVFS_BULK = 0xC0185502
    BULK_TIMEOUT_MS = 300

    def __init__(self, fd: int, ep_in: int, ep_out: int) -> None:
        self.fd = fd
        self.ep_in = ep_in
        self.ep_out = ep_out

    @staticmethod
    def find(vid: int, pid: int) -> dict | None:
        """Locate the USB device and its bulk endpoints through sysfs."""
        base = Path("/sys/bus/usb/devices")
        for device in sorted(base.glob("*")):
            try:
                if (device / "idVendor").read_text().strip().lower() != f"{vid:04x}":
                    continue
                if (device / "idProduct").read_text().strip().lower() != f"{pid:04x}":
                    continue
                bus = int((device / "busnum").read_text())
                address = int((device / "devnum").read_text())
            except (OSError, ValueError):
                continue
            bulk_in = bulk_out = None
            for interface in sorted(device.glob("*:*.*")):
                try:
                    number = int((interface / "bInterfaceNumber").read_text(), 16) \
                        if (interface / "bInterfaceNumber").exists() else 0
                except ValueError:
                    number = 0
                for endpoint in interface.glob("ep_*"):
                    try:
                        attributes = int((endpoint / "bmAttributes").read_text(), 16)
                        ep = int((endpoint / "bEndpointAddress").read_text(), 16)
                    except (OSError, ValueError):
                        continue
                    if attributes & 0x3 != 0x2:
                        continue
                    if ep & 0x80 and bulk_in is None:
                        bulk_in = ep
                    elif not ep & 0x80 and bulk_out is None:
                        bulk_out = ep
                if bulk_in and bulk_out:
                    return {"node": f"/dev/bus/usb/{bus:03d}/{address:03d}",
                            "interface": number, "in": bulk_in, "out": bulk_out}
            return None
        return None

    @classmethod
    def open(cls, vid: int = 0x04B4, pid: int = 0x6A6A) -> "UsbfsTransport":
        import ctypes
        import fcntl
        import os

        found = cls.find(vid, pid)
        if found is None:
            raise SkillError(
                "usb_device_not_found",
                f"{vid:04x}:{pid:04x} is not on this USB bus",
                ["attach it: usbipd attach --wsl --busid <id>"],
            )
        try:
            fd = os.open(found["node"], os.O_RDWR)
        except OSError as exc:
            raise SkillError(
                "usb_permission_denied",
                f"cannot open {found['node']}: {exc.strerror}",
                ["install the udev rule: sudo bash scripts/install_udev.sh",
                 "then re-attach the device and log in again for the group change"],
            )
        interface = ctypes.c_uint(found["interface"])
        fcntl.ioctl(fd, cls.USBDEVFS_CLAIMINTERFACE, interface)
        return cls(fd, found["in"], found["out"])

    def _bulk(self, endpoint: int, buffer, length: int, timeout: int) -> int:
        import ctypes
        import fcntl

        class Bulk(ctypes.Structure):
            _fields_ = [("ep", ctypes.c_uint), ("len", ctypes.c_uint),
                        ("timeout", ctypes.c_uint), ("data", ctypes.c_void_p)]

        request = Bulk(endpoint, length, timeout, ctypes.cast(buffer, ctypes.c_void_p))
        try:
            return fcntl.ioctl(self.fd, self.USBDEVFS_BULK, request)
        except OSError:
            return -1

    def write(self, data: bytes) -> int:
        import ctypes

        buffer = ctypes.create_string_buffer(bytes(data), len(data))
        return self._bulk(self.ep_out, buffer, len(data), self.BULK_TIMEOUT_MS)

    def read(self, size: int = 512) -> bytes:
        import ctypes

        buffer = ctypes.create_string_buffer(size)
        got = self._bulk(self.ep_in, buffer, size, self.BULK_TIMEOUT_MS)
        return buffer.raw[:got] if got and got > 0 else b""

    def drain(self, limit: int = 64) -> bytes:
        data = b""
        for _ in range(limit):
            chunk = self.read()
            if not chunk:
                break
            data += chunk
        return data

    def close(self) -> None:
        import os

        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


def open_transport() -> "Transport | UsbfsTransport":
    """pyusb when it has a backend, otherwise the libusb-free ioctl path."""
    try:
        return Transport().open()
    except SkillError as error:
        if error.code != "usb_backend_missing":
            raise
    except Exception as exc:  # pyusb raises NoBackendError before our checks
        if type(exc).__name__ not in ("NoBackendError", "USBError"):
            raise
    return UsbfsTransport.open()


PACKET_START = 0x0A
PACKET_TRAILER = b"\x00\x0b"
PACKET_TYPES = frozenset(range(1, 7))   # 1 = channel samples, 2..6 = status
PACKET_OVERHEAD = 16                    # measured: total = length field + 16
CHANNEL_OFFSET = 14                     # measured: channel id (2 B LE) at packet+14


def iter_packets(data: bytes):
    """Yield (type, channel, payload) packets from a DL32 capture stream.

    Measured layout (verified against a 1 kHz / 50 % calibration source)::

        0A | type | len(2 LE) | 10 B metadata | channel(2 LE) | samples | 00 0B

    with ``total = len + 16``; ``payload`` is the sample region (``len - 2``
    bytes, eight samples per byte, least significant bit first).
    """
    offset = 0
    while offset + PACKET_OVERHEAD <= len(data):
        if data[offset] != PACKET_START or data[offset + 1] not in PACKET_TYPES:
            offset += 1
            continue
        length = int.from_bytes(data[offset + 2:offset + 4], "little")
        total = length + PACKET_OVERHEAD
        if length < 2 or offset + total > len(data):
            offset += 1
            continue
        if data[offset + total - 2:offset + total] != PACKET_TRAILER:
            offset += 1
            continue
        channel = int.from_bytes(data[offset + CHANNEL_OFFSET:offset + CHANNEL_OFFSET + 2], "little")
        payload = data[offset + 4 + CHANNEL_OFFSET - 4 + 2:offset + total - 2]
        yield data[offset + 1], channel, payload
        offset += total


def parse_stream(data: bytes) -> dict:
    """Split a capture stream into per-channel packed samples."""
    channels: dict[int, bytearray] = {}
    status = 0
    packets = 0
    for packet_type, channel, payload in iter_packets(data):
        packets += 1
        if packet_type == 1:
            channels.setdefault(channel, bytearray()).extend(payload)
        else:
            status += 1
    return {"channels": {key: bytes(value) for key, value in channels.items()},
            "packets": packets, "status": status}


def remove_glitches(bits: list[int], max_width: int) -> list[int]:
    """Absorb pulses shorter than ``max_width`` samples into their neighbours."""
    if max_width <= 0 or len(bits) < 3:
        return list(bits)

    def runs(values):
        out = []
        current, length = values[0], 1
        for value in values[1:]:
            if value == current:
                length += 1
            else:
                out.append([current, length])
                current, length = value, 1
        out.append([current, length])
        return out

    changed = True
    while changed:
        changed = False
        current = runs(bits)
        for index in range(1, len(current) - 1):
            if current[index][1] < max_width:
                start_index = sum(length for _, length in current[:index])
                end_index = start_index + current[index][1]
                value = current[index - 1][0]
                bits = bits[:start_index] + [value] * (end_index - start_index) + bits[end_index:]
                changed = True
                break
    return bits


def unpack_bits(block: bytes) -> list[int]:
    """One byte carries 8 consecutive samples, least significant bit first."""
    return [(byte >> bit) & 1 for byte in block for bit in range(8)]


def summarise_channels(channels: dict[int, bytes]) -> list[dict]:
    summary = []
    for channel, body in sorted(channels.items()):
        total = len(body) * 8
        high = sum(byte.bit_count() for byte in body)
        summary.append({"channel": channel, "samples": total, "high": high,
                        "low": total - high, "constant": high in (0, total)})
    return summary


def poll_reply(transport, timeout: float = 1.5) -> bytes:
    """Read until a complete 0A..0B packet arrives or the timeout expires."""
    import time

    deadline = time.monotonic() + timeout
    data = b""
    while time.monotonic() < deadline:
        chunk = transport.read(512)
        if not chunk:
            continue
        data += chunk
        for packet in _packets(data):
            if packet and packet[0] == 0x0A:
                return data
    return data


def apply_config(transport, frequency_hz: int, duration_ms: int, threshold_volts: float,
                 trigger_position_percent: float, states: dict[int, str],
                 only: str = "") -> dict:
    """Reset, send 0x11 parameters and 0x12 simple trigger, report the replies.

    Ends with stop + reset so the device does not stay armed if the caller
    only wanted to test the control path.
    """
    transcript = []

    def exchange(label: str, data: bytes) -> list[str]:
        transport.write(data)
        reply = poll_reply(transport)
        packets = [packet.hex() for packet in _packets(reply)]
        transcript.append({"step": label, "sent": data.hex(), "replies": packets,
                           "bytes": len(reply)})
        return packets

    parameters = parameter_payload(frequency_hz, duration_ms, threshold_volts,
                                   trigger_position_percent)
    trigger = simple_trigger_payload(states)
    steps = {
        "reset-high": raw_packet(CMD_RESET, bytes((1,))),
        "parameters": frame(CMD_PARAMETERS, parameters),
        "trigger-simple": frame(CMD_TRIGGER_SIMPLE, trigger),
        "stop": frame(CMD_STOP),
        "reset-low": raw_packet(CMD_RESET, bytes((0,))),
    }
    for label, data in steps.items():
        if only and label != only:
            continue
        exchange(label, data)
    return {
        "parametersHex": parameters.hex(),
        "triggerHex": trigger.hex(),
        "transcript": transcript,
    }


def capture_native(frequency_hz: int, duration_ms: int, threshold_volts: float,
                   trigger_position_percent: float, states: dict[int, str],
                   collect_type: int = 2, read_seconds: float = 3.0,
                   glitch_width: int = 0, include_packed: bool = False,
                   transport=None) -> dict:
    """hello -> reset -> parameters -> trigger -> read -> stop, then decode.

    ``collect_type=2`` is the only mode that returns real channel data on the
    DL32; 0 and 3 stream an internal pattern.
    """
    import time

    own = transport is None
    handle = transport or open_transport()
    transcript = []
    try:
        for label, packet in (
            ("hello", raw_packet(CMD_HELLO, b"a" * 8)),
            ("reset", raw_packet(CMD_RESET, bytes((1,)))),
        ):
            handle.write(packet)
            transcript.append({"step": label, "reply": poll_reply(handle, 0.5).hex()})
        parameters = parameter_payload(frequency_hz, duration_ms, threshold_volts,
                                       trigger_position_percent)
        trigger = simple_trigger_payload(states, collect_type=collect_type)
        for label, packet in (("parameters", frame(CMD_PARAMETERS, parameters)),
                              ("trigger", frame(CMD_TRIGGER_SIMPLE, trigger))):
            handle.write(packet)
            transcript.append({"step": label, "reply": poll_reply(handle, 0.5).hex()})
        data = b""
        quiet = 0
        deadline = time.monotonic() + read_seconds
        while time.monotonic() < deadline and quiet < 4:
            chunk = handle.read(65536)
            if chunk:
                data += chunk
                quiet = 0
            else:
                quiet += 1
        handle.write(frame(CMD_STOP))
    finally:
        if own:
            handle.close()
    parsed = parse_stream(data)
    stats = []
    for channel, packed in sorted(parsed["channels"].items()):
        bits = unpack_bits(packed)
        if glitch_width:
            bits = remove_glitches(bits, glitch_width)
        if not bits:
            continue
        edges = sum(1 for a, b in zip(bits, bits[1:]) if a != b)
        high = sum(bits)
        seconds = len(bits) / frequency_hz if frequency_hz else 0
        rises = [i for i in range(1, len(bits)) if bits[i] and not bits[i - 1]]
        periods = [b - a for a, b in zip(rises, rises[1:])]
        glitches = sum(1 for period in periods if period < 3)
        clean = sorted(periods)[len(periods) // 2] if periods else 0
        stats.append({
            "frequencyHz": round(frequency_hz / clean, 1) if clean else 0,
            "periodSamples": clean,
            "glitches": glitches,
            "channel": channel,
            "samples": len(bits),
            "high": high,
            "dutyPercent": round(100 * high / len(bits), 3),
            "edges": edges,
            "edgesPerSecond": round(edges / seconds, 1) if seconds else 0,
            "cyclesPerSecond": round(edges / 2 / seconds, 1) if seconds else 0,
            "constant": high in (0, len(bits)),
            "glitchFiltered": glitch_width,
        })
    result = {"bytes": len(data), "packets": parsed["packets"],
              "statusPackets": parsed["status"], "channels": stats,
              "parametersHex": parameters.hex(), "triggerHex": trigger.hex(),
              "transcript": transcript}
    if include_packed:
        result["packed"] = parsed["channels"]
    return result


def read_only_info(transport) -> dict:
    """Handshake and device data: no acquisition, no configuration change."""
    transport.write(raw_packet(CMD_HELLO))
    hello = parse_hello(transport.drain(8))
    if hello is None:
        raise SkillError(
            "usb_handshake_failed",
            "the analyzer did not answer the hello packet",
            ["check the driver binding", "replug the device"],
        )
    transport.write(raw_packet(CMD_RESET, bytes((0,))))
    transport.write(raw_packet(CMD_RESET, bytes((1,))))
    transport.drain(8)
    transport.write(frame(CMD_DEVICE_DATA))
    device = parse_device_data(transport.drain(8))
    return {
        "mode": hello.mode,
        "mcuVersion": hello.mcu_version,
        "variant": hello.variant,
        "plus": hello.plus,
        "device": device,
    }

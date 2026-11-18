import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import usb  # noqa: E402


def crc_reference(data: bytes) -> int:
    """Bit-by-bit reflected CRC-32, seed 0, final NOT (independent of zlib)."""
    crc = 0x00000000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
    return (~crc) & 0xFFFFFFFF


class FrameTest(unittest.TestCase):
    def test_crc_matches_reference(self):
        for payload in (b"", b"\x10", bytes(range(13)), bytes(range(64))):
            self.assertEqual(usb.crc32_atk(payload), crc_reference(payload))

    def test_frame_layout(self):
        payload = bytes(range(5))
        packet = usb.frame(0x11, payload)
        self.assertEqual(len(packet), len(payload) + 17)
        self.assertEqual(packet[:8], bytes(8))
        self.assertEqual(packet[8], 0x0A)
        self.assertEqual(packet[9], 0x11)
        self.assertEqual(packet[10], len(payload) + 1)
        self.assertEqual(packet[11:11 + len(payload)], payload)
        self.assertEqual(packet[-6], 0x0B)
        crc = int.from_bytes(packet[-5:-1], "little")
        self.assertEqual(crc, crc_reference(packet[9:11 + len(payload)]))
        self.assertEqual(packet[-1], 0)

    def test_raw_packet_is_padded(self):
        packet = usb.raw_packet(0x81)
        self.assertEqual(len(packet), usb.RAW_SIZE)
        self.assertEqual(packet[:3], bytes((0x0A, 0x81, 0x0B)))
        self.assertEqual(packet[3:], bytes(usb.RAW_SIZE - 3))


class PayloadTest(unittest.TestCase):
    def test_parameter_payload(self):
        payload = usb.parameter_payload(1_000_000, 10, 1.8, 50)
        self.assertEqual(len(payload), 13)
        self.assertEqual(payload[0], 0x80)
        self.assertEqual(payload[1], 0x12)
        self.assertEqual(payload[2], 1)
        self.assertEqual(int.from_bytes(payload[3:8], "little"), 10_000)
        self.assertEqual(int.from_bytes(payload[8:13], "little"), 5_000)

    def test_parameter_flags(self):
        stream = usb.parameter_payload(2_000_000, 5, -1.2, 25, buffer_mode=False, rle=True)
        self.assertEqual(stream[0], 0x40)
        self.assertEqual(stream[1], 0x80 | 12)
        self.assertEqual(stream[2], 2)
        self.assertEqual(int.from_bytes(stream[3:8], "little"), 10_000)
        self.assertEqual(int.from_bytes(stream[8:13], "little"), 2_500)

    def test_unknown_rate(self):
        with self.assertRaises(Exception):
            usb.parameter_payload(3_000_000, 10, 1.8)

    def test_simple_trigger_layout(self):
        payload = usb.simple_trigger_payload({0: "rising", 1: "falling"})
        self.assertEqual(len(payload), 17)
        self.assertEqual(payload[0], 0x9A)     # ch0 rising (0x8|0x1), ch1 falling (0x8|0x2)
        self.assertEqual(payload[16], 0)       # trigger armed, not immediate

    def test_immediate_capture_flag(self):
        self.assertEqual(usb.simple_trigger_payload({0: "none"})[16], 1)
        self.assertEqual(usb.simple_trigger_payload({12: "high"})[0], 0x00)
        self.assertEqual(usb.simple_trigger_payload({12: "high"})[6], 0xC0)

    def test_hello_from_the_documented_reply(self):
        reply = bytes.fromhex("0a8101" "61" "0100" "01" "000000" "0b")
        hello = usb.parse_hello(reply)
        self.assertIsNotNone(hello)
        self.assertEqual(hello.mode, "a")
        self.assertEqual(hello.mcu_version, "1.0")
        self.assertEqual(hello.variant, 1)
        self.assertFalse(hello.plus)

    def test_hello_plus(self):
        reply = bytes.fromhex("0a8101" "61" "0106" "01" "00" "01" "00" "0b")
        hello = usb.parse_hello(reply)
        self.assertTrue(hello.plus)

    def test_device_data_finds_the_name(self):
        reply = bytes.fromhex("0a020d00ff0000032001220a2a") + b"DL32" + bytes.fromhex("000b")
        info = usb.parse_device_data(reply)
        self.assertEqual(info["name"], "DL32")

    def test_garbage_has_no_hello(self):
        self.assertIsNone(usb.parse_hello(b"\x00" * 32))


if __name__ == "__main__":
    unittest.main()


class StreamTest(unittest.TestCase):
    @staticmethod
    def packet(kind, channel, samples, metadata=b"\x00" * 10):
        body = metadata + channel.to_bytes(2, "little") + samples
        length = len(body) - len(metadata)
        return bytes([0x0A, kind]) + length.to_bytes(2, "little") + body + b"\x00\x0b"

    def test_iter_packets_reads_channel_and_samples(self):
        data = self.packet(1, 5, b"\xaa\x55") + self.packet(1, 6, b"\xff")
        packets = list(usb.iter_packets(data))
        self.assertEqual([(kind, channel) for kind, channel, _ in packets], [(1, 5), (1, 6)])
        self.assertEqual(packets[0][2], b"\xaa\x55")

    def test_parse_stream_groups_samples_per_channel(self):
        data = self.packet(1, 2, b"\x0f") + self.packet(5, 0, b"") + self.packet(1, 2, b"\xf0")
        parsed = usb.parse_stream(data)
        self.assertEqual(parsed["channels"][2], b"\x0f\xf0")
        self.assertEqual(parsed["status"], 1)
        self.assertEqual(parsed["packets"], 3)

    def test_bad_trailer_is_skipped(self):
        broken = bytes([0x0A, 1]) + (2).to_bytes(2, "little") + b"\xaa\xbb\x00\x0c"
        self.assertEqual(list(usb.iter_packets(broken)), [])

    def test_unpack_bits_lsb_first(self):
        self.assertEqual(usb.unpack_bits(bytes([0b00000001, 0b10000000])),
                         [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1])





class GlitchTest(unittest.TestCase):
    def test_short_pulse_is_absorbed(self):
        bits = [0] * 100 + [1] * 100 + [0] * 1 + [1] * 1 + [0] * 100
        filtered = usb.remove_glitches(bits, 3)
        edges = sum(1 for a, b in zip(filtered, filtered[1:]) if a != b)
        self.assertEqual(edges, 2)
        self.assertEqual(len(filtered), len(bits))

    def test_all_glitches_collapse_to_dc(self):
        filtered = usb.remove_glitches([1, 1, 0, 1, 1] * 20, 2)
        self.assertEqual(sum(filtered), len(filtered))

    def test_zero_width_is_a_noop(self):
        bits = [0, 1, 0, 1]
        self.assertEqual(usb.remove_glitches(bits, 0), bits)


class StageTriggerTest(unittest.TestCase):
    def test_single_stage_layout(self):
        payload = usb.stage_trigger_payload([{"states": {2: "rising"}, "counter": 3}])
        self.assertEqual(payload[0], 1)          # stage number
        self.assertEqual(payload[2:4], b"\x03\x00")
        self.assertEqual(payload[4], 0x00)       # contiguous
        self.assertEqual(payload[5], 0x00)       # ch2 is the high nibble of pair 1
        self.assertEqual(payload[6], 0x90)       # ch2 rising in the high nibble of pair 1

    def test_two_stages_concatenate(self):
        payload = usb.stage_trigger_payload([
            {"states": {0: "high"}},
            {"states": {1: "falling"}, "contiguous": False},
        ])
        self.assertEqual(len(payload), 2 * 21)
        self.assertEqual(payload[21], 2)
        self.assertEqual(payload[25], 0x40)

    def test_serial_payload_shape(self):
        payload = usb.serial_trigger_payload(2, 8, 0x55, 1, 1,
                                             {2: "rising"}, {2: "falling"})
        self.assertEqual(payload[0], 2)
        self.assertEqual(payload[1], 8)
        self.assertEqual(payload[2:4], b"\x55\x00")
        self.assertEqual(len(payload), 4 + 2 + 16 + 16)

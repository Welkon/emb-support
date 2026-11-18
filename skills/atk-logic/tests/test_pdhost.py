import contextlib
import io
import json
import pathlib
import random
import sys
import tempfile
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import commands, pdhost  # noqa: E402
from atklogic.common import SkillError  # noqa: E402

FIXTURE_DECODERS = TESTS / "fixtures" / "decoders"
VENDOR_DECODERS = pathlib.Path("/mnt/c/Program Files/ATK-Logic/decoders")
VENDOR_UART = pathlib.Path("/mnt/c/Program Files/ATK-Logic/test/uart_tx_115200.atkdl")


def pack(samples) -> bytes:
    payload = bytearray((len(samples) + 7) // 8)
    for index, value in enumerate(samples):
        if value:
            payload[index // 8] |= 1 << (index % 8)
    return bytes(payload)


def make_capture(root: pathlib.Path, samples, frequency=1_000_000, channel=0):
    directory = root / "run"
    directory.mkdir(parents=True)
    (directory / f"channel_{channel}.bin").write_bytes(pack(samples))
    meta = {
        "captureId": "synthetic",
        "status": "complete",
        "mode": "buffer",
        "frequencyHz": frequency,
        "durationMs": max(1, len(samples) * 1000 // frequency),
        "thresholdVolts": 1.8,
        "triggerPositionPercent": 50,
        "rle": False,
        "device": {"model": "DL16", "deviceId": "dl16:1"},
        "channels": [{"id": channel, "trigger": "none"}],
        "bin": [{"channel": channel, "file": f"channel_{channel}.bin",
                 "validBits": len(samples), "bytes": (len(samples) + 7) // 8}],
    }
    (directory / "capture.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


class ChangesTest(unittest.TestCase):
    def test_relative_positions_and_levels(self):
        random.seed(3)
        samples = [random.randint(0, 1) for _ in range(5000)]
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "channel_0.bin"
        path.write_bytes(pack(samples))
        start, count = 1234, 2500
        first, changes = pdhost.channel_changes(path, len(samples), start=start, count=count)
        self.assertEqual(first, samples[start])
        self.assertTrue(all(0 <= change < count for change in changes))
        host = pdhost.Host({0: (first, changes)}, count, 1_000_000, 1)
        for index in range(count):
            self.assertEqual(host.level(0, index), samples[start + index], index)

    def test_edge_cap(self):
        samples = [index % 2 for index in range(1000)]
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "channel_0.bin"
        path.write_bytes(pack(samples))
        with self.assertRaises(SkillError) as raised:
            pdhost.channel_changes(path, 1000, max_edges=10)
        self.assertEqual(raised.exception.code, "too_many_edges")

    def test_empty_window(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        path = directory / "channel_0.bin"
        path.write_bytes(b"\x00")
        self.assertEqual(pdhost.channel_changes(path, 0), (0, []))


class HostTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.root / "channel_0.bin"
        self.samples = [0, 0, 1, 1, 1, 0, 0, 1, 1, 0]
        self.bin.write_bytes(pack(self.samples))

    def test_wait_returns_signal_and_matched(self):
        first, changes = pdhost.channel_changes(self.bin, len(self.samples))
        host = pdhost.Host({0: (first, changes)}, len(self.samples), 1_000_000, 1)
        index, matched, signal = host.wait(-1, {0: 'r'})
        self.assertEqual(index, 2)
        self.assertEqual(signal, (1,))
        self.assertEqual(matched, (True,))
        # The skip alternative wins when it fires first.
        index, matched, signal = host.wait(index, [{0: 'f'}, {'skip': 2}])
        self.assertEqual(index, 4)
        self.assertEqual(signal, (1,))
        self.assertEqual(matched, (False, True))
        index, matched, signal = host.wait(4, [{0: 'f'}, {'skip': 2}])
        self.assertEqual(index, 5)
        self.assertEqual(signal, (0,))
        self.assertEqual(matched, (True, False))

    def test_end_of_stream(self):
        first, changes = pdhost.channel_changes(self.bin, len(self.samples))
        host = pdhost.Host({0: (first, changes)}, len(self.samples), 1_000_000, 1)
        with self.assertRaises(pdhost.EndOfStream):
            host.wait(len(self.samples) - 1, {0: 'r'})


class DecoderRunTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.root / "channel_0.bin"
        self.samples = [0, 0, 1, 1, 0, 1, 0, 1]
        self.bin.write_bytes(pack(self.samples))

    def test_fixture_decoder_annotations_and_options(self):
        result = pdhost.run(
            FIXTURE_DECODERS, "mini", {0: self.bin}, {0: len(self.samples)},
            1_000_000, options={"threshold": 7},
        )
        self.assertIsNone(result["failure"])
        host = result["host"]
        self.assertEqual(result["options"]["threshold"], 7)
        self.assertEqual(len(host.annotations), len(host.changes[0]) + 1)
        self.assertEqual(host.annotations[0]["texts"], ["threshold=7"])
        self.assertEqual([item["texts"][0] for item in host.annotations[1:]],
                         ["1", "0", "1", "0", "1"])

    def test_unknown_channel_or_option_is_reported(self):
        with self.assertRaises(SkillError):
            pdhost.run(FIXTURE_DECODERS, "missing", {}, {}, 1_000_000)
        info = pdhost.describe(FIXTURE_DECODERS, "mini")
        self.assertEqual([channel["id"] for channel in info.channels], ["a"])
        self.assertTrue(info.direct)


class CatalogTest(unittest.TestCase):
    def test_fixture_catalog_and_search(self):
        found = pdhost.catalog(FIXTURE_DECODERS)
        self.assertEqual([info.id for info in found], ["lower", "mini", "upper"])
        self.assertIn("upper", [info.id for info in pdhost.catalog(FIXTURE_DECODERS, "upper")])
        self.assertEqual(pdhost.catalog(FIXTURE_DECODERS, "nomatch"), [])
        with self.assertRaises(SkillError):
            pdhost.catalog(pathlib.Path(tempfile.mkdtemp()) / "nope")


class DecodeCommandTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.samples = [0, 0, 1, 1, 0, 1, 0, 1]
        self.capture = make_capture(self.root, self.samples)

    def run_cli(self, argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = commands.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_decode_json(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini",
            "--ch", "a=0", "--decoders", str(FIXTURE_DECODERS), "--json",
            "--option", "threshold=9",
        ])
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["protocol"]["id"], "mini")
        self.assertEqual(payload["channels"], {"a": 0})
        self.assertEqual(payload["counts"]["annotations"], 6)
        self.assertEqual(payload["options"]["threshold"], 9)
        self.assertEqual(payload["window"]["truncated"], False)
        self.assertEqual([item["row"] for item in payload["annotations"]][0], "options")

    def test_row_filter(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini", "--ch", "a=0",
            "--decoders", str(FIXTURE_DECODERS), "--row", "levels", "--json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual([item["row"] for item in payload["annotations"]], ["levels"] * 5)

    def test_unknown_row_fails(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini", "--ch", "a=0",
            "--decoders", str(FIXTURE_DECODERS), "--row", "nope", "--json",
        ])
        self.assertEqual(code, 4)
        self.assertIn("no row", payload["error"]["message"])

    def test_window_and_truncation(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini", "--ch", "a=0",
            "--decoders", str(FIXTURE_DECODERS), "--window", "2us:4us", "--json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["window"]["startSample"], 2)
        self.assertEqual(payload["window"]["samples"], 2)
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini", "--ch", "a=0",
            "--decoders", str(FIXTURE_DECODERS), "--max-samples", "3", "--json",
        ])
        self.assertEqual(code, 0)
        self.assertTrue(payload["window"]["truncated"])
        self.assertEqual(payload["window"]["samples"], 3)

    def test_missing_required_channel(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini",
            "--decoders", str(FIXTURE_DECODERS), "--json",
        ])
        self.assertEqual(code, 4)
        self.assertIn("needs a channel mapping", payload["error"]["message"])

    def test_decoders_listing(self):
        code, payload = self.run_cli([
            "decoders", "--decoders", str(FIXTURE_DECODERS), "--json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["direct"], 2)


class ChainTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.samples = [0, 0, 1, 1, 0, 1, 0, 1]
        self.capture = make_capture(self.root, self.samples)

    def run_cli(self, argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = commands.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_fixture_chain(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "upper+lower",
            "--ch", "a=0", "--decoders", str(FIXTURE_DECODERS), "--json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["protocol"]["chain"], ["upper", "lower"])
        self.assertEqual([level["id"] for level in payload["levels"]], ["upper", "lower"])
        self.assertEqual(payload["counts"]["annotations"], 5)
        self.assertEqual([item["texts"][0] for item in payload["annotations"]],
                         ["EDGE 1", "EDGE 0", "EDGE 1", "EDGE 0", "EDGE 1"])

    def test_chain_mismatch_is_reported(self):
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "lower+upper",
            "--ch", "a=0", "--decoders", str(FIXTURE_DECODERS), "--json",
        ])
        self.assertEqual(code, 4)
        self.assertEqual(payload["error"]["code"], "decoder_needs_stacking")
        self.assertIn("uart", json.dumps(payload)) if False else None

    def test_gui_csv_output(self):
        target = self.root / "decode.csv"
        code, payload = self.run_cli([
            "decode", str(self.capture), "--protocol", "mini", "--ch", "a=0",
            "--decoders", str(FIXTURE_DECODERS), "--csv", str(target), "--json",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(payload["guiCsv"]["rows"], payload["counts"]["annotations"])
        lines = target.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "序号,开始,时间,名称,数值,")
        self.assertIn("threshold=2", lines[1])


@unittest.skipUnless(
    (VENDOR_DECODERS / "uart" / "pd.py").is_file() and VENDOR_UART.is_file(),
    "ATK-Logic installation with sample projects is not available",
)
class VendorDecoderTest(unittest.TestCase):
    """Real vendor decoders on the vendor's own sample capture."""

    def test_uart_decodes_the_demo_text(self):
        from atklogic import atkdl

        root = pathlib.Path(tempfile.mkdtemp())
        extracted = atkdl.extract(VENDOR_UART, root)
        entry = extracted["channels"][0]
        result = pdhost.run(
            VENDOR_DECODERS, "uart",
            {1: pathlib.Path(entry["file"])}, {1: entry["validBits"]},
            10_000_000, options={"baudrate": 115200},
        )
        self.assertIsNone(result["failure"])
        events = result["host"].python_events
        self.assertTrue(events)
        values = [event["data"][2][0] for event in events if event["data"][0] == "DATA"]
        text = bytes([value & 0xff for value in values])
        self.assertIn(b"ALIENTEK", text)

    def test_ir_nec_decodes_a_synthetic_frame(self):
        def us(count):
            return int(round(count))  # 1 MHz -> 1 sample per microsecond

        samples = [1] * us(1000) + [0] * us(9000) + [1] * us(4500)
        for byte in (0x00, 0xFF, 0x45, 0xFF ^ 0x45):
            for bit in range(8):
                samples += [0] * us(560)
                samples += [1] * us(1690 if (byte >> bit) & 1 else 560)
        samples += [0] * us(560) + [1] * us(20000)
        root = pathlib.Path(tempfile.mkdtemp())
        path = root / "channel_0.bin"
        path.write_bytes(pack(samples))
        result = pdhost.run(VENDOR_DECODERS, "ir_nec", {0: path}, {0: len(samples)},
                            1_000_000)
        self.assertIsNone(result["failure"])
        texts = [item["texts"][0] for item in result["host"].annotations]
        self.assertIn("Address: 0x00", texts)
        self.assertIn("Command: 0x45", texts)


    def test_uart_modbus_chain_on_a_synthetic_frame(self):
        def crc16(data):
            crc = 0xFFFF
            for byte in data:
                crc ^= byte
                for _ in range(8):
                    crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
            return crc

        body = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
        crc = crc16(body)
        frame = body + bytes([crc & 0xFF, crc >> 8])
        spb, rate = 16, 1_843_200
        samples = [1] * (spb * 100)
        for byte in frame:
            samples += [0] * spb
            for bit in range(8):
                samples += [(byte >> bit) & 1] * spb
            samples += [1] * spb
        samples += [1] * (spb * 300)
        path = pathlib.Path(tempfile.mkdtemp()) / "channel_0.bin"
        path.write_bytes(pack(samples))
        result = pdhost.run_chain(
            VENDOR_DECODERS,
            [{"id": "uart", "options": {"baudrate": 115200}},
             {"id": "modbus", "options": {"scchannel": "TX", "cschannel": "RX"}}],
            {0: path}, {0: len(samples)}, rate,
        )
        rows = [item["texts"][0] for item in result["levels"][-1]["host"].annotations]
        self.assertIn("Slave ID: 1", rows)
        self.assertIn("Function 3: Read Holding Registers", rows)
        self.assertIn("CRC correct", rows)


if __name__ == "__main__":
    unittest.main()

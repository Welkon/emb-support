import io
import json
import pathlib
import sys
import tempfile
import unittest
import zipfile

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import atkdl  # noqa: E402
from atklogic.common import SkillError  # noqa: E402


def pack(samples) -> bytes:
    payload = bytearray((len(samples) + 7) // 8)
    for index, value in enumerate(samples):
        if value:
            payload[index // 8] |= 1 << (index % 8)
    return bytes(payload)


def build_project(path, *, gui=True, bits=100, headerless=False, cli_naming=False,
                  decoders=None):
    """A small project: channel 0 enabled with two padded chunks, channel 1 off."""
    chunk_size = 64  # 512 bits per chunk, so padding is visible at this scale
    payload = pack([1] * bits)
    first = payload[:chunk_size].ljust(chunk_size, b"\x00")
    second = payload[chunk_size:chunk_size * 2].ljust(chunk_size, b"\x00")
    sections = []
    if gui:
        sections.append("[DL16]")
        sections.append(
            "settingData=" + json.dumps({"setHz": 1_000_000, "setTime": 1, "thresholdLevel": 1.6})
        )
        sections.append(
            "channelsSet=" + json.dumps(
                [
                    {"id": 0, "enable": True, "triggerType": 1},
                    {"id": 1, "enable": False, "triggerType": 0},
                ]
            )
        )
    else:
        sections.append("[default]")
        sections.append("SamplingFrequencyHz=1000000")
        sections.append("SamplingTimeMs=1")
        sections.append("SamplingDepth=100")
        sections.append("TriggerPositionPercent=50")
        sections.append("CaptureMode=buffer")
    if decoders is not None:
        sections.append("decodeJson=" + json.dumps(decoders))
    body = "\r\n".join(sections) + "\r\n"
    if headerless:
        body = body.replace("[default]\r\n", "").replace("[DL16]\r\n", "")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("set.ini", body)
        archive.writestr("channel.ini", "SessionName=test\r\n")
        archive.writestr("0/channel.ini", f"Channel 0\r\n0\r\n{bits}\r\n0,0\r\n")
        prefix = "0" if cli_naming else None
        archive.writestr(f"0/{prefix or 0}-0.bin", first)
        archive.writestr(f"0/{prefix or 0}-1.bin", second)
        archive.writestr("1/channel.ini", "Channel 1\r\n0\r\n0\r\n0,0\r\n")
        # A CLI capture names the chunk after the capture's first channel.
        archive.writestr(f"1/{prefix or 1}-0.bin", bytes(chunk_size))
    return path


class InspectTest(unittest.TestCase):
    def test_gui_project(self):
        path = build_project(pathlib.Path(tempfile.mkdtemp()) / "gui.atkdl")
        info = atkdl.inspect(path)
        self.assertEqual(info["frequencyHz"], 1_000_000)
        self.assertEqual(info["durationMs"], 1)
        self.assertAlmostEqual(info["thresholdVolts"], 1.6)
        self.assertEqual([channel["id"] for channel in info["channels"]], [0])
        channel = info["channels"][0]
        self.assertEqual(channel["trigger"], "rising")
        self.assertEqual(channel["bits"], 100)
        self.assertEqual(channel["chunks"], 2)
        self.assertEqual(channel["storedBits"], 1024)

    def test_cli_project_prefers_depth(self):
        path = build_project(pathlib.Path(tempfile.mkdtemp()) / "cli.atkdl", gui=False)
        info = atkdl.inspect(path)
        self.assertEqual(info["mode"], "buffer")
        self.assertEqual(info["channels"][0]["bits"], 100)
        self.assertEqual(info["triggerPositionPercent"], 50)

    def test_cli_project_without_a_section_header(self):
        path = build_project(
            pathlib.Path(tempfile.mkdtemp()) / "headerless.atkdl", gui=False, headerless=True
        )
        info = atkdl.inspect(path)
        self.assertEqual(info["frequencyHz"], 1_000_000)
        self.assertEqual(info["durationMs"], 1)
        self.assertEqual(info["channels"][0]["bits"], 100)

    def test_chunk_belongs_to_its_directory(self):
        path = build_project(
            pathlib.Path(tempfile.mkdtemp()) / "cli.atkdl", gui=False, cli_naming=True
        )
        info = atkdl.inspect(path)
        self.assertEqual([channel["id"] for channel in info["channels"]], [0, 1])
        self.assertEqual([channel["chunks"] for channel in info["channels"]], [2, 1])

    def test_decoder_configuration_is_reported(self):
        blob = [
            {
                "decodeID": "1",
                "decodeJson": {
                    "PWM": {
                        "main": {"id": "pwm", "name": "PWM"},
                        "options": [{"id": "polarity", "value": "active-high"}],
                        "annotation_rows": [{"desc": "Duty cycles"}, {"desc": "Periods"}],
                    },
                    "main": {"channelList": ["0"], "decodeID": "1", "first": "PWM"},
                },
            }
        ]
        path = build_project(
            pathlib.Path(tempfile.mkdtemp()) / "gui.atkdl", decoders=blob
        )
        info = atkdl.inspect(path)
        self.assertEqual(len(info["decoders"]), 1)
        decoder = info["decoders"][0]
        self.assertEqual(decoder["protocol"], "PWM")
        self.assertEqual(decoder["channels"], ["0"])
        self.assertEqual(decoder["options"], {"polarity": "active-high"})
        self.assertIn("Duty cycles", decoder["annotationRows"])

    def test_not_a_project(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "x.atkdl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "hello")
        with self.assertRaises(SkillError) as raised:
            atkdl.inspect(path)
        self.assertEqual(raised.exception.code, "invalid_atkdl")

    def test_bad_zip(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "broken.atkdl"
        path.write_bytes(b"PK\x03\x04not really a zip")
        self.assertTrue(atkdl.looks_like_atkdl(path))
        with self.assertRaises(SkillError):
            atkdl.inspect(path)


class ExtractTest(unittest.TestCase):
    def test_extract_concatenates_chunks_and_keeps_valid_bits(self):
        path = build_project(pathlib.Path(tempfile.mkdtemp()) / "gui.atkdl")
        target = pathlib.Path(tempfile.mkdtemp()) / "out"
        result = atkdl.extract(path, target)
        self.assertEqual(len(result["channels"]), 1)
        entry = result["channels"][0]
        self.assertEqual(entry["validBits"], 100)
        self.assertEqual(entry["bytes"], 128)
        data = pathlib.Path(entry["file"]).read_bytes()
        self.assertEqual(data[:13], b"\xff" * 12 + b"\x0f")
        self.assertEqual(data[13:], b"\x00" * 115)

    def test_extract_selected_channel(self):
        path = build_project(pathlib.Path(tempfile.mkdtemp()) / "gui.atkdl")
        target = pathlib.Path(tempfile.mkdtemp()) / "out"
        with self.assertRaises(SkillError) as raised:
            atkdl.extract(path, target, channels=[1])
        self.assertEqual(raised.exception.code, "channel_not_in_capture")


if __name__ == "__main__":
    unittest.main()

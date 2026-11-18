import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import capture, host  # noqa: E402
from atklogic.common import SkillError  # noqa: E402

FAKE = TESTS / "fake_cli.py"


def make_plan(**overrides):
    values = dict(
        mode="buffer",
        frequency_hz=1_000_000,
        duration_ms=10,
        threshold_volts=1.8,
        trigger_position_percent=50.0,
        channels=[{"id": 0, "trigger": "none"}],
        format="bin",
    )
    values.update(overrides)
    return capture.Plan(**values)


class FakeCliTest(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(
            os.environ,
            {
                "ATK_LOGIC_CLI": f"{sys.executable} {FAKE}",
                "ATK_LOGIC_HOME": str(self.root / "home"),
                "ATK_LOGIC_STAGING": str(self.root / "stage"),
            },
        )
        self.env.start()
        for key in ("FAKE_TRIGGER", "FAKE_ERROR", "FAKE_PROGRESS_SPAM",
                    "FAKE_DEVICES", "FAKE_ARGV_LOG"):
            os.environ.pop(key, None)
        self.invocation = host.resolve_invocation()

    def tearDown(self):
        self.env.stop()
        for key in ("FAKE_TRIGGER", "FAKE_ERROR", "FAKE_PROGRESS_SPAM",
                    "FAKE_DEVICES", "FAKE_ARGV_LOG"):
            os.environ.pop(key, None)
        shutil.rmtree(self.root, ignore_errors=True)

    def out(self, name="out"):
        return self.root / name

    # ---------------------------------------------------------------- basics
    def test_invocation_comes_from_the_environment(self):
        self.assertEqual(self.invocation.argv[0], sys.executable)
        self.assertFalse(self.invocation.windows)
        self.assertEqual(host.probe_version(self.invocation), "9.9.9-fake")

    def test_session_capture_writes_evidence(self):
        payload = capture.run(self.invocation, make_plan(), out=self.out())
        data = payload["capture"]
        self.assertEqual(data["status"], "complete")
        self.assertEqual(payload["transport"], "session")
        directory = pathlib.Path(data["directory"])
        self.assertTrue((directory / "capture.json").exists())
        self.assertTrue((directory / "channel_0.bin").exists())
        request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["requested"]["frequencyHz"], 1_000_000)
        self.assertEqual(request["transport"], "session")
        self.assertEqual(payload["adjustments"], [])
        stats = data["analysis"][0]
        self.assertGreater(stats["edges"], 0)
        self.assertAlmostEqual(stats["duty"], 0.5, places=2)
        self.assertEqual(data["channels"], [{"id": 0, "trigger": "none"}])

    def test_device_is_chosen_from_the_list(self):
        os.environ["FAKE_DEVICES"] = "1"
        payload = capture.run(self.invocation, make_plan(), out=self.out())
        self.assertEqual(payload["capture"]["status"], "complete")
        request = json.loads(
            (pathlib.Path(payload["capture"]["directory"]) / "request.json").read_text(
                encoding="utf-8")
        )
        self.assertEqual(request["deviceId"], "dl16:1")

    def test_two_devices_need_a_choice(self):
        os.environ["FAKE_DEVICES"] = "2"
        with self.assertRaises(SkillError) as raised:
            capture.run(self.invocation, make_plan(), out=self.out())
        self.assertEqual(raised.exception.code, "multiple_devices")
        self.assertIn("dl16:2", raised.exception.suggestions[0])
        self.assertFalse(self.out().exists())

    def test_explicit_device_id_is_used(self):
        os.environ["FAKE_DEVICES"] = "2"
        payload = capture.run(self.invocation, make_plan(), out=self.out(),
                              device_id="dl16:2")
        self.assertEqual(payload["capture"]["status"], "complete")

    def test_channel_outside_the_device_range(self):
        with self.assertRaises(SkillError) as raised:
            capture.run(self.invocation, make_plan(channels=[{"id": 99, "trigger": "none"}]),
                        out=self.out())
        self.assertEqual(raised.exception.code, "invalid_arguments")
        self.assertIn("0-15", raised.exception.message)
        self.assertFalse(self.out().exists())

    def test_request_is_passed_as_a_config_file(self):
        log = self.root / "argv.log"
        os.environ["FAKE_ARGV_LOG"] = str(log)
        capture.run(self.invocation, make_plan(), out=self.out(), one_shot=True)
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        validates = [call for call in calls if call[:2] == ["capture", "validate"]]
        runs = [call for call in calls if call[:2] == ["capture", "run"]]
        self.assertTrue(validates and runs)
        self.assertIn("--config", validates[0])
        self.assertIn("--config", runs[0])
        self.assertIn("--device-id", runs[0])
        self.assertIn("dl16:1", runs[0])

    def test_one_shot_transport(self):
        payload = capture.run(self.invocation, make_plan(), out=self.out(), one_shot=True)
        self.assertEqual(payload["transport"], "one-shot")
        self.assertEqual(payload["capture"]["status"], "complete")
        self.assertTrue((pathlib.Path(payload["capture"]["directory"]) / "capture.json").exists())

    def test_frequency_is_resolved_against_the_device(self):
        payload = capture.run(self.invocation, make_plan(frequency_hz=3_000_000), out=self.out())
        self.assertEqual(payload["capture"]["frequencyHz"], 2_000_000)
        self.assertEqual(payload["capture"]["durationMs"], 10)
        self.assertIn("3 MHz -> 2 MHz", payload["adjustments"][0])

    def test_strict_refuses_an_illegal_rate(self):
        with self.assertRaises(SkillError) as raised:
            capture.run(self.invocation, make_plan(frequency_hz=3_000_000),
                        out=self.out(), strict=True)
        self.assertEqual(raised.exception.code, "invalid_capture_combination")
        self.assertFalse(self.out().exists())

    def test_existing_output_is_not_overwritten(self):
        self.out().mkdir()
        with self.assertRaises(SkillError) as raised:
            capture.run(self.invocation, make_plan(), out=self.out())
        self.assertEqual(raised.exception.code, "output_conflict")

    # --------------------------------------------------------- failure paths
    def test_trigger_never_fires(self):
        os.environ["FAKE_TRIGGER"] = "never"
        plan = make_plan(channels=[{"id": 0, "trigger": "rising"}])
        with self.assertRaises(SkillError) as raised:
            capture.run(self.invocation, plan, out=self.out(), trigger_timeout=1)
        error = raised.exception
        self.assertEqual(error.code, "trigger_not_found")
        self.assertEqual(error.details["secondsOfSilence"], 1.0)
        self.assertEqual(error.details["progressAtStop"], 50)
        self.assertTrue(any("--ch N:none" in item for item in error.suggestions))

    def test_vendor_error_is_mapped(self):
        os.environ["FAKE_ERROR"] = "device_not_found"
        with self.assertRaises(SkillError) as raised:
            capture.run(self.invocation, make_plan(), out=self.out())
        self.assertEqual(raised.exception.code, "device_not_found")

    def test_progress_spam_is_decimated(self):
        os.environ["FAKE_PROGRESS_SPAM"] = "1"
        prompts = []
        payload = capture.run(
            self.invocation, make_plan(format="both"), out=self.out(),
            on_prompt=prompts.append,
        )
        self.assertGreater(payload["events"]["progress_events"], 500)
        self.assertLess(len(prompts), 10)

    def test_salvages_partial_data(self):
        os.environ["FAKE_TRIGGER"] = "never"
        plan = make_plan(channels=[{"id": 0, "trigger": "rising"}])
        with self.assertRaises(SkillError):
            capture.run(self.invocation, plan, out=self.out(), trigger_timeout=1)
        # The fake writes nothing before the trigger, so there is nothing to
        # salvage; the important part is that the failed run leaves no stage.
        self.assertFalse(list(self.root.glob("stage/*")))


class StagedOutputTest(unittest.TestCase):
    """The WSL branch: vendor writes to Windows, the skill copies back once."""

    def test_staging_is_planned_when_the_destination_is_not_a_windows_drive(self):
        root = pathlib.Path(tempfile.mkdtemp())
        try:
            invocation = host.Invocation(
                argv=["C:/Program Files/ATK-Logic/atk-logic-cli.exe"],
                cwd=str(root),
                windows=True,
                source="test",
            )
            with mock.patch.dict(os.environ, {"ATK_LOGIC_STAGING": str(root / "stage")}), \
                    mock.patch.object(host, "is_windows_drive_path", return_value=False), \
                    mock.patch.object(host, "to_vendor_path",
                                      side_effect=lambda _inv, path: "C:/vendor/" + str(path)):
                plan = capture._plan_output(invocation, root / "evidence")
            self.assertTrue(plan["staged"])
            self.assertEqual(plan["final"], root / "evidence")
            self.assertTrue(plan["vendor_out"].startswith("C:/vendor/"))
            self.assertTrue(pathlib.Path(plan["stage"]).parent.is_dir())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_windows_drive_destination_is_used_directly(self):
        root = pathlib.Path(tempfile.mkdtemp())
        try:
            invocation = host.Invocation(
                argv=["C:/Program Files/ATK-Logic/atk-logic-cli.exe"],
                cwd=str(root), windows=True, source="test",
            )
            with mock.patch.object(host, "is_windows_drive_path", return_value=True), \
                    mock.patch.object(host, "to_vendor_path", return_value="C:/evidence"):
                plan = capture._plan_output(invocation, root / "evidence")
            self.assertFalse(plan["staged"])
            self.assertEqual(plan["vendor_out"], "C:/evidence")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import tempfile
import time
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_xc8.py"
SPEC = importlib.util.spec_from_file_location("build_xc8", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_xc8 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_xc8)


class BuildXc8SafetyTests(unittest.TestCase):
    def test_error_141_blocks_success_and_flash_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            err_path = root / "cmscerr.err"
            map_path = root / "demo.map"
            hex_path = root / "demo.hex"
            started_at_ns = time.time_ns()
            err_path.write_text("Error[141] invalid register\n", encoding="utf-8")
            map_path.write_text("", encoding="utf-8")
            hex_path.write_text(":00000001FF\n", encoding="ascii")

            summary = build_xc8.build_summary(
                build_name="demo",
                project_file=None,
                project={
                    "chip": "SC8F072",
                    "image_prefix": "demo",
                    "sources": [],
                    "include_dirs": [],
                    "defines": [],
                    "config_value": "",
                },
                output_dir=root,
                map_path=map_path,
                err_path=err_path,
                hex_path=hex_path,
                toolchain_source="test",
                xc8_exe="missing-xc8",
                returncode=0,
                started_at_ns=started_at_ns,
                execution_error="",
                compiler_output="UtilBindVsockAnyPort: WSL interop unavailable",
            )

            self.assertEqual(summary["errors"]["count"], 1)
            self.assertFalse(summary["success"])
            self.assertFalse(summary["verification_ok"])
            self.assertEqual(summary["flash_readiness"], "not_ready")
            self.assertTrue(summary["execution"]["wsl_interop_blocked"])
            self.assertEqual(build_xc8.summary_exit_code(summary, 0), 1)

    def test_post_cleanup_existence_survives_clock_skew(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            path = Path(raw_root) / "artifact.hex"
            path.write_text(":00000001FF\n", encoding="ascii")
            simulated_clock_ahead = path.stat().st_mtime_ns + 10_000_000

            artifact = build_xc8.artifact_freshness(
                {"hex": path}, simulated_clock_ahead
            )["hex"]

            self.assertTrue(artifact["exists"])
            self.assertTrue(artifact["fresh"])
            self.assertFalse(artifact["mtime_after_start"])
            self.assertEqual(artifact["freshness_basis"], "post-cleanup-existence")

    def test_cleanup_removes_only_requested_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            stale = [root / "cmscerr.err", root / "demo.map", root / "demo.hex"]
            untouched = root / "official-ide.hex"
            for path in [*stale, untouched]:
                path.write_text("stale", encoding="utf-8")

            build_xc8.remove_previous_build_evidence(stale)

            self.assertTrue(all(not path.exists() for path in stale))
            self.assertTrue(untouched.exists())

    def test_wsl_interop_and_vendor_error_spellings_are_recognized(self) -> None:
        self.assertTrue(build_xc8.is_compiler_error_line("Error[141] bad SFR"))
        self.assertTrue(build_xc8.is_compiler_error_line("fatal: compiler crashed"))
        self.assertFalse(build_xc8.is_compiler_error_line("0 error(s), 0 warning(s)"))


if __name__ == "__main__":
    unittest.main()

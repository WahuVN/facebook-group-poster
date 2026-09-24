import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import package_portable as packaging
import portable_preflight as preflight


class PortablePackagingTests(unittest.TestCase):
    def test_runtime_lock_is_exact_and_matches_contract(self):
        runtime_text = (packaging.ROOT / "requirements-runtime.lock").read_text(encoding="utf-8")
        for name, version in packaging.LOCKED_RUNTIME.items():
            self.assertIn(f"{name}=={version}", runtime_text)
        self.assertNotIn(">=", runtime_text)
        self.assertNotIn("~=", runtime_text)

        build_text = (packaging.ROOT / "requirements-build.lock").read_text(encoding="utf-8")
        for name, version in packaging.LOCKED_BUILD.items():
            self.assertIn(f"{name.lower()}=={version}".lower(), build_text.lower())
        self.assertNotIn(">=", build_text)
        self.assertNotIn("~=", build_text)

    def test_public_release_gate_fails_closed_without_authority(self):
        allowed, blockers = packaging.public_release_allowed()
        self.assertFalse(allowed)
        self.assertTrue(any("LICENSE" in item for item in blockers))
        self.assertTrue(any("authority" in item for item in blockers))

    def test_forbidden_local_state_is_rejected(self):
        forbidden = [
            Path(".fb_session.json"), Path("session.json"), Path("posts.csv"),
            Path("error_1_20260917.png"), Path("logs/events.jsonl"),
            Path("__pycache__/x.pyc"), Path(".venv/Scripts/python.exe"),
        ]
        for path in forbidden:
            self.assertTrue(packaging.is_forbidden_relative(path), path)
        self.assertFalse(packaging.is_forbidden_relative(Path("README.md")))

    def test_deterministic_zip_normalizes_order_and_timestamp(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "b.txt").write_text("B", encoding="utf-8")
            (source / "a.txt").write_text("A", encoding="utf-8")
            zip1 = root / "one.zip"
            zip2 = root / "two.zip"
            packaging.deterministic_zip(source, zip1)
            packaging.deterministic_zip(source, zip2)
            self.assertEqual(packaging.sha256_file(zip1), packaging.sha256_file(zip2))
            with zipfile.ZipFile(zip1) as archive:
                self.assertEqual(archive.namelist(), ["a.txt", "b.txt"])
                self.assertEqual(archive.getinfo("a.txt").date_time, (1980, 1, 1, 0, 0, 0))

    def test_preflight_report_does_not_expose_configured_browser_path(self):
        with tempfile.TemporaryDirectory() as td:
            fake_browser = Path(td) / "browser.exe"
            fake_browser.write_bytes(b"stub")
            with patch.dict(
                "os.environ",
                {"LOCALAPPDATA": td, "BROWSER_EXECUTABLE_PATH": str(fake_browser)},
                clear=False,
            ):
                report = preflight.build_report()
            serialized = json.dumps(report, ensure_ascii=False)
            self.assertNotIn(str(fake_browser), serialized)
            self.assertTrue(report["browser"]["ok"])

    def test_canonical_source_inputs_exist(self):
        hashes = packaging.source_hashes()
        self.assertEqual(set(hashes), set(packaging.SOURCE_INPUTS))
        for digest in hashes.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

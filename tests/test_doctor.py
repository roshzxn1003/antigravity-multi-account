"""
Unit tests for agm doctor diagnostics.
"""

import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from agm import core, doctor


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="agm_doc_test_"))
        self.orig_config_dir = core.CONFIG_DIR
        self.orig_profiles_dir = core.PROFILES_DIR
        self.orig_config_file = core.CONFIG_FILE
        self.orig_active_file = core.ACTIVE_PROFILE_FILE

        core.CONFIG_DIR = self.test_dir / ".config" / "agy-accounts"
        core.PROFILES_DIR = core.CONFIG_DIR / "profiles"
        core.CONFIG_FILE = core.CONFIG_DIR / "config.json"
        core.ACTIVE_PROFILE_FILE = core.CONFIG_DIR / "active"
        core.ensure_base_dirs()

    def tearDown(self):
        core.CONFIG_DIR = self.orig_config_dir
        core.PROFILES_DIR = self.orig_profiles_dir
        core.CONFIG_FILE = self.orig_config_file
        core.ACTIVE_PROFILE_FILE = self.orig_active_file
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_run_doctor_checks(self):
        checks = doctor.run_doctor_checks(core)
        self.assertTrue(len(checks) >= 5)
        names = [c.name for c in checks]
        self.assertTrue(any("Antigravity CLI Binary" in n for n in names))
        self.assertTrue(any("Configuration Directory" in n for n in names))

    def test_print_doctor_report(self):
        checks = doctor.run_doctor_checks(core)
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            doctor.print_doctor_report(checks)
            out = fake_out.getvalue()
            self.assertIn("Antigravity System Diagnostics", out)


if __name__ == "__main__":
    unittest.main()

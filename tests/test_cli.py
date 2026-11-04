"""
Unit tests for CLI commands and argument handling.
"""

import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from agm import cli, core


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="agm_cli_test_"))
        self.orig_config_dir = core.CONFIG_DIR
        self.orig_profiles_dir = core.PROFILES_DIR
        self.orig_config_file = core.CONFIG_FILE
        self.orig_active_file = core.ACTIVE_PROFILE_FILE
        self.orig_default_token = core.DEFAULT_TOKEN_FILE

        core.CONFIG_DIR = self.test_dir / ".config" / "agy-accounts"
        core.PROFILES_DIR = core.CONFIG_DIR / "profiles"
        core.CONFIG_FILE = core.CONFIG_DIR / "config.json"
        core.ACTIVE_PROFILE_FILE = core.CONFIG_DIR / "active"
        core.DEFAULT_TOKEN_FILE = self.test_dir / "nonexistent_token"
        core.ensure_base_dirs()

    def tearDown(self):
        core.CONFIG_DIR = self.orig_config_dir
        core.PROFILES_DIR = self.orig_profiles_dir
        core.CONFIG_FILE = self.orig_config_file
        core.ACTIVE_PROFILE_FILE = self.orig_active_file
        core.DEFAULT_TOKEN_FILE = self.orig_default_token
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cli_list_empty(self):
        with patch.object(core, "DEFAULT_TOKEN_FILE", self.test_dir / "nonexistent_token"):
            with patch("sys.stdout", new=io.StringIO()) as fake_out:
                cli.cmd_list(None)
                self.assertIn("No Antigravity accounts", fake_out.getvalue())

    def test_cli_add_no_login(self):
        args = cli.argparse.Namespace(name="personal", copy_from=None, no_login=True)
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            cli.cmd_add(args)
            self.assertIn("personal", fake_out.getvalue())

        cfg = core.load_config()
        self.assertIn("personal", cfg["profiles"])

    def test_cli_env(self):
        core.create_profile("tester")
        args = cli.argparse.Namespace(profile="tester")
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            cli.cmd_env(args)
            out = fake_out.getvalue()
            self.assertIn('export HOME="', out)
            self.assertIn('export AGM_PROFILE="tester"', out)

    def test_cli_whoami_short(self):
        core.create_profile("tester")
        core.switch_profile("tester")
        args = cli.argparse.Namespace(short=True)
        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            cli.cmd_whoami(args)
            self.assertEqual(fake_out.getvalue().strip(), "tester")


if __name__ == "__main__":
    unittest.main()

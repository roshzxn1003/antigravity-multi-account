"""
Unit tests for core profile and shadow environment management.
"""

import base64
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from agm import core
from agm.models import TokenStatus


class TestCore(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="agm_test_"))
        # Patch paths to point inside temp directory
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

    def test_jwt_payload_decode(self):
        payload = {"email": "tester@example.com", "sub": "123456789"}
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        token_str = f"header.{payload_b64}.signature"

        decoded = core.decode_jwt_payload(token_str)
        self.assertEqual(decoded.get("email"), "tester@example.com")
        self.assertEqual(decoded.get("sub"), "123456789")

    def test_shadow_home_setup(self):
        profile_dir = self.test_dir / "profile_alpha"
        core.setup_shadow_home(profile_dir)

        self.assertTrue(profile_dir.exists())
        self.assertTrue((profile_dir / ".gemini" / "antigravity-cli").is_dir())
        self.assertTrue((profile_dir / ".config").is_dir())

    def test_profile_lifecycle(self):
        # Create profile
        p_dir = core.create_profile("work")
        self.assertTrue(p_dir.exists())

        cfg = core.load_config()
        self.assertIn("work", cfg["profiles"])

        # Write mock token
        token_file = p_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        mock_payload = {"email": "work@company.com", "sub": "999"}
        mock_b64 = base64.urlsafe_b64encode(json.dumps(mock_payload).encode()).decode().rstrip("=")
        mock_jwt = f"hdr.{mock_b64}.sig"
        mock_data = {
            "token": {"access_token": "mock_tok", "refresh_token": "mock_ref", "expiry": "2099-01-01T00:00:00Z"},
            "id_token": mock_jwt,
        }
        with open(token_file, "w") as f:
            json.dump(mock_data, f)

        # Inspect token
        meta = core.inspect_token_file(token_file)
        self.assertEqual(meta.email, "work@company.com")
        self.assertEqual(meta.status, TokenStatus.ACTIVE_AUTO_REFRESH)
        self.assertTrue(meta.has_refresh)

        # Update info and list
        core.update_profile_info("work")
        profiles = core.list_profiles()
        work_entry = next((p for p in profiles if p["name"] == "work"), None)
        self.assertIsNotNone(work_entry)
        self.assertEqual(work_entry["email"], "work@company.com")

        # Delete profile
        deleted = core.delete_profile("work")
        self.assertTrue(deleted)
        self.assertNotIn("work", core.load_config()["profiles"])

    def test_inspect_token_with_id_token_email(self):
        p_dir = core.create_profile("beta")
        token_file = p_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        mock_data = {
            "token": {"access_token": "mock_tok", "refresh_token": "mock_ref", "expiry": "2099-01-01T00:00:00Z"},
            "auth_method": "consumer",
            "id_token_email": "direct_email@example.com",
        }
        with open(token_file, "w") as f:
            json.dump(mock_data, f)

        meta = core.inspect_token_file(token_file)
        self.assertEqual(meta.email, "direct_email@example.com")
        self.assertEqual(meta.status, TokenStatus.ACTIVE_AUTO_REFRESH)

    def test_keyring_isolation_in_env(self):
        env = core.get_profile_env("test_isolated")
        self.assertEqual(env.get("DBUS_SESSION_BUS_ADDRESS"), "unix:path=/dev/null")
        self.assertEqual(env.get("AGM_PROFILE"), "test_isolated")

    def test_config_antigravity_is_directory_not_symlink(self):
        p_dir = core.create_profile("gamma")
        antigravity_cfg = p_dir / ".config" / "antigravity"
        self.assertTrue(antigravity_cfg.is_dir())
        self.assertFalse(antigravity_cfg.is_symlink())

    def test_active_file_persistence(self):
        core.create_profile("work")
        self.assertTrue(core.switch_profile("work"))
        active = core.ACTIVE_PROFILE_FILE.read_text().strip()
        self.assertEqual(active, "work")


if __name__ == "__main__":
    unittest.main()

"""
Core profile and account management logic for Antigravity Multi-Account Manager (agm).
"""

import base64
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

from agm.models import AccountProfile, TokenMetadata, TokenStatus

REAL_HOME = Path(os.path.expanduser("~")).resolve()
CONFIG_DIR = REAL_HOME / ".config" / "agy-accounts"
PROFILES_DIR = CONFIG_DIR / "profiles"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_GEMINI_DIR = REAL_HOME / ".gemini"
DEFAULT_CLI_DIR = DEFAULT_GEMINI_DIR / "antigravity-cli"
DEFAULT_TOKEN_FILE = DEFAULT_CLI_DIR / "antigravity-oauth-token"
DEFAULT_SETTINGS_FILE = DEFAULT_CLI_DIR / "settings.json"


def decode_jwt_payload(token_str: str) -> Dict[str, Any]:
    """Decode the payload of a JWT without external libraries."""
    if not token_str:
        return {}
    parts = token_str.strip().split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    # Add padding if needed
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)
    try:
        payload_json = base64.urlsafe_b64decode(payload_b64).decode(
            "utf-8", errors="replace"
        )
        return json.loads(payload_json)
    except Exception:
        return {}


def inspect_token_file(token_file: Path) -> TokenMetadata:
    """Read an antigravity-oauth-token file and extract typed metadata."""
    if not token_file.exists():
        return TokenMetadata(
            email="None",
            status=TokenStatus.MISSING,
            expiry_str=None,
            expiry_dt=None,
            has_refresh=False,
        )

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        token_info = data.get("token", {})
        id_token_str = data.get("id_token", "")
        payload = decode_jwt_payload(id_token_str)

        email = (
            data.get("id_token_email")
            or payload.get("email")
            or data.get("email")
            or "Unknown"
        )
        expiry_str = token_info.get("expiry")
        has_refresh = bool(token_info.get("refresh_token"))

        is_expired = False
        expiry_dt = None
        if expiry_str:
            try:
                clean_exp = expiry_str.split(".")[0]
                if "+" in expiry_str:
                    clean_exp += "+" + expiry_str.split("+")[-1]
                elif "-" in expiry_str and len(expiry_str.split("-")) > 3:
                    clean_exp += "-" + expiry_str.split("-")[-1]
                expiry_dt = datetime.datetime.fromisoformat(clean_exp)
                now = datetime.datetime.now(expiry_dt.tzinfo) if expiry_dt.tzinfo else datetime.datetime.now()
                is_expired = now > expiry_dt
            except Exception:
                pass

        if has_refresh:
            status = TokenStatus.ACTIVE_AUTO_REFRESH
        elif is_expired:
            status = TokenStatus.EXPIRED
        else:
            status = TokenStatus.ACTIVE

        return TokenMetadata(
            email=email,
            status=status,
            expiry_str=expiry_str,
            expiry_dt=expiry_dt,
            has_refresh=has_refresh,
            auth_method=data.get("auth_method", "consumer"),
            sub=payload.get("sub"),
            raw_data=data,
        )
    except Exception:
        return TokenMetadata(
            email="Error",
            status=TokenStatus.ERROR,
            expiry_str=None,
            expiry_dt=None,
            has_refresh=False,
        )


def ensure_base_dirs():
    """Ensure configuration and profile directories exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        initial_cfg = {
            "active_profile": "default",
            "profiles": {},
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_cfg, f, indent=2)


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json."""
    ensure_base_dirs()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active_profile": "default", "profiles": {}}


def save_config(cfg: Dict[str, Any]):
    """Save configuration to config.json."""
    ensure_base_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def get_profile_dir(profile_name: str) -> Path:
    """Return the filesystem path for a profile's shadow home."""
    return PROFILES_DIR / profile_name


def setup_shadow_home(profile_dir: Path):
    """
    Set up a shadow home directory with symlinks to user config/tools
    while isolating the .gemini/antigravity-cli runtime directory.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)

    # 1. Private Antigravity CLI and state directories for this profile
    gemini_cli_dir = profile_dir / ".gemini" / "antigravity-cli"
    gemini_cli_dir.mkdir(parents=True, exist_ok=True)
    gemini_app_dir = profile_dir / ".gemini" / "antigravity"
    gemini_app_dir.mkdir(parents=True, exist_ok=True)

    # 2. Shared Antigravity config (rules, mcp_config, projects)
    profile_gemini_config = profile_dir / ".gemini" / "config"
    real_gemini_config = REAL_HOME / ".gemini" / "config"
    if real_gemini_config.exists() and not profile_gemini_config.exists():
        try:
            profile_gemini_config.symlink_to(real_gemini_config, target_is_directory=True)
        except OSError:
            pass

    # 3. Symlink essential user dotfiles for Git, SSH, shells, toolchains
    dotfiles_to_link = [
        ".gitconfig",
        ".ssh",
        ".bashrc",
        ".profile",
        ".cargo",
        ".rustup",
        ".local",
    ]

    for item in dotfiles_to_link:
        source = REAL_HOME / item
        dest = profile_dir / item
        if source.exists() and not dest.exists():
            try:
                dest.symlink_to(source, target_is_directory=source.is_dir())
            except OSError:
                pass

    # 4. Mirror ~/.config subdirectories (e.g. gh, git, code) except agy-accounts
    real_user_config = REAL_HOME / ".config"
    profile_user_config = profile_dir / ".config"
    profile_user_config.mkdir(parents=True, exist_ok=True)

    if real_user_config.exists():
        for child in real_user_config.iterdir():
            if child.name == "agy-accounts":
                continue
            dest_child = profile_user_config / child.name
            if not dest_child.exists():
                try:
                    dest_child.symlink_to(child, target_is_directory=child.is_dir())
                except OSError:
                    pass

    # 5. Copy base settings.json if profile doesn't have one yet
    profile_settings = gemini_cli_dir / "settings.json"
    if not profile_settings.exists() and DEFAULT_SETTINGS_FILE.exists():
        try:
            shutil.copy2(DEFAULT_SETTINGS_FILE, profile_settings)
        except OSError:
            pass


def import_existing_account_if_needed() -> Optional[str]:
    """
    If this is the first run and the user already has an authenticated account
    in ~/.gemini/antigravity-cli, import it into the 'default' profile.
    Also synchronizes token metadata if 'default' email is Unknown.
    """
    ensure_base_dirs()
    cfg = load_config()

    default_dir = get_profile_dir("default")
    profile_token = default_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"

    if "default" not in cfg.get("profiles", {}):
        if DEFAULT_TOKEN_FILE.exists():
            setup_shadow_home(default_dir)
            if not profile_token.exists():
                shutil.copy2(DEFAULT_TOKEN_FILE, profile_token)
                try:
                    os.chmod(profile_token, 0o600)
                except OSError:
                    pass

            meta = inspect_token_file(profile_token)
            cfg.setdefault("profiles", {})["default"] = {
                "name": "default",
                "email": meta.email,
                "created_at": datetime.datetime.now().isoformat(),
                "last_used": datetime.datetime.now().isoformat(),
                "path": str(default_dir),
            }
            cfg["active_profile"] = "default"
            save_config(cfg)
            return "default"
    else:
        # If default profile token is missing or has Unknown email, refresh from source
        if DEFAULT_TOKEN_FILE.exists() and not profile_token.exists():
            setup_shadow_home(default_dir)
            shutil.copy2(DEFAULT_TOKEN_FILE, profile_token)
            try:
                os.chmod(profile_token, 0o600)
            except OSError:
                pass

        meta = inspect_token_file(profile_token)
        if meta.email not in ("Unknown", "None", "Error"):
            current_saved = cfg.get("profiles", {}).get("default", {}).get("email")
            if current_saved != meta.email:
                cfg.setdefault("profiles", {}).setdefault("default", {})["email"] = meta.email
                save_config(cfg)

    return None


def get_default_authenticated_profile() -> str:
    """Find a configured profile that has valid credentials, defaulting to 'default'."""
    cfg = load_config()
    active = cfg.get("active_profile", "default")

    # 1. Check active profile
    active_tok = get_profile_dir(active) / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    if active_tok.exists() and inspect_token_file(active_tok).status != TokenStatus.MISSING:
        return active

    # 2. Check "default" profile
    default_tok = get_profile_dir("default") / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    if default_tok.exists() and inspect_token_file(default_tok).status != TokenStatus.MISSING:
        return "default"

    # 3. Check any configured profile with active credentials
    for name in cfg.get("profiles", {}).keys():
        tok = get_profile_dir(name) / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        if tok.exists() and inspect_token_file(tok).status != TokenStatus.MISSING:
            return name

    # 4. Check real base token file
    if DEFAULT_TOKEN_FILE.exists():
        import_existing_account_if_needed()
        return "default"

    return "default"


def get_effective_profile(requested_name: Optional[str] = None):
    """
    Resolve the target profile to use for execution.
    If the requested profile is missing, doesn't exist, or has no login credentials,
    seamlessly fall back / redirect to the default authenticated profile without asking for login.

    Returns: (target_profile_name, was_redirected, redirect_reason)
    """
    import_existing_account_if_needed()
    cfg = load_config()
    default_prof = get_default_authenticated_profile()

    if not requested_name or requested_name in ("", "default"):
        return (default_prof, False, None)

    # Specific profile requested
    if requested_name not in cfg.get("profiles", {}):
        return (
            default_prof,
            True,
            f"Profile '{requested_name}' does not exist.",
        )

    prof_dir = get_profile_dir(requested_name)
    tok_file = prof_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    meta = inspect_token_file(tok_file)

    if not tok_file.exists() or meta.status == TokenStatus.MISSING:
        return (
            default_prof,
            True,
            f"Profile '{requested_name}' has no saved login credentials.",
        )

    return (requested_name, False, None)


def copy_profile_credentials(src_name: str, dst_name: str) -> bool:
    """Copy authentication credentials from one profile to another."""
    cfg = load_config()
    if src_name not in cfg.get("profiles", {}):
        return False

    src_dir = get_profile_dir(src_name)
    src_token = src_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    if not src_token.exists():
        return False

    dst_dir = get_profile_dir(dst_name)
    if not dst_dir.exists():
        create_profile(dst_name)

    dst_token = dst_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    shutil.copy2(src_token, dst_token)
    try:
        os.chmod(dst_token, 0o600)
    except OSError:
        pass

    update_profile_info(dst_name)
    return True


def create_profile(name: str, copy_from: Optional[str] = None) -> Path:
    """Create a new profile."""
    ensure_base_dirs()
    cfg = load_config()

    profile_dir = get_profile_dir(name)
    setup_shadow_home(profile_dir)

    target_token = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"

    if copy_from:
        src_profile_dir = get_profile_dir(copy_from)
        src_token = src_profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        if src_token.exists() and not target_token.exists():
            shutil.copy2(src_token, target_token)
            try:
                os.chmod(target_token, 0o600)
            except OSError:
                pass

    meta = inspect_token_file(target_token)

    cfg.setdefault("profiles", {})[name] = {
        "name": name,
        "email": meta.email,
        "created_at": datetime.datetime.now().isoformat(),
        "last_used": None,
        "path": str(profile_dir),
    }
    save_config(cfg)
    return profile_dir


def update_profile_info(name: str):
    """Re-inspect the profile token and update registry metadata."""
    cfg = load_config()
    if name not in cfg.get("profiles", {}):
        return
    profile_dir = get_profile_dir(name)
    token_file = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    meta = inspect_token_file(token_file)
    cfg["profiles"][name]["email"] = meta.email
    save_config(cfg)


def list_profiles() -> List[Dict[str, Any]]:
    """Return all profiles and their runtime metadata."""
    import_existing_account_if_needed()
    cfg = load_config()
    active = cfg.get("active_profile", "default")
    profiles_data = cfg.get("profiles", {})

    result = []
    for name, data in profiles_data.items():
        profile_dir = get_profile_dir(name)
        token_file = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        meta = inspect_token_file(token_file)

        item = {
            "name": name,
            "email": meta.email if meta.email != "Unknown" else data.get("email", "Unknown"),
            "status": meta.status.value,
            "expiry": meta.expiry_str,
            "is_active": (name == active),
            "created_at": data.get("created_at"),
            "last_used": data.get("last_used"),
            "path": str(profile_dir),
        }
        result.append(item)
    return result


def switch_profile(name: str) -> bool:
    """Set the system-wide default active profile."""
    cfg = load_config()
    if name not in cfg.get("profiles", {}):
        return False

    profile_dir = get_profile_dir(name)
    src_token = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    src_settings = profile_dir / ".gemini" / "antigravity-cli" / "settings.json"

    DEFAULT_CLI_DIR.mkdir(parents=True, exist_ok=True)
    if src_token.exists():
        shutil.copy2(src_token, DEFAULT_TOKEN_FILE)
        try:
            os.chmod(DEFAULT_TOKEN_FILE, 0o600)
        except OSError:
            pass

    if src_settings.exists():
        shutil.copy2(src_settings, DEFAULT_SETTINGS_FILE)

    cfg["active_profile"] = name
    cfg["profiles"][name]["last_used"] = datetime.datetime.now().isoformat()
    save_config(cfg)
    return True


def delete_profile(name: str) -> bool:
    """Delete a profile and its isolated directory."""
    cfg = load_config()
    if name not in cfg.get("profiles", {}):
        return False

    profile_dir = get_profile_dir(name)
    if profile_dir.exists():
        shutil.rmtree(profile_dir, ignore_errors=True)

    del cfg["profiles"][name]
    if cfg.get("active_profile") == name:
        remaining = list(cfg.get("profiles", {}).keys())
        cfg["active_profile"] = remaining[0] if remaining else "default"

    save_config(cfg)
    return True


def get_profile_env(name: str) -> Dict[str, str]:
    """Get environment variables for executing commands in this profile."""
    profile_dir = get_profile_dir(name)
    env = os.environ.copy()
    env["HOME"] = str(profile_dir)
    env["AGM_PROFILE"] = name
    return env


def run_profile_command(
    name: str,
    cmd_args: List[str],
    cwd: Optional[str] = None,
    stream_output: bool = True,
) -> int:
    """Run an arbitrary command under the profile's environment."""
    profile_dir = get_profile_dir(name)
    if not profile_dir.exists():
        setup_shadow_home(profile_dir)

    env = get_profile_env(name)

    cfg = load_config()
    if name in cfg.get("profiles", {}):
        cfg["profiles"][name]["last_used"] = datetime.datetime.now().isoformat()
        save_config(cfg)

    exec_cwd = cwd or os.getcwd()

    if stream_output:
        proc = subprocess.run(cmd_args, env=env, cwd=exec_cwd)
        update_profile_info(name)
        return proc.returncode
    else:
        proc = subprocess.run(
            cmd_args, env=env, cwd=exec_cwd, capture_output=True, text=True
        )
        update_profile_info(name)
        return proc.returncode

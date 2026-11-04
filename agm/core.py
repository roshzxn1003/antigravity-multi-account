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
ACTIVE_PROFILE_FILE = CONFIG_DIR / "active"

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
        payload = decode_jwt_payload(id_token_str) if id_token_str else {}
        if not payload and "access_token" in token_info:
            payload = decode_jwt_payload(token_info.get("access_token", ""))

        email = data.get("id_token_email") or data.get("email") or payload.get("email") or "Unknown"
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
    """Ensure configuration and profile directories exist and profiles are repaired."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        initial_cfg = {
            "active_profile": "default",
            "profiles": {},
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(initial_cfg, f, indent=2)
    if not ACTIVE_PROFILE_FILE.exists():
        try:
            cfg = load_config()
            active = cfg.get("active_profile", "default")
            ACTIVE_PROFILE_FILE.write_text(f"{active}\n", encoding="utf-8")
        except Exception:
            pass

    for p in PROFILES_DIR.iterdir():
        if p.is_dir():
            repair_profile_isolation(p)


def load_config() -> Dict[str, Any]:
    """Load configuration from config.json."""
    ensure_base_dirs()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"active_profile": "default", "profiles": {}}


def save_config(cfg: Dict[str, Any]):
    """Save configuration to config.json and active state file."""
    ensure_base_dirs()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    active = cfg.get("active_profile", "default")
    try:
        ACTIVE_PROFILE_FILE.write_text(f"{active}\n", encoding="utf-8")
    except Exception:
        pass


def get_profile_dir(profile_name: str) -> Path:
    """Return the filesystem path for a profile's shadow home."""
    return PROFILES_DIR / profile_name


def repair_profile_isolation(profile_dir: Path):
    """Ensure sensitive Antigravity config in .config is an isolated directory and not symlinked."""
    antigravity_cfg = profile_dir / ".config" / "antigravity"
    if antigravity_cfg.is_symlink():
        try:
            antigravity_cfg.unlink()
        except OSError:
            pass
    antigravity_cfg.mkdir(parents=True, exist_ok=True)


def setup_shadow_home(profile_dir: Path):
    """
    Set up a shadow home directory with symlinks to user config/tools
    while isolating the .gemini/antigravity-cli runtime directory.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)

    # 1. Private Antigravity CLI directory for this profile
    gemini_cli_dir = profile_dir / ".gemini" / "antigravity-cli"
    gemini_cli_dir.mkdir(parents=True, exist_ok=True)

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

    # 4. Mirror ~/.config subdirectories (e.g. gh, git, code) except agy-accounts & antigravity
    real_user_config = REAL_HOME / ".config"
    profile_user_config = profile_dir / ".config"
    profile_user_config.mkdir(parents=True, exist_ok=True)

    if real_user_config.exists():
        for child in real_user_config.iterdir():
            if child.name in ("agy-accounts", "antigravity"):
                continue
            dest_child = profile_user_config / child.name
            if not dest_child.exists():
                try:
                    dest_child.symlink_to(child, target_is_directory=child.is_dir())
                except OSError:
                    pass

    # Ensure antigravity in profile .config is an isolated directory
    repair_profile_isolation(profile_dir)

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
    """
    ensure_base_dirs()
    cfg = load_config()

    if "default" not in cfg.get("profiles", {}):
        if DEFAULT_TOKEN_FILE.exists():
            default_dir = get_profile_dir("default")
            setup_shadow_home(default_dir)
            profile_token = default_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
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
            if not cfg.get("active_profile"):
                cfg["active_profile"] = "default"
            save_config(cfg)
            return "default"
    return None


def create_profile(name: str, copy_from: Optional[str] = None) -> Path:
    """Create a new profile."""
    ensure_base_dirs()
    cfg = load_config()

    profile_dir = get_profile_dir(name)
    setup_shadow_home(profile_dir)

    target_token = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    target_settings = profile_dir / ".gemini" / "antigravity-cli" / "settings.json"

    if copy_from:
        src_profile_dir = get_profile_dir(copy_from)
        src_token = src_profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        if not src_token.exists() and copy_from == "default":
            src_token = DEFAULT_TOKEN_FILE

        if src_token.exists():
            shutil.copy2(src_token, target_token)
            try:
                os.chmod(target_token, 0o600)
            except OSError:
                pass

        src_settings = src_profile_dir / ".gemini" / "antigravity-cli" / "settings.json"
        if not src_settings.exists() and copy_from == "default":
            src_settings = DEFAULT_SETTINGS_FILE

        if src_settings.exists():
            try:
                shutil.copy2(src_settings, target_settings)
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

    # Invalidate GNOME Keyring token so it does not override the switched profile
    try:
        subprocess.run(
            ["secret-tool", "clear", "service", "gemini", "username", "antigravity"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        pass

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
    repair_profile_isolation(profile_dir)
    env = os.environ.copy()
    env["HOME"] = str(profile_dir)
    env["AGM_PROFILE"] = name

    # Preserve real DBUS address for the browser launcher if needed
    if "DBUS_SESSION_BUS_ADDRESS" in env:
        env["AGM_ORIG_DBUS_SESSION_BUS_ADDRESS"] = env["DBUS_SESSION_BUS_ADDRESS"]

    # Isolate from global desktop GNOME Keyring / Secret Service so that
    # keyringAuth does not load or overwrite the default Google account token.
    env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/dev/null"
    return env


def setup_oauth_interceptor() -> Path:
    """
    Create an xdg-open wrapper that forces Google OAuth account selection
    and opens in Incognito mode so Google does not auto-login to an existing account.
    """
    bin_dir = CONFIG_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    xdg_open_script = bin_dir / "xdg-open"

    content = """#!/usr/bin/env bash
# Antigravity Multi-Account OAuth Interceptor
URL="$1"

# Restore desktop D-Bus address for browser launch if preserved
if [ -n "$AGM_ORIG_DBUS_SESSION_BUS_ADDRESS" ]; then
    export DBUS_SESSION_BUS_ADDRESS="$AGM_ORIG_DBUS_SESSION_BUS_ADDRESS"
fi

if [[ "$URL" == *"accounts.google.com"* ]]; then
    # 1. Force account selection parameter so Google always shows the account chooser
    if [[ "$URL" != *"prompt="* ]]; then
        if [[ "$URL" == *"?"* ]]; then
            URL="${URL}&prompt=select_account"
        else
            URL="${URL}?prompt=select_account"
        fi
    fi

    # 2. Print clear instructions in terminal
    echo "" >&2
    echo "================================================================================" >&2
    echo "  ANTIGRAVITY GOOGLE OAUTH SIGN-IN" >&2
    echo "================================================================================" >&2
    echo "  Opening Incognito / Account Selection window..." >&2
    echo "" >&2
    echo "  Direct OAuth URL:" >&2
    echo "  $URL" >&2
    echo "" >&2
    echo "  IMPORTANT:" >&2
    echo "  Sign in with your OTHER / SECOND Google account (not your default account)!" >&2
    echo "  If the browser didn't open or opened the wrong account, copy and paste" >&2
    echo "  the link above into an Incognito/Private window or another browser." >&2
    echo "================================================================================" >&2
    echo "" >&2

    # 3. Open in Incognito/Private mode
    if command -v google-chrome &>/dev/null; then
        google-chrome --incognito "$URL" >/dev/null 2>&1 &
        exit 0
    elif command -v google-chrome-stable &>/dev/null; then
        google-chrome-stable --incognito "$URL" >/dev/null 2>&1 &
        exit 0
    elif command -v brave-browser &>/dev/null; then
        brave-browser --incognito "$URL" >/dev/null 2>&1 &
        exit 0
    elif command -v firefox &>/dev/null; then
        firefox --private-window "$URL" >/dev/null 2>&1 &
        exit 0
    fi
fi

# Fallback to system xdg-open
if [ -x /usr/bin/xdg-open ]; then
    exec /usr/bin/xdg-open "$@"
elif [ -x /bin/xdg-open ]; then
    exec /bin/xdg-open "$@"
else
    echo "Open URL in your browser: $URL" >&2
fi
"""
    with open(xdg_open_script, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chmod(xdg_open_script, 0o755)
    except OSError:
        pass
    return bin_dir


def run_profile_command(
    name: str,
    cmd_args: List[str],
    cwd: Optional[str] = None,
    stream_output: bool = True,
    use_interceptor: bool = False,
) -> int:
    """Run an arbitrary command under the profile's environment."""
    profile_dir = get_profile_dir(name)
    if not profile_dir.exists():
        setup_shadow_home(profile_dir)

    env = get_profile_env(name)

    if use_interceptor:
        interceptor_bin = setup_oauth_interceptor()
        env["PATH"] = f"{interceptor_bin}:{env.get('PATH', '')}"

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


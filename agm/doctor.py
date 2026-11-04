"""
System diagnostics and environment health checker for Antigravity Multi-Account Manager.
"""

from pathlib import Path
import os
import shutil
import sys
from typing import List

from agm.models import HealthCheckItem
from agm.ui import BOLD, GREEN, RED, RESET, YELLOW, DIM, colorize, render_table


def run_doctor_checks(core_module) -> List[HealthCheckItem]:
    """Execute all system health checks."""
    checks: List[HealthCheckItem] = []

    # 1. Check Antigravity CLI binary
    agy_path = shutil.which("agy")
    if agy_path:
        is_exec = os.access(agy_path, os.X_OK)
        checks.append(
            HealthCheckItem(
                name="Antigravity CLI Binary (`agy`)",
                passed=is_exec,
                status="OK" if is_exec else "Permission Issue",
                details=f"Found at {agy_path} (Executable: {is_exec})",
            )
        )
    else:
        checks.append(
            HealthCheckItem(
                name="Antigravity CLI Binary (`agy`)",
                passed=False,
                status="Missing",
                details="`agy` executable not found in PATH",
            )
        )

    # 2. Base Configuration Directory
    config_dir = core_module.CONFIG_DIR
    can_write_config = os.access(config_dir.parent, os.W_OK) if not config_dir.exists() else os.access(config_dir, os.W_OK)
    checks.append(
        HealthCheckItem(
            name="Configuration Directory",
            passed=can_write_config,
            status="OK" if can_write_config else "Permission Denied",
            details=f"Writable at {config_dir}",
        )
    )

    # 3. Base Antigravity Runtime Directory
    cli_dir = core_module.DEFAULT_CLI_DIR
    checks.append(
        HealthCheckItem(
            name="Antigravity State Directory",
            passed=cli_dir.exists(),
            status="Found" if cli_dir.exists() else "Not Found",
            details=f"{cli_dir}",
        )
    )

    # 4. User System Dotfiles
    real_home = core_module.REAL_HOME
    gitconfig = real_home / ".gitconfig"
    checks.append(
        HealthCheckItem(
            name="User Git Configuration",
            passed=gitconfig.exists(),
            status="Found" if gitconfig.exists() else "Missing",
            details=f"{gitconfig} (Mirrored into shadow homes)",
        )
    )

    # 5. Shell Integration in .bashrc
    bashrc = real_home / ".bashrc"
    has_integration = False
    if bashrc.exists():
        try:
            with open(bashrc, "r", encoding="utf-8") as f:
                content = f.read()
                has_integration = "agy()" in content and "agm run" in content
        except Exception:
            pass

    checks.append(
        HealthCheckItem(
            name="Shell Integration (`agy @profile`)",
            passed=has_integration,
            status="Enabled" if has_integration else "Not Configured",
            details="Bash function configured in ~/.bashrc" if has_integration else "Add `agy()` function to ~/.bashrc",
        )
    )

    # 6. Active Profile State File
    active_file = core_module.ACTIVE_PROFILE_FILE
    has_active_file = active_file.exists()
    checks.append(
        HealthCheckItem(
            name="Persistent Active Profile State",
            passed=has_active_file,
            status="Synced" if has_active_file else "Missing",
            details=f"Tracks reboot-safe active profile at {active_file}",
        )
    )

    # 7. Keyring & Config Isolation Health
    test_env = core_module.get_profile_env("default")
    is_keyring_isolated = test_env.get("DBUS_SESSION_BUS_ADDRESS") == "unix:path=/dev/null"
    checks.append(
        HealthCheckItem(
            name="GNOME Keyring Isolation",
            passed=is_keyring_isolated,
            status="Isolated" if is_keyring_isolated else "Vulnerable",
            details="Desktop keyring blocked from leaking default token across profiles",
        )
    )

    # 8. Profile Tokens Health
    profiles = core_module.list_profiles()
    valid_count = 0
    total_profiles = len(profiles)
    for p in profiles:
        if "Active" in p["status"]:
            valid_count += 1

    checks.append(
        HealthCheckItem(
            name="Account Profiles & Credentials",
            passed=(total_profiles > 0 and valid_count > 0),
            status=f"{valid_count}/{total_profiles} Ready",
            details=f"{valid_count} active accounts ready for simultaneous execution",
        )
    )

    return checks


def print_doctor_report(checks: List[HealthCheckItem]):
    """Print formatted doctor diagnostic report."""
    print(f"\n{BOLD}Antigravity System Diagnostics (agm doctor):{RESET}\n")

    headers = ["CHECK", "STATUS", "DETAILS"]
    rows = []
    all_passed = True

    for c in checks:
        if c.passed:
            status_str = colorize(f"✔ {c.status}", GREEN + BOLD)
        else:
            all_passed = False
            status_str = colorize(f"✖ {c.status}", RED + BOLD)
        rows.append([c.name, status_str, c.details])

    render_table(headers, rows, alignments=["L", "L", "L"])

    print()
    if all_passed:
        print(colorize("✔ All systems healthy! Antigravity multi-account environment is ready.", GREEN + BOLD))
    else:
        print(colorize("⚠ Some checks had warnings. Please review the table above.", YELLOW + BOLD))
    print()

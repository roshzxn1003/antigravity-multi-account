"""
Command Line Interface for Antigravity Multi-Account Manager (agm).
"""

import argparse
import os
import sys
from typing import List

from agm import core
from agm.doctor import print_doctor_report, run_doctor_checks
from agm.models import TokenStatus
from agm.ui import (
    BOLD,
    CYAN,
    DIM,
    GREEN,
    RED,
    RESET,
    YELLOW,
    badge,
    colorize,
    print_banner,
    print_step,
    render_table,
)


def cmd_list(args: argparse.Namespace):
    """List all configured Google accounts and profiles."""
    profiles = core.list_profiles()

    if not profiles:
        print(colorize("No Antigravity accounts configured yet.", YELLOW))
        print("Run `agm add <profile_name>` to add your first account.")
        return

    print_banner()
    print(f"{BOLD}Configured Google Accounts & Profiles:{RESET}\n")

    headers = ["ACTIVE", "PROFILE", "GOOGLE ACCOUNT", "STATUS", "LAST USED"]
    rows = []

    for p in profiles:
        active_mark = colorize("● active", GREEN + BOLD) if p["is_active"] else ""
        name_str = colorize(p["name"], CYAN + BOLD) if p["is_active"] else p["name"]
        email_str = p["email"]
        status_badge = badge(p["status"])

        last_used = p["last_used"]
        if last_used:
            try:
                last_used = last_used.split("T")[0]
            except Exception:
                pass
        else:
            last_used = "Never"

        rows.append([active_mark, name_str, email_str, status_badge, last_used])

    render_table(headers, rows, alignments=["C", "L", "L", "L", "L"])

    print()
    current_env = os.environ.get("AGM_PROFILE")
    if current_env:
        print(colorize(f"Current terminal session pinned to: {current_env}", YELLOW + BOLD))
    print(colorize("Simultaneous execution:  agm run <profile> [agy args...] (or agy @<profile>)", DIM))
    print(colorize("Global default switch:   agm switch <profile>", DIM))
    print(colorize("System health check:     agm doctor\n", DIM))


def cmd_add(args: argparse.Namespace):
    """Add a new profile with an interactive, friendly guide."""
    core.import_existing_account_if_needed()
    name = args.name
    cfg = core.load_config()

    if name in cfg.get("profiles", {}):
        print(colorize(f"Profile '{name}' already exists.", YELLOW + BOLD))
        print(f"To launch this profile, run: `agm run {name}` (or `agy @{name}`)")
        return

    print_banner()
    print(f"{BOLD}Adding New Google Account Profile: {colorize(name, CYAN + BOLD)}{RESET}")

    print_step(1, 3, "Provisioning Isolated Environment")
    profile_dir = core.create_profile(name, copy_from=args.copy_from)
    print(f"  ✔ Shadow filesystem initialized at: {colorize(profile_dir, DIM)}")
    print("  ✔ Linked developer tools: ~/.gitconfig, ~/.ssh, ~/.cargo, ~/.config/gh")

    token_file = profile_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"

    if args.copy_from:
        core.update_profile_info(name)
        meta = core.inspect_token_file(token_file)
        print(colorize(f"\n✔ Copied credentials from '{args.copy_from}' ({meta.email})", GREEN + BOLD))
        return

    if args.no_login:
        print_step(2, 3, "Skipping Login (--no-login)")
        print(colorize(f"Profile '{name}' created in waiting state.", YELLOW))
        print(f"When ready to sign in, run: `agm run {name}`")
        return

    print_step(2, 3, "Google OAuth Authentication")
    print("  Next, Antigravity will launch its Google OAuth consent flow.")
    print("  1. A browser window will open automatically.")
    print(f"  2. Sign in with your {BOLD}secondary Google account{RESET}.")
    print("  3. Grant the requested permissions for Antigravity.")
    print(f"\nPress {colorize('Enter', BOLD)} to open the browser...")

    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return

    # Run agy in profile's environment to trigger OAuth onboarding
    core.run_profile_command(name, ["agy"], stream_output=True)

    print_step(3, 3, "Verifying Credentials")
    core.update_profile_info(name)
    meta = core.inspect_token_file(token_file)

    if meta.status != TokenStatus.MISSING and meta.email != "None":
        print(colorize(f"\n✔ Successfully authenticated as: {meta.email}", GREEN + BOLD))
        print(f"✔ Ready for simultaneous use! Launch anytime via: {colorize('agy @' + name, CYAN + BOLD)}")
    else:
        print(colorize(f"\nAuthentication incomplete. Run `agm run {name}` to complete login.", YELLOW + BOLD))


def cmd_run(args: argparse.Namespace, extra_args: List[str]):
    """Run agy within the specified profile's environment."""
    core.import_existing_account_if_needed()

    requested_profile = args.profile
    # If the user ran `agm run -p "prompt"`: args.profile might start with '-'
    if requested_profile and requested_profile.startswith("-"):
        extra_args.insert(0, requested_profile)
        requested_profile = None

    # Strip redundant 'agy' if provided (e.g. `agm run default agy -p "hello"`)
    if extra_args and extra_args[0] == "agy":
        extra_args = extra_args[1:]

    target_profile, redirected, reason = core.get_effective_profile(requested_profile)

    if redirected:
        target_dir = core.get_profile_dir(target_profile)
        target_meta = core.inspect_token_file(
            target_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
        )
        email_str = f" ({target_meta.email})" if target_meta.email not in ("None", "Unknown") else ""
        print(
            colorize(
                f"ℹ {reason} Redirecting to default account '{target_profile}'{email_str} without asking for login.",
                YELLOW + BOLD,
            ),
            file=sys.stderr,
        )

    cmd = ["agy"] + extra_args
    sys.exit(core.run_profile_command(target_profile, cmd, stream_output=True))


def cmd_copy(args: argparse.Namespace):
    """Copy authentication credentials from one profile to another."""
    core.import_existing_account_if_needed()
    src = args.src
    dst = args.dst
    if core.copy_profile_credentials(src, dst):
        cfg = core.load_config()
        email = cfg.get("profiles", {}).get(dst, {}).get("email", "Unknown")
        print(colorize(f"✔ Copied credentials from '{src}' to '{dst}' ({email})", GREEN + BOLD))
    else:
        print(colorize(f"Error: Could not copy credentials from '{src}' to '{dst}'.", RED + BOLD))
        sys.exit(1)


def cmd_switch(args: argparse.Namespace):
    """Switch the system-wide active account."""
    core.import_existing_account_if_needed()
    name = args.profile
    if core.switch_profile(name):
        cfg = core.load_config()
        email = cfg.get("profiles", {}).get(name, {}).get("email", "Unknown")
        print(colorize(f"✔ Switched global active Antigravity account to '{name}' ({email})", GREEN + BOLD))
        print("Default `agy` commands will now use this account.")
    else:
        print(colorize(f"Error: Profile '{name}' not found.", RED + BOLD))
        sys.exit(1)


def cmd_whoami(args: argparse.Namespace):
    """Display active account details."""
    core.import_existing_account_if_needed()
    cfg = core.load_config()
    active_name = cfg.get("active_profile", "default")
    env_name = os.environ.get("AGM_PROFILE")

    print_banner()
    print(f"{BOLD}Active Antigravity Account Identity:{RESET}\n")

    if env_name:
        env_dir = core.get_profile_dir(env_name)
        meta = core.inspect_token_file(env_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token")
        print(f"  {BOLD}Current Terminal Profile:{RESET} {colorize(env_name, CYAN + BOLD)} ({meta.email}) [via $AGM_PROFILE]")

    active_dir = core.get_profile_dir(active_name)
    meta_global = core.inspect_token_file(active_dir / ".gemini" / "antigravity-cli" / "antigravity-oauth-token")
    print(f"  {BOLD}Global Default Profile:{RESET}   {colorize(active_name, GREEN + BOLD)} ({meta_global.email})")
    print(f"  {BOLD}Token Status:{RESET}             {badge(meta_global.status.value)}")
    print()


def cmd_remove(args: argparse.Namespace):
    """Remove a profile and its isolated data."""
    core.import_existing_account_if_needed()
    name = args.profile
    cfg = core.load_config()

    if name not in cfg.get("profiles", {}):
        print(colorize(f"Error: Profile '{name}' does not exist.", RED + BOLD))
        sys.exit(1)

    if not args.yes:
        confirm = input(f"Are you sure you want to delete profile '{name}' and its sessions? [y/N]: ")
        if confirm.lower() not in ("y", "yes"):
            print("Cancelled.")
            return

    core.delete_profile(name)
    print(colorize(f"✔ Removed profile '{name}'.", GREEN))


def cmd_env(args: argparse.Namespace):
    """Output shell environment variables for this profile."""
    core.import_existing_account_if_needed()
    name = args.profile
    cfg = core.load_config()
    if name not in cfg.get("profiles", {}):
        print(f"echo 'Profile {name} not found' >&2; return 1 2>/dev/null || exit 1")
        return

    profile_dir = core.get_profile_dir(name)
    print(f'export HOME="{profile_dir}"')
    print(f'export AGM_PROFILE="{name}"')
    print(f"# Active Antigravity profile set to: {name}")


def cmd_doctor(args: argparse.Namespace):
    """Run diagnostic checks on the Antigravity multi-account environment."""
    core.import_existing_account_if_needed()
    print_banner()
    checks = run_doctor_checks(core)
    print_doctor_report(checks)


def cmd_pool(args: argparse.Namespace, extra_args: List[str]):
    """Execute a prompt with automatic failover across configured accounts."""
    core.import_existing_account_if_needed()
    cfg = core.load_config()
    profiles = list(cfg.get("profiles", {}).keys())

    if not profiles:
        print(colorize("No profiles available for pooling.", RED + BOLD))
        sys.exit(1)

    active = cfg.get("active_profile", "default")
    if active in profiles:
        profiles.remove(active)
        profiles.insert(0, active)

    cmd = ["agy"] + extra_args
    success = False

    for profile_name in profiles:
        meta = core.inspect_token_file(core.get_profile_dir(profile_name) / ".gemini" / "antigravity-cli" / "antigravity-oauth-token")
        if meta.status == TokenStatus.MISSING:
            continue

        print(colorize(f"Attempting execution using account '{profile_name}' ({meta.email})...", CYAN))
        ret = core.run_profile_command(profile_name, cmd, stream_output=True)
        if ret == 0:
            success = True
            break
        else:
            print(colorize(f"Execution failed or rate-limited on '{profile_name}'. Failing over to next account...", YELLOW))

    if not success:
        print(colorize("All configured accounts failed or exhausted quotas.", RED + BOLD))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="agm",
        description="Antigravity Multi-Account Manager - Run multiple Google accounts simultaneously.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # list
    sub_list = subparsers.add_parser("list", aliases=["ls"], help="List all accounts, emails, and statuses")
    sub_list.set_defaults(func=cmd_list)

    # add
    sub_add = subparsers.add_parser("add", help="Add a new Google account profile")
    sub_add.add_argument("name", help="Unique name/alias for this profile (e.g., work, personal, bot)")
    sub_add.add_argument("--copy-from", help="Copy credentials from an existing profile")
    sub_add.add_argument("--no-login", action="store_true", help="Create profile environment without launching OAuth")
    sub_add.set_defaults(func=cmd_add)

    # run
    sub_run = subparsers.add_parser("run", help="Run agy under a specific account profile (or default)")
    sub_run.add_argument("profile", nargs="?", default=None, help="Profile to run under (defaults to active/default account)")
    sub_run.set_defaults(func=cmd_run)

    # copy
    sub_cp = subparsers.add_parser("copy", aliases=["cp"], help="Copy credentials from one profile to another")
    sub_cp.add_argument("src", help="Source profile")
    sub_cp.add_argument("dst", help="Destination profile")
    sub_cp.set_defaults(func=cmd_copy)

    # switch
    sub_switch = subparsers.add_parser("switch", aliases=["use"], help="Set the default active account")
    sub_switch.add_argument("profile", help="Profile to set as default")
    sub_switch.set_defaults(func=cmd_switch)

    # whoami
    sub_whoami = subparsers.add_parser("whoami", help="Display current active account")
    sub_whoami.set_defaults(func=cmd_whoami)

    # doctor
    sub_doc = subparsers.add_parser("doctor", help="Run diagnostic health checks on Antigravity setup")
    sub_doc.set_defaults(func=cmd_doctor)

    # remove
    sub_rm = subparsers.add_parser("remove", aliases=["rm"], help="Delete a profile")
    sub_rm.add_argument("profile", help="Profile to delete")
    sub_rm.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    sub_rm.set_defaults(func=cmd_remove)

    # env
    sub_env = subparsers.add_parser("env", help="Print shell export statements for this profile")
    sub_env.add_argument("profile", help="Profile to export")
    sub_env.set_defaults(func=cmd_env)

    # pool
    sub_pool = subparsers.add_parser("pool", help="Execute with automatic failover across accounts")
    sub_pool.set_defaults(func=cmd_pool)

    args, extra = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    if args.subcommand == "run":
        cmd_run(args, extra)
    elif args.subcommand == "pool":
        cmd_pool(args, extra)
    else:
        args.func(args)


if __name__ == "__main__":
    main()

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

    if getattr(args, "token_file", None):
        import shutil
        from pathlib import Path
        src_path = Path(args.token_file).expanduser().resolve()

        if not src_path.exists():
            print(colorize(f"\nError: Token file '{args.token_file}' not found.", RED + BOLD))
            sys.exit(1)
        shutil.copy2(src_path, token_file)
        try:
            os.chmod(token_file, 0o600)
        except OSError:
            pass
        core.update_profile_info(name)
        meta = core.inspect_token_file(token_file)
        print(colorize(f"\n✔ Successfully imported token for: {meta.email}", GREEN + BOLD))
        print(f"✔ Ready for simultaneous use! Launch anytime via: {colorize('agy @' + name, CYAN + BOLD)}")
        return

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
    print("  Antigravity will launch Google sign-in with account chooser protection:")
    print(f"  {CYAN}● Incognito / Private Window{RESET} will open to prevent auto-login.")
    print(f"  {CYAN}● Account Selector forced{RESET} so Google displays the account chooser.")
    print(f"  ● Please sign into your {BOLD}OTHER / SECOND Google account{RESET}.")
    print(f"  ● Once signed in via browser, exit Antigravity ({CYAN}/exit{RESET} or {CYAN}Ctrl+C{RESET}) to finish.")
    print(f"\nPress {colorize('Enter', BOLD)} to begin sign-in...")

    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return

    # Run agy with our OAuth interceptor to force account selection & incognito mode
    try:
        core.run_profile_command(name, ["agy"], stream_output=True, use_interceptor=True)
    except KeyboardInterrupt:
        print("\n\n" + colorize("Returned from Antigravity session.", DIM))

    print_step(3, 3, "Verifying Credentials")
    core.update_profile_info(name)
    meta = core.inspect_token_file(token_file)

    if meta.status != TokenStatus.MISSING and meta.email != "None":
        # Check if the user accidentally signed in with an already configured account
        other_profiles = [p for p in core.list_profiles() if p["name"] != name and p["email"] not in ("None", "Unknown", "Error")]
        matching_profile = next((p for p in other_profiles if p["email"].lower() == meta.email.lower()), None)

        if matching_profile:
            print(colorize(f"\n⚠ Warning: Authenticated as '{meta.email}', which is ALREADY used by profile '{matching_profile['name']}'!", YELLOW + BOLD))
            print("Your browser automatically signed into your existing Google account instead of your other account.")
            print("\nTo fix this and authenticate your other Google account:")
            print(f"  1. Delete this profile:  {CYAN}agm rm {name}{RESET}")
            print(f"  2. Re-add and paste the OAuth URL into an Incognito window: {CYAN}agm add {name}{RESET}")
            print(f"  3. Make sure to click 'Use another account' on Google's sign-in screen.\n")
        else:
            print(colorize(f"\n✔ Successfully authenticated as: {meta.email}", GREEN + BOLD))
            print(f"✔ Ready for simultaneous use! Launch anytime via: {colorize('agy @' + name, CYAN + BOLD)}\n")
    else:
        print(colorize(f"\nAuthentication incomplete. Run `agm run {name}` to complete login.", YELLOW + BOLD))



def cmd_run(args: argparse.Namespace, extra_args: List[str]):
    """Run agy within the specified profile's environment."""
    core.import_existing_account_if_needed()
    name = args.profile
    cfg = core.load_config()

    if name not in cfg.get("profiles", {}):
        print(colorize(f"Error: Profile '{name}' does not exist.", RED + BOLD))
        print(f"Available profiles: {', '.join(cfg.get('profiles', {}).keys())}")
        print(f"Create it with: `agm add {name}`")
        sys.exit(1)

    cmd = ["agy"] + extra_args
    sys.exit(core.run_profile_command(name, cmd, stream_output=True))


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
    sub_add.add_argument("--token-file", help="Import an existing antigravity-oauth-token file directly")
    sub_add.add_argument("--no-login", action="store_true", help="Create profile environment without launching OAuth")
    sub_add.set_defaults(func=cmd_add)


    # run
    sub_run = subparsers.add_parser("run", help="Run agy under a specific account profile")
    sub_run.add_argument("profile", help="Profile to run under")
    sub_run.set_defaults(func=cmd_run)

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

    try:
        if args.subcommand == "run":
            cmd_run(args, extra)
        elif args.subcommand == "pool":
            cmd_pool(args, extra)
        else:
            args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


if __name__ == "__main__":
    main()

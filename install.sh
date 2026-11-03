#!/usr/bin/env bash
#
# Antigravity Multi-Account Manager (agm) Installer
#
set -e

BOLD="\033[1m"
GREEN="\033[92m"
CYAN="\033[96m"
YELLOW="\033[93m"
RESET="\033[0m"

echo -e "${CYAN}${BOLD}Installing Antigravity Multi-Account Manager (agm)...${RESET}\n"

# Verify Python 3
if ! command -v python3 &>/dev/null; then
    echo -e "${YELLOW}Error: Python 3 is required but not installed.${RESET}"
    exit 1
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SHARE_DIR="$HOME/.local/share/agy-accounts"

mkdir -p "$BIN_DIR"
mkdir -p "$HOME/.local/share"

# Link or update share directory
rm -rf "$SHARE_DIR"
ln -sf "$PROJECT_DIR" "$SHARE_DIR"

# Install binary entrypoints
cat << 'EOF' > "$BIN_DIR/agm"
#!/usr/bin/env python3
import sys
from pathlib import Path

pkg_dir = Path(__file__).resolve().parent.parent / "share" / "agy-accounts"
if str(pkg_dir) not in sys.path:
    sys.path.insert(0, str(pkg_dir))

from agm.cli import main

if __name__ == "__main__":
    main()
EOF

chmod +x "$BIN_DIR/agm"
ln -sf "$BIN_DIR/agm" "$BIN_DIR/agy-multi"

echo -e "✔ Binaries installed to ${BOLD}$BIN_DIR/agm${RESET} and ${BOLD}$BIN_DIR/agy-multi${RESET}"

# Configure shell integration in ~/.bashrc and ~/.zshrc
SHELL_SNIPPET='
# Antigravity Multi-Account Integration
agy() {
    if [[ "$1" == @* ]]; then
        local profile="${1#@}"
        shift
        agm run "$profile" "$@"
    elif [[ "$1" == "--profile" || "$1" == "-P" ]]; then
        local profile="$2"
        shift 2
        agm run "$profile" "$@"
    else
        command agy "$@"
    fi
}'

for rc_file in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc_file" ]; then
        if grep -q "Antigravity Multi-Account Integration" "$rc_file"; then
            sed -i '/# Antigravity Multi-Account Integration/,+13d' "$rc_file" 2>/dev/null || true
        fi
        echo "$SHELL_SNIPPET" >> "$rc_file"
        echo -e "✔ Configured shell dispatcher in ${BOLD}$rc_file${RESET}"
    fi
done

# Run diagnostics
echo -e "\n${CYAN}Running system diagnostics...${RESET}"
"$BIN_DIR/agm" doctor

echo -e "\n${GREEN}${BOLD}Installation complete!${RESET}"
echo -e "${YELLOW}${BOLD}⚡ IMPORTANT: Run '${CYAN}source ~/.bashrc${YELLOW}' (or restart your terminal) to enable '${CYAN}agy @<profile>${YELLOW}'.${RESET}"
echo -e "Try: ${CYAN}agm list${RESET} or ${CYAN}agm add <profile_name>${RESET}\n"

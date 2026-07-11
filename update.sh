#!/usr/bin/env bash
set -e

REPO_RAW="https://raw.githubusercontent.com/PSGtatitos/papyrus/main"
INSTALL_DIR="${HOME}/.local/bin"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m'

info()    { echo -e "${CYAN}[papyrus]${NC} $1"; }
success() { echo -e "${GREEN}[papyrus]${NC} $1"; }

info "Downloading latest version..."
curl -fsSL "$REPO_RAW/papyrus.py" -o "$INSTALL_DIR/papyrus"
chmod +x "$INSTALL_DIR/papyrus"

success "Papyrus updated successfully!"
echo ""
echo "  Restart the app to apply the update."
echo ""

#!/usr/bin/env bash
set -e

REPO_RAW="https://raw.githubusercontent.com/PSGtatitos/papyrus/main"
INSTALL_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${CYAN}[papyrus]${NC} $1"; }
success() { echo -e "${GREEN}[papyrus]${NC} $1"; }
warn()    { echo -e "${YELLOW}[papyrus]${NC} $1"; }

echo ""
echo -e "${CYAN}"
echo "  ██████╗  █████╗ ██████╗ ██╗   ██╗██████╗ ██╗   ██╗███████╗"
echo "  ██╔══██╗██╔══██╗██╔══██╗╚██╗ ██╔╝██╔══██╗██║   ██║██╔════╝"
echo "  ██████╔╝███████║██████╔╝ ╚████╔╝ ██████╔╝██║   ██║███████╗"
echo "  ██╔═══╝ ██╔══██║██╔═══╝   ╚██╔╝  ██╔══██╗██║   ██║╚════██║"
echo "  ██║     ██║  ██║██║        ██║   ██║  ██║╚██████╔╝███████║"
echo "  ╚═╝     ╚═╝  ╚═╝╚═╝        ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
echo -e "${NC}"
echo "  Animated wallpaper manager for COSMIC"
echo ""

# ── check OS ──────────────────────────────────────────────────────────────────
if ! grep -qi "pop" /etc/os-release 2>/dev/null; then
    warn "This app is designed for Pop!_OS COSMIC. Continuing anyway..."
fi

# ── system dependencies ───────────────────────────────────────────────────────
info "Installing system dependencies..."
sudo apt install -y \
    python3-gi \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    ffmpeg \
    git \
    meson \
    ninja-build \
    libmpv-dev \
    wayland-protocols \
    libwayland-dev

info "Installing Pillow..."
pip3 install pillow --break-system-packages --quiet 2>/dev/null || python3 -m pip install pillow --break-system-packages --quiet

# ── mpvpaper ──────────────────────────────────────────────────────────────────
if command -v mpvpaper &>/dev/null; then
    success "mpvpaper already installed, skipping"
else
    info "Building mpvpaper from source..."
    TMP=$(mktemp -d)
    git clone --single-branch https://github.com/GhostNaN/mpvpaper "$TMP/mpvpaper"
    cd "$TMP/mpvpaper"
    meson setup build --prefix=/usr/local
    ninja -C build
    sudo ninja -C build install
    cd -
    rm -rf "$TMP"
    success "mpvpaper installed"
fi

# ── install Papyrus ───────────────────────────────────────────────────────────
info "Installing Papyrus..."
mkdir -p "$INSTALL_DIR" "$DESKTOP_DIR" "$ICON_DIR"

# download script directly from GitHub
curl -fsSL "$REPO_RAW/papyrus.py" -o "$INSTALL_DIR/papyrus"
chmod +x "$INSTALL_DIR/papyrus"

# download icon
curl -fsSL "$REPO_RAW/assets/icon.png" -o "$ICON_DIR/io.github.papyrus.png"
ICON="io.github.papyrus"

# desktop entry
cat > "$DESKTOP_DIR/io.github.papyrus.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=Papyrus
Comment=Animated wallpaper manager for COSMIC
Exec=$INSTALL_DIR/papyrus
Icon=$ICON
Terminal=false
Categories=Utility;GTK;
Keywords=wallpaper;animated;video;COSMIC;
DESKTOP

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# create default wallpaper folder
WALLPAPER_DIR="$HOME/Wallpapers/Papyrus"
mkdir -p "$WALLPAPER_DIR"
success "Wallpaper folder created at $WALLPAPER_DIR"
info "Drop your video files there and Papyrus will find them automatically."

# ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    warn "~/.local/bin is not in your PATH."
    warn "Add this to your ~/.bashrc or ~/.zshrc:"
    warn '  export PATH="$HOME/.local/bin:$PATH"'
fi

echo ""
success "Papyrus installed successfully!"
echo ""
echo -e "  Run it:   ${CYAN}papyrus${NC}"
echo -e "  Or find it in your app launcher"
echo ""

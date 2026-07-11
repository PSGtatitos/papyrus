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

# ── distro detection ──────────────────────────────────────────────────────────
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO="$ID"
else
    DISTRO="unknown"
fi
info "Detected: $DISTRO"

# ── package manager ───────────────────────────────────────────────────────────
APT_DEPS=(
    python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg
    git meson ninja-build libmpv-dev wayland-protocols libwayland-dev
)
PACMAN_DEPS=(
    python-gobject gtk4 libadwaita ffmpeg
    git meson ninja libmpv wayland wayland-protocols base-devel
)
DNF_DEPS=(
    python3-gobject gtk4-devel libadwaita ffmpeg-free
    git meson ninja-build libmpv-devel wayland-devel wayland-protocols-devel
    gcc
)

install_system_deps() {
    if command -v apt &>/dev/null; then
        sudo apt update
        sudo apt install -y "${APT_DEPS[@]}"
    elif command -v pacman &>/dev/null; then
        sudo pacman -Sy --noconfirm "${PACMAN_DEPS[@]}"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "${DNF_DEPS[@]}"
    elif command -v zypper &>/dev/null; then
        sudo zypper refresh
        sudo zypper install -y \
            python3-gobject python3-gobject-Gtk gtk4-devel libadwaita \
            ffmpeg git meson ninja libmpv-devel libwayland-devel \
            wayland-protocols-devel gcc
    else
        warn "Unsupported package manager. Install dependencies manually."
        warn "See: https://github.com/PSGtatitos/papyrus"
    fi
}

install_python_deps() {
    if command -v pip3 &>/dev/null; then
        pip3 install pillow --break-system-packages --quiet 2>/dev/null || \
        python3 -m pip install pillow --break-system-packages --quiet 2>/dev/null || \
        warn "Could not install Pillow via pip. Try: sudo pip3 install pillow"
    fi
}

# ── system dependencies ───────────────────────────────────────────────────────
info "Installing system dependencies..."
install_system_deps

info "Installing Python packages..."
install_python_deps

# ── mpvpaper ──────────────────────────────────────────────────────────────────
if command -v mpvpaper &>/dev/null; then
    success "mpvpaper already installed, skipping"
else
    info "Building mpvpaper from source..."
    TMP=$(mktemp -d)
    git clone --single-branch --depth 1 --branch 1.5 \
        https://github.com/GhostNaN/mpvpaper "$TMP/mpvpaper"
    cd "$TMP/mpvpaper"
    CFLAGS="-Wno-error=incompatible-pointer-types" meson setup build
    ninja -C build
    sudo cp build/mpvpaper /usr/local/bin/
    sudo cp build/mpvpaper-holder /usr/local/bin/
    cd - > /dev/null
    rm -rf "$TMP"
    success "mpvpaper installed to /usr/local/bin"
fi

# ── install Papyrus ───────────────────────────────────────────────────────────
info "Installing Papyrus..."
mkdir -p "$INSTALL_DIR" "$DESKTOP_DIR" "$ICON_DIR"

curl -fsSL "$REPO_RAW/papyrus.py" -o "$INSTALL_DIR/papyrus"
chmod +x "$INSTALL_DIR/papyrus"

curl -fsSL "$REPO_RAW/assets/icon.png" -o "$ICON_DIR/io.github.PSGtatitos.papyrus.png"

cat > "$DESKTOP_DIR/io.github.PSGtatitos.papyrus.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=Papyrus
Comment=Animated wallpaper manager for COSMIC
Exec=$INSTALL_DIR/papyrus
Icon=io.github.PSGtatitos.papyrus
Terminal=false
Categories=GTK;Utility;
StartupNotify=true
Keywords=wallpaper;animated;video;COSMIC;
DESKTOP

update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

WALLPAPER_DIR="$HOME/Wallpapers/Papyrus"
mkdir -p "$WALLPAPER_DIR"
success "Wallpaper folder created at $WALLPAPER_DIR"

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

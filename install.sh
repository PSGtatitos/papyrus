#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/PSGtatitos/papyrus"
VERSION="1.2.1"

# --- Utils ---
die() { echo -e "\033[31mError: $*\033[0m" >&2; exit 1; }
info() { echo -e "\033[36m==>\033[0m $*"; }
warn() { echo -e "\033[33mWarning:\033[0m $*"; }

# --- Distro detection ---
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_ID="$ID"
        DISTRO_LIKE="$ID_LIKE"
    elif command -v lsb_release &>/dev/null; then
        DISTRO_ID="$(lsb_release -is | tr '[:upper:]' '[:lower:]')"
    else
        die "Cannot detect your Linux distribution. Please install manually."
    fi
}

# --- Package manager helpers ---
INSTALL_CMD=""
UPDATE_CMD=""
PKG_GROUPS=()

detect_pkg_manager() {
    if command -v apt &>/dev/null; then
        INSTALL_CMD="sudo apt install -y"
        UPDATE_CMD="sudo apt update"
        DISTRO_FAMILY="debian"
    elif command -v pacman &>/dev/null; then
        INSTALL_CMD="sudo pacman -S --noconfirm"
        UPDATE_CMD="sudo pacman -Sy"
        DISTRO_FAMILY="arch"
        if command -v yay &>/dev/null; then
            AUR_HELPER="yay"
        elif command -v paru &>/dev/null; then
            AUR_HELPER="paru"
        fi
    elif command -v dnf &>/dev/null; then
        INSTALL_CMD="sudo dnf install -y"
        UPDATE_CMD="sudo dnf check-update || true"
        DISTRO_FAMILY="fedora"
    elif command -v zypper &>/dev/null; then
        INSTALL_CMD="sudo zypper install -y"
        UPDATE_CMD="sudo zypper refresh"
        DISTRO_FAMILY="suse"
    else
        die "No supported package manager found. Supported: apt, pacman, dnf, zypper"
    fi
}

install_deps() {
    info "Installing dependencies..."

    case "$DISTRO_FAMILY" in
        debian)
            $UPDATE_CMD
            $INSTALL_CMD \
                python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 \
                ffmpeg python3-pip python3-pil \
                libmpv-dev libwayland-dev wayland-protocols \
                meson ninja-build pkg-config git
            pip3 install pillow --break-system-packages 2>/dev/null || true
            ;;
        arch)
            $UPDATE_CMD
            $INSTALL_CMD \
                python python-gobject gtk4 libadwaita \
                ffmpeg python-pillow \
                libmpv wayland wayland-protocols \
                meson ninja pkgconf git base-devel
            if [ -n "${AUR_HELPER:-}" ]; then
                info "Installing mpvpaper from AUR via $AUR_HELPER..."
                $AUR_HELPER -S --noconfirm mpvpaper 2>/dev/null || warn "Could not install mpvpaper from AUR, will build from source"
            fi
            ;;
        fedora)
            $UPDATE_CMD
            $INSTALL_CMD \
                python3 python3-gobject gtk4-devel libadwaita \
                ffmpeg python3-pillow python3-pip \
                libmpv-devel wayland-devel wayland-protocols-devel \
                meson ninja-build pkgconfig git gcc
            pip3 install pillow --break-system-packages 2>/dev/null || true
            ;;
        suse)
            $UPDATE_CMD
            $INSTALL_CMD \
                python3 python3-gobject python3-gobject-Gtk \
                gtk4-devel libadwaita \
                ffmpeg python3-pillow python3-pip \
                libmpv-devel libwayland-devel wayland-protocols-devel \
                meson ninja pkg-config git gcc
            pip3 install pillow --break-system-packages 2>/dev/null || true
            ;;
    esac
}

build_mpvpaper() {
    if command -v mpvpaper &>/dev/null; then
        info "mpvpaper already installed, skipping build"
        return 0
    fi
    info "Building mpvpaper from source..."
    TMP_DIR="$(mktemp -d)"
    git clone --depth 1 --branch 1.5 https://github.com/GhostNaN/mpvpaper.git "$TMP_DIR/mpvpaper"
    cd "$TMP_DIR/mpvpaper"
    CFLAGS="-Wno-error=incompatible-pointer-types" meson setup build
    ninja -C build
    sudo cp build/mpvpaper /usr/local/bin/
    sudo cp build/mpvpaper-holder /usr/local/bin/
    cd /
    rm -rf "$TMP_DIR"
    info "mpvpaper installed to /usr/local/bin"
}

install_papyrus() {
    info "Installing Papyrus..."

    SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

    sudo mkdir -p /usr/local/bin
    sudo mkdir -p /usr/local/share/applications
    sudo mkdir -p /usr/local/share/metainfo
    sudo mkdir -p /usr/local/share/icons/hicolor/256x256/apps

    sudo cp "$SRC_DIR/papyrus.py" /usr/local/bin/papyrus
    sudo chmod 755 /usr/local/bin/papyrus

    # Update desktop file with correct path
    sed "s|Exec=papyrus|Exec=/usr/local/bin/papyrus|" \
        "$SRC_DIR/io.github.PSGtatitos.papyrus.desktop" | \
        sudo tee /usr/local/share/applications/io.github.PSGtatitos.papyrus.desktop > /dev/null

    sudo cp "$SRC_DIR/io.github.PSGtatitos.papyrus.metainfo.xml" \
        /usr/local/share/metainfo/

    sudo cp "$SRC_DIR/assets/icon.png" \
        /usr/local/share/icons/hicolor/256x256/apps/io.github.PSGtatitos.papyrus.png

    info "Papyrus installed to /usr/local"
}

post_install() {
    info "Updating desktop database..."
    sudo update-desktop-database 2>/dev/null || true
    sudo gtk-update-icon-cache /usr/local/share/icons/hicolor/ 2>/dev/null || true
    sudo gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true

    mkdir -p "$HOME/Wallpapers/Papyrus" 2>/dev/null || true

    echo ""
    echo -e "\033[32mPapyrus v$VERSION installed successfully!\033[0m"
    echo ""
    echo "  Run: papyrus"
    echo ""
    echo "  Add video files to ~/Wallpapers/Papyrus"
    echo "  or add folders from the app's sidebar."
    echo ""
    echo "  To uninstall:"
    echo "    sudo rm /usr/local/bin/papyrus /usr/local/bin/mpvpaper /usr/local/bin/mpvpaper-holder"
    echo "    sudo rm /usr/local/share/applications/io.github.PSGtatitos.papyrus.desktop"
    echo "    sudo rm /usr/local/share/metainfo/io.github.PSGtatitos.papyrus.metainfo.xml"
    echo "    sudo rm /usr/local/share/icons/hicolor/256x256/apps/io.github.PSGtatitos.papyrus.png"
}

# --- Main ---
main() {
    echo "Papyrus v$VERSION Installer"
    echo "=========================="
    echo ""

    detect_distro
    detect_pkg_manager

    echo "Detected: $DISTRO_ID ($DISTRO_FAMILY)"
    echo ""

    if [ "$(id -u)" = "0" ]; then
        die "Do not run this script as root. It will use sudo when needed."
    fi

    if ! command -v sudo &>/dev/null; then
        die "sudo is required but not installed."
    fi

    install_deps
    build_mpvpaper
    install_papyrus
    post_install
}

main "$@"

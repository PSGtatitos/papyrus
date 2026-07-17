<div align="center">
  <img src="assets/icon.png" alt="Papyrus Logo" width="128" height="128">
  <h1>Papyrus</h1>
  <p>Animated wallpaper manager for Pop!_OS COSMIC</p>

  ![License](https://img.shields.io/badge/license-GPL--3.0-blue)
  ![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)
  ![DE](https://img.shields.io/badge/DE-COSMIC-orange)
  ![Python](https://img.shields.io/badge/python-3.10%2B-blue)
  [![Build .deb](https://github.com/PSGtatitos/papyrus/actions/workflows/build-deb.yml/badge.svg)](https://github.com/PSGtatitos/papyrus/actions/workflows/build-deb.yml)
  [![AUR](https://img.shields.io/aur/version/papyrus-wallpaper)](https://aur.archlinux.org/packages/papyrus-wallpaper)

</div>

---
<img width="983" height="636" alt="image" src="https://github.com/user-attachments/assets/cab200e9-4b70-4c3f-975d-5cc839f22711" />


Papyrus is a free, open-source animated wallpaper manager for Pop!_OS COSMIC. Pick a video, click it, and it becomes your live wallpaper — no accounts, no telemetry, no Wallpaper Engine required.

It also automatically extracts the dominant color from your wallpaper and applies it as your COSMIC accent color, so your entire desktop theme matches your wallpaper vibe.

## Features

- 🎬 **Animated wallpapers** — supports MP4, WebM, MKV, AVI, MOV
- 🖥️ **Per-monitor wallpapers** — set different videos on each monitor independently
- 📐 **Per-monitor scaling** — choose Fit, Fill, or Stretch for each output
- 🔄 **Playlist rotation** — auto-switch wallpapers at a set interval (random or sequential order)
- 🎨 **Auto-theme** — extracts accent color from wallpaper and applies it to COSMIC
- 🌙 **Auto dark/light mode** — detects wallpaper brightness and switches accordingly
- 📁 **Folder picker** — choose any folder of video files to scan
- 🖼️ **Thumbnail previews** — auto-generated from your video files
- 🔁 **Start on login** — one toggle to persist your wallpaper across reboots
- ⬆️ **Self-update** — app checks for updates and can download & install them with one click
- 🚫 **No telemetry, no accounts, no cloud** — config is a plain JSON file

## COSMIC Store

Papyrus is available in the [cosmic-flatpak](https://github.com/cosmic-utils/cosmic-flatpak) repository and can be installed directly from the COSMIC Store. You can also install manually.

## Installation

### Quick install (any distro)

The universal installer detects your distro and handles everything:

```bash
curl -fsSL https://raw.githubusercontent.com/PSGtatitos/papyrus/main/install.sh | bash
```

Supports: Pop, Ubuntu, Debian, Fedora, openSUSE. Arch-based users should use the [AUR package](#aur-arch-linux--cachyos--manjaro) instead.

### AUR (Arch Linux / CachyOS / Manjaro)

Install from the AUR using your preferred AUR helper:

```bash
yay -S papyrus-wallpaper
# or
paru -S papyrus-wallpaper
```

Dependencies (`mpvpaper`, `python-gobject`, `gtk4`, etc.) are handled automatically.

### .deb package (Debian/Ubuntu/Pop)

Download the latest `.deb` from the [releases page](https://github.com/PSGtatitos/papyrus/releases) and install:

```bash
sudo apt install ./papyrus_*.deb
```

The `.deb` bundles mpvpaper and includes all dependencies.

### COSMIC Store (Flatpak)

Search for "Papyrus" in the COSMIC Store or run:

```bash
flatpak install io.github.PSGtatitos.papyrus
```

## Updating

- **Local install:** Run `./update.sh` or re-run the installer. The app can also self-update from the banner.
- **.deb install:** Download the latest `.deb` from the releases page and reinstall.
- **Flatpak:** Updated automatically via the COSMIC Store.
- **AUR:** Updated via your AUR helper (`yay -Syu` or `paru -Syu`).

## Usage

Launch Papyrus from your app launcher or run:

```bash
papyrus
```

- **Click** any thumbnail to set it as your wallpaper
- **Folder** button (top left) to add wallpaper folders
- **Playlist** tab in Settings to enable auto-rotation with configurable interval (random or sequential)
- **Auto-theme DE** toggle to enable/disable automatic COSMIC theming
- **Stop** button (top right) to remove the wallpaper
- Update banner appears automatically when a new version is available

## Where to find animated wallpapers

- [MoeWalls](https://moewalls.com) — anime/gaming, optimized WebM/MP4
- [MotionBGs](https://motionbgs.com) — 8,000+ wallpapers in 4K
- [Wallsflow](https://wallsflow.com) — growing collection, free
- [Pexels Videos](https://pexels.com/videos) — cinematic/nature, 4K

## How it works

Papyrus uses [mpvpaper](https://github.com/GhostNaN/mpvpaper) to render video files as Wayland layer surfaces behind your desktop. When you select a wallpaper, Papyrus:

1. Kills any running mpvpaper instance
2. Starts mpvpaper with loop enabled on your display output
3. Extracts the most vibrant pixel from the video thumbnail
4. Writes the color to COSMIC's compiled theme config files
5. COSMIC picks up the file changes and updates the accent color

## Auto-theming

When Auto-theme DE is enabled, Papyrus writes directly to:

```
~/.config/cosmic/com.system76.CosmicTheme.Dark/v1/accent
~/.config/cosmic/com.system76.CosmicTheme.Dark/v1/background
~/.config/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark
```

No restart required — COSMIC watches these files and applies changes live.

## Config

Config is stored at `~/.config/papyrus/config.json`:

```json
{
  "current": "/home/user/Wallpapers/Papyrus/my-wallpaper.mp4",
  "dirs": ["/home/user/Wallpapers/Papyrus"],
  "output": "HDMI-A-1",
  "auto_theme": true,
  "rotation": true,
  "interval": 30,
  "order": "random"
}
```

## Uninstall

**Local install:**
```bash
rm ~/.local/bin/papyrus
rm ~/.local/share/applications/io.github.PSGtatitos.papyrus.desktop
rm ~/.local/share/icons/hicolor/256x256/apps/io.github.PSGtatitos.papyrus.png
rm -rf ~/.config/papyrus
rm -f ~/.config/autostart/papyrus.desktop
update-desktop-database ~/.local/share/applications
```

**.deb install:**
```bash
sudo apt remove --purge papyrus
rm -rf ~/.config/papyrus
```

**AUR:**
```bash
yay -Rns papyrus-wallpaper
rm -rf ~/.config/papyrus
```

**Flatpak:**
```bash
flatpak uninstall io.github.PSGtatitos.papyrus
```

## Contributing

Pull requests are welcome. For major changes, open an issue first.

Built with assistance from: Claude (Anthropic) was used as a coding assistant during development.

## License

[GPL-3.0](LICENSE) — same license as mpvpaper.

---

<div align="center">
  Made with ❤️ for the COSMIC desktop community
</div>

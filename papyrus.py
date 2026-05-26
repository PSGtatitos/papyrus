#!/usr/bin/env python3
"""
Papyrus — animated wallpaper picker for Pop!_OS COSMIC
Uses mpvpaper under the hood. No metadata, no telemetry, no accounts.

Requirements:
    sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 ffmpeg
    pip install pillow --break-system-packages
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk

import subprocess
import json
import shutil
import threading
import signal
import urllib.request
from datetime import datetime
from pathlib import Path
import os

VERSION      = "1.1.0"
API_URL      = "https://api.github.com/repos/PSGtatitos/papyrus/releases/latest"
RELEASES_URL = "https://github.com/PSGtatitos/papyrus/releases/latest"
IN_FLATPAK   = Path("/app/bin/mpvpaper").exists()

def check_for_updates(callback):
    from gi.repository import GLib
    def _check():
        try:
            req = urllib.request.Request(
                API_URL,
                headers={"User-Agent": f"papyrus/{VERSION}"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                latest = data.get("tag_name", "").lstrip("v")
                if not latest:
                    return
                current = [int(x) for x in VERSION.split(".")]
                remote  = [int(x) for x in latest.split(".")]
                if remote > current:
                    GLib.idle_add(callback, latest)
        except Exception as e:
            print(f"[papyrus] update check failed: {e}")
    threading.Thread(target=_check, daemon=True).start()

CONFIG_DIR    = Path.home() / ".config" / "papyrus"
CONFIG_FILE   = CONFIG_DIR / "config.json"
AUTOSTART     = Path.home() / ".config" / "autostart" / "papyrus.desktop"
DEFAULT_DIRS  = [Path.home() / "Wallpapers" / "Papyrus", Path.home() / "Downloads", Path.home() / "Videos", Path.home() / "Pictures"]
VIDEO_EXTS    = {".mp4", ".webm", ".mkv", ".avi", ".mov"}

COSMIC_DARK   = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Dark/v1"
COSMIC_LIGHT  = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Light/v1"
COSMIC_DARK_B = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Dark.Builder/v1"
COSMIC_LIGHT_B= Path.home() / ".config/cosmic/com.system76.CosmicTheme.Light.Builder/v1"
COSMIC_MODE   = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Mode/v1"

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"current": None, "dirs": [str(d) for d in DEFAULT_DIRS], "output": "*", "auto_theme": False}

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

_mpvpaper_pids = set()

def kill_mpvpaper():
    for pid in list(_mpvpaper_pids):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    _mpvpaper_pids.clear()
    subprocess.run(["pkill", "-f", "mpvpaper"], capture_output=True)

def _mpvpaper_bin():
    if Path("/app/bin/mpvpaper").exists():
        return "/app/bin/mpvpaper"
    return "mpvpaper"

def detect_output():
    try:
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display:
            monitors = display.get_monitors()
            if monitors.get_n_items() > 0:
                monitor = monitors.get_item(0)
                if hasattr(monitor, "get_connector") and monitor.get_connector():
                    return monitor.get_connector()
    except Exception as e:
        print(f"[papyrus] Native Gdk display detection failed: {e}")

    for cmd in [["wlr-randr"], ["wayland-info"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if r.returncode != 0:
                continue
            for line in r.stdout.splitlines():
                if cmd[0] == "wlr-randr" and "connected" in line:
                    return line.split()[0]
        except Exception:
            continue

    return "*"

def apply_wallpaper(path: str, output: str):
    kill_mpvpaper()
    bin_path = _mpvpaper_bin()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = CONFIG_DIR / "mpvpaper.log"
    cmd = [bin_path, output, path]
    ts = datetime.now().isoformat()
    log_file.write_text(f"[{ts}] running: {' '.join(cmd)}\n")
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        _mpvpaper_pids.add(proc.pid)
        ts = datetime.now().isoformat()
        with log_file.open("a") as f:
            f.write(f"[{ts}] mpvpaper PID: {proc.pid}\n")

        def log_stderr():
            with log_file.open("a") as f:
                for line in iter(proc.stderr.readline, b""):
                    f.write(f"[{datetime.now().isoformat()}] {line.decode()}")
                    f.flush()
        threading.Thread(target=log_stderr, daemon=True).start()

        def monitor(timeout=5):
            import time
            time.sleep(timeout)
            ret = proc.poll()
            with log_file.open("a") as f:
                if ret is not None:
                    f.write(f"[{datetime.now().isoformat()}] mpvpaper exited with code {ret}\n")
                else:
                    f.write(f"[{datetime.now().isoformat()}] mpvpaper still running after {timeout}s\n")
        threading.Thread(target=monitor, daemon=True).start()

        return True
    except Exception as e:
        ts = datetime.now().isoformat()
        with log_file.open("a") as f:
            f.write(f"[{ts}] failed to start: {e}\n")
        return False

def write_autostart(path: str, output: str):
    if IN_FLATPAK:
        return
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Papyrus\n"
        f'Exec=mpvpaper -o "loop" {output} {path}\n'
        "X-GNOME-Autostart-enabled=true\n"
    )

def remove_autostart():
    if IN_FLATPAK:
        return
    if AUTOSTART.exists():
        AUTOSTART.unlink()

def extract_palette(thumb_path):
    try:
        from PIL import Image
        import colorsys

        img = Image.open(thumb_path).convert("RGB")
        img = img.resize((200, 200))
        pixels = list(img.getdata())

        best_vibrancy = -1
        best_color = (1.0, 0.5, 0.0)

        for pr, pg, pb in pixels:
            h, s, v = colorsys.rgb_to_hsv(pr/255, pg/255, pb/255)
            if v < 0.15 or v > 0.97:
                continue
            vibrancy = s * v
            if vibrancy > best_vibrancy:
                best_vibrancy = vibrancy
                best_color = (pr/255.0, pg/255.0, pb/255.0)

        avg_lum = sum(0.299*p[0] + 0.587*p[1] + 0.114*p[2] for p in pixels) / len(pixels)
        is_dark = avg_lum < 128

        return best_color, is_dark
    except Exception as e:
        print(f"[papyrus] extract_palette error: {e}")
        return None, None

def darken(r, g, b, factor):
    return max(0.0, r*factor), max(0.0, g*factor), max(0.0, b*factor)

def lighten(r, g, b, amount):
    return min(1.0, r+amount), min(1.0, g+amount), min(1.0, b+amount)

def c(r, g, b, a=1.0):
    return f"(\n        red: {r:.7f},\n        green: {g:.7f},\n        blue: {b:.7f},\n        alpha: {a:.1f},\n    )"

def write_accent(path: Path, r, g, b):
    dr, dg, db = darken(r, g, b, 0.85)
    pr, pg, pb = darken(r, g, b, 0.55)
    path.write_text(f"""Some((
    base: {c(r, g, b)},
    hover: {c(dr, dg, db)},
    pressed: {c(pr, pg, pb)},
    selected: {c(dr, dg, db)},
    selected_text: {c(r, g, b)},
    focus: {c(r, g, b)},
    divider: {c(0.0, 0.0, 0.0)},
    on: {c(0.0, 0.0, 0.0)},
    disabled: {c(r, g, b)},
    on_disabled: {c(pr, pg, pb)},
    border: {c(r, g, b)},
    disabled_border: {c(r, g, b, 0.5)},
))""")

def write_background(path: Path, r, g, b, is_dark: bool):
    if is_dark:
        br, bg_, bb = darken(r, g, b, 0.15)
        br, bg_, bb = max(br, 0.08), max(bg_, 0.08), max(bb, 0.08)
    else:
        br, bg_, bb = lighten(r, g, b, 0.7)
        br, bg_, bb = min(br, 0.96), min(bg_, 0.96), min(bb, 0.96)

    cr, cg, cb = lighten(br, bg_, bb, 0.1) if is_dark else darken(br, bg_, bb, 0.9)
    path.write_text(f"""(
    base: {c(br, bg_, bb)},
    component: (
        base: {c(cr, cg, cb)},
        hover: {c(*lighten(cr, cg, cb, 0.05))},
        pressed: {c(*lighten(cr, cg, cb, 0.1))},
        selected: {c(*lighten(cr, cg, cb, 0.05))},
        selected_text: {c(r, g, b)},
        focus: {c(r, g, b)},
        divider: {c(0.02, 0.01, 0.005, 0.2)},
        on: {c(0.02, 0.01, 0.005)},
        disabled: {c(cr, cg, cb, 0.5)},
        on_disabled: {c(0.02, 0.01, 0.005, 0.65)},
        border: {c(r, g, b)},
        disabled_border: {c(r, g, b, 0.5)},
    ),
    divider: {c(*lighten(br, bg_, bb, 0.12))},
    on: {c(1.0, 1.0, 1.0) if is_dark else c(0.0, 0.0, 0.0)},
    small_widget: {c(r, g, b, 0.25)},
)""")

def write_builder_accent(path: Path, r, g, b):
    path.write_text(f"Some((\n    red: {r:.7f},\n    green: {g:.7f},\n    blue: {b:.7f},\n))")

def apply_cosmic_theme(thumb_path, auto_dark=True):
    color, is_dark = extract_palette(thumb_path)
    if color is None:
        return False

    r, g, b = color
    print(f"[papyrus] accent: r={r:.3f} g={g:.3f} b={b:.3f} dark={is_dark}")

    for variant, builder_var in [(COSMIC_DARK, COSMIC_DARK_B), (COSMIC_LIGHT, COSMIC_LIGHT_B)]:
        variant.mkdir(parents=True, exist_ok=True)
        write_accent(variant / "accent", r, g, b)
        write_background(variant / "background", r, g, b, variant is COSMIC_DARK)
        (variant / "is_dark").write_text("true" if variant is COSMIC_DARK else "false")

        builder_var.mkdir(parents=True, exist_ok=True)
        write_builder_accent(builder_var / "accent", r, g, b)

    if auto_dark:
        COSMIC_MODE.mkdir(parents=True, exist_ok=True)
        (COSMIC_MODE / "is_dark").write_text("true" if is_dark else "false")

    return True

def scan_videos(dirs):
    videos = []
    for d in dirs:
        p = Path(d)
        if p.exists():
            for f in sorted(p.iterdir()):
                if f.suffix.lower() in VIDEO_EXTS:
                    videos.append(f)
    return videos

def get_thumb(path: Path) -> Path:
    thumb = CONFIG_DIR / "thumbs" / (path.stem[:80] + ".jpg")
    if not thumb.exists():
        thumb.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ss", "00:00:01",
             "-vframes", "1", "-vf", "scale=160:-1", str(thumb)],
            capture_output=True,
        )
    return thumb

def get_thumb_large(path: Path) -> Path:
    thumb = CONFIG_DIR / "thumbs" / (path.stem[:80] + "_large.jpg")
    if not thumb.exists():
        thumb.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ss", "00:00:01",
             "-vframes", "1", "-vf", "scale=640:-1", str(thumb)],
            capture_output=True,
        )
    return thumb

def short_name(path: Path, n=22):
    s = path.stem
    return s[:n] + "\u2026" if len(s) > n else s

CSS = """
/* ── Kinetic Slate Design System ──────────────────────────────── */
* {
    font-family: 'Inter', sans-serif;
}

/* Colors */
@define-color surface #131313;
@define-color surface-dim #131313;
@define-color surface-bright #393939;
@define-color surface-container-lowest #0e0e0e;
@define-color surface-container-low #1c1b1b;
@define-color surface-container #20201f;
@define-color surface-container-high #2a2a2a;
@define-color surface-container-highest #353535;
@define-color surface-variant #353535;
@define-color on-surface #e5e2e1;
@define-color on-surface-variant #c1c6d4;
@define-color outline #8b919e;
@define-color outline-variant #414752;
@define-color primary #a7c8ff;
@define-color on-primary #003061;
@define-color primary-container #4691f2;
@define-color on-primary-container #002a55;
@define-color secondary #68d9c9;
@define-color on-secondary #003731;
@define-color secondary-container #22a193;
@define-color on-secondary-container #00302b;
@define-color tertiary #efb0ff;
@define-color error #ffb4ab;
@define-color error-container #93000a;
@define-color on-error-container #ffdad6;
@define-color background #131313;
@define-color on-background #e5e2e1;

/* Typography classes */
.window-title {
    font-family: 'Inter', sans-serif;
    font-size: 16px;
    font-weight: 700;
    line-height: 24px;
}
.banner-heading {
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    font-weight: 600;
    line-height: 20px;
}
.body-base {
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    font-weight: 400;
    line-height: 21px;
}
.control-label {
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 400;
    line-height: 18px;
}
.card-title {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    font-weight: 600;
    line-height: 16px;
}
.status-label {
    font-family: 'Inter', sans-serif;
    font-size: 11px;
    font-weight: 500;
    line-height: 14px;
    letter-spacing: 0.02em;
}

/* Sidebar */
.sidebar {
    background-color: @surface-container-low;
    border-right: 1px solid @outline-variant;
    padding: 12px;
}
.sidebar-title {
    padding: 0 8px;
    margin-bottom: 32px;
}
.sidebar-subtitle {
    color: @on-surface-variant;
}
.nav-row {
    background: transparent;
    border-radius: 8px;
    padding: 8px 12px;
    margin: 2px 0;
    transition: all 150ms ease;
}
.nav-row:hover {
    background-color: @surface-variant;
}
.nav-row:selected {
    background-color: @secondary-container;
    font-weight: 700;
}
.nav-row:selected label,
.nav-row:selected image {
    color: @on-secondary-container;
}
.nav-row:selected .nav-label {
    font-weight: 700;
}

.nav-label {
    color: @on-surface-variant;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    font-weight: 400;
}
.nav-icon {
    color: @on-surface-variant;
}

/* Header Bar */
.top-header {
    background-color: @surface;
    border-bottom: 1px solid @outline-variant;
    min-height: 48px;
    padding: 0 16px;
}
.header-btn {
    background: transparent;
    border: none;
    border-radius: 9999px;
    padding: 6px;
    min-width: 32px;
    min-height: 32px;
    transition: all 100ms ease;
}
.header-btn:hover {
    background-color: @surface-variant;
}
.header-btn:active {
    background-color: @surface-variant;
    opacity: 0.8;
}
.header-btn image {
    color: @on-surface-variant;
}
.stop-btn {
    background-color: @error-container;
    border-radius: 9999px;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 13px;
    color: @on-error-container;
}
.stop-btn:hover {
    opacity: 0.9;
}

/* Cards */
.wallpaper-card {
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid @outline-variant;
    transition: all 300ms ease;
}
.wallpaper-card:hover {
    border-color: @outline;
}
.wallpaper-card:hover .card-thumb {
    transform: scale(1.1);
}
.wallpaper-card.active {
    border: 2px solid @primary;
}
.card-thumb {
    border-radius: 12px;
    overflow: hidden;
    transition: transform 500ms ease;
}
.card-play-overlay {
    background-color: alpha(@primary, 0.1);
}
.card-play-btn {
    background-color: @primary;
    color: @on-primary;
    border-radius: 9999px;
    padding: 6px;
}

/* Info Banner */
.info-banner {
    background-color: @primary-container;
    color: @on-primary-container;
    border-radius: 8px;
    padding: 16px;
}
.info-banner label {
    color: @on-primary-container;
}

/* Settings */
.settings-section-title {
    color: @primary;
    margin-bottom: 16px;
}
.settings-row {
    background-color: @surface-container;
    border-radius: 8px;
    border: 1px solid transparent;
    padding: 12px 16px;
    transition: all 150ms ease;
}
.settings-row:hover {
    border-color: @outline-variant;
}
.settings-row label {
    color: @on-surface;
}
.settings-row .settings-desc {
    color: @on-surface-variant;
    font-size: 11px;
}

/* Toggle switch */
toggle-switch {
    background-color: @surface-variant;
    border-radius: 9999px;
}
toggle-switch:checked {
    background-color: @secondary-container;
}
toggle-switch slider {
    background-color: @on-surface;
    border-radius: 9999px;
}

/* Custom toggle */
.custom-toggle {
    background-color: @surface-variant;
    border-radius: 9999px;
    min-height: 24px;
    min-width: 44px;
}
.custom-toggle:checked {
    background-color: @secondary-container;
}
.custom-toggle:checked slider {
    background-color: @on-surface;
}

/* Footer */
.footer-bar {
    background-color: @surface;
    border-top: 1px solid @outline-variant;
    padding: 4px 16px;
}
.footer-link {
    color: @on-surface-variant;
    font-size: 11px;
}
.footer-link:hover {
    color: @primary;
}

/* Scrollbar */
scrollbar {
    background: transparent;
}
scrollbar trough {
    background: transparent;
    border: none;
}
scrollbar slider {
    background: @surface-variant;
    border-radius: 4px;
    min-width: 4px;
}
scrollbar slider:hover {
    background: @outline-variant;
}

/* Active card label */
.active-card-label {
    color: @primary;
    font-weight: 700;
}

/* FlowBox */
flowbox {
    background: @surface;
}
flowboxchild {
    background: transparent;
    border: none;
    padding: 0;
    border-radius: 8px;
}
flowboxchild:selected {
    background: transparent;
}

/* Dropdown */
dropdown {
    background-color: @surface-container-highest;
    border: 1px solid @outline-variant;
    border-radius: 8px;
    color: @on-surface;
    font-size: 13px;
    padding: 4px 12px;
    min-height: 32px;
}
dropdown:hover {
    border-color: @on-surface-variant;
}
dropdown popover {
    background-color: @surface-container-high;
    border: 1px solid @outline-variant;
    border-radius: 8px;
}
dropdown popover list {
    background: transparent;
}

/* Separator */
separator {
    background-color: @outline-variant;
    min-height: 1px;
}

/* Engine status */
.engine-status {
    background-color: @surface-container;
    border-radius: 12px;
    padding: 16px;
}
.engine-dot {
    min-height: 8px;
    min-width: 8px;
    border-radius: 9999px;
    background-color: @secondary;
}

/* Detail page */
.detail-backdrop {
    background: alpha(@surface-dim, 0.85);
}
.detail-card {
    background-color: @surface-container-low;
    border: 1px solid @outline-variant;
    border-radius: 12px;
}
.detail-sidebar {
    background-color: @surface-container;
}
.color-swatch {
    border-radius: 9999px;
    border: 1px solid @outline-variant;
    min-height: 40px;
    min-width: 40px;
}
.color-swatch.active {
    border: 2px solid @primary;
}

/* Folder list */
.folder-entry {
    padding: 16px;
    border-bottom: 1px solid @outline-variant;
}
.folder-entry:last-child {
    border-bottom: none;
}
.folder-entry:hover {
    background-color: @surface-variant;
}
.folder-icon {
    background-color: @surface-container-high;
    border-radius: 8px;
    min-height: 40px;
    min-width: 40px;
}
.folder-icon image {
    color: @primary;
}
.folder-delete-btn {
    color: @error;
    border-radius: 9999px;
    padding: 8px;
}
.folder-delete-btn:hover {
    background: alpha(@error, 0.15);
}

/* Empty state */
.empty-state {
    opacity: 0.4;
}

/* Glow effect for active cards */
.active-glow {
    box-shadow: 0 0 15px 2px alpha(@primary, 0.15);
}

/* Bottom action bar */
.action-bar {
    background-color: @surface-container-low;
    border-top: 1px solid @outline-variant;
    padding: 16px;
}
.primary-btn {
    background-color: @primary;
    color: @on-primary;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 700;
}
.primary-btn:hover {
    opacity: 0.9;
}
.primary-btn:active {
    opacity: 0.8;
}
"""

class CWApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.PSGtatitos.papyrus",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.connect("activate", self._activate)
        self.cfg = load_config()
        self.output = self.cfg.get("output") or detect_output()
        self._current_page = "library"

    def _activate(self, app):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self.win = Gtk.ApplicationWindow(application=app)
        self.win.set_default_size(960, 640)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.win.get_display(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.header = Adw.HeaderBar()
        self.header_title = Adw.WindowTitle(title="Library", subtitle="")
        self.header.set_title_widget(self.header_title)
        self.win.set_titlebar(self.header)

        self.add_btn = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Add folder")
        self.add_btn.connect("clicked", self._add_folder)
        self.header.pack_start(self.add_btn)

        self.stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text="Stop wallpaper")
        self.stop_btn.add_css_class("stop-btn")
        self.stop_btn.connect("clicked", self._stop)
        self.header.pack_end(self.stop_btn)

        self.back_btn = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text="Back to Library")
        self.back_btn.connect("clicked", lambda _: self._show_page("library"))
        self.back_btn.set_visible(False)
        self.header.pack_start(self.back_btn)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, vexpand=True)

        sidebar = self._build_sidebar()
        main_box.append(sidebar)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)

        self.lib_page = self._build_library_page()
        self.settings_page = self._build_settings_page()
        self.help_page = self._build_help_page()

        self.stack.add_titled(self.lib_page, "library", "Library")
        self.stack.add_titled(self.settings_page, "settings", "Settings")
        self.stack.add_titled(self.help_page, "help", "Help")

        main_box.append(self.stack)

        footer = self._build_footer()
        root.append(main_box)
        root.append(footer)

        self.win.set_child(root)

        first_row = self.nav_list.get_row_at_index(0)
        if first_row:
            self.nav_list.select_row(first_row)

        self._populate()

        current = self.cfg.get("current")
        if current:
            self.header_title.set_subtitle(f"Active: {Path(current).name}")

        self.win.present()
        check_for_updates(self._on_update_available)

    def _build_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(240, -1)
        sidebar.add_css_class("sidebar")

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_box.add_css_class("sidebar-title")
        title_lbl = Gtk.Label(label="Papyrus")
        title_lbl.add_css_class("window-title")
        subtitle_lbl = Gtk.Label(label="Wallpaper Manager")
        subtitle_lbl.add_css_class("status-label")
        subtitle_lbl.add_css_class("sidebar-subtitle")
        title_box.append(title_lbl)
        title_box.append(subtitle_lbl)
        sidebar.append(title_box)

        nav_list = Gtk.ListBox()
        nav_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        nav_list.add_css_class("nav-list")

        lib_row = self._make_nav_row("library", "Library")
        nav_list.append(lib_row)
        set_row = self._make_nav_row("settings", "Settings")
        nav_list.append(set_row)
        help_row = self._make_nav_row("help", "Help")
        nav_list.append(help_row)

        nav_list.connect("row-selected", self._on_nav_selected)
        self.nav_list = nav_list
        sidebar.append(nav_list)

        engine_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        engine_box.set_vexpand(True)
        engine_box.set_valign(Gtk.Align.END)
        engine_box.set_margin_top(16)
        engine_box.set_margin_bottom(8)

        engine_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        engine_inner.add_css_class("engine-status")
        engine_lbl = Gtk.Label(label="ENGINE STATUS")
        engine_lbl.add_css_class("status-label")
        engine_lbl.set_halign(Gtk.Align.START)
        engine_inner.append(engine_lbl)

        status_box = Gtk.Box(spacing=8)
        status_box.set_halign(Gtk.Align.START)
        dot = Gtk.Box()
        dot.set_size_request(8, 8)
        dot.add_css_class("engine-dot")
        status_box.append(dot)
        status_lbl = Gtk.Label(label="Active: mpv-gl")
        status_lbl.add_css_class("control-label")
        status_box.append(status_lbl)
        engine_inner.append(status_box)

        engine_box.append(engine_inner)
        sidebar.append(engine_box)

        return sidebar

    def _make_nav_row(self, page_name, label_text):
        box = Gtk.Box(spacing=12)
        icon_name = "emblem-photos-symbolic" if page_name == "library" else \
                    "preferences-system-symbolic" if page_name == "settings" else \
                    "help-browser-symbolic"
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        icon.add_css_class("nav-icon")
        box.append(icon)
        label = Gtk.Label(label=label_text)
        label.add_css_class("nav-label")
        box.append(label)
        row = Gtk.ListBoxRow()
        row.set_child(box)
        row.add_css_class("nav-row")
        row._page_name = page_name
        return row

    def _on_nav_selected(self, listbox, row):
        if row is None:
            return
        page = row._page_name
        self._current_page = page
        self.stack.set_visible_child_name(page)
        self._update_header_for_page(page)

    def _build_library_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.banner = Adw.Banner(title="No wallpaper active", revealed=True)
        outer.append(self.banner)

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)

        self.flow = Gtk.FlowBox(
            valign=Gtk.Align.START,
            max_children_per_line=6,
            selection_mode=Gtk.SelectionMode.SINGLE,
            column_spacing=12, row_spacing=12,
        )
        self.flow.connect("child-activated", self._on_activated)

        self.content_box.append(self.flow)
        scroll.set_child(self.content_box)
        outer.append(scroll)

        return outer

    def _build_settings_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)
        page.set_halign(Gtk.Align.CENTER)
        page.set_size_request(720, -1)

        # General section
        gen_title = Gtk.Label(label="General")
        gen_title.add_css_class("settings-section-title")
        gen_title.set_halign(Gtk.Align.START)
        page.append(gen_title)

        gen_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        gen_box.add_css_class("settings-group-container")

        # Start on Login row
        login_box = Gtk.Box(spacing=16)
        login_box.add_css_class("settings-row")
        login_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        login_lbl = Gtk.Label(label="Start on Login", xalign=0)
        login_lbl.add_css_class("control-label")
        login_desc = Gtk.Label(label="Automatically launch Papyrus when you log in to your desktop.", xalign=0, wrap=True)
        login_desc.add_css_class("status-label")
        login_desc.add_css_class("settings-desc")
        login_text.append(login_lbl)
        login_text.append(login_desc)
        login_box.append(login_text)

        self.autostart_sw = Gtk.Switch(active=AUTOSTART.exists())
        self.autostart_sw.set_valign(Gtk.Align.CENTER)
        self.autostart_sw.connect("notify::active", self._on_autostart)
        login_box.append(self.autostart_sw)

        gen_box.append(login_box)

        # Display Output row
        out_box = Gtk.Box(spacing=16)
        out_box.add_css_class("settings-row")
        out_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        out_lbl = Gtk.Label(label="Display Output", xalign=0)
        out_lbl.add_css_class("control-label")
        out_desc = Gtk.Label(label="Choose which monitor displays the animated wallpaper.", xalign=0, wrap=True)
        out_desc.add_css_class("status-label")
        out_desc.add_css_class("settings-desc")
        out_text.append(out_lbl)
        out_text.append(out_desc)
        out_box.append(out_text)

        output_options = ["All Monitors", "DP-1 (Primary)", "HDMI-1", "eDP-1"]
        self.output_dropdown = Gtk.DropDown.new_from_strings(output_options)
        try:
            idx = output_options.index(next(o for o in output_options if self.output in o or (self.output == "*" and o == "All Monitors")))
        except (StopIteration, ValueError):
            idx = 0
        self.output_dropdown.set_selected(idx)
        self.output_dropdown.set_valign(Gtk.Align.CENTER)
        self.output_dropdown.connect("notify::selected", self._on_output_changed)
        out_box.append(self.output_dropdown)

        gen_box.append(out_box)
        page.append(gen_box)

        page.append(Gtk.Label(label="", margin_top=32))

        # Integration section
        int_title = Gtk.Label(label="Integration")
        int_title.add_css_class("settings-section-title")
        int_title.set_halign(Gtk.Align.START)
        page.append(int_title)

        int_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Auto-theme COSMIC row
        theme_box = Gtk.Box(spacing=16)
        theme_box.add_css_class("settings-row")
        theme_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, margin_end=32)
        theme_lbl = Gtk.Label(label="Auto-theme COSMIC", xalign=0)
        theme_lbl.add_css_class("control-label")
        theme_desc = Gtk.Label(label="Sync system accent colors with the dominant color of the active wallpaper.", xalign=0, wrap=True)
        theme_desc.add_css_class("status-label")
        theme_desc.add_css_class("settings-desc")
        theme_text.append(theme_lbl)
        theme_text.append(theme_desc)
        theme_box.append(theme_text)

        self.theme_sw = Gtk.Switch(active=self.cfg.get("auto_theme", False))
        self.theme_sw.set_valign(Gtk.Align.CENTER)
        self.theme_sw.connect("notify::active", self._on_theme_toggle)
        theme_box.append(self.theme_sw)

        int_box.append(theme_box)

        # Auto Dark/Light Mode row
        dark_box = Gtk.Box(spacing=16)
        dark_box.add_css_class("settings-row")
        dark_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        dark_lbl = Gtk.Label(label="Auto Dark/Light Mode", xalign=0)
        dark_lbl.add_css_class("control-label")
        dark_desc = Gtk.Label(label="Switch system theme based on wallpaper brightness.", xalign=0, wrap=True)
        dark_desc.add_css_class("status-label")
        dark_desc.add_css_class("settings-desc")
        dark_text.append(dark_lbl)
        dark_text.append(dark_desc)
        dark_box.append(dark_text)

        self.dark_sw = Gtk.Switch(active=self.cfg.get("auto_dark", True))
        self.dark_sw.set_valign(Gtk.Align.CENTER)
        self.dark_sw.connect("notify::active", self._on_dark_toggle)
        dark_box.append(self.dark_sw)

        int_box.append(dark_box)
        page.append(int_box)

        # Folder management section
        page.append(Gtk.Label(label="", margin_top=32))

        folder_title = Gtk.Label(label="Managed Directories")
        folder_title.add_css_class("settings-section-title")
        folder_title.set_halign(Gtk.Align.START)
        page.append(folder_title)

        self.folder_list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.folder_list_box.add_css_class("settings-row")
        page.append(self.folder_list_box)

        add_folder_btn = Gtk.Button(label="Add Folder")
        add_folder_btn.add_css_class("primary-btn")
        add_folder_btn.set_halign(Gtk.Align.CENTER)
        add_folder_btn.set_margin_top(16)
        add_folder_btn.connect("clicked", self._add_folder)
        page.append(add_folder_btn)

        scroll.set_child(page)
        outer.append(scroll)

        return outer

    def _build_help_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)
        page.set_halign(Gtk.Align.CENTER)
        page.set_size_request(600, -1)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        info_box.add_css_class("settings-row")

        app_name = Gtk.Label(label=f"Papyrus v{VERSION}", xalign=0)
        app_name.add_css_class("window-title")
        info_box.append(app_name)

        desc = Gtk.Label(
            label="Animated wallpaper picker for Pop!_OS COSMIC.\nUses mpvpaper under the hood. No metadata, no telemetry, no accounts.",
            xalign=0, wrap=True
        )
        desc.add_css_class("body-base")
        info_box.append(desc)
        page.append(info_box)

        links_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        links_box.add_css_class("settings-row")

        release_btn = Gtk.Button(label="Check for Updates")
        release_btn.add_css_class("primary-btn")
        release_btn.set_halign(Gtk.Align.START)
        release_btn.connect("clicked", lambda _: self._open_releases())
        links_box.append(release_btn)

        doc_btn = Gtk.Button(label="View Documentation")
        doc_btn.add_css_class("primary-btn")
        doc_btn.set_halign(Gtk.Align.START)
        doc_btn.connect("clicked", lambda _: subprocess.Popen(["xdg-open", RELEASES_URL]))
        links_box.append(doc_btn)

        page.append(links_box)

        scroll.set_child(page)
        outer.append(scroll)
        return outer

    def _build_footer(self):
        footer = Gtk.Box(spacing=0)
        footer.add_css_class("footer-bar")
        footer.set_size_request(-1, 32)

        left = Gtk.Box(spacing=16)
        left.set_halign(Gtk.Align.START)
        left.set_hexpand(True)

        cosmic_lbl = Gtk.Label(label="COSMIC Desktop Integration")
        cosmic_lbl.add_css_class("status-label")
        left.append(cosmic_lbl)

        sep = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        sep.set_size_request(1, 12)
        left.append(sep)

        self.monitor_lbl = Gtk.Label(label=f"Output: {self.output}")
        self.monitor_lbl.add_css_class("status-label")
        left.append(self.monitor_lbl)

        footer.append(left)

        right = Gtk.Box(spacing=16)
        right.set_halign(Gtk.Align.END)

        doc_link = Gtk.Label(label="Documentation")
        doc_link.add_css_class("footer-link")
        doc_link.add_css_class("status-label")
        right.append(doc_link)

        source_link = Gtk.Label(label="Source Code")
        source_link.add_css_class("footer-link")
        source_link.add_css_class("status-label")
        right.append(source_link)

        footer.append(right)
        return footer

    def _build_detail_page(self, path_obj):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)
        content.set_halign(Gtk.Align.CENTER)

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        card.set_size_request(800, -1)
        card.add_css_class("detail-card")

        # Preview area
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        preview_box.set_hexpand(True)
        preview_box.add_css_class("detail-sidebar")

        thumb_path = get_thumb_large(path_obj)
        pic = Gtk.Picture.new_for_filename(str(thumb_path)) if thumb_path.exists() else Gtk.Picture()
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(500, 350)
        preview_box.append(pic)
        card.append(preview_box)

        # Sidebar
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        sidebar.set_size_request(240, -1)
        sidebar.add_css_class("detail-sidebar")
        sidebar.set_margin_start(1)

        name_lbl = Gtk.Label(label=path_obj.stem, xalign=0, wrap=True)
        name_lbl.add_css_class("window-title")
        sidebar.append(name_lbl)

        subtitle_lbl = Gtk.Label(label="Animated Video Wallpaper", xalign=0)
        subtitle_lbl.add_css_class("control-label")
        sidebar.append(subtitle_lbl)

        # Resolution / Size
        metrics = Gtk.Box(spacing=8)
        res_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        res_box.add_css_class("settings-row")
        res_box.set_hexpand(True)
        res_hdr = Gtk.Label(label="RESOLUTION", xalign=0)
        res_hdr.add_css_class("status-label")
        res_box.append(res_hdr)
        res_val = Gtk.Label(label="1920 × 1080", xalign=0)
        res_val.add_css_class("control-label")
        res_box.append(res_val)
        metrics.append(res_box)

        size_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        size_box.add_css_class("settings-row")
        size_box.set_hexpand(True)
        size_hdr = Gtk.Label(label="FILE SIZE", xalign=0)
        size_hdr.add_css_class("status-label")
        size_box.append(size_hdr)
        try:
            sz = path_obj.stat().st_size
            sz_str = f"{sz / 1024 / 1024:.1f} MB" if sz > 1024*1024 else f"{sz / 1024:.0f} KB"
        except OSError:
            sz_str = "Unknown"
        size_val = Gtk.Label(label=sz_str, xalign=0)
        size_val.add_css_class("control-label")
        size_box.append(size_val)
        metrics.append(size_box)
        sidebar.append(metrics)

        # Apply button
        apply_btn = Gtk.Button(label="Apply Wallpaper")
        apply_btn.add_css_class("primary-btn")
        apply_btn.set_halign(Gtk.Align.FILL)
        apply_btn.connect("clicked", lambda _: self._apply(str(path_obj)))
        sidebar.append(apply_btn)

        # Back to library
        back_lib_btn = Gtk.Button(label="Back to Library")
        back_lib_btn.add_css_class("header-btn")
        back_lib_btn.set_halign(Gtk.Align.FILL)
        back_lib_btn.connect("clicked", lambda _: self._show_page("library"))
        sidebar.append(back_lib_btn)

        card.append(sidebar)
        content.append(card)

        # Navigation hint
        hint = Gtk.Label(label="Use arrow keys to navigate gallery")
        hint.add_css_class("status-label")
        hint.set_margin_top(24)
        hint.set_opacity(0.6)
        content.append(hint)

        scroll.set_child(content)
        page.append(scroll)

        return page

    def _update_header_for_page(self, page, detail_name=None):
        if page == "library":
            self.header_title.set_title("Library")
            self.add_btn.set_visible(True)
            self.stop_btn.set_visible(True)
            self.back_btn.set_visible(False)
            videos = scan_videos(self.cfg.get("dirs", [str(d) for d in DEFAULT_DIRS]))
            self.header_title.set_subtitle(f"{len(videos)} items found")
        elif page == "settings":
            self.header_title.set_title("Settings")
            self.header_title.set_subtitle("")
            self.add_btn.set_visible(True)
            self.stop_btn.set_visible(True)
            self.back_btn.set_visible(False)
        elif page == "help":
            self.header_title.set_title("Help")
            self.header_title.set_subtitle("")
            self.add_btn.set_visible(False)
            self.stop_btn.set_visible(False)
            self.back_btn.set_visible(False)
        elif page == "detail" and detail_name:
            self.header_title.set_title(detail_name)
            self.header_title.set_subtitle("")
            self.add_btn.set_visible(False)
            self.stop_btn.set_visible(True)
            self.back_btn.set_visible(True)

    def _show_page(self, name):
        self._current_page = name
        self.stack.set_visible_child_name(name)
        self._update_header_for_page(name)
        if name in ("library", "settings", "help") and self.nav_list:
            idx = {"library": 0, "settings": 1, "help": 2}[name]
            row = self.nav_list.get_row_at_index(idx)
            if row:
                self.nav_list.select_row(row)

    def _populate(self):
        while child := self.flow.get_first_child():
            self.flow.remove(child)

        self._refresh_folder_list()

        videos = scan_videos(self.cfg.get("dirs", [str(d) for d in DEFAULT_DIRS]))
        current = self.cfg.get("current")

        self.header_title.set_subtitle(f"{len(videos)} items found")

        if not videos:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                margin_top=80)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.add_css_class("empty-state")
            icon = Gtk.Image.new_from_icon_name("emblem-photos-symbolic")
            icon.set_pixel_size(48)
            empty_box.append(icon)
            lbl = Gtk.Label(
                label="No video files found.\nClick the folder button above to add a folder.",
                justify=Gtk.Justification.CENTER,
            )
            lbl.add_css_class("control-label")
            empty_box.append(lbl)
            self.flow.append(empty_box)
            return

        for v in videos:
            self.flow.append(self._make_card(v, active=str(v) == current))

    def _refresh_folder_list(self):
        while child := self.folder_list_box.get_first_child():
            self.folder_list_box.remove(child)

        dirs = self.cfg.get("dirs", [str(d) for d in DEFAULT_DIRS])
        for d in dirs:
            row = Gtk.Box(spacing=16)
            row.add_css_class("folder-entry")

            icon_box = Gtk.CenterBox()
            icon_box.add_css_class("folder-icon")
            icon_box.set_size_request(40, 40)
            icon_box.set_valign(Gtk.Align.CENTER)
            folder_icon = Gtk.Image.new_from_icon_name("folder-symbolic")
            folder_icon.set_pixel_size(20)
            icon_box.set_center_widget(folder_icon)
            row.append(icon_box)

            text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
            path_lbl = Gtk.Label(label=d, xalign=0, ellipsize=3)
            path_lbl.add_css_class("control-label")
            text_box.append(path_lbl)

            count = len([f for f in Path(d).iterdir() if f.suffix.lower() in VIDEO_EXTS]) if Path(d).exists() else 0
            detail_lbl = Gtk.Label(label=f"{count} items detected", xalign=0)
            detail_lbl.add_css_class("status-label")
            text_box.append(detail_lbl)
            row.append(text_box)

            del_btn = Gtk.Button()
            del_btn.set_icon_name("user-trash-symbolic")
            del_btn.add_css_class("folder-delete-btn")
            del_btn.set_tooltip_text("Remove folder")
            del_btn._dir = d
            del_btn.connect("clicked", self._remove_folder)
            row.append(del_btn)

            self.folder_list_box.append(row)

    def _remove_folder(self, btn):
        d = btn._dir
        dirs = self.cfg.get("dirs", [])
        if d in dirs:
            dirs.remove(d)
            self.cfg["dirs"] = dirs
            save_config(self.cfg)
            self._refresh_folder_list()
            self._populate()

    def _make_card(self, path: Path, active=False):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_size_request(160, -1)
        outer._video_path = str(path)

        thumb_box = Gtk.Box()
        thumb_box.set_size_request(-1, 100)
        thumb_box.set_hexpand(True)
        thumb_box.add_css_class("wallpaper-card")

        if active:
            thumb_box.add_css_class("active")
            thumb_box.add_css_class("active-glow")

        thumb = get_thumb(path)
        if thumb.exists():
            pic = Gtk.Picture.new_for_filename(str(thumb))
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_hexpand(True)
            pic.set_vexpand(True)
            pic.add_css_class("card-thumb")
            thumb_box.append(pic)
        else:
            icon = Gtk.Image.new_from_icon_name("video-x-generic")
            icon.set_pixel_size(48)
            icon.set_halign(Gtk.Align.CENTER)
            icon.set_valign(Gtk.Align.CENTER)
            thumb_box.append(icon)

        outer.append(thumb_box)

        label_box = Gtk.Box(spacing=4)
        label_box.set_halign(Gtk.Align.START)

        if active:
            play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
            play_icon.set_pixel_size(14)
            label_box.append(play_icon)

        lbl = Gtk.Label(label=short_name(path), xalign=0, ellipsize=3)
        lbl.set_max_width_chars(18)
        lbl.add_css_class("card-title")
        if active:
            lbl.add_css_class("active-card-label")
        label_box.append(lbl)

        outer.append(label_box)
        outer.set_tooltip_text(path.name)
        return outer

    def _on_activated(self, _fb, child):
        inner = child.get_child()
        path = getattr(inner, "_video_path", None)
        if path:
            old = self.stack.get_child_by_name("detail")
            if old:
                self.stack.remove(old)
            path_obj = Path(path)
            detail_page = self._build_detail_page(path_obj)
            self.stack.add_titled(detail_page, "detail", "Detail")
            self.stack.set_visible_child_name("detail")
            self._update_header_for_page("detail", path_obj.name)

    def _update_header_info(self, text):
        pass

    def _apply(self, path: str):
        ok = apply_wallpaper(path, self.output)
        if not ok:
            self.banner.set_title("Failed to start mpvpaper")
            return
        self.cfg["current"] = path
        self.cfg["output"] = self.output
        save_config(self.cfg)

        thumb = get_thumb(Path(path))
        if self.cfg.get("auto_theme", False) and thumb.exists():
            ok = apply_cosmic_theme(thumb, self.cfg.get("auto_dark", True))
            status = f"Active: {Path(path).name}" + (" · theme applied" if ok else " · theme failed")
        else:
            status = f"Active: {Path(path).name}"

        self.banner.set_title(status)
        if self.autostart_sw.get_active():
            write_autostart(path, self.output)
        self._populate()
        self._show_page("library")

    def _stop(self, _btn):
        kill_mpvpaper()
        self.cfg["current"] = None
        save_config(self.cfg)
        remove_autostart()
        self.autostart_sw.set_active(False)
        self.banner.set_title("No wallpaper active")
        self._populate()

    def _on_autostart(self, sw, _param):
        current = self.cfg.get("current")
        if sw.get_active() and current:
            write_autostart(current, self.output)
        else:
            remove_autostart()

    def _on_theme_toggle(self, sw, _param):
        self.cfg["auto_theme"] = sw.get_active()
        save_config(self.cfg)

    def _on_dark_toggle(self, sw, _param):
        self.cfg["auto_dark"] = sw.get_active()
        save_config(self.cfg)

    def _on_output_changed(self, dd, _param):
        options = ["All Monitors", "DP-1 (Primary)", "HDMI-1", "eDP-1"]
        idx = dd.get_selected()
        selected = options[idx]
        mapping = {
            "All Monitors": "*",
            "DP-1 (Primary)": "DP-1",
            "HDMI-1": "HDMI-1",
            "eDP-1": "eDP-1",
        }
        self.output = mapping.get(selected, "*")
        self.cfg["output"] = self.output
        save_config(self.cfg)
        self.monitor_lbl.set_label(f"Output: {self.output}")

    def _add_folder(self, _btn):
        dialog = Gtk.FileDialog(title="Choose wallpaper folder")
        dialog.select_folder(self.win, None, self._folder_chosen)

    def _folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            path = folder.get_path()
            dirs = self.cfg.get("dirs", [])
            if path not in dirs:
                dirs.append(path)
            self.cfg["dirs"] = dirs
            save_config(self.cfg)
            self._populate()
            self._refresh_folder_list()
        except Exception:
            pass

    def _on_update_available(self, latest: str):
        self.banner.set_title(f"Update available: v{latest} — click to download")
        self.banner.set_button_label("Download")
        self.banner.connect("button-clicked", lambda _: self._open_releases())
        self.banner.set_revealed(True)

    def _open_releases(self):
        Gio.AppInfo.launch_default_for_uri(RELEASES_URL)

if __name__ == "__main__":
    if not shutil.which("mpvpaper") and not Path("/app/bin/mpvpaper").exists():
        print("mpvpaper not found. Install it first.")
        raise SystemExit(1)
    CWApp().run(None)

#!/usr/bin/env python3
"""
Papyrus — animated wallpaper picker for Pop!_OS COSMIC
Uses mpvpaper under the hood. No metadata, no telemetry, no accounts.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio

import subprocess
import json
import shutil
import threading
import urllib.request
from pathlib import Path
import os

# Force disable D-Bus service registration issues in Flatpak
os.environ["GIO_USE_VFS"] = "local"

# ── version ───────────────────────────────────────────────────────────────────
VERSION      = "1.0.1"
API_URL      = "https://api.github.com/repos/PSGtatitos/papyrus/releases/latest"
RELEASES_URL = "https://github.com/PSGtatitos/papyrus/releases/latest"

def check_for_updates(callback):
    """Check GitHub for a newer release in a background thread."""
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

# ── paths ─────────────────────────────────────────────────────────────────────
CONFIG_DIR    = Path.home() / ".config" / "papyrus"
CONFIG_FILE   = CONFIG_DIR / "config.json"
AUTOSTART     = Path.home() / ".config" / "autostart" / "papyrus.desktop"
DEFAULT_DIRS  = [Path.home() / "Wallpapers" / "Papyrus", Path.home() / "Downloads", Path.home() / "Videos", Path.home() / "Pictures"]
VIDEO_EXTS    = {".mp4", ".webm", ".mkv", ".avi", ".mov"}

# COSMIC compiled theme paths
COSMIC_DARK   = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Dark/v1"
COSMIC_LIGHT  = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Light/v1"
COSMIC_DARK_B = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Dark.Builder/v1"
COSMIC_LIGHT_B= Path.home() / ".config/cosmic/com.system76.CosmicTheme.Light.Builder/v1"
COSMIC_MODE   = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Mode/v1"

# ── config helpers ────────────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"current": None, "dirs": [str(d) for d in DEFAULT_DIRS], "output": "*", "auto_theme": True}

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

# ── mpvpaper helpers ──────────────────────────────────────────────────────────
def kill_mpvpaper():
    subprocess.run(["flatpak-spawn", "--host", "pkill", "-f", "mpvpaper"], capture_output=True)

def detect_output():
    for cmd in [["wlr-randr"], ["wayland-info"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            for line in r.stdout.splitlines():
                for token in line.split():
                    if any(token.startswith(p) for p in ("HDMI", "DP-", "eDP", "VGA")):
                        return token.strip("\"'")
        except Exception:
            pass
    return "*"

def apply_wallpaper(path: str, output: str):
    kill_mpvpaper()
    subprocess.Popen(
        ["flatpak-spawn", "--host", "mpvpaper", "-o", "loop", output, path],
        stdout=subprocess.DEVNULL,  
        stderr=subprocess.DEVNULL,
    )

def write_autostart(path: str, output: str):
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Papyrus\n"
        f'Exec=mpvpaper -o "loop" {output} {path}\n'
        "X-GNOME-Autostart-enabled=true\n"
    )

def remove_autostart():
    if AUTOSTART.exists():
        AUTOSTART.unlink()

# ── COSMIC theming ────────────────────────────────────────────────────────────
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
    path.write_text(f"""(
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
)""")

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

def apply_cosmic_theme(thumb_path):
    color, is_dark = extract_palette(thumb_path)
    if color is None:
        return False

    r, g, b = color
    print(f"[papyrus] accent: r={r:.3f} g={g:.3f} b={b:.3f} dark={is_dark}")

    target = COSMIC_DARK if is_dark else COSMIC_LIGHT
    target.mkdir(parents=True, exist_ok=True)
    write_accent(target / "accent", r, g, b)
    write_background(target / "background", r, g, b, is_dark)
    (target / "is_dark").write_text("true" if is_dark else "false")

    builder = COSMIC_DARK_B if is_dark else COSMIC_LIGHT_B
    builder.mkdir(parents=True, exist_ok=True)
    write_builder_accent(builder / "accent", r, g, b)

    COSMIC_MODE.mkdir(parents=True, exist_ok=True)
    (COSMIC_MODE / "is_dark").write_text("true" if is_dark else "false")
    (COSMIC_MODE / "auto_switch").write_text("false")

    return True

# ── video scanning ────────────────────────────────────────────────────────────
def scan_videos(dirs):
    videos = []
    for d in dirs:
        p = Path(d)
        if p.exists():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
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

def short_name(path: Path, n=22):
    s = path.stem
    return s[:n] + "\u2026" if len(s) > n else s

# ── app ───────────────────────────────────────────────────────────────────────
class CWApp(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.PSGtatitos.papyrus",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.set_inactivity_timeout(0)   # Helps with Flatpak D-Bus issues
        
        self.connect("activate", self._activate)
        self.cfg = load_config()
        self.output = self.cfg.get("output") or detect_output()

    def _activate(self, app):
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_title("Papyrus")
        self.win.set_default_size(720, 540)

        # ... (rest of your UI code remains exactly the same)
        hb = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Papyrus", subtitle="animated wallpapers via mpvpaper")
        hb.set_title_widget(title)

        add_btn = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Add folder")
        add_btn.connect("clicked", self._add_folder)
        hb.pack_start(add_btn)

        stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic", tooltip_text="Stop wallpaper")
        stop_btn.connect("clicked", self._stop)
        hb.pack_end(stop_btn)

        self.banner = Adw.Banner(title="No wallpaper active", revealed=True)

        self.flow = Gtk.FlowBox(
            valign=Gtk.Align.START,
            max_children_per_line=4,
            selection_mode=Gtk.SelectionMode.SINGLE,
            column_spacing=12, row_spacing=12,
            margin_top=16, margin_bottom=16,
            margin_start=16, margin_end=16,
        )
        self.flow.connect("child-activated", self._on_activated)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.flow)

        out_label = Gtk.Label(label=f"Output: {self.output}", hexpand=True, xalign=0, opacity=0.5)

        autostart_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        autostart_row.append(Gtk.Label(label="Start on login"))
        self.autostart_sw = Gtk.Switch(active=AUTOSTART.exists(), valign=Gtk.Align.CENTER)
        self.autostart_sw.connect("notify::active", self._on_autostart)
        autostart_row.append(self.autostart_sw)

        theme_row = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        theme_row.append(Gtk.Label(label="Auto-theme DE"))
        self.theme_sw = Gtk.Switch(active=self.cfg.get("auto_theme", True), valign=Gtk.Align.CENTER)
        self.theme_sw.connect("notify::active", self._on_theme_toggle)
        theme_row.append(self.theme_sw)

        bottom = Gtk.Box(spacing=16, margin_top=8, margin_bottom=12, margin_start=16, margin_end=16)
        bottom.append(out_label)
        bottom.append(theme_row)
        bottom.append(autostart_row)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(hb)
        root.append(self.banner)
        root.append(scroll)
        root.append(Gtk.Separator())
        root.append(bottom)

        self.win.set_content(root)
        self._populate()

        current = self.cfg.get("current")
        if current:
            self.banner.set_title(f"Active: {Path(current).name}")

        self.win.present()
        check_for_updates(self._on_update_available)

    # ... (all your other methods remain unchanged)
    def _populate(self):
        while child := self.flow.get_first_child():
            self.flow.remove(child)

        videos = scan_videos(self.cfg.get("dirs", [str(d) for d in DEFAULT_DIRS]))
        current = self.cfg.get("current")

        if not videos:
            lbl = Gtk.Label(
                label="No video files found.\nClick the folder button above to add a folder.",
                justify=Gtk.Justification.CENTER,
                margin_top=80, opacity=0.5,
            )
            self.flow.append(lbl)
            return

        for v in videos:
            self.flow.append(self._make_card(v, active=str(v) == current))

    def _make_card(self, path: Path, active=False):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_size_request(160, 128)
        box._video_path = str(path)

        thumb = get_thumb(path)
        if thumb.exists():
            pic = Gtk.Picture.new_for_filename(str(thumb))
            pic.set_size_request(160, 96)
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.add_css_class("card")
            box.append(pic)
        else:
            icon = Gtk.Image.new_from_icon_name("video-x-generic")
            icon.set_pixel_size(64)
            icon.set_size_request(160, 96)
            box.append(icon)

        lbl = Gtk.Label(label=short_name(path), max_width_chars=20)
        lbl.set_ellipsize(3)
        if active:
            lbl.add_css_class("accent")
            playing = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
            playing.add_css_class("accent")
            box.append(playing)

        box.append(lbl)
        box.set_tooltip_text(path.name)
        return box

    def _on_activated(self, _fb, child):
        inner = child.get_child()
        path = getattr(inner, "_video_path", None)
        if path:
            self._apply(path)

    def _apply(self, path: str):
        apply_wallpaper(path, self.output)
        self.cfg["current"] = path
        self.cfg["output"] = self.output
        save_config(self.cfg)

        thumb = get_thumb(Path(path))
        if self.cfg.get("auto_theme", True) and thumb.exists():
            ok = apply_cosmic_theme(thumb)
            status = f"Active: {Path(path).name}" + (" · theme applied" if ok else " · theme failed")
        else:
            status = f"Active: {Path(path).name}"

        self.banner.set_title(status)
        if self.autostart_sw.get_active():
            write_autostart(path, self.output)
        self._populate()

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

    def _add_folder(self, _btn):
        dialog = Gtk.FileDialog(title="Choose wallpaper folder")
        dialog.select_folder(self.win, None, self._folder_chosen)

    def _folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            path = folder.get_path()
            self.cfg["dirs"] = [path]
            save_config(self.cfg)
            self._populate()
        except Exception:
            pass

    def _on_update_available(self, latest: str):
        self.banner.set_title(f"Update available: v{latest} — click to download")
        self.banner.set_button_label("Download")
        self.banner.connect("button-clicked", lambda _: self._open_releases())
        self.banner.set_revealed(True)

    def _open_releases(self):
        import subprocess
        subprocess.Popen(["xdg-open", RELEASES_URL])

if __name__ == "__main__":
    if not shutil.which("mpvpaper"):
        print("mpvpaper not found. Install it first.")
        raise SystemExit(1)
    CWApp().run(None)
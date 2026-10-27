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
import shlex
import shutil
import threading
import signal
import random
import re
import urllib.request
import sys
import time
import fcntl
from datetime import datetime
from pathlib import Path
import os

VERSION      = "1.3.7"
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
                latest = data.get("tag_name", "").lstrip("v").split("-")[0].split("+")[0]
                if not latest:
                    return
                current = [int(x) for x in VERSION.split("-")[0].split("+")[0].split(".")]
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
IMAGE_EXTS    = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
WALLPAPER_EXTS = VIDEO_EXTS | IMAGE_EXTS

COSMIC_DARK   = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Dark/v1"
COSMIC_LIGHT  = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Light/v1"
COSMIC_DARK_B = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Dark.Builder/v1"
COSMIC_LIGHT_B= Path.home() / ".config/cosmic/com.system76.CosmicTheme.Light.Builder/v1"
COSMIC_MODE   = Path.home() / ".config/cosmic/com.system76.CosmicTheme.Mode/v1"
ROTATION_LOCK = CONFIG_DIR / "rotation.lock"
SMART_PAUSE_LOCK = CONFIG_DIR / "smart-pause.lock"

def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"current": None, "wallpapers": {}, "dirs": [str(d) for d in DEFAULT_DIRS], "output": "*",
            "scaling": {}, "auto_theme": False, "rotation": False, "interval": 30, "order": "random",
            "frosted_glass": True, "glass_blur": 18,
            "backdrop_source": "wallpaper", "backdrop_custom": None,
            "smart_pause": False,
            "seq_index": 0, "last_output_idx": 0, "last_scaling_idx": 0}

def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

_mpvpaper_pids = {}  # output → pid

def discover_mpvpaper_pids():
    """Re-register mpvpaper PIDs (and their output→path mapping) after app restart."""
    global _mpvpaper_pids
    _mpvpaper_pids = {}
    running = {}
    for pid_dir in os.listdir("/proc"):
        if not pid_dir.isdigit():
            continue
        try:
            with open(f"/proc/{pid_dir}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        decoded = [a.decode(errors="ignore") for a in args if a]
        if not decoded:
            continue
        # mpvpaper can be launched directly or, in Flatpak, through
        # `flatpak-spawn --host mpvpaper ...`. Find the mpvpaper token instead
        # of trusting argv[0], so running wallpapers are still tracked/stopped
        # after the app restarts or was started by the store/portal.
        try:
            mpv_idx = next(i for i, a in enumerate(decoded)
                           if os.path.basename(a) in ("mpvpaper", "mpvpaper-holder"))
        except StopIteration:
            continue
        tail = decoded[mpv_idx + 1:]
        # Expected shape: ["-o", "<opts>", "<output>", "<path>"] (opts optional).
        if len(tail) >= 3:
            output = tail[-2]
            path = tail[-1]
            _mpvpaper_pids[output] = int(pid_dir)
            running[output] = path
    return running

def kill_mpvpaper(output=None):
    def resume_and_stop(pid):
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    if output:
        pid = _mpvpaper_pids.pop(output, None)
        if pid:
            resume_and_stop(pid)
    else:
        discover_mpvpaper_pids()
        for pid in list(_mpvpaper_pids.values()):
            resume_and_stop(pid)
        _mpvpaper_pids.clear()
        # Also kill any mpvpaper started before this app session (e.g. from
        # a previous launch) so "Stop" always stops every wallpaper.
        try:
            if Path("/app/bin/mpvpaper").exists():
                subprocess.run(["flatpak-spawn", "--host", "pkill", "-CONT", "-x", "mpvpaper"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["flatpak-spawn", "--host", "pkill", "-x", "mpvpaper"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["pkill", "-CONT", "-x", "mpvpaper"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["pkill", "-x", "mpvpaper"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def _mpvpaper_cmd(output, path, scaling="fit"):
    # --no-config: mpvpaper renders a wallpaper, not a regular player window.
    # A user's ~/.config/mpv/mpv.conf can otherwise cause a black/blank image
    # (e.g. a broken vo, custom hwdec, or odd shaders). Command-line options
    # (loop-file=inf, --no-audio, scaling) still apply.
    opts = "loop-file=inf --no-audio --no-config"
    if scaling == "fill":
        opts += " --panscan=1.0"
    elif scaling == "stretch":
        opts += " --no-keepaspect"
    if Path("/app/bin/mpvpaper").exists():
        return ["flatpak-spawn", "--host", "mpvpaper", "-o", opts, output, path]
    return ["mpvpaper", "-o", opts, output, path]

def detect_outputs():
    try:
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display:
            monitors = display.get_monitors()
            outs = []
            for i in range(monitors.get_n_items()):
                mon = monitors.get_item(i)
                if hasattr(mon, "get_connector") and mon.get_connector():
                    outs.append(mon.get_connector())
            if outs:
                return outs
    except Exception as e:
        print(f"[papyrus] Native Gdk display detection failed: {e}")

    for cmd in [["wlr-randr"], ["wayland-info"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if r.returncode != 0:
                continue
            outs = []
            for line in r.stdout.splitlines():
                if cmd[0] == "wlr-randr" and " connected" in line:
                    outs.append(line.split()[0])
            if outs:
                return outs
        except Exception:
            continue

    return ["*"]

def detect_smart_pause_backend():
    """Return a compositor with a usable window-state query, if available."""
    if IN_FLATPAK:
        return None
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if shutil.which("hyprctl") and (
        os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or "hyprland" in desktop
    ):
        return "hyprland"
    if shutil.which("swaymsg") and (
        os.environ.get("SWAYSOCK") or "sway" in desktop
    ):
        return "sway"
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if (session_type == "x11" or
            (not os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"))):
        if all(shutil.which(tool) for tool in ("wmctrl", "xprop", "xrandr")):
            return "x11"
    return None

def smart_pause_backend_name(backend=None):
    backend = backend or detect_smart_pause_backend()
    return {
        "sway": "Sway",
        "hyprland": "Hyprland",
        "x11": "X11 desktops with EWMH and wmctrl support",
    }.get(backend)

def _read_command_json(command):
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=2
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "window-state query failed")
    return json.loads(result.stdout)

def _rect_covers_monitor(windows, monitor):
    """Return true only when visible window rectangles cover the whole output."""
    mx, my, mw, mh = monitor
    if mw <= 0 or mh <= 0:
        return False
    right, bottom = mx + mw, my + mh
    clipped = []
    xs = {mx, right}
    for rect in windows:
        if not rect or len(rect) != 4:
            continue
        x, y, width, height = rect
        left = max(mx, x)
        top = max(my, y)
        r = min(right, x + width)
        b = min(bottom, y + height)
        if r <= left or b <= top:
            continue
        clipped.append((left, top, r, b))
        xs.add(left)
        xs.add(r)

    edges = sorted(xs)
    for left, right_edge in zip(edges, edges[1:]):
        if right_edge <= left:
            continue
        midpoint = (left + right_edge) / 2
        spans = sorted(
            (top, bottom_edge)
            for x1, top, x2, bottom_edge in clipped
            if x1 <= midpoint < x2
        )
        covered_to = my
        for top, bottom_edge in spans:
            if top > covered_to:
                break
            covered_to = max(covered_to, bottom_edge)
            if covered_to >= bottom:
                break
        if covered_to < bottom:
            return False
    return True

def _sway_covered_outputs():
    tree = _read_command_json(["swaymsg", "-r", "-t", "get_tree"])
    all_outputs, covered_outputs = {}, set()

    def collect(node, rectangles, full_screen):
        node_type = node.get("type")
        if node_type == "workspace" and not node.get("visible", False):
            return
        if node.get("fullscreen_mode", 0):
            full_screen[0] = True
        children = node.get("nodes", []) + node.get("floating_nodes", [])
        if node_type in ("con", "floating_con") and not children:
            rect = node.get("rect", {})
            if rect.get("width", 0) and rect.get("height", 0):
                rectangles.append((rect.get("x", 0), rect.get("y", 0),
                                   rect["width"], rect["height"]))
        for child in children:
            collect(child, rectangles, full_screen)

    for output in tree.get("nodes", []):
        if output.get("type") != "output" or not output.get("active", True):
            continue
        name = output.get("name")
        rect = output.get("rect", {})
        if not name or not rect.get("width") or not rect.get("height"):
            continue
        bounds = (rect.get("x", 0), rect.get("y", 0), rect["width"], rect["height"])
        all_outputs[name] = bounds
        rectangles, full_screen = [], [False]
        for workspace in output.get("nodes", []):
            collect(workspace, rectangles, full_screen)
        if full_screen[0] or _rect_covers_monitor(rectangles, bounds):
            covered_outputs.add(name)
    return all_outputs, covered_outputs

def _hyprland_covered_outputs():
    monitors = _read_command_json(["hyprctl", "-j", "monitors"])
    clients = _read_command_json(["hyprctl", "-j", "clients"])
    all_outputs, covered_outputs = {}, set()
    for monitor in monitors:
        if monitor.get("disabled"):
            continue
        name = monitor.get("name")
        bounds = (monitor.get("x", 0), monitor.get("y", 0),
                  monitor.get("width", 0), monitor.get("height", 0))
        if not name or bounds[2] <= 0 or bounds[3] <= 0:
            continue
        all_outputs[name] = bounds
        active_workspace = (monitor.get("activeWorkspace") or {}).get("id")
        rectangles, full_screen = [], False
        for client in clients:
            if client.get("monitor") != monitor.get("id"):
                continue
            if client.get("hidden") or client.get("mapped") is False:
                continue
            workspace = client.get("workspace") or {}
            if not client.get("pinned") and active_workspace is not None \
                    and workspace.get("id") != active_workspace:
                continue
            fullscreen = client.get("fullscreen", 0)
            if fullscreen == 2:
                full_screen = True
            at = client.get("at", [])
            size = client.get("size", [])
            if len(at) >= 2 and len(size) >= 2:
                rectangles.append((at[0], at[1], size[0], size[1]))
        if full_screen or _rect_covers_monitor(rectangles, bounds):
            covered_outputs.add(name)
    return all_outputs, covered_outputs

def _x11_covered_outputs():
    """Use EWMH/X11 window properties to detect windows covering each output."""
    root = subprocess.run(
        ["xprop", "-root", "_NET_CURRENT_DESKTOP"],
        capture_output=True, text=True, timeout=3, check=True,
    ).stdout
    desktop_match = re.search(r"_NET_CURRENT_DESKTOP\([^)]*\)\s*=\s*(\d+)", root)
    if not desktop_match:
        raise RuntimeError("The X11 window manager does not expose the current EWMH desktop")
    current_desktop = int(desktop_match.group(1))
    windows_result = subprocess.run(
        ["wmctrl", "-lG"], capture_output=True, text=True, timeout=3, check=True,
    )

    monitor_result = subprocess.run(
        ["xrandr", "--listmonitors"], capture_output=True, text=True,
        timeout=3, check=True,
    )
    all_outputs = {}
    monitor_re = re.compile(
        r"^\s*\d+:\s+\S+\s+(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)\s+(\S+)"
    )
    for line in monitor_result.stdout.splitlines():
        match = monitor_re.match(line)
        if not match:
            continue
        width, height, x, y, name = match.groups()
        all_outputs[name] = (int(x), int(y), int(width), int(height))
    if not all_outputs:
        raise RuntimeError("XRandR did not report monitor geometry")

    rectangles = []
    for line in windows_result.stdout.splitlines():
        fields = line.split(None, 7)
        if len(fields) < 7:
            continue
        try:
            desktop = int(fields[1], 0)
            x, y, width, height = map(int, fields[2:6])
        except ValueError:
            continue
        if (current_desktop is not None and
                desktop not in (current_desktop, -1, 0xFFFFFFFF)):
            continue
        if width > 0 and height > 0:
            rectangles.append((x, y, width, height))

    covered = {
        name for name, bounds in all_outputs.items()
        if _rect_covers_monitor(rectangles, bounds)
    }
    return all_outputs, covered

def get_smart_pause_covered_outputs(backend=None):
    backend = backend or detect_smart_pause_backend()
    if backend == "hyprland":
        return _hyprland_covered_outputs()
    if backend == "sway":
        return _sway_covered_outputs()
    if backend == "x11":
        return _x11_covered_outputs()
    return None

def start_smart_pause_daemon():
    if not detect_smart_pause_backend():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--smart-pause-daemon"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
    except Exception as e:
        print(f"[papyrus] failed to start smart-pause service: {e}")

def run_smart_pause_daemon():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = SMART_PAUSE_LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return

    paused = {}
    stop_requested = False

    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True

    old_term = signal.signal(signal.SIGTERM, request_stop)
    old_int = signal.signal(signal.SIGINT, request_stop)
    try:
        while not stop_requested:
            cfg = load_config()
            if not cfg.get("smart_pause", False):
                break
            try:
                snapshot = get_smart_pause_covered_outputs()
            except Exception as e:
                print(f"[papyrus] smart-pause state query failed: {e}")
                snapshot = None

            discover_mpvpaper_pids()
            processes = dict(_mpvpaper_pids)
            if snapshot is None:
                should_pause = {}
            else:
                active_outputs, covered = snapshot
                any_covered = bool(active_outputs) and bool(covered)
                should_pause = {
                    # A single wildcard mpvpaper process serves every monitor.
                    # Pause it when a fullscreen/covering window occupies any
                    # output, so fullscreen games on one monitor still save
                    # decode resources in the common all-monitors mode.
                    output: (any_covered if output == "*" else output in covered)
                    for output in processes
                }

            for output, pid in list(paused.items()):
                if processes.get(output) != pid or not should_pause.get(output, False):
                    try:
                        os.kill(pid, signal.SIGCONT)
                    except ProcessLookupError:
                        pass
                    paused.pop(output, None)

            for output, pid in processes.items():
                if should_pause.get(output, False) and paused.get(output) != pid:
                    try:
                        os.kill(pid, signal.SIGSTOP)
                        paused[output] = pid
                        print(f"[papyrus] smart-pause: paused {output} (fullscreen-or-covered)")
                    except ProcessLookupError:
                        pass
            time.sleep(1)
    finally:
        for pid in paused.values():
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)

def apply_wallpaper(path: str, output: str, scaling="fit"):
    # Re-discover first: the existing wallpaper may have been launched by the
    # login autostart script or a previous Papyrus session, not this process.
    # Registering it here lets kill_mpvpaper() replace it instead of creating a
    # second mpvpaper instance for the same output.
    discover_mpvpaper_pids()
    kill_mpvpaper(output)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = CONFIG_DIR / "mpvpaper.log"
    cmd = _mpvpaper_cmd(output, path, scaling)
    ts = datetime.now().isoformat()
    with log_file.open("a") as f:
        f.write(f"[{ts}] running: {' '.join(cmd)}\n")
    try:
        err_path = CONFIG_DIR / f"mpvpaper_{output}.log"
        err_fd = open(err_path, "w")
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err_fd,
        )
        def _cleanup(p=proc, fd=err_fd):
            p.wait()
            fd.close()
        threading.Thread(target=_cleanup, daemon=True).start()
    except Exception as e:
        msg = f"failed to start mpvpaper: {e}"
        ts = datetime.now().isoformat()
        with log_file.open("a") as f:
            f.write(f"[{ts}] {msg}\n")
        return None, msg

    _mpvpaper_pids[output] = proc.pid
    ts = datetime.now().isoformat()
    with log_file.open("a") as f:
        f.write(f"[{ts}] mpvpaper PID: {proc.pid} (output: {output})\n")

    return proc, None

def write_autostart_script(wallpapers: dict, scaling: dict) -> Path:
    script = CONFIG_DIR / "autostart.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#!/usr/bin/env bash", "set -e"]
    for output, path in wallpapers.items():
        sc = scaling.get(output, "fit")
        opts = "loop-file=inf --no-audio --no-config"
        if sc == "fill":
            opts += " --panscan=1.0"
        elif sc == "stretch":
            opts += " --no-keepaspect"
        # Quote both output and path. "All Monitors" uses output "*", which
        # shell glob expansion (notably on zsh) would otherwise turn into a
        # (non-existing) filename and break the command.
        out_q = shlex.quote(str(output))
        path_q = shlex.quote(str(path))
        if Path("/app/bin/mpvpaper").exists():
            lines.append(f'flatpak-spawn --host mpvpaper --fork -o "{opts}" {out_q} {path_q}')
        else:
            lines.append(f'mpvpaper --fork -o "{opts}" {out_q} {path_q}')
    if load_config().get("rotation", False):
        executable = shlex.quote(str(Path(__file__).resolve()))
        python = shlex.quote(sys.executable)
        lines.append(f"{python} {executable} --rotation-daemon &")
    if load_config().get("smart_pause", False) and detect_smart_pause_backend():
        executable = shlex.quote(str(Path(__file__).resolve()))
        python = shlex.quote(sys.executable)
        lines.append(f"{python} {executable} --smart-pause-daemon &")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return script

def write_autostart(wallpapers: dict, scaling: dict):
    if IN_FLATPAK or not wallpapers:
        return
    script = write_autostart_script(wallpapers, scaling)
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Papyrus\n"
        f"Exec={script}\n"
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

def scan_wallpapers(dirs):
    wallpapers = []
    for d in dirs:
        p = Path(d)
        if p.exists():
            for f in sorted(p.iterdir()):
                if f.is_file() and f.suffix.lower() in WALLPAPER_EXTS:
                    wallpapers.append(f)
    return wallpapers

def start_rotation_daemon():
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--rotation-daemon"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )
    except Exception as e:
        print(f"[papyrus] failed to start rotation service: {e}")

def run_rotation_daemon():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock = ROTATION_LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return

    elapsed = 0
    while True:
        cfg = load_config()
        if not cfg.get("rotation", False):
            return
        if not cfg.get("current") and not cfg.get("wallpapers"):
            return
        interval = max(int(cfg.get("interval", 30)), 1) * 60
        if elapsed < interval:
            time.sleep(1)
            elapsed += 1
            continue

        files = sorted(scan_wallpapers(cfg.get("dirs", [str(d) for d in DEFAULT_DIRS])), key=lambda p: str(p))
        if files:
            order = cfg.get("order", "random")
            index = int(cfg.get("seq_index", 0))
            current = cfg.get("current") or next(iter((cfg.get("wallpapers", {}) or {}).values()), None)
            candidates = [path for path in files if str(path) != current] or files
            if order == "random":
                selected = random.choice(candidates)
            else:
                selected = files[index % len(files)]
                if str(selected) == current and len(files) > 1:
                    index = (index + 1) % len(files)
                    selected = files[index]
                cfg["seq_index"] = (index + 1) % len(files)
            output_map = cfg.get("wallpapers", {}) or {}
            outputs = list(output_map) or [cfg.get("output", "*")]
            scaling_map = cfg.get("scaling", {}) or {}
            for output in outputs:
                proc, err = apply_wallpaper(str(selected), output, scaling_map.get(output, "fit"))
                if err:
                    print(f"[papyrus] rotation service error on {output}: {err}")
                    continue
                output_map[output] = str(selected)
            cfg["wallpapers"] = output_map
            cfg["current"] = str(selected)
            save_config(cfg)
        elapsed = 0

def _make_image_thumbnail(path: Path, thumb: Path, width: int):
    """Create an image thumbnail without relying on ffmpeg's still-image handling."""
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            height = max(1, round(img.height * width / img.width))
            img.resize((width, height), Image.Resampling.LANCZOS).save(thumb, "JPEG")
        return True
    except Exception as e:
        print(f"[papyrus] image thumbnail failed for {path}: {e}")
        return False

def get_thumb(path: Path) -> Path:
    thumb = CONFIG_DIR / "thumbs" / (path.stem[:80] + ".jpg")
    if not thumb.exists():
        thumb.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in IMAGE_EXTS:
            _make_image_thumbnail(path, thumb, 160)
            return thumb
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
        if path.suffix.lower() in IMAGE_EXTS:
            _make_image_thumbnail(path, thumb, 640)
            return thumb
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ss", "00:00:01",
             "-vframes", "1", "-vf", "scale=640:-1", str(thumb)],
            capture_output=True,
        )
    return thumb

def get_thumb_blurred(thumb: Path, radius=18) -> Path:
    """Return a cached, blurred copy of a wallpaper thumbnail for the app backdrop."""
    radius = max(0, min(40, int(radius)))
    if radius == 0:
        return thumb
    blurred = thumb.with_name(f"{thumb.stem}_blur_{radius}.jpg")
    try:
        if not thumb.exists():
            return thumb
        if blurred.exists() and blurred.stat().st_mtime >= thumb.stat().st_mtime:
            return blurred
        from PIL import Image, ImageFilter
        with Image.open(thumb) as image:
            image.convert("RGB").filter(ImageFilter.GaussianBlur(radius)).save(
                blurred, "JPEG", quality=82
            )
        return blurred
    except Exception as e:
        print(f"[papyrus] failed to generate blurred thumbnail {blurred}: {e}", file=sys.stderr)
        return thumb

def get_fallback_backdrop(radius=18) -> Path:
    """Create a soft, wallpaper-independent image for the frosted-glass UI."""
    fallback = CONFIG_DIR / "thumbs" / "papyrus_frosted_fallback_v2.jpg"
    if not fallback.exists():
        try:
            from PIL import Image, ImageDraw

            width, height = 960, 640
            image = Image.new("RGB", (width, height))
            pixels = image.load()
            top = (32, 39, 67)
            bottom = (75, 43, 82)
            for y in range(height):
                t = y / (height - 1)
                color = tuple(round(a * (1 - t) + b * t) for a, b in zip(top, bottom))
                for x in range(width):
                    pixels[x, y] = color

            shapes = Image.new("RGBA", (width, height))
            draw = ImageDraw.Draw(shapes)
            draw.ellipse((-220, -180, 470, 510), fill=(75, 145, 179, 180))
            draw.ellipse((430, 170, 1160, 900), fill=(174, 91, 150, 150))
            draw.ellipse((160, 300, 770, 910), fill=(90, 94, 173, 125))
            image = Image.alpha_composite(image.convert("RGBA"), shapes)
            fallback.parent.mkdir(parents=True, exist_ok=True)
            image.convert("RGB").save(fallback, "JPEG", quality=88)
        except Exception as e:
            print(f"[papyrus] fallback backdrop creation failed: {e}")
            return None
    return get_thumb_blurred(fallback, radius)

def get_video_resolution(path: Path) -> str:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
             str(path)],
            capture_output=True, text=True, timeout=5,
        )
        out = r.stdout.strip()
        if out and "x" in out:
            return out
    except Exception:
        pass
    return "Unknown"

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
    background-color: alpha(@surface-container-low, 0.62);
    border-right: 1px solid alpha(@outline-variant, 0.62);
    padding: 12px;
    box-shadow: 4px 0 20px alpha(black, 0.18);
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
    background-color: alpha(@surface, 0.62);
    border-bottom: 1px solid alpha(@outline-variant, 0.55);
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
    background-color: alpha(@surface-container, 0.72);
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
    border-top: 1px solid alpha(@outline-variant, 0.55);
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
    background: transparent;
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
    background-color: alpha(@surface-container, 0.72);
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
    background-color: alpha(@surface-container-low, 0.72);
    border: 1px solid alpha(@outline-variant, 0.55);
    border-radius: 12px;
    box-shadow: 0 12px 32px alpha(black, 0.24);
}
.detail-sidebar {
    background-color: alpha(@surface-container, 0.62);
}
.main-content {
    background-color: transparent;
}
.app-backdrop-tint {
    background-color: alpha(@surface-dim, 0.22);
}
.frosted-glass-off .sidebar { background-color: @surface-container-low; }
.frosted-glass-off .footer-bar { background-color: @surface; }
.frosted-glass-off .settings-row { background-color: @surface-container; }
.frosted-glass-off .main-content { background-color: @surface; }
.frosted-glass-off flowbox { background: @surface; }
.frosted-glass-off .engine-status { background-color: @surface-container; }
.frosted-glass-off .detail-card { background-color: @surface-container-low; }
.frosted-glass-off .detail-sidebar { background-color: @surface-container; }
.top-header.frosted-glass-off { background-color: @surface; }
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
    color: #000000;
    border-radius: 8px;
    padding: 8px 24px;
    font-weight: 700;
}
button.primary-btn,
button.primary-btn label {
    color: #000000;
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
        self.outputs = detect_outputs()
        self._selected_output = self.outputs[0]
        self._selected_scaling = "fit"
        for d in DEFAULT_DIRS:
            d.mkdir(parents=True, exist_ok=True)
        self._current_page = "library"
        self._rotation_source = None
        self._library_total = 0
        self._library_visible = 0

    def _ensure_icon_theme(self):
        # COSMIC / Pop!_OS ship an icon theme that reports having the Adwaita
        # symbolic icons via has_icon() but fails to actually render some of
        # them (e.g. preferences-system-symbolic, folder-open-symbolic), so the
        # Settings nav icon and the Add Folder button stay blank. has_icon() is
        # therefore unreliable. Select Adwaita through Gtk.Settings before
        # obtaining the display's singleton icon theme; that singleton cannot
        # be renamed directly. Diagnostics are written to papyrus.log.
        try:
            from gi.repository import Gdk
            import os
            display = Gdk.Display.get_default()
            if display is None:
                return
            settings = Gtk.Settings.get_for_display(display)
            before = settings.get_property("gtk-icon-theme-name")
            settings.set_property("gtk-icon-theme-name", "Adwaita")
            old_theme = Gtk.IconTheme.get_for_display(display)
            desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
            needed = [
                "emblem-photos-symbolic", "preferences-system-symbolic",
                "help-browser-symbolic", "media-playback-stop-symbolic",
                "media-playback-start-symbolic", "folder-symbolic",
                "folder-open-symbolic", "video-x-generic",
                "go-previous-symbolic", "user-trash-symbolic",
            ]
            missing = [n for n in needed if not old_theme.has_icon(n)]
            after = settings.get_property("gtk-icon-theme-name")
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                with (CONFIG_DIR / "papyrus.log").open("a") as f:
                    f.write(
                        f"[icon-theme] desktop={desktop!r} before={before!r} "
                        f"after={after!r} missing={missing}\n"
                    )
            except Exception:
                pass
        except Exception as e:
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                with (CONFIG_DIR / "papyrus.log").open("a") as f:
                    f.write(f"[icon-theme] error: {e}\n")
            except Exception:
                pass

    def _activate(self, app):
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        self._ensure_icon_theme()
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
        self.header.add_css_class("top-header")
        self.header_title = Adw.WindowTitle(title="Library", subtitle="")
        self.header.set_title_widget(self.header_title)
        self.header_backdrop = Gtk.Picture()
        self.header_backdrop.set_content_fit(Gtk.ContentFit.COVER)
        self.header_backdrop.set_can_shrink(True)
        self.header_backdrop.set_hexpand(True)
        self.header_backdrop.set_vexpand(False)
        self.header_backdrop.set_opacity(0.82)
        self.header_backdrop.set_can_target(False)
        self.titlebar_shell = Gtk.Overlay()
        titlebar_spacer = Gtk.Box()
        titlebar_spacer.set_size_request(1, 1)
        self.titlebar_shell.set_child(titlebar_spacer)
        self.titlebar_shell.add_overlay(self.header_backdrop)
        self.titlebar_shell.set_measure_overlay(self.header_backdrop, False)
        self.titlebar_shell.add_overlay(self.header)
        self.titlebar_shell.set_measure_overlay(self.header, True)
        self.win.set_titlebar(self.titlebar_shell)

        self.add_btn = Gtk.Button(tooltip_text="Add folder")
        self.add_btn.set_child(Gtk.Image.new_from_gicon(
            Gio.ThemedIcon.new_from_names(
                ["folder-open-symbolic", "folder-symbolic", "list-add-symbolic",
                 "document-open-symbolic"])))
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
        self.stack.add_css_class("main-content")
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)

        self.lib_page = self._build_library_page()
        self.settings_page = self._build_settings_page()
        self.help_page = self._build_help_page()
        self.discover_page = self._build_discover_page()

        self.stack.add_titled(self.lib_page, "library", "Library")
        self.stack.add_titled(self.settings_page, "settings", "Settings")
        self.stack.add_titled(self.help_page, "help", "Help")
        self.stack.add_titled(self.discover_page, "discover", "Find Wallpapers")

        main_box.append(self.stack)

        footer = self._build_footer()
        root.append(main_box)
        root.append(footer)

        self.app_backdrop = Gtk.Picture()
        self.app_backdrop.set_content_fit(Gtk.ContentFit.COVER)
        self.app_backdrop.set_can_shrink(True)
        self.app_backdrop.set_hexpand(True)
        self.app_backdrop.set_vexpand(True)
        self.app_shell = Gtk.Overlay()
        self.app_shell.set_child(self.app_backdrop)
        self.glass_tint = Gtk.Box()
        self.glass_tint.add_css_class("app-backdrop-tint")
        self.glass_tint.set_can_target(False)
        self.app_shell.add_overlay(self.glass_tint)
        self.app_shell.add_overlay(root)
        self.win.set_child(self.app_shell)

        first_row = self.nav_list.get_row_at_index(0)
        if first_row:
            self.nav_list.select_row(first_row)

        self._populate()

        wallpapers = self.cfg.get("wallpapers", {}) or {}
        running = discover_mpvpaper_pids()
        if running:
            self.cfg["wallpapers"] = running
            for out, path in running.items():
                sc_map = self.cfg.setdefault("scaling", {})
                sc_map.setdefault(out, "fit")
            self.cfg.setdefault("current", None)
        if self.cfg.get("smart_pause", False):
            start_smart_pause_daemon()
            save_config(self.cfg)
            wallpapers = running
        elif not wallpapers and self.cfg.get("current"):
            out = self.cfg.get("output", "*")
            wallpapers[out] = self.cfg["current"]
            self.cfg["wallpapers"] = wallpapers
            save_config(self.cfg)
        self._update_footer(wallpapers)
        self._set_app_backdrop(
            self.cfg.get("current") or next(iter(wallpapers.values()), None)
        )

        if self.cfg.get("rotation", False):
            self._start_rotation()

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
        discover_row = self._make_nav_row("discover", "Find Wallpapers")
        nav_list.append(discover_row)

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

        sidebar_overlay = Gtk.Overlay()
        sidebar_spacer = Gtk.Box()
        sidebar_spacer.set_size_request(1, 1)
        sidebar_overlay.set_child(sidebar_spacer)
        self.sidebar_backdrop = Gtk.Picture()
        self.sidebar_backdrop.set_content_fit(Gtk.ContentFit.COVER)
        self.sidebar_backdrop.set_can_shrink(True)
        self.sidebar_backdrop.set_hexpand(True)
        self.sidebar_backdrop.set_vexpand(True)
        self.sidebar_backdrop.set_can_target(False)
        sidebar_overlay.add_overlay(self.sidebar_backdrop)
        sidebar_overlay.set_measure_overlay(self.sidebar_backdrop, False)
        sidebar_overlay.add_overlay(sidebar)
        sidebar_overlay.set_measure_overlay(sidebar, True)
        return sidebar_overlay

    def _make_nav_row(self, page_name, label_text):
        box = Gtk.Box(spacing=12)
        fallbacks = {
            "library": ["emblem-photos-symbolic", "folder-pictures-symbolic",
                        "image-x-generic"],
            "settings": ["preferences-system-symbolic", "applications-system-symbolic",
                         "preferences-desktop-symbolic"],
            "help": ["help-browser-symbolic", "help-about-symbolic",
                     "dialog-question"],
            "discover": ["web-browser-symbolic", "internet-web-browser-symbolic"],
        }
        icon = Gtk.Image()
        icon.set_from_gicon(Gio.ThemedIcon.new_from_names(fallbacks.get(page_name, [])))
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

        self.library_controls = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_bottom=12
        )
        self.library_search = Gtk.SearchEntry(
            placeholder_text="Search wallpapers by name or folder…",
            hexpand=True,
        )
        self.library_search.connect("search-changed", self._on_library_controls_changed)
        self.library_controls.append(self.library_search)

        filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.library_type_filter = Gtk.DropDown.new_from_strings(
            ["All Types", "Videos", "Images"]
        )
        self.library_type_filter.set_hexpand(True)
        self.library_type_filter.connect(
            "notify::selected", self._on_library_controls_changed
        )
        filter_row.append(self.library_type_filter)

        self.library_status_filter = Gtk.DropDown.new_from_strings(
            ["All Wallpapers", "Active", "Inactive"]
        )
        self.library_status_filter.set_hexpand(True)
        self.library_status_filter.connect(
            "notify::selected", self._on_library_controls_changed
        )
        filter_row.append(self.library_status_filter)

        self.library_sort = Gtk.DropDown.new_from_strings(
            ["Name: A–Z", "Name: Z–A", "Newest", "Oldest", "Largest", "Smallest"]
        )
        self.library_sort.set_hexpand(True)
        self.library_sort.connect(
            "notify::selected", self._on_library_controls_changed
        )
        filter_row.append(self.library_sort)
        self.library_controls.append(filter_row)
        self.content_box.append(self.library_controls)

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

        # General section
        gen_title = Gtk.Label(label="General")
        gen_title.add_css_class("settings-section-title")
        gen_title.set_halign(Gtk.Align.START)
        page.append(gen_title)

        gen_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        gen_box.add_css_class("settings-group-container")

        # Frosted glass controls
        glass_box = Gtk.Box(spacing=16)
        glass_box.add_css_class("settings-row")
        glass_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        glass_lbl = Gtk.Label(label="Frosted Glass", xalign=0)
        glass_lbl.add_css_class("control-label")
        glass_desc = Gtk.Label(
            label="Show a blurred wallpaper behind the top bar, sidebar, and content panels.",
            xalign=0, wrap=True,
        )
        glass_desc.add_css_class("status-label")
        glass_desc.add_css_class("settings-desc")
        glass_text.append(glass_lbl)
        glass_text.append(glass_desc)
        glass_box.append(glass_text)

        self.frosted_glass_sw = Gtk.Switch(
            active=self.cfg.get("frosted_glass", True)
        )
        self.frosted_glass_sw.set_valign(Gtk.Align.CENTER)
        self.frosted_glass_sw.connect("notify::active", self._on_frosted_glass_toggled)
        glass_box.append(self.frosted_glass_sw)
        gen_box.append(glass_box)

        blur_box = Gtk.Box(spacing=16)
        blur_box.add_css_class("settings-row")
        blur_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        blur_lbl = Gtk.Label(label="Backdrop Blur", xalign=0)
        blur_lbl.add_css_class("control-label")
        blur_desc = Gtk.Label(
            label="0 is clear; increase the value for a softer, blurrier backdrop.",
            xalign=0, wrap=True,
        )
        blur_desc.add_css_class("status-label")
        blur_desc.add_css_class("settings-desc")
        blur_text.append(blur_lbl)
        blur_text.append(blur_desc)
        blur_box.append(blur_text)

        self.glass_blur_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 40, 1
        )
        self.glass_blur_scale.set_digits(0)
        self.glass_blur_scale.set_draw_value(True)
        self.glass_blur_scale.set_hexpand(True)
        self.glass_blur_scale.set_size_request(180, -1)
        self.glass_blur_scale.set_value(self.cfg.get("glass_blur", 18))
        self.glass_blur_scale.set_sensitive(self.frosted_glass_sw.get_active())
        self.glass_blur_scale.connect("value-changed", self._on_glass_blur_changed)
        blur_box.append(self.glass_blur_scale)
        gen_box.append(blur_box)

        backdrop_box = Gtk.Box(spacing=16)
        backdrop_box.add_css_class("settings-row")
        backdrop_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        backdrop_lbl = Gtk.Label(label="App Backdrop", xalign=0)
        backdrop_lbl.add_css_class("control-label")
        backdrop_desc = Gtk.Label(
            label="Choose the image shown behind Papyrus's frosted-glass panels.",
            xalign=0, wrap=True,
        )
        backdrop_desc.add_css_class("status-label")
        backdrop_desc.add_css_class("settings-desc")
        backdrop_text.append(backdrop_lbl)
        backdrop_text.append(backdrop_desc)
        backdrop_box.append(backdrop_text)

        backdrop_controls = Gtk.Box(spacing=8)
        self.backdrop_source_dd = Gtk.DropDown.new_from_strings(
            ["Active wallpaper", "Generated fallback", "Custom image"]
        )
        source_idx = {"wallpaper": 0, "fallback": 1, "custom": 2}.get(
            self.cfg.get("backdrop_source", "wallpaper"), 0
        )
        self.backdrop_source_dd.set_selected(source_idx)
        self.backdrop_source_dd.connect("notify::selected", self._on_backdrop_source_changed)
        backdrop_controls.append(self.backdrop_source_dd)

        self.backdrop_choose_btn = Gtk.Button(label="Choose Image")
        self.backdrop_choose_btn.connect("clicked", self._choose_backdrop_image)
        self.backdrop_choose_btn.set_visible(source_idx == 2)
        backdrop_controls.append(self.backdrop_choose_btn)
        backdrop_box.append(backdrop_controls)
        gen_box.append(backdrop_box)

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

        output_options = ["All Monitors"] + self.outputs
        self.output_dropdown = Gtk.DropDown.new_from_strings(output_options)
        self.output_dropdown.set_selected(0)
        self.output_dropdown.set_valign(Gtk.Align.CENTER)
        self.output_dropdown.connect("notify::selected", self._on_output_changed)
        out_box.append(self.output_dropdown)

        gen_box.append(out_box)
        page.append(gen_box)

        # Resource Control section
        resource_title = Gtk.Label(label="Resource Control", margin_top=28)
        resource_title.add_css_class("settings-section-title")
        resource_title.set_halign(Gtk.Align.START)
        page.append(resource_title)
        resource_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        resource_box.add_css_class("settings-group-container")
        smart_pause_box = Gtk.Box(spacing=16)
        smart_pause_box.add_css_class("settings-row")
        smart_pause_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                   spacing=2, hexpand=True)
        smart_pause_lbl = Gtk.Label(label="Smart Auto-Pause", xalign=0)
        smart_pause_lbl.add_css_class("control-label")
        backend = detect_smart_pause_backend()
        if backend:
            backend_note = smart_pause_backend_name(backend)
            smart_pause_description = (
                f"Pause wallpaper playback when windows fully cover a display or a fullscreen game is active. "
                f"Window detection is available on {backend_note}."
            )
        else:
            smart_pause_description = (
                "Pause wallpaper playback when windows fully cover a display. Window detection is currently "
                "available on Sway, Hyprland, and X11 sessions with wmctrl support."
            )
        self.smart_pause_desc = Gtk.Label(label=smart_pause_description,
                                          xalign=0, wrap=True)
        self.smart_pause_desc.add_css_class("status-label")
        self.smart_pause_desc.add_css_class("settings-desc")
        smart_pause_text.append(smart_pause_lbl)
        smart_pause_text.append(self.smart_pause_desc)
        smart_pause_box.append(smart_pause_text)
        self.smart_pause_sw = Gtk.Switch(active=self.cfg.get("smart_pause", False))
        self.smart_pause_sw.set_valign(Gtk.Align.CENTER)
        self.smart_pause_sw.connect("notify::active", self._on_smart_pause_toggled)
        smart_pause_box.append(self.smart_pause_sw)
        resource_box.append(smart_pause_box)
        page.append(resource_box)

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

        page.append(Gtk.Label(label="", margin_top=32))

        # Playlist section
        pl_title = Gtk.Label(label="Playlist")
        pl_title.add_css_class("settings-section-title")
        pl_title.set_halign(Gtk.Align.START)
        page.append(pl_title)

        pl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pl_box.add_css_class("settings-group-container")

        # Rotation toggle row
        rot_box = Gtk.Box(spacing=16)
        rot_box.add_css_class("settings-row")
        rot_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        rot_lbl = Gtk.Label(label="Auto-rotate", xalign=0)
        rot_lbl.add_css_class("control-label")
        rot_desc = Gtk.Label(label="Automatically switch to a random or sequential wallpaper at a set interval.", xalign=0, wrap=True)
        rot_desc.add_css_class("status-label")
        rot_desc.add_css_class("settings-desc")
        rot_text.append(rot_lbl)
        rot_text.append(rot_desc)
        rot_box.append(rot_text)

        self.rotation_sw = Gtk.Switch(active=self.cfg.get("rotation", False))
        self.rotation_sw.set_valign(Gtk.Align.CENTER)
        self.rotation_sw.connect("notify::active", self._on_rotation_toggle)
        rot_box.append(self.rotation_sw)

        pl_box.append(rot_box)

        # Interval row
        intv_box = Gtk.Box(spacing=16)
        intv_box.add_css_class("settings-row")
        intv_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        intv_lbl = Gtk.Label(label="Rotation Interval", xalign=0)
        intv_lbl.add_css_class("control-label")
        intv_desc = Gtk.Label(label="Minutes between wallpaper changes.", xalign=0, wrap=True)
        intv_desc.add_css_class("status-label")
        intv_desc.add_css_class("settings-desc")
        intv_text.append(intv_lbl)
        intv_text.append(intv_desc)
        intv_box.append(intv_text)

        adj = Gtk.Adjustment(value=self.cfg.get("interval", 30), lower=1, upper=999, step_increment=1)
        self.interval_spin = Gtk.SpinButton(adjustment=adj)
        self.interval_spin.set_valign(Gtk.Align.CENTER)
        self.interval_spin.connect("notify::value", self._on_interval_changed)
        intv_box.append(self.interval_spin)

        pl_box.append(intv_box)

        # Order row
        ord_box = Gtk.Box(spacing=16)
        ord_box.add_css_class("settings-row")
        ord_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        ord_lbl = Gtk.Label(label="Order", xalign=0)
        ord_lbl.add_css_class("control-label")
        ord_desc = Gtk.Label(label="Random picks a wallpaper at random; Sequential goes through the list in order.", xalign=0, wrap=True)
        ord_desc.add_css_class("status-label")
        ord_desc.add_css_class("settings-desc")
        ord_text.append(ord_lbl)
        ord_text.append(ord_desc)
        ord_box.append(ord_text)

        order_options = ["Random", "Sequential"]
        self.order_dropdown = Gtk.DropDown.new_from_strings(order_options)
        idx = 0 if self.cfg.get("order", "random") == "random" else 1
        self.order_dropdown.set_selected(idx)
        self.order_dropdown.set_valign(Gtk.Align.CENTER)
        self.order_dropdown.connect("notify::selected", self._on_order_changed)
        ord_box.append(self.order_dropdown)

        pl_box.append(ord_box)
        page.append(pl_box)

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

        clamp = Adw.Clamp(maximum_size=720)
        clamp.set_child(page)
        scroll.set_child(clamp)
        outer.append(scroll)

        return outer

    def _build_help_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)

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

        clamp = Adw.Clamp(maximum_size=600)
        clamp.set_child(page)
        scroll.set_child(clamp)
        outer.append(scroll)
        return outer

    def _build_discover_page(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       margin_start=16, margin_end=16, margin_top=16, margin_bottom=16)
        intro = Gtk.Label(
            label="Browse wallpaper collections from your browser, then add downloaded files to your Papyrus library.",
            xalign=0, wrap=True
        )
        intro.add_css_class("body-base")
        page.append(intro)

        sources = [
            ("MoeWalls", "Anime and gaming wallpapers, often available as WebM or MP4.",
             "https://moewalls.com/", True),
            ("MotionBGs", "A large collection of animated wallpapers, including 4K.",
             "https://motionbgs.com/", False),
            ("Wallsflow", "A growing collection of free wallpapers.",
             "https://wallsflow.com/", False),
            ("Pexels Videos", "Cinematic and nature videos, including 4K footage.",
             "https://www.pexels.com/videos/", False),
        ]
        for name, description, url, recommended in sources:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class("settings-row")
            title = Gtk.Label(label=f"{name}  ·  Recommended" if recommended else name, xalign=0)
            title.add_css_class("window-title" if recommended else "control-label")
            card.append(title)
            detail = Gtk.Label(label=description, xalign=0, wrap=True)
            detail.add_css_class("settings-desc")
            card.append(detail)
            open_btn = Gtk.Button(label=f"Visit {name}")
            open_btn.set_halign(Gtk.Align.START)
            if recommended:
                open_btn.add_css_class("primary-btn")
            open_btn.connect("clicked", lambda _, target=url: Gio.AppInfo.launch_default_for_uri(target))
            card.append(open_btn)
            page.append(card)

        note = Gtk.Label(
            label="Papyrus does not download files from these sites. Download only files you trust, then choose them from your library.",
            xalign=0, wrap=True
        )
        note.add_css_class("status-label")
        page.append(note)

        clamp = Adw.Clamp(maximum_size=720)
        clamp.set_child(page)
        scroll.set_child(clamp)
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

        self.monitor_lbl = Gtk.Label(label="No wallpaper active")
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
        content.set_hexpand(True)
        content.set_halign(Gtk.Align.FILL)

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        card.set_hexpand(True)
        card.add_css_class("detail-card")
        # Preview area
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        preview_box.set_hexpand(True)
        preview_box.add_css_class("detail-sidebar")

        thumb_path = get_thumb_large(path_obj)
        pic = Gtk.Picture.new_for_filename(str(thumb_path)) if thumb_path.exists() else Gtk.Picture()
        pic.set_content_fit(Gtk.ContentFit.CONTAIN)
        pic.set_hexpand(True)
        pic.set_vexpand(False)
        pic.set_valign(Gtk.Align.START)
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

        kind = "Animated Video Wallpaper" if path_obj.suffix.lower() in VIDEO_EXTS else "Static Image Wallpaper"
        subtitle_lbl = Gtk.Label(label=kind, xalign=0)
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
        res_val = Gtk.Label(label=get_video_resolution(path_obj), xalign=0)
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

        # Output selector
        out_selector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        out_selector.add_css_class("settings-row")
        out_hdr = Gtk.Label(label="OUTPUT", xalign=0)
        out_hdr.add_css_class("status-label")
        out_selector.append(out_hdr)
        out_names = ["All Monitors"] + self.outputs
        self._detail_output_dd = Gtk.DropDown.new_from_strings(out_names)
        wallpapers = self.cfg.get("wallpapers", {}) or {}
        active_outs = [o for o, w in wallpapers.items() if w == str(path_obj)]
        if active_outs:
            out = active_outs[0]
            saved_out = 0 if out == "*" else (out_names.index(out) if out in out_names else 0)
            scaling_map = self.cfg.get("scaling", {}) or {}
            out_sc = scaling_map.get(out, "fit")
            saved_sc = ["fit", "fill", "stretch"].index(out_sc) if out_sc in ("fit", "fill", "stretch") else 0
        else:
            saved_out = min(self.cfg.get("last_output_idx", 0), len(out_names) - 1)
            saved_sc = min(self.cfg.get("last_scaling_idx", 0), 2)
        self._detail_output_dd.set_selected(saved_out)
        self._detail_output_dd.set_halign(Gtk.Align.FILL)
        self._detail_output_dd.set_hexpand(True)
        out_selector.append(self._detail_output_dd)
        sidebar.append(out_selector)

        # Scaling selector
        sc_selector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sc_selector.add_css_class("settings-row")
        sc_hdr = Gtk.Label(label="SCALING", xalign=0)
        sc_hdr.add_css_class("status-label")
        sc_selector.append(sc_hdr)
        self._detail_scaling_dd = Gtk.DropDown.new_from_strings(["Fit", "Fill", "Stretch"])
        self._detail_scaling_dd.set_selected(saved_sc)
        self._detail_scaling_dd.set_halign(Gtk.Align.FILL)
        self._detail_scaling_dd.set_hexpand(True)
        sc_selector.append(self._detail_scaling_dd)
        sidebar.append(sc_selector)

        # Apply button
        apply_btn = Gtk.Button(label="Apply Wallpaper")
        apply_btn.add_css_class("primary-btn")
        apply_btn.set_halign(Gtk.Align.FILL)
        self._detail_path = str(path_obj)
        apply_btn.connect("clicked", lambda _: self._apply(self._detail_path))
        sidebar.append(apply_btn)

        # Back to library
        back_lib_btn = Gtk.Button(label="Back to Library")
        back_lib_btn.add_css_class("header-btn")
        back_lib_btn.set_halign(Gtk.Align.FILL)
        back_lib_btn.connect("clicked", lambda _: self._show_page("library"))
        sidebar.append(back_lib_btn)

        card.append(sidebar)
        responsive_card = Adw.BreakpointBin()
        responsive_card.set_hexpand(True)
        breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 560px")
        )
        breakpoint.add_setter(card, "orientation", Gtk.Orientation.VERTICAL)
        responsive_card.add_breakpoint(breakpoint)
        responsive_card.set_child(card)
        content.append(responsive_card)

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
            total = getattr(self, "_library_total", 0)
            visible = getattr(self, "_library_visible", total)
            self.header_title.set_subtitle(f"{visible} of {total} wallpapers")
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
        elif page == "discover":
            self.header_title.set_title("Find Wallpapers")
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
        if name in ("library", "settings", "help", "discover") and self.nav_list:
            idx = {"library": 0, "settings": 1, "help": 2, "discover": 3}[name]
            row = self.nav_list.get_row_at_index(idx)
            if row:
                self.nav_list.select_row(row)

    def _populate(self):
        while child := self.flow.get_first_child():
            self.flow.remove(child)

        self._refresh_folder_list()

        wallpapers_found = scan_wallpapers(self.cfg.get("dirs", [str(d) for d in DEFAULT_DIRS]))
        wallpapers = self.cfg.get("wallpapers", {}) or {}
        active_paths = set(wallpapers.values())
        query = self.library_search.get_text().strip().casefold()
        type_filter = self.library_type_filter.get_selected()
        status_filter = self.library_status_filter.get_selected()
        sort_mode = self.library_sort.get_selected()

        visible = []
        metadata = {}
        for path in wallpapers_found:
            path_string = str(path)
            active = path_string in active_paths
            suffix = path.suffix.lower()
            if query and query not in path.name.casefold() and query not in str(path.parent).casefold():
                continue
            if type_filter == 1 and suffix not in VIDEO_EXTS:
                continue
            if type_filter == 2 and suffix not in IMAGE_EXTS:
                continue
            if status_filter == 1 and not active:
                continue
            if status_filter == 2 and active:
                continue
            try:
                stat = path.stat()
                metadata[path] = (stat.st_mtime, stat.st_size)
            except OSError:
                metadata[path] = (0, 0)
            visible.append(path)

        if sort_mode in (0, 1):
            visible.sort(key=lambda path: path.name.casefold(), reverse=(sort_mode == 1))
        elif sort_mode in (2, 3):
            visible.sort(
                key=lambda path: (metadata[path][0], path.name.casefold()),
                reverse=(sort_mode == 2),
            )
        else:
            visible.sort(
                key=lambda path: (metadata[path][1], path.name.casefold()),
                reverse=(sort_mode == 4),
            )

        self._library_total = len(wallpapers_found)
        self._library_visible = len(visible)
        self.header_title.set_subtitle(
            f"{len(visible)} of {len(wallpapers_found)} wallpapers"
        )

        if not wallpapers_found:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                margin_top=80)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.add_css_class("empty-state")
            icon = Gtk.Image.new_from_icon_name("emblem-photos-symbolic")
            icon.set_pixel_size(48)
            empty_box.append(icon)
            lbl = Gtk.Label(
                label="No wallpaper files found.\nClick the folder button above to add a folder.",
                justify=Gtk.Justification.CENTER,
            )
            lbl.add_css_class("control-label")
            empty_box.append(lbl)
            self.flow.append(empty_box)
            return

        if not visible:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                                margin_top=80)
            empty_box.set_halign(Gtk.Align.CENTER)
            empty_box.add_css_class("empty-state")
            icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
            icon.set_pixel_size(48)
            empty_box.append(icon)
            lbl = Gtk.Label(
                label="No wallpapers match your search and filters.",
                justify=Gtk.Justification.CENTER,
            )
            lbl.add_css_class("control-label")
            empty_box.append(lbl)
            clear_btn = Gtk.Button(label="Clear Search and Filters")
            clear_btn.add_css_class("flat")
            clear_btn.connect("clicked", self._clear_library_controls)
            empty_box.append(clear_btn)
            self.flow.append(empty_box)
            return

        for wallpaper in visible:
            self.flow.append(self._make_card(wallpaper, active=str(wallpaper) in active_paths))

    def _on_library_controls_changed(self, *_args):
        self._populate()

    def _clear_library_controls(self, _button):
        self.library_search.set_text("")
        self.library_type_filter.set_selected(0)
        self.library_status_filter.set_selected(0)
        self.library_sort.set_selected(0)
        self._populate()

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

            count = len([f for f in Path(d).iterdir()
                         if f.is_file() and f.suffix.lower() in WALLPAPER_EXTS]) if Path(d).exists() else 0
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

    def _update_footer(self, wallpapers):
        if not wallpapers:
            self.monitor_lbl.set_label("No wallpaper active")
            return
        parts = []
        for out, wp in wallpapers.items():
            name = Path(wp).stem[:16]
            lbl = out if out == "*" else out
            parts.append(f"{lbl}: {name}")
        self.monitor_lbl.set_label(" | ".join(parts))

    def _active_status(self, wallpapers):
        """Return a banner label that includes every active output."""
        if not wallpapers:
            return "No wallpaper active"
        parts = []
        for output, path in wallpapers.items():
            label = "All monitors" if output == "*" else output
            parts.append(f"{label}: {Path(path).name}")
        return "Active: " + " | ".join(parts)

    def _update_header_info(self, text):
        pass

    def _set_app_backdrop(self, path):
        enabled = self.cfg.get("frosted_glass", True)
        if enabled:
            self.app_shell.remove_css_class("frosted-glass-off")
            self.header.remove_css_class("frosted-glass-off")
            self.glass_tint.set_visible(True)
        else:
            self.app_shell.add_css_class("frosted-glass-off")
            self.header.add_css_class("frosted-glass-off")
            self.glass_tint.set_visible(False)
            self.app_backdrop.set_paintable(None)
            self.header_backdrop.set_paintable(None)
            self.sidebar_backdrop.set_paintable(None)
            return
        source = self.cfg.get("backdrop_source", "wallpaper")
        source_path = path
        backdrop = None
        if source == "fallback":
            backdrop = get_fallback_backdrop(self.cfg.get("glass_blur", 18))
        else:
            if source == "custom":
                source_path = self.cfg.get("backdrop_custom")
            if source_path and Path(source_path).exists():
                thumb = get_thumb_large(Path(source_path))
                if thumb.exists():
                    backdrop = get_thumb_blurred(thumb, self.cfg.get("glass_blur", 18))

        if not backdrop or not backdrop.exists():
            backdrop = get_fallback_backdrop(self.cfg.get("glass_blur", 18))
            print("[papyrus] using generated fallback backdrop")

        if backdrop and backdrop.exists():
            self.app_backdrop.set_filename(str(backdrop))
            self.header_backdrop.set_filename(str(backdrop))
            self.sidebar_backdrop.set_filename(str(backdrop))
        else:
            print("[papyrus] no backdrop image available")
            self.app_backdrop.set_paintable(None)
            self.header_backdrop.set_paintable(None)
            self.sidebar_backdrop.set_paintable(None)

    def _on_backdrop_source_changed(self, dropdown, _param):
        sources = ["wallpaper", "fallback", "custom"]
        selected = dropdown.get_selected()
        if selected >= len(sources):
            return
        source = sources[selected]
        self.cfg["backdrop_source"] = source
        self.backdrop_choose_btn.set_visible(source == "custom")
        save_config(self.cfg)
        if source == "custom" and not self.cfg.get("backdrop_custom"):
            self._refresh_app_backdrop()
            self._choose_backdrop_image(None)
        else:
            self._refresh_app_backdrop()

    def _choose_backdrop_image(self, _button):
        dialog = Gtk.FileDialog(title="Choose app backdrop image")
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Images")
        for extension in IMAGE_EXTS:
            image_filter.add_pattern(f"*{extension}")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog.set_filters(filters)
        dialog.open(self.win, None, self._backdrop_image_chosen)

    def _backdrop_image_chosen(self, dialog, result):
        try:
            image = dialog.open_finish(result)
            path = image.get_path()
            if not path or Path(path).suffix.lower() not in IMAGE_EXTS:
                return
            self.cfg["backdrop_custom"] = path
            self.cfg["backdrop_source"] = "custom"
            save_config(self.cfg)
            self._refresh_app_backdrop()
        except Exception:
            pass

    def _refresh_app_backdrop(self):
        current = self.cfg.get("current") or next(
            iter((self.cfg.get("wallpapers", {}) or {}).values()), None
        )
        self._set_app_backdrop(current)

    def _on_frosted_glass_toggled(self, switch, _param):
        self.cfg["frosted_glass"] = switch.get_active()
        self.glass_blur_scale.set_sensitive(switch.get_active())
        save_config(self.cfg)
        current = self.cfg.get("current") or next(
            iter((self.cfg.get("wallpapers", {}) or {}).values()), None
        )
        self._set_app_backdrop(current)

    def _on_glass_blur_changed(self, scale):
        self.cfg["glass_blur"] = int(scale.get_value())
        print(f"[papyrus] blur slider changed: {self.cfg['glass_blur']}")
        save_config(self.cfg)
        current = self.cfg.get("current") or next(
            iter((self.cfg.get("wallpapers", {}) or {}).values()), None
        )
        self._set_app_backdrop(current)

    def _apply(self, path: str):
        print(f"[papyrus] _apply called with {path}")

        dd_idx = self._detail_output_dd.get_selected()
        scaling_idx = self._detail_scaling_dd.get_selected()
        self.cfg["last_output_idx"] = dd_idx
        self.cfg["last_scaling_idx"] = scaling_idx
        scaling = ["fit", "fill", "stretch"][scaling_idx]
        targets = ["*"] if dd_idx == 0 else [self.outputs[dd_idx - 1]]

        theme_status = ""
        for output in targets:
            proc, err = apply_wallpaper(path, output, scaling)
            if err:
                print(f"[papyrus] _apply error on {output}: {err}")
                self.banner.set_title(err)
                continue
            wallpapers = self.cfg.setdefault("wallpapers", {})
            wallpapers[output] = path
            sc_map = self.cfg.setdefault("scaling", {})
            sc_map[output] = scaling
            save_config(self.cfg)

            thumb = get_thumb(Path(path))
            if self.cfg.get("auto_theme", False) and thumb.exists():
                ok = apply_cosmic_theme(thumb, self.cfg.get("auto_dark", True))
                theme_status = " · theme applied" if ok else " · theme failed"

            def monitor(p=proc, out=output):
                err_log = CONFIG_DIR / f"mpvpaper_{out}.log"
                # Some mpvpaper failures exit within the first second or two.
                try:
                    rc = p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    rc = None
                if rc is not None and rc != 0:
                    tail = ""
                    try:
                        if err_log.exists():
                            error_lines = [line.strip() for line in err_log.read_text(errors="ignore").splitlines() if line.strip()]
                            tail = " — " + error_lines[-1] if error_lines else ""
                    except Exception:
                        pass
                    if any(term in tail.lower() for term in ("layer_shell", "layer shell", "layer-shell")):
                        message = "This compositor does not support mpvpaper's required Wayland layer-shell protocol. GNOME is currently unsupported."
                    else:
                        message = f"mpvpaper failed (code {rc}){tail}"
                    GLib.idle_add(lambda m=message: self.banner.set_title(m))
            threading.Thread(target=monitor, daemon=True).start()

        self.cfg["current"] = path
        save_config(self.cfg)
        self._set_app_backdrop(path)
        self.banner.set_title(self._active_status(self.cfg.get("wallpapers", {})) + theme_status)

        if self.autostart_sw.get_active():
            write_autostart(self.cfg.get("wallpapers", {}), self.cfg.get("scaling", {}))

        self._update_footer(self.cfg.get("wallpapers", {}))
        self._populate()
        self._show_page("library")

        if self.cfg.get("rotation", False):
            self._start_rotation()

    def _stop(self, _btn):
        self._stop_rotation()
        kill_mpvpaper()
        self.cfg["current"] = None
        self.cfg["wallpapers"] = {}
        save_config(self.cfg)
        self._set_app_backdrop(None)
        self.banner.set_title("No wallpaper active")
        self._update_footer({})
        self._populate()

    def _on_autostart(self, sw, _param):
        wallpapers = self.cfg.get("wallpapers", {})
        if sw.get_active() and wallpapers:
            write_autostart(wallpapers, self.cfg.get("scaling", {}))
        else:
            remove_autostart()

    def _on_smart_pause_toggled(self, sw, _param):
        active = sw.get_active()
        self.cfg["smart_pause"] = active
        save_config(self.cfg)
        backend = detect_smart_pause_backend()
        if active and backend:
            start_smart_pause_daemon()
            backend_name = smart_pause_backend_name(backend)
            self.smart_pause_desc.set_text(
                f"Pause wallpaper playback when windows fully cover a display or a fullscreen game is active. "
                f"Window detection is available on {backend_name}."
            )
        elif active:
            self.smart_pause_desc.set_text(
                "Enabled, but window detection is unavailable in this desktop session. "
                "Supported paths currently include Sway, Hyprland, and X11 sessions with wmctrl support."
            )
        else:
            self.smart_pause_desc.set_text(
                "Pause wallpaper playback when windows fully cover a display. Window detection is currently "
                "available on Sway, Hyprland, and X11 sessions with wmctrl support."
            )
        if self.autostart_sw.get_active():
            write_autostart(self.cfg.get("wallpapers", {}), self.cfg.get("scaling", {}))

    def _on_theme_toggle(self, sw, _param):
        self.cfg["auto_theme"] = sw.get_active()
        save_config(self.cfg)

    def _on_dark_toggle(self, sw, _param):
        self.cfg["auto_dark"] = sw.get_active()
        save_config(self.cfg)

    def _on_output_changed(self, dd, _param):
        idx = dd.get_selected()
        selected = "*" if idx == 0 else self.outputs[idx - 1]
        self.cfg["output"] = selected
        save_config(self.cfg)

    def _collect_wallpapers(self):
        dirs = self.cfg.get("dirs", [str(d) for d in DEFAULT_DIRS])
        return sorted(scan_wallpapers(dirs), key=lambda p: str(p))

    def _rotate_wallpaper(self):
        print(f"[papyrus] rotate tick")
        wallpapers = self._collect_wallpapers()
        if not wallpapers:
            print("[papyrus] rotate: no wallpapers found")
            return True
        order = self.cfg.get("order", "random")
        idx = self.cfg.get("seq_index", 0)
        outputs = self.outputs
        scaling_map = self.cfg.get("scaling", {})
        for output in outputs:
            if order == "random":
                pick = random.choice(wallpapers)
            else:
                pick = wallpapers[idx % len(wallpapers)]
                if output == outputs[-1]:
                    self.cfg["seq_index"] = (idx + 1) % len(wallpapers)
                    save_config(self.cfg)
            print(f"[papyrus] rotate: {pick.name} → {output}")
            proc, err = apply_wallpaper(str(pick), output, scaling_map.get(output, "fit"))
            if err:
                print(f"[papyrus] rotate error on {output}: {err}")
                continue
            wallpapers = self.cfg.setdefault("wallpapers", {})
            wallpapers[output] = str(pick)
            save_config(self.cfg)
        self.cfg["current"] = str(pick)
        save_config(self.cfg)
        self._set_app_backdrop(str(pick))
        self._update_footer(self.cfg.get("wallpapers", {}))
        self._populate()
        return True

    def _start_rotation(self):
        self._stop_rotation()
        print(f"[papyrus] rotation service requested: interval={self.cfg.get('interval', 30)}min")
        start_rotation_daemon()

    def _stop_rotation(self):
        self._rotation_source = None

    def _on_rotation_toggle(self, sw, _param):
        active = sw.get_active()
        print(f"[papyrus] rotation toggle: {'ON' if active else 'OFF'}")
        self.cfg["rotation"] = active
        save_config(self.cfg)
        if active:
            self._start_rotation()
        else:
            self._stop_rotation()
        if self.autostart_sw.get_active():
            write_autostart(self.cfg.get("wallpapers", {}), self.cfg.get("scaling", {}))

    def _on_interval_changed(self, spin, _param):
        self.cfg["interval"] = int(spin.get_value())
        save_config(self.cfg)
        if self.cfg.get("rotation", False):
            self._start_rotation()
            if self.autostart_sw.get_active():
                write_autostart(self.cfg.get("wallpapers", {}), self.cfg.get("scaling", {}))

    def _on_order_changed(self, dd, _param):
        idx = dd.get_selected()
        self.cfg["order"] = "random" if idx == 0 else "sequential"
        self.cfg["seq_index"] = 0
        save_config(self.cfg)

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
        self._update_version = latest
        self.banner.set_title(f"Update available: v{latest} — click to download")
        self.banner.set_button_label("Download")
        self.banner.connect("button-clicked", lambda _: self._perform_update())
        self.banner.set_revealed(True)

    def _perform_update(self):
        latest = getattr(self, "_update_version", None)
        if not latest:
            return
        if IN_FLATPAK:
            Gio.AppInfo.launch_default_for_uri(RELEASES_URL)
            return
        url = "https://raw.githubusercontent.com/PSGtatitos/papyrus/main/papyrus.py"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "papyrus-updater"})
            with urllib.request.urlopen(req, timeout=10) as r:
                new_code = r.read()
        except Exception as e:
            self.banner.set_title(f"Update failed: {e}")
            self.banner.set_button_label("")
            return
        script = Path(__file__).resolve()
        try:
            tmp = script.with_name(script.name + ".tmp")
            tmp.write_bytes(new_code)
            tmp.chmod(0o755)
            tmp.replace(script)
            self.banner.set_title(f"Updated to v{latest}. Restart the app.")
            self.banner.set_button_label("")
        except PermissionError:
            self.banner.set_title(f"Can't write to {script.parent}. Open releases page?")
            self.banner.set_button_label("Open")
            self.banner.connect("button-clicked", lambda _: Gio.AppInfo.launch_default_for_uri(RELEASES_URL))

    def _open_releases(self):
        Gio.AppInfo.launch_default_for_uri(RELEASES_URL)

if __name__ == "__main__":
    if "--rotation-daemon" in sys.argv:
        run_rotation_daemon()
        raise SystemExit(0)
    if "--smart-pause-daemon" in sys.argv:
        run_smart_pause_daemon()
        raise SystemExit(0)
    if not shutil.which("mpvpaper") and not Path("/app/bin/mpvpaper").exists():
        print("mpvpaper not found. Install it first.")
        raise SystemExit(1)
    CWApp().run(None)

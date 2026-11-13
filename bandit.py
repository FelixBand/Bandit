#!/usr/bin/env python3
from __future__ import annotations

import base64
import glob
import json
import os
import platform
import plistlib
import random
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime

import requests
from PyQt6.QtCore import (
    QDateTime, QEvent, QLocale, QModelIndex, QObject, QPointF, QRect, QRectF, QRunnable,
    QSettings, QSize, QSortFilterProxyModel, Qt, QThread, QThreadPool, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QFont, QIcon, QKeySequence, QLinearGradient, QPainter,
    QPainterPath, QPalette, QPen, QPixmap, QStandardItem, QStandardItemModel,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QSizePolicy, QSlider, QSplitter, QStackedWidget, QStyle,
    QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

# --------------------------------------------------------------------------- #
# 1. Constants & platform paths
# --------------------------------------------------------------------------- #

VERSION = "3.0.0"
BASE_URL = "https://thuis.felixband.nl/bandit"
TELEMETRY_ENDPOINTS = (
    "https://thuis.felixband.nl/api/telemetry",
    "http://thuis.felixband.nl:5001/api/telemetry",
)
GITHUB_LATEST = "https://api.github.com/repos/FelixBand/Bandit/releases/latest"
RELEASES_PAGE = "https://github.com/FelixBand/Bandit/releases/latest"
PROTON_API = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"

# Set BANDIT_DEBUG_OS=Windows (etc.) to test another platform's catalog.
OS = os.environ.get("BANDIT_DEBUG_OS") or platform.system()  # Windows / Linux / Darwin
HOME = os.path.expanduser("~")

if OS == "Windows":
    USER_DATA = os.path.join(os.getenv("APPDATA", HOME), "BanditGameLauncher")
    PROGRAM_DATA = os.path.join(os.getenv("PROGRAMDATA", HOME), "BanditGameLauncher")
elif OS == "Darwin":
    USER_DATA = os.path.join(HOME, "Library", "Application Support", "BanditGameLauncher")
    PROGRAM_DATA = "/Library/Application Support/BanditGameLauncher"
else:
    USER_DATA = os.path.join(HOME, ".config", "BanditGameLauncher")
    PROGRAM_DATA = "/etc/BanditGameLauncher"

GAMES_FOLDER = "/Applications" if OS == "Darwin" else os.path.join(PROGRAM_DATA, "Games")
WIN_GAMES_FOLDER = os.path.join(PROGRAM_DATA, "Games")  # where Windows builds install (Linux + macOS)
WINDOWS_SUBDIR = os.path.join(PROGRAM_DATA, "Windows")  # Linux + macOS: Windows-build manifests
PFX_ROOT = os.path.join(HOME, ".banditpfx")  # Windows compatibility prefix: Proton (Linux) / CrossOver (macOS)
WINE_PREFIX = os.path.join(PFX_ROOT, "pfx")
HAS_WINDOWS_LAYER = OS in ("Linux", "Darwin")  # can run Windows builds (Proton / CrossOver)
NATIVE_NAME = {"Linux": "Linux", "Darwin": "macOS"}.get(OS, OS)
COMPAT_LAYER = "CrossOver" if OS == "Darwin" else "Proton"
CROSSOVER_DOWNLOAD_PAGE = "https://www.codeweavers.com/crossover/download"
WINE_DLL_OVERRIDES = "dinput8,winhttp,winmm=n,b"

SETTINGS_PATH = os.path.join(USER_DATA, "settings.json")
PREREQS_PATH = os.path.join(USER_DATA, "installed_prereqs.json")
INSTALLED_PATH = os.path.join(PROGRAM_DATA, "installed_games.json")

MP_LABELS = {
    "0": ("Offline", "Singleplayer or local multiplayer only."),
    "1": ("LAN", "LAN multiplayer supported."),
    "2": ("Online · Unofficial", "Unofficial online multiplayer."),
    "3": ("Online · Anyone", "Online multiplayer with anyone supported."),
}


def resource_path(relative: str) -> str:
    """Resolve a bundled resource (works in dev and under PyInstaller)."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative)


def ensure_program_data() -> str | None:
    """Create the system-wide data folders. Returns an error message on failure."""
    try:
        os.makedirs(USER_DATA, exist_ok=True)
    except OSError as e:
        return f"Could not create {USER_DATA}: {e}"

    if os.path.isdir(os.path.join(PROGRAM_DATA, "Games")) or (
        OS == "Darwin" and os.path.isdir(PROGRAM_DATA)
    ):
        pass  # already set up
    elif OS == "Windows":
        try:
            os.makedirs(os.path.join(PROGRAM_DATA, "Games"), exist_ok=True)
        except OSError as e:
            return f"Failed to create {PROGRAM_DATA}: {e}\nTry running Bandit as administrator once."
    elif OS == "Linux":
        dirs = [PROGRAM_DATA, os.path.join(PROGRAM_DATA, "Games"), WINDOWS_SUBDIR]
        script = " && ".join(f"mkdir -p {shlex.quote(d)} && chmod 777 {shlex.quote(d)}" for d in dirs)
        # One graphical password prompt for everything.
        subprocess.run(["pkexec", "sh", "-c", script], check=False)
        if not os.path.isdir(PROGRAM_DATA):
            return f"Failed to create {PROGRAM_DATA}.\nPlease run Bandit as root or with sudo once."
    elif OS == "Darwin":
        q = PROGRAM_DATA.replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e",
             f'do shell script "mkdir -p \\"{q}\\" && chmod -R 777 \\"{q}\\"" with administrator privileges'],
            check=False,
        )
        if not os.path.isdir(PROGRAM_DATA):
            return f"Failed to create {PROGRAM_DATA}."

    if OS == "Linux":
        os.makedirs(WINDOWS_SUBDIR, exist_ok=True)
        _setup_linux_prefix()
    elif OS == "Darwin":
        if not os.access(PROGRAM_DATA, os.W_OK):
            q = PROGRAM_DATA.replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'do shell script "chmod -R 777 \\"{q}\\"" with administrator privileges'],
                check=False, timeout=30,
            )
        for d in (WINDOWS_SUBDIR, WIN_GAMES_FOLDER):  # Windows builds + their manifests (CrossOver)
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
    return None


def _setup_linux_prefix() -> None:
    """Create the Proton prefix skeleton and link the usual user folders into it."""
    if os.path.exists(PFX_ROOT):
        return
    pfxhome = os.path.join(PFX_ROOT, "pfx", "drive_c", "users", "steamuser")
    appdata = os.path.join(pfxhome, "AppData")
    os.makedirs(appdata, exist_ok=True)
    links = [(appdata, os.path.join(HOME, "AppData"))]
    for name in ("Downloads", "Documents", "Desktop", "Music", "Pictures", "Videos"):
        links.append((os.path.join(HOME, name), os.path.join(pfxhome, name)))
    for target, link in links:
        try:
            if not os.path.lexists(link):
                os.symlink(target, link)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 2. Data layer
# --------------------------------------------------------------------------- #

def read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def default_account_name() -> str:
    return os.getenv("USER", os.getenv("USERNAME", "unknown"))


class Settings:
    DEFAULTS = {
        "Ask where to install games to": False,
        "Enable Telemetry": True,
        "Check for updates on startup": True,
        "UI scale": 125,
        "CrossOver path": "",
        "Account name": "",
        "_first_launch": True,
    }

    def __init__(self) -> None:
        self.data = dict(self.DEFAULTS)
        self.data.update(read_json(SETTINGS_PATH, {}))
        if not os.path.exists(SETTINGS_PATH):
            self.save()

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        write_json(SETTINGS_PATH, self.data)

    @property
    def account_name(self) -> str:
        return (self.data.get("Account name") or "").strip() or default_account_name()


def prefix_roaming_dirs() -> list[str]:
    """AppData\\Roaming folders of the Windows users inside the compatibility prefix."""
    users = os.path.join(WINE_PREFIX, "drive_c", "users")
    names = ["steamuser"] if OS == "Linux" else []  # Proton always uses steamuser
    try:
        names += [n for n in sorted(os.listdir(users)) if n.lower() != "public" and n not in names]
    except OSError:
        pass
    return [os.path.join(users, n, "AppData", "Roaming") for n in names]


def write_account_name_files(name: str) -> None:
    """Games read the player's name from these files."""
    if not name:
        return
    if OS == "Windows":
        appdata = os.getenv("APPDATA")
        if not appdata:
            return
        folders = [os.path.join(appdata, g, "settings") for g in ("Goldberg SteamEmu Saves", "Goldberg SocialClub Emu Saves")]
    else:
        folders = [os.path.join(HOME, ".local", "share", g, "settings") for g in ("Goldberg SteamEmu Saves", "Goldberg SocialClub Emu Saves")]
        if HAS_WINDOWS_LAYER:  # same folders inside the prefix, for Windows builds
            folders += [os.path.join(r, g, "settings") for r in prefix_roaming_dirs() for g in ("Goldberg SteamEmu Saves", "Goldberg SocialClub Emu Saves")]
    for folder in folders:
        try:
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, "account_name.txt"), "w", encoding="utf-8") as f:
                f.write(name)
        except OSError as e:
            print(f"[WARNING] Could not write account_name.txt to {folder}: {e}")


@dataclass
class Game:
    id: str
    name: str
    size: int | None
    mp: str = "0"
    sources: set = field(default_factory=set)  # which platform builds exist: "Linux"/"Windows"/...
    steam_appid: str | None = None             # optional 5th list.txt field: Steam appid (for artwork)


def _section_dir(section: str) -> str:
    return WINDOWS_SUBDIR if (section == "Windows" and HAS_WINDOWS_LAYER) else PROGRAM_DATA


def load_catalog() -> dict[str, Game]:
    games: dict[str, Game] = {}

    def read(path: str, source: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            return
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2 or not parts[0] or not parts[1]:
                continue
            name, gid = parts[0], parts[1]
            size = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            mp = parts[3] if len(parts) > 3 and parts[3] in MP_LABELS else "0"
            steam = parts[4] if len(parts) > 4 and parts[4].isdigit() else None
            if gid in games:
                games[gid].sources.add(source)
                if steam and not games[gid].steam_appid:
                    games[gid].steam_appid = steam
            else:
                games[gid] = Game(gid, name, size, mp, {source}, steam)

    read(os.path.join(PROGRAM_DATA, "list.txt"), OS)
    if HAS_WINDOWS_LAYER:
        read(os.path.join(WINDOWS_SUBDIR, "list.txt"), "Windows")
    return games


class Manifest:
    """Per-platform executable / prerequisite / icon tables."""

    def __init__(self, section: str) -> None:
        folder = _section_dir(section)
        self.executables: dict = read_json(os.path.join(folder, "executable_paths.json"), {})
        self.prereqs: dict = read_json(os.path.join(folder, "prereq_paths.json"), {})
        self.icons: dict = read_json(os.path.join(folder, "icon_paths.json"), {})

    def first_folder(self, game_id: str) -> str | None:
        exe = self.executables.get(game_id)
        return exe.split("/")[0] if exe else None


class InstalledStore:
    """installed_games.json: {"Windows": {id: install_dir}, "Linux": {...}, "Darwin": {...}}"""

    def __init__(self) -> None:
        if not os.path.exists(INSTALLED_PATH):
            self._migrate_legacy()
        if not os.path.exists(INSTALLED_PATH):
            self._write({"Windows": {}, "Linux": {}, "Darwin": {}})

    @staticmethod
    def _migrate_legacy() -> None:
        legacy = [
            os.path.join(USER_DATA, "saved_paths.json"),
            os.path.join(HOME, ".config", "banditgamelauncher", "saved_paths.json"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_paths.json"),
        ]
        for old in legacy:
            if os.path.exists(old):
                try:
                    write_json(INSTALLED_PATH, read_json(old, {}))
                    return
                except OSError:
                    pass

    @staticmethod
    def _read() -> dict:
        return read_json(INSTALLED_PATH, {})

    @staticmethod
    def _write(data: dict) -> None:
        write_json(INSTALLED_PATH, data)

    @staticmethod
    def _sections() -> list[str]:
        return [OS] + (["Windows"] if HAS_WINDOWS_LAYER else [])

    def installed_ids(self) -> set[str]:
        data = self._read()
        ids: set[str] = set()
        for s in self._sections():
            ids.update(data.get(s, {}).keys())
        return ids

    def find(self, game_id: str) -> tuple[str | None, str | None]:
        data = self._read()
        for s in self._sections():
            path = data.get(s, {}).get(game_id)
            if path:
                return s, path
        return None, None

    def add(self, section: str, game_id: str, path: str) -> None:
        data = self._read()
        data.setdefault(section, {})[game_id] = path
        self._write(data)

    def remove(self, section: str, game_id: str) -> None:
        data = self._read()
        data.get(section, {}).pop(game_id, None)
        self._write(data)


class PrereqStore:
    def __init__(self) -> None:
        self.data: dict = read_json(PREREQS_PATH, {})

    def done(self, game_id: str) -> bool:
        return bool(self.data.get(game_id))

    def mark(self, game_id: str) -> None:
        self.data[game_id] = True
        write_json(PREREQS_PATH, self.data)

    def clear(self, game_id: str) -> None:
        if self.data.pop(game_id, None) is not None:
            write_json(PREREQS_PATH, self.data)


META_PATH = os.path.join(USER_DATA, "library.json")


class UserMeta:
    """Per-user extras: favorites, playtime, last played, and per-game launch settings."""

    def __init__(self) -> None:
        d = read_json(META_PATH, {})
        self.favorites: set[str] = set(d.get("favorites", []))
        self.playtime: dict[str, int] = {k: int(v) for k, v in d.get("playtime", {}).items()}
        self.last_played: dict[str, int] = {k: int(v) for k, v in d.get("last_played", {}).items()}
        self.launch_args: dict[str, str] = dict(d.get("launch_args", {}))
        self.graphics_backend: dict[str, str] = dict(d.get("graphics_backend", {}))
        self.winemsync: dict[str, bool] = dict(d.get("winemsync", {}))
        self.mtl_hud_enabled: dict[str, bool] = dict(d.get("mtl_hud_enabled", {}))
        self.proton_use_wined3d: dict[str, bool] = dict(d.get("proton_use_wined3d", {}))

    def save(self) -> None:
        try:
            write_json(META_PATH, {
                "favorites": sorted(self.favorites),
                "playtime": self.playtime,
                "last_played": self.last_played,
                "launch_args": self.launch_args,
                "graphics_backend": self.graphics_backend,
                "winemsync": self.winemsync,
                "mtl_hud_enabled": self.mtl_hud_enabled,
                "proton_use_wined3d": self.proton_use_wined3d,
            })
        except OSError as e:
            print(f"[WARNING] Could not save {META_PATH}: {e}")


def dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def sync_library() -> None:
    """Fetch the latest catalog + manifests. Raises on failure (caller keeps the cached copy)."""
    jobs = [(OS, PROGRAM_DATA)]
    if HAS_WINDOWS_LAYER:
        jobs.append(("Windows", WINDOWS_SUBDIR))
    for remote_os, folder in jobs:
        os.makedirs(folder, exist_ok=True)
        for name in ("list.txt", "executable_paths.json", "prereq_paths.json", "icon_paths.json"):
            r = requests.get(f"{BASE_URL}/{remote_os}/{name}", timeout=15)
            r.raise_for_status()
            dest = os.path.join(folder, name)
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(r.content)
            os.replace(tmp, dest)


# --------------------------------------------------------------------------- #
# 3. Background workers
# --------------------------------------------------------------------------- #

class _Cancelled(Exception):
    pass


def format_size(n: int | None) -> str:
    if n is None:
        return "Unknown size"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.2f} KB"
    return f"{n} bytes"


def format_speed(bps: float) -> str:
    kb = bps / 1024
    return f"{kb / 1024:.2f} MB/s" if kb >= 1024 else f"{kb:.1f} KB/s"


def format_eta(sec: float) -> str:
    if sec >= 3600:
        return f"{int(sec // 3600)} h {int(sec % 3600 // 60)} min remaining"
    if sec >= 60:
        return f"{int(sec // 60)} min remaining"
    return "Less than a minute remaining"


class _ProgressStream:
    """File-like wrapper that reports bytes read and honours cancellation."""

    def __init__(self, raw, on_bytes, cancel_event: threading.Event) -> None:
        self.raw, self.on_bytes, self.cancel = raw, on_bytes, cancel_event

    def read(self, size=-1):
        if self.cancel.is_set():
            raise _Cancelled()
        data = self.raw.read(size)
        if self.cancel.is_set():
            raise _Cancelled()
        if data:
            self.on_bytes(len(data))
        return data

    def readable(self) -> bool:
        return True


def _extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, dest: str) -> None:
    real_dest = os.path.realpath(dest)
    target = os.path.realpath(os.path.join(dest, member.name))
    if target != real_dest and not target.startswith(real_dest + os.sep):
        raise RuntimeError(f"Unsafe path in archive: {member.name}")
    if hasattr(tarfile, "tar_filter"):
        tar.extract(member, dest, filter="tar")
    else:
        tar.extract(member, dest)


class DownloadWorker(QThread):
    """Streams a .tar.gz and extracts it on the fly.

    If `fixed_folder` is set, the archive is unpacked to a temp dir and its content is
    moved into `<dest>/<fixed_folder>` (used for Proton-GE).
    """

    progress = pyqtSignal(float, str)   # fraction 0..1, status text
    result = pyqtSignal(bool, str)      # ok, "" | "cancelled" | error message

    def __init__(self, url, dest: str, label: str, fixed_folder: str | None = None, parent=None):
        super().__init__(parent)
        self.url, self.dest, self.label, self.fixed_folder = url, dest, label, fixed_folder
        self._cancel = threading.Event()
        self._downloaded = 0
        self._total = 0
        self._t0 = 0.0
        self._last_emit = 0.0
        self._last_pct = -1

    def cancel(self) -> None:
        self._cancel.set()

    def _on_bytes(self, n: int) -> None:
        self._downloaded += n
        now = time.time()
        if not self._total:
            if now - self._last_emit >= 0.25:
                self._last_emit = now
                self.progress.emit(0.0, f"Downloading {self.label}: {format_size(self._downloaded)}")
            return
        frac = self._downloaded / self._total
        pct = int(frac * 100)
        if pct != self._last_pct or now - self._last_emit >= 0.25:
            self._last_pct, self._last_emit = pct, now
            speed = self._downloaded / max(now - self._t0, 0.001)
            eta = (self._total - self._downloaded) / speed if speed > 0 else 0
            self.progress.emit(
                min(frac, 1.0),
                f"Downloading {self.label}: {frac * 100:.1f}%\n{format_speed(speed)} • {format_eta(eta)}",
            )

    def run(self) -> None:
        try:
            url = self.url() if callable(self.url) else self.url
            self._t0 = time.time()
            with requests.get(url, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                self._total = int(r.headers.get("Content-Length") or 0)
                stream = _ProgressStream(r.raw, self._on_bytes, self._cancel)
                with tarfile.open(fileobj=stream, mode="r|gz") as tar:
                    if self.fixed_folder:
                        self._extract_fixed(tar)
                    else:
                        self._extract(tar, self.dest)
            self.result.emit(True, "")
        except _Cancelled:
            self.result.emit(False, "cancelled")
        except Exception as e:  # noqa: BLE001
            self.result.emit(False, str(e))

    @staticmethod
    def _extract(tar: tarfile.TarFile, dest: str) -> set[str]:
        os.makedirs(dest, exist_ok=True)
        roots: set[str] = set()
        for member in tar:
            _extract_member(tar, member, dest)
            top = member.name.lstrip("./").split("/", 1)[0]
            if top:
                roots.add(top)
        return roots

    def _extract_fixed(self, tar: tarfile.TarFile) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roots = self._extract(tar, tmp)
            src = os.path.join(tmp, next(iter(roots))) if len(roots) == 1 and \
                os.path.isdir(os.path.join(tmp, next(iter(roots)))) else tmp
            target = os.path.join(self.dest, self.fixed_folder)
            if os.path.exists(target):
                shutil.rmtree(target)
            os.makedirs(target, exist_ok=True)
            for item in os.listdir(src):
                shutil.move(os.path.join(src, item), os.path.join(target, item))


class TaskWorker(QThread):
    """Run any callable off the UI thread."""

    done = pyqtSignal(object, object)  # (result, exception)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(), None)
        except Exception as e:  # noqa: BLE001
            self.done.emit(None, e)


# --------------------------------------------------------------------------- #
# 4. Platform helpers
# --------------------------------------------------------------------------- #

def send_telemetry(settings: Settings, event: str, game: Game | None = None) -> None:
    if not settings.get("Enable Telemetry", True):
        return
    payload = {
        "event_type": event,
        "account_name": settings.account_name,
        "username": default_account_name(),
        "app_version": VERSION,
        "os": OS,
    }
    if game:
        payload["game_id"], payload["game_name"] = game.id, game.name

    def post() -> None:
        for url in TELEMETRY_ENDPOINTS:
            try:
                if requests.post(url, json=payload, timeout=5).status_code == 200:
                    return
            except requests.RequestException as e:
                print(f"[TELEMETRY] {url} failed: {type(e).__name__}: {e}")
        print(f"[TELEMETRY] all endpoints failed for {event}")

    threading.Thread(target=post, daemon=True).start()


def latest_proton_ge_url() -> str:
    r = requests.get(PROTON_API, timeout=15)
    r.raise_for_status()
    for asset in r.json().get("assets", []):
        if asset.get("name", "").endswith(".tar.gz"):
            return asset["browser_download_url"]
    raise RuntimeError("No Proton-GE tar.gz asset found on the latest release.")


def game_last_updated(game: Game) -> int | None:
    timestamps = []
    failures = []
    for source in sorted(game.sources):
        try:
            response = requests.head(f"{BASE_URL}/{source}/{game.id}.tar.gz", timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            failures.append(f"{source}: {e}")
            continue

        modified = response.headers.get("Last-Modified")
        if not modified:
            continue
        try:
            parsed = parsedate_to_datetime(modified)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            timestamps.append(int(parsed.timestamp()))
        except (TypeError, ValueError, OverflowError) as e:
            failures.append(f"{source}: invalid Last-Modified header ({e})")

    if timestamps:
        return max(timestamps)
    if failures:
        raise RuntimeError("; ".join(failures))
    return None


def find_proton_binary() -> str | None:
    root = os.path.join(PROGRAM_DATA, "Proton-GE")
    for rel in ("proton", os.path.join("dist", "proton"), os.path.join("bin", "proton")):
        path = os.path.join(root, rel)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def proton_env(use_wined3d: bool = False) -> dict:
    env = os.environ.copy()
    env["STEAM_COMPAT_DATA_PATH"] = PFX_ROOT
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = PFX_ROOT
    env["WINEDLLOVERRIDES"] = "dinput8,winhttp,winmm=n,b"
    env.pop("PROTON_USE_WINED3D", None)
    if use_wined3d:
        env["PROTON_USE_WINED3D"] = "1"
    return env


# ---- CrossOver (macOS): runs Windows builds the way Proton does on Linux ---- #

@dataclass
class CrossOver:
    app: str        # .../CrossOver.app
    root: str       # .../Contents/SharedSupport/CrossOver  (what CrossOver calls CX_ROOT)
    loader: str     # the Wine loader that runs a Windows program
    server: str     # the matching wineserver
    unix_dir: str   # .../lib/wine/<arch>-unix
    arm64: bool     # True: native arm64 Wine (FEX build); False: x86_64 Wine under Rosetta 2


def crossover_from_app(app: str) -> CrossOver | None:
    """Validate a CrossOver.app and locate its Wine loader + wineserver (None if it isn't usable)."""
    root = os.path.join(app, "Contents", "SharedSupport", "CrossOver")
    if not os.path.isdir(os.path.join(root, "lib", "wine")):
        return None

    def exe(*parts: str) -> str | None:
        p = os.path.join(root, *parts)
        return p if os.path.isfile(p) and os.access(p, os.X_OK) else None

    loader = exe("lib", "wine", "x86_64-unix", "wine")
    server = exe("bin", "wineserver") or exe("bin", "wineserver-x86")
    if loader and server:
        return CrossOver(app, root, loader, server, os.path.join(root, "lib", "wine", "x86_64-unix"), False)
    loader = exe("lib", "wine", "aarch64-unix", "wine.app", "Contents", "MacOS", "wine")
    server = exe("bin", "wineserver-arm64")
    if loader and server:
        return CrossOver(app, root, loader, server, os.path.join(root, "lib", "wine", "aarch64-unix"), True)
    return None


def find_crossover(custom: str = "") -> CrossOver | None:
    """The user's chosen CrossOver.app first, then the usual places, then Spotlight."""
    candidates: list[str] = [custom] if custom else []
    for base in ("/Applications", os.path.join(HOME, "Applications")):
        candidates.append(os.path.join(base, "CrossOver.app"))
        candidates += sorted(glob.glob(os.path.join(base, "CrossOver*.app")))  # e.g. CrossOver Preview
    seen: set[str] = set()
    for app in candidates:
        if app not in seen:
            seen.add(app)
            cx = crossover_from_app(app)
            if cx:
                return cx
    try:
        out = subprocess.run(
            ["mdfind", "kMDItemCFBundleIdentifier == 'com.codeweavers.CrossOver'"],
            capture_output=True, text=True, timeout=5).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        out = []
    for app in out:
        if app.endswith(".app") and app not in seen:
            seen.add(app)
            cx = crossover_from_app(app)
            if cx:
                return cx
    return None


def is_apple_silicon() -> bool:
    try:
        r = subprocess.run(["sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return platform.machine() == "arm64"


def rosetta_installed() -> bool:
    return os.path.exists("/Library/Apple/usr/libexec/oah/libRosettaRuntime")


def crossover_env(cx: CrossOver, graphics_backend: str = "", winemsync: bool = True,
                  mtl_hud_enabled: bool = False) -> dict:
    """Environment for running CrossOver's Wine straight against Bandit's own prefix."""
    env = os.environ.copy()
    win_dlls = os.path.join(cx.root, "lib", "wine", "x86_64-windows")
    env.update({
        "CX_ROOT": cx.root,
        "CX_HOME": os.path.join(HOME, "Library", "Application Support", "CrossOver"),
        "WINEPREFIX": WINE_PREFIX,
        "WINELOADER": cx.loader,
        "WINESERVER": cx.server,
        "WINEDLLPATH": ":".join(p for p in (win_dlls, cx.unix_dir, env.get("WINEDLLPATH", "")) if p),
        "PATH": os.path.join(cx.root, "bin") + ":" + env.get("PATH", ""),
        "WINEDLLOVERRIDES": WINE_DLL_OVERRIDES,
        "WINEMSYNC": "1" if winemsync else "0",
        "MTL_HUD_ENABLED": "1" if mtl_hud_enabled else "0",
    })
    if graphics_backend.strip():
        env["CX_GRAPHICS_BACKEND"] = graphics_backend.strip()
    d3d = os.path.join(cx.root, "lib64", "apple_gptk", "external", "libd3dshared.dylib")
    if os.path.exists(d3d):
        env["CX_APPLEGPTK_LIBD3DSHARED_PATH"] = d3d
    env.setdefault("ROSETTA_ADVERTISE_AVX", "1")   # many modern games refuse to start without AVX
    env.setdefault("WINEDEBUG", "fixme-all")       # keep the log readable
    return env


def prefix_ready() -> bool:
    return all(os.path.exists(os.path.join(WINE_PREFIX, f)) for f in ("system.reg", "user.reg"))


def create_prefix(cx: CrossOver) -> None:
    """First-launch setup: let CrossOver's Wine build the Windows environment. Raises on failure."""
    os.makedirs(WINE_PREFIX, exist_ok=True)
    env = crossover_env(cx)
    env.pop("WINEDLLOVERRIDES", None)
    log_path = os.path.join(USER_DATA, "crossover-setup.log")
    os.makedirs(USER_DATA, exist_ok=True)
    with open(log_path, "w") as log:
        subprocess.run([cx.loader, "wineboot", "--init"], env=env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=600, check=False)
        subprocess.run([cx.server, "-w"], env=env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=300, check=False)
    if not prefix_ready():
        raise RuntimeError(f"CrossOver didn't finish creating the Windows environment.\nSee {log_path}")


def wine_target(game_path: str) -> list[str]:
    """What to hand the Wine loader for this file (batch/script files go through their interpreter)."""
    ext = os.path.splitext(game_path)[1].lower()
    dos = "Z:" + game_path.replace("/", "\\")  # Wine maps the Mac's whole filesystem to Z:
    if ext in (".bat", ".cmd"):
        return ["cmd.exe", "/c", "call", dos]
    if ext == ".vbs":
        return ["wscript.exe", dos]
    return [game_path]


def create_crossover_shortcut(display_name: str, exe: str, icon: str | None, cx: CrossOver) -> None:
    """Desktop launcher for a Windows game: a tiny .app that runs it through CrossOver. Raises on failure."""
    desk, safe = desktop_path(), sanitize_filename(display_name) or "Game"
    os.makedirs(desk, exist_ok=True)
    app = os.path.join(desk, f"{safe}.app")
    shutil.rmtree(app, ignore_errors=True)
    macos, resources = os.path.join(app, "Contents", "MacOS"), os.path.join(app, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(resources)

    env = crossover_env(cx)
    keys = ("CX_ROOT", "CX_HOME", "WINEPREFIX", "WINELOADER", "WINESERVER", "WINEDLLPATH", "PATH",
            "WINEDLLOVERRIDES", "CX_APPLEGPTK_LIBD3DSHARED_PATH", "ROSETTA_ADVERTISE_AVX", "WINEDEBUG")
    lines = ["#!/bin/bash"] + [f"export {k}={shlex.quote(env[k])}" for k in keys if k in env]
    lines.append(f"cd {shlex.quote(os.path.dirname(exe))}")
    lines.append("exec " + " ".join(shlex.quote(a) for a in [cx.loader] + wine_target(exe)))
    launcher = os.path.join(macos, "launcher")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(launcher, 0o755)

    plist = {
        "CFBundleName": display_name,
        "CFBundleDisplayName": display_name,
        "CFBundleExecutable": "launcher",
        "CFBundleIdentifier": "bandit.shortcut." + (re.sub(r"[^A-Za-z0-9]+", "-", safe).strip("-").lower() or "game"),
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSApplicationCategoryType": "public.app-category.games",
        "NSHighResolutionCapable": True,
    }
    if icon and os.path.exists(icon):
        try:  # sips reads .ico/.png/.jpg and writes .icns
            subprocess.run(["sips", "-s", "format", "icns", icon, "--out", os.path.join(resources, "icon.icns")],
                           capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
        if os.path.exists(os.path.join(resources, "icon.icns")):
            plist["CFBundleIconFile"] = "icon"
    with open(os.path.join(app, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump(plist, f)


def version_tuple(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", tag)) or (0,)


def sanitize_filename(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in " -_").rstrip()


def desktop_path() -> str:
    if OS == "Windows":
        try:
            from ctypes import create_unicode_buffer, windll, wintypes
            buf = create_unicode_buffer(wintypes.MAX_PATH)
            windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)
            if os.path.isdir(buf.value):
                return buf.value
        except Exception:  # noqa: BLE001
            pass
    return os.path.join(HOME, "Desktop")


def remove_desktop_shortcut(display_name: str) -> None:
    desk, safe = desktop_path(), sanitize_filename(display_name)
    if OS == "Windows":
        names = [f"{safe}.lnk", f"{safe}.url", f"{display_name}.lnk", f"{display_name}.url"]
    elif OS == "Darwin":
        names = [safe, display_name, f"{safe}.app"]
    else:
        names = [f"{safe}.desktop", f"{display_name}.desktop"]
    for n in names:
        try:
            p = os.path.join(desk, n)
            if n.endswith(".app") and os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            elif os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def create_desktop_shortcut(display_name: str, exe: str, icon: str | None, via_proton: bool) -> None:
    """Raises on failure."""
    desk, safe = desktop_path(), sanitize_filename(display_name)
    os.makedirs(desk, exist_ok=True)

    if OS == "Windows":
        try:
            from win32com.client import Dispatch  # optional
            sc = Dispatch("WScript.Shell").CreateShortCut(os.path.join(desk, f"{safe}.lnk"))
            sc.Targetpath = exe
            sc.WorkingDirectory = os.path.dirname(exe)
            sc.IconLocation = icon or exe
            sc.save()
        except Exception:  # noqa: BLE001
            with open(os.path.join(desk, f"{safe}.url"), "w", encoding="utf-8") as f:
                f.write("[InternetShortcut]\nURL=file:///" + exe.replace("\\", "/") + "\n")
                f.write(f"IconFile={icon or exe}\nIconIndex=0\n")
    elif OS == "Darwin":
        script = (
            f'tell application "Finder" to make alias file to (POSIX file "{exe}") '
            f'at (POSIX file "{desk}") with properties {{name:"{safe}"}}'
        )
        subprocess.run(["osascript", "-e", script], check=False)
        if icon:
            subprocess.run(["osascript", "-e", (
                f'set src to POSIX file "{icon}"\n'
                f'set dst to POSIX file "{os.path.join(desk, safe)}"\n'
                'tell application "Finder" to set icon of dst to icon of src')], check=False)
    else:
        if via_proton:
            proton = find_proton_binary() or "proton"
            ext = os.path.splitext(exe)[1].lower()
            if ext in (".bat", ".cmd"):
                target = f'cmd.exe /c call "{exe}"'
            elif ext == ".vbs":
                target = f'wscript.exe "{exe}"'
            else:
                target = f'"{exe}"'
            exec_line = (f'env "STEAM_COMPAT_DATA_PATH={PFX_ROOT}" '
                         f'"STEAM_COMPAT_CLIENT_INSTALL_PATH={PFX_ROOT}" '
                         f'"WINEDLLOVERRIDES=dinput8,winhttp,winmm=n,b" "{proton}" run {target}')
        else:
            exec_line = f'"{exe}"'
        path = os.path.join(desk, f"{safe}.desktop")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join([
                "[Desktop Entry]", f"Name={display_name}", f"Exec={exec_line}",
                "Type=Application", f"Path={os.path.dirname(exe)}",
                f"Icon={icon or os.path.splitext(exe)[0]}", "Terminal=false",
            ]))
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 5. UI  (stock Qt widgets only: the look comes from the user's OS / Qt style)
# --------------------------------------------------------------------------- #

C_FAV, C_NAME, C_STATUS, C_SIZE, C_MP, C_LAST, C_TIME = range(7)
HEADERS = ["", "Name", "Status", "Size", "Multiplayer", "Last Played", "Play Time"]

ROLE_ID = Qt.ItemDataRole.UserRole + 1
ROLE_SORT = Qt.ItemDataRole.UserRole + 2
ROLE_INSTALLED = Qt.ItemDataRole.UserRole + 3
ROLE_FAV = Qt.ItemDataRole.UserRole + 4
ROLE_RECENT = Qt.ItemDataRole.UserRole + 5
ROLE_MP = Qt.ItemDataRole.UserRole + 6

SHOW_FILTERS = [
    ("all", "All Games"),
    ("installed", "Installed"),
    ("favorites", "Favorites"),
    ("recent", "Recently Played"),
]


def format_playtime(seconds: int) -> str:
    if seconds <= 0:
        return "—"
    if seconds < 60:
        return "< 1 min"
    h, m = divmod(seconds // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def format_when(ts: int) -> str:
    if not ts:
        return "Never"
    return QLocale().toString(QDateTime.fromSecsSinceEpoch(int(ts)), QLocale.FormatType.ShortFormat)


@dataclass
class Job:
    game: Game
    source: str
    dest: str
    folder: str | None
    preexisting: bool
    repair: bool = False


# ---- artwork ---------------------------------------------------------------

ART_HOSTS = ("https://cdn.cloudflare.steamstatic.com", "https://steamcdn-a.akamaihd.net")
ART_FILES = {                       # kind -> candidate file names on the CDN (first hit wins)
    "header": ["header.jpg"],       # 460x215 capsule, also used (cropped) as the list icon
    "hero": ["library_hero.jpg", "header.jpg"],
    "logo": ["logo.png"],
}
ART_EXT = {"header": "jpg", "hero": "jpg", "logo": "png"}
ART_MISSING_TTL = 7 * 24 * 3600     # don't re-ask the CDN for art it said doesn't exist


class _ArtSignals(QObject):
    done = pyqtSignal(str, str, bool)


class _ArtJob(QRunnable):
    def __init__(self, appid: str, kind: str, dest: str, signals: _ArtSignals) -> None:
        super().__init__()
        self.appid, self.kind, self.dest, self.signals = appid, kind, dest, signals

    def run(self) -> None:
        ok, definitive_missing = False, True
        for fname in ART_FILES[self.kind]:
            for host in ART_HOSTS:
                try:
                    r = requests.get(f"{host}/steam/apps/{self.appid}/{fname}", timeout=10)
                except requests.RequestException:
                    definitive_missing = False
                    continue
                if r.status_code == 200 and r.content:
                    try:
                        os.makedirs(os.path.dirname(self.dest), exist_ok=True)
                        tmp = self.dest + ".tmp"
                        with open(tmp, "wb") as f:
                            f.write(r.content)
                        os.replace(tmp, self.dest)
                        ok = True
                    except OSError:
                        definitive_missing = False
                    break
                if r.status_code == 404:
                    break               # authoritative: the other host won't have it either
                definitive_missing = False
            if ok:
                break
        if not ok and definitive_missing:
            try:
                os.makedirs(os.path.dirname(self.dest), exist_ok=True)
                open(self.dest + ".missing", "w").close()
            except OSError:
                pass
        self.signals.done.emit(self.appid, self.kind, ok)


class ArtworkManager(QObject):
    """Disk-cached Steam artwork. get() never blocks: it returns a pixmap if it has one,
    otherwise None and fetches in the background, then emits ready(appid, kind)."""

    ready = pyqtSignal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.dir = os.path.join(USER_DATA, "artwork")
        self.mem: dict[tuple[str, str], QPixmap] = {}
        self.pending: set[tuple[str, str]] = set()
        self.failed: set[tuple[str, str]] = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.signals = _ArtSignals(self)
        self.signals.done.connect(self._done)

    def path(self, appid: str, kind: str) -> str:
        return os.path.join(self.dir, appid, f"{kind}.{ART_EXT[kind]}")

    def get(self, appid: str, kind: str) -> QPixmap | None:
        key = (appid, kind)
        if key in self.mem:
            return self.mem[key]
        p = self.path(appid, kind)
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                self.mem[key] = pm
                return pm
            try:
                os.remove(p)            # corrupt download: fetch again
            except OSError:
                pass
        if key in self.pending or key in self.failed:
            return None
        try:
            if time.time() - os.path.getmtime(p + ".missing") < ART_MISSING_TTL:
                return None
        except OSError:
            pass
        self.pending.add(key)
        self.pool.start(_ArtJob(appid, kind, p, self.signals))
        return None

    def _done(self, appid: str, kind: str, ok: bool) -> None:
        key = (appid, kind)
        self.pending.discard(key)
        if ok:
            self.ready.emit(appid, kind)
        else:
            self.failed.add(key)

    def shutdown(self) -> None:
        self.pool.clear()
        self.pool.waitForDone(3000)


def square_icon_pixmap(src: QPixmap, size: int = 96) -> QPixmap:
    side = min(src.width(), src.height())
    x, y = (src.width() - side) // 2, (src.height() - side) // 2
    return src.copy(x, y, side, side).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def letter_pixmap(name: str, size: int = 96) -> QPixmap:
    """Neutral placeholder icon for games without artwork (mods etc.)."""
    pal = QApplication.palette()
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(pal.color(QPalette.ColorRole.Mid))
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.16, size * 0.16)
    f = QFont()
    f.setPixelSize(int(size * 0.55))
    f.setBold(True)
    p.setFont(f)
    p.setPen(pal.color(QPalette.ColorRole.Window))
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, (name.strip()[:1] or "?").upper())
    p.end()
    return pm


def dimmed(pm: QPixmap, opacity: float = 0.4) -> QPixmap:
    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setOpacity(opacity)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


class ArtBanner(QWidget):
    """Hero image (cropped to fill) with the game's logo over a soft shade, like a Steam page."""

    ASPECT = 215 / 460

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hero: QPixmap | None = None
        self.logo: QPixmap | None = None
        self._scaled: tuple[QSize, QPixmap] | None = None
        sp = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return int(w * self.ASPECT)

    def sizeHint(self) -> QSize:
        return QSize(460, 215)

    def set_art(self, hero: QPixmap | None, logo: QPixmap | None) -> None:
        self.hero, self.logo, self._scaled = hero, logo, None
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        r = self.rect()
        pal = self.palette()
        if self.hero is None:
            p.fillRect(r, pal.color(QPalette.ColorRole.AlternateBase))
        else:
            if self._scaled is None or self._scaled[0] != r.size():
                sc = self.hero.scaled(r.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation)
                self._scaled = (r.size(), sc)
            sc = self._scaled[1]
            p.drawPixmap(r, sc, QRect((sc.width() - r.width()) // 2, (sc.height() - r.height()) // 2,
                                      r.width(), r.height()))
            if self.logo is not None:
                g = QLinearGradient(0, r.height() * 0.45, 0, r.height())
                g.setColorAt(0, QColor(0, 0, 0, 0))
                g.setColorAt(1, QColor(0, 0, 0, 170))
                p.fillRect(r, g)
                lw, lh = int(r.width() * 0.5), int(r.height() * 0.42)
                lg = self.logo.scaled(lw, lh, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
                m = int(r.height() * 0.07)
                p.drawPixmap(m, r.height() - lg.height() - m, lg)
        p.setPen(QPen(pal.color(QPalette.ColorRole.Mid)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(0, 0, -1, -1))


def heart_path(r: QRectF) -> QPainterPath:
    x, y, w, h = r.x(), r.y(), r.width(), r.height()

    def pt(px: float, py: float) -> QPointF:
        return QPointF(x + px * w, y + py * h)

    p = QPainterPath()
    p.moveTo(pt(0.5, 1.0))
    p.cubicTo(pt(0.5, 1.0), pt(0.0, 0.62), pt(0.0, 0.30))
    p.cubicTo(pt(0.0, 0.10), pt(0.14, 0.0), pt(0.28, 0.0))
    p.cubicTo(pt(0.40, 0.0), pt(0.50, 0.10), pt(0.50, 0.22))
    p.cubicTo(pt(0.50, 0.10), pt(0.60, 0.0), pt(0.72, 0.0))
    p.cubicTo(pt(0.86, 0.0), pt(1.0, 0.10), pt(1.0, 0.30))
    p.cubicTo(pt(1.0, 0.62), pt(0.5, 1.0), pt(0.5, 1.0))
    return p


class HeartDelegate(QStyledItemDelegate):
    """Filled heart = favorite; outline appears while the row is hovered (click to toggle)."""

    FAV = QColor(226, 62, 98)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hover_row = -1

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)

        fav = bool(index.data(ROLE_FAV))
        hovered = index.row() == self.hover_row
        if not (fav or hovered):
            return
        side = min(option.rect.height() * 0.46, option.rect.width() * 0.6)
        c = QRectF(option.rect).center()
        rect = QRectF(c.x() - side / 2, c.y() - side * 0.47, side, side * 0.95)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = heart_path(rect)
        if fav:
            painter.fillPath(path, self.FAV)
        else:
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            col = QColor(option.palette.color(
                QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
            col.setAlpha(170)
            painter.setPen(QPen(col, max(1.3, side / 11)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.restore()

class DimDelegate(QStyledItemDelegate):
    """Draws the text of not-installed games dimmed.

    Done by hand instead of with Qt.ForegroundRole, because some Qt styles/versions
    (notably older Windows styles) ignore the foreground brush."""

    def paint(self, painter: QPainter, option, index) -> None:
        installed = index.sibling(index.row(), C_NAME).data(ROLE_INSTALLED)
        if installed or (option.state & QStyle.StateFlag.State_Selected):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = option.widget
        style = widget.style() if widget else QApplication.style()
        text = opt.text
        # measure the text area while the text is still set, then let the style draw
        # everything else (background, icon, alternating rows) without the text
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        opt.text = ""
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasDisplay
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        if not text:
            return
        m = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, opt, widget) + 1
        rect = rect.adjusted(m, 0, -m, 0)
        fg, bg = opt.palette.color(QPalette.ColorRole.Text), opt.palette.color(QPalette.ColorRole.Base)
        t = 0.45  # how far toward the background
        color = QColor(round(fg.red() * (1 - t) + bg.red() * t),
                       round(fg.green() * (1 - t) + bg.green() * t),
                       round(fg.blue() * (1 - t) + bg.blue() * t))
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(color)
        painter.drawText(rect, int(opt.displayAlignment.value),
                         opt.fontMetrics.elidedText(text, opt.textElideMode, rect.width()))
        painter.restore()

def scaled_font(factor: float = 1.0, bold: bool = False) -> QFont:
    base = QApplication.font()
    f = QFont(base)
    f.setBold(bold)
    if base.pointSizeF() > 0:
        f.setPointSizeF(base.pointSizeF() * factor)
    else:
        f.setPixelSize(max(1, round(base.pixelSize() * factor)))
    return f


class GameFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = "all"
        self.mp: str | None = None
        self.needle = ""
        self.setSortRole(ROLE_SORT)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        idx = self.sourceModel().index(row, C_NAME, parent)
        if self.mode == "installed" and not idx.data(ROLE_INSTALLED):
            return False
        if self.mode == "favorites" and not idx.data(ROLE_FAV):
            return False
        if self.mode == "recent" and not idx.data(ROLE_RECENT):
            return False
        if self.mp is not None and idx.data(ROLE_MP) != self.mp:
            return False
        return not self.needle or self.needle in str(idx.data(Qt.ItemDataRole.DisplayRole)).lower()


UI_SCALE_MIN, UI_SCALE_MAX, UI_SCALE_DEFAULT = 75, 200, 125
_base_font: QFont | None = None


def clamp_scale(percent) -> int:
    try:
        return max(UI_SCALE_MIN, min(UI_SCALE_MAX, int(percent)))
    except (TypeError, ValueError):
        return UI_SCALE_DEFAULT


def apply_ui_scale(percent) -> None:
    """Scale the whole UI by resizing the application font (layouts follow the font)."""
    global _base_font
    app = QApplication.instance()
    if _base_font is None:
        _base_font = QFont(app.font())
    percent = clamp_scale(percent)
    f = QFont(_base_font)
    if _base_font.pointSizeF() > 0:
        f.setPointSizeF(_base_font.pointSizeF() * percent / 100)
    else:
        f.setPixelSize(max(1, round(_base_font.pixelSize() * percent / 100)))
    app.setFont(f)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.checks: dict[str, QCheckBox] = {}

        form = QFormLayout()
        self.name_edit = QLineEdit(settings.get("Account name", ""))
        self.name_edit.setPlaceholderText(default_account_name())
        form.addRow("Username in games:", self.name_edit)

        self.initial_scale = clamp_scale(settings.get("UI scale", UI_SCALE_DEFAULT))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(UI_SCALE_MIN, UI_SCALE_MAX)
        self.scale_slider.setSingleStep(5)
        self.scale_slider.setPageStep(25)
        self.scale_slider.setTickInterval(25)
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setValue(self.initial_scale)
        self.scale_label = QLabel(f"{self.initial_scale}%")
        self.scale_label.setMinimumWidth(self.fontMetrics().horizontalAdvance("200%") + 8)
        reset = QPushButton("Reset")
        reset.clicked.connect(lambda: self.scale_slider.setValue(UI_SCALE_DEFAULT))
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.scale_slider, 1)
        scale_row.addWidget(self.scale_label)
        scale_row.addWidget(reset)
        form.addRow("Interface scale:", scale_row)
        self.scale_slider.valueChanged.connect(self._preview_scale)
        for key, value in settings.data.items():
            if key.startswith("_") or not isinstance(value, bool):
                continue
            cb = QCheckBox(key)
            cb.setChecked(value)
            self.checks[key] = cb
            form.addRow("", cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _preview_scale(self, value: int) -> None:
        """Live preview: the whole app resizes as the slider moves."""
        self.scale_label.setText(f"{value}%")
        apply_ui_scale(value)
        if hasattr(self.parent(), "on_scale_changed"):
            self.parent().on_scale_changed()
        self.adjustSize()

    def reject(self) -> None:
        if self.scale_slider.value() != self.initial_scale:
            self.scale_slider.setValue(self.initial_scale)  # revert the preview
        super().reject()

    def values(self) -> tuple[str, dict[str, bool]]:
        return self.name_edit.text(), {k: cb.isChecked() for k, cb in self.checks.items()}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Bandit - Game Launcher v{VERSION}")
        self.qs = QSettings("Bandit", "BanditGameLauncher")

        self.settings = Settings()
        self.store = InstalledStore()
        self.prereqs = PrereqStore()
        self.meta = UserMeta()

        self.games: dict[str, Game] = {}
        self.manifests: dict[str, Manifest] = {}
        self.selected_id: str | None = None
        self._installed_cache: set[str] = set()
        self.health: dict[str, bool] = {}
        self.row_of: dict[str, int] = {}
        self._icon_cache: dict[tuple[str, bool], QIcon] = {}
        self._game_update_dates: dict[str, int | None] = {}
        self._game_update_errors: dict[str, str] = {}
        self._game_update_pending: set[str] = set()
        self.art = ArtworkManager(self)
        self.art.ready.connect(self.on_art_ready)

        self.worker: QThread | None = None
        self.active: tuple[str, str | None] | None = None  # (kind, game_id)
        self.queue: list[Job] = []
        self._tasks: set[TaskWorker] = set()

        self.proc: subprocess.Popen | None = None
        self.proc_game: Game | None = None
        self.proc_mac_app: tuple[str, str] | None = None
        self.proc_cx: tuple[CrossOver, dict] | None = None
        self.proc_cx_waiting = False
        self.proc_started = 0.0

        self._build_actions()
        self._build_menus()
        self._build_ui()
        self._wire()
        self._restore_state()
        QTimer.singleShot(0, self.startup)

    # ---- construction ------------------------------------------------- #

    def _icon(self, theme: str, fallback: QStyle.StandardPixmap) -> QIcon:
        return QIcon.fromTheme(theme, self.style().standardIcon(fallback))

    def _mk(self, text: str, slot, key=None, icon: QIcon | None = None) -> QAction:
        a = QAction(text, self)
        if icon is not None:
            a.setIcon(icon)
        if key is not None:
            a.setShortcut(QKeySequence(key))
        a.triggered.connect(lambda _checked=False, s=slot: s())
        return a

    def _build_actions(self) -> None:
        SP = QStyle.StandardPixmap
        self.act_primary = self._mk("Play", self.on_primary, "Ctrl+Return",
                                    self._icon("media-playback-start", SP.SP_MediaPlay))
        self.act_fav = QAction("Favorite", self, checkable=True)
        self.act_fav.setShortcut(QKeySequence("Ctrl+D"))
        self.act_fav.triggered.connect(self.set_favorite)
        self.act_args = self._mk("Launch Options…", self.edit_launch_options)
        self.act_steam = self._mk("Open Steam Store Page", self.open_steam_page)
        self.act_browse = self._mk("Browse File Location", self.browse_location, None,
                                   self._icon("folder-open", SP.SP_DirOpenIcon))
        self.act_move = self._mk("Move Game…", self.move_game)
        self.act_shortcut = self._mk("Create Desktop Shortcut", self.make_shortcut)
        self.act_repair = self._mk("Verify / Repair Installation", self.repair)
        self.act_uninstall = self._mk("Uninstall…", self.uninstall, "Delete",
                                      self._icon("edit-delete", SP.SP_TrashIcon))
        self.act_locate = self._mk("Locate Existing Installation…", self.locate_existing_installation)

        self.act_refresh = self._mk("Refresh Library", self.refresh_library,
                                    QKeySequence.StandardKey.Refresh,
                                    self._icon("view-refresh", SP.SP_BrowserReload))
        self.act_disk = self._mk("Disk Usage…", self.show_disk_usage)
        self.act_random = self._mk("Pick a Random Game", self.pick_random, "Ctrl+Shift+R")
        self.act_find = self._mk("Find", self._focus_search, QKeySequence.StandardKey.Find)
        self.act_zoom_in = self._mk("Zoom In", lambda: self.zoom(+10))
        self.act_zoom_in.setShortcuts([QKeySequence(QKeySequence.StandardKey.ZoomIn), QKeySequence("Ctrl+=")])
        self.act_zoom_out = self._mk("Zoom Out", lambda: self.zoom(-10), QKeySequence.StandardKey.ZoomOut)
        self.act_zoom_reset = self._mk("Actual Size", lambda: self.zoom(0), "Ctrl+0")

        self.act_settings = self._mk("Settings…", self.open_settings)
        seq = QKeySequence(QKeySequence.StandardKey.Preferences)
        self.act_settings.setShortcut(seq if not seq.isEmpty() else QKeySequence("Ctrl+,"))
        self.act_settings.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.act_quit = self._mk("Quit", self.close, QKeySequence.StandardKey.Quit)
        self.act_quit.setMenuRole(QAction.MenuRole.QuitRole)

        self.act_update = self._mk("Check for Updates…", lambda: self.check_updates(manual=True))
        self.act_locate_cx = self._mk("Locate CrossOver…", self.locate_crossover)
        self.act_about = self._mk("About Bandit", self.show_about)
        self.act_about.setMenuRole(QAction.MenuRole.AboutRole)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&File")
        m.addAction(self.act_settings)
        if OS == "Darwin":
            m.addAction(self.act_locate_cx)
        m.addSeparator()
        m.addAction(self.act_quit)

        m = mb.addMenu("&Library")
        m.addAction(self.act_find)
        m.addAction(self.act_refresh)
        m.addSeparator()
        m.addAction(self.act_random)
        m.addAction(self.act_disk)

        m = mb.addMenu("&View")
        m.addAction(self.act_zoom_in)
        m.addAction(self.act_zoom_out)
        m.addAction(self.act_zoom_reset)

        m = mb.addMenu("&Game")
        m.addAction(self.act_primary)
        m.addAction(self.act_fav)
        m.addAction(self.act_args)
        m.addAction(self.act_steam)
        m.addAction(self.act_locate)
        m.addSeparator()
        for a in (self.act_browse, self.act_move, self.act_shortcut, self.act_repair):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_uninstall)

        m = mb.addMenu("&Help")
        m.addAction(self.act_update)
        m.addAction(self.act_about)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # search / filter row
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.show_combo = QComboBox()
        for key, label in SHOW_FILTERS:
            self.show_combo.addItem(label, key)
        self.mp_combo = QComboBox()
        self.mp_combo.addItem("All Player Modes", None)
        for key, (label, _desc) in MP_LABELS.items():
            self.mp_combo.addItem(label, key)
        row.addWidget(self.search, 1)
        row.addWidget(self.show_combo)
        row.addWidget(self.mp_combo)
        outer.addLayout(row)

        # list + details
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(self.splitter, 1)

        self.model = QStandardItemModel(0, len(HEADERS), self)
        self.model.setHorizontalHeaderLabels(HEADERS)
        self.model.setHeaderData(C_FAV, Qt.Orientation.Horizontal, "Favorites", Qt.ItemDataRole.ToolTipRole)
        self.proxy = GameFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.list = QTreeView()
        self.list.setModel(self.proxy)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAlternatingRowColors(True)
        self.list.setSortingEnabled(True)
        self.list.setMouseTracking(True)
        self.list.setItemDelegate(DimDelegate(self.list))
        self.heart = HeartDelegate(self.list)
        self.list.setItemDelegateForColumn(C_FAV, self.heart)
        self.list.viewport().installEventFilter(self)
        self.list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(C_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(C_FAV, QHeaderView.ResizeMode.Fixed)
        for c in (C_STATUS, C_SIZE, C_MP, C_LAST, C_TIME):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.list.sortByColumn(C_NAME, Qt.SortOrder.AscendingOrder)
        self.splitter.addWidget(self.list)

        self.stack = QStackedWidget()
        empty = QLabel("Select a game from the list.")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setEnabled(False)
        self.stack.addWidget(empty)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        self.banner = ArtBanner()
        self.banner.hide()
        pl.addWidget(self.banner)
        self.d_title = QLabel()
        self.d_title.setWordWrap(True)
        f = self.d_title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.5)
        self.d_title.setFont(f)
        pl.addWidget(self.d_title)

        self.btn_primary = QPushButton("Play")
        self.btn_primary.setDefault(True)
        self.btn_primary.setMinimumHeight(44)
        self.btn_primary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_primary.clicked.connect(self.on_primary)
        pl.addWidget(self.btn_primary)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.f_status, self.f_size, self.f_mp, self.f_platform = QLabel(), QLabel(), QLabel(), QLabel()
        self.f_location, self.f_played, self.f_last, self.f_updated, self.f_args, self.f_graphics = (
            QLabel(), QLabel(), QLabel(), QLabel(), QLabel(), QLabel())
        for lbl in (self.f_status, self.f_size, self.f_mp, self.f_platform,
                    self.f_location, self.f_played, self.f_last, self.f_updated, self.f_args,
                    self.f_graphics):
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.form = form
        for text, w in (("Status:", self.f_status), ("Size:", self.f_size), ("Multiplayer:", self.f_mp),
                        ("Version:", self.f_platform), ("Location:", self.f_location),
                        ("Play time:", self.f_played), ("Last played:", self.f_last),
                        ("Last updated on Bandit:", self.f_updated),
                        ("Launch options:", self.f_args),
                        ("CrossOver graphics backend:", self.f_graphics)):
            form.addRow(text, w)
        pl.addLayout(form)
        pl.addStretch(1)

        buttons = QHBoxLayout()
        self.btn_uninstall = QPushButton("Uninstall…")
        self.btn_uninstall.clicked.connect(self.uninstall)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_uninstall)
        pl.addLayout(buttons)
        self.stack.addWidget(panel)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)

        # centered download panel (hidden until something is downloading)
        self.dl_panel = QWidget()
        pv = QVBoxLayout(self.dl_panel)
        pv.setContentsMargins(0, 0, 0, 0)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        pv.addWidget(line)
        ph = QHBoxLayout()
        ph.addStretch(1)
        self.dl_col = QWidget()
        grid = QGridLayout(self.dl_col)
        grid.setContentsMargins(0, 6, 0, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self.dl_pad = QWidget()               # mirrors the Cancel button so the bar stays centered
        self.dl_title = QLabel()
        self.dl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 1000)
        self.dl_bar.setTextVisible(False)
        self.cancel_btn = QPushButton("Cancel")
        self.dl_pct = QLabel()
        self.dl_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.dl_detail = QLabel()
        self.dl_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.dl_pad, 1, 0)
        grid.addWidget(self.dl_title, 0, 1)
        grid.addWidget(self.dl_bar, 1, 1)
        grid.addWidget(self.cancel_btn, 1, 2)
        grid.addWidget(self.dl_pct, 2, 1)
        grid.addWidget(self.dl_detail, 3, 1)
        grid.setColumnStretch(1, 1)
        ph.addWidget(self.dl_col, 4)
        ph.addStretch(1)
        pv.addLayout(ph)
        self.dl_panel.hide()
        outer.addWidget(self.dl_panel)

        # status bar
        sb = self.statusBar()
        self.count_label = QLabel()
        self.count_label.setMinimumWidth(190)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        self.progress.setRange(0, 1000)
        self.progress.hide()
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.count_label)

    def _wire(self) -> None:
        self.search.textChanged.connect(self._on_search)
        self.show_combo.currentIndexChanged.connect(self._on_filters)
        self.mp_combo.currentIndexChanged.connect(self._on_filters)
        self.list.selectionModel().currentRowChanged.connect(self._on_current_changed)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        self.list.activated.connect(self._on_activated)
        self.list.clicked.connect(self._on_clicked)
        self.list.entered.connect(self._on_entered)
        self.cancel_btn.clicked.connect(self.cancel_active)

        self.proc_timer = QTimer(self, interval=1000)
        self.proc_timer.timeout.connect(self._poll_process)
        self.proc_timer.start()

    def _restore_state(self) -> None:
        k = clamp_scale(self.settings.get("UI scale", UI_SCALE_DEFAULT)) / 100
        avail = self.screen().availableGeometry()
        self.resize(min(int(980 * k), avail.width() - 40), min(int(620 * k), avail.height() - 80))
        geo = self.qs.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        split = self.qs.value("splitter")
        if split:
            self.splitter.restoreState(split)
        else:  # first run: favour the list, the details panel needs less room
            self.splitter.setSizes([int(self.width() * 0.68), int(self.width() * 0.32)])
        hdr = self.qs.value("header")
        if hdr:
            self.list.header().restoreState(hdr)
        show = self.qs.value("show_filter", "all")
        i = self.show_combo.findData(show)
        if i >= 0:
            self.show_combo.setCurrentIndex(i)
        self.on_scale_changed()

    # ---- helpers ------------------------------------------------------ #

    def run_task(self, fn, callback) -> TaskWorker:
        w = TaskWorker(fn, self)
        self._tasks.add(w)

        def finished(result, err) -> None:
            self._tasks.discard(w)
            callback(result, err)
            w.deleteLater()

        w.done.connect(finished)
        w.start()
        return w

    def set_status(self, text: str) -> None:
        self.statusBar().showMessage(text.replace("\n", "  —  "))

    def _show_progress(self, visible: bool, busy: bool = False) -> None:
        self.progress.setVisible(visible)
        self.progress.setRange(0, 0 if busy else 1000)
        if not busy:
            self.progress.setValue(0)

    def selected_game(self) -> Game | None:
        return self.games.get(self.selected_id) if self.selected_id else None

    def is_installed(self, game: Game) -> bool:
        return game.id in self._installed_cache

    def _focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _alert(self) -> None:
        if not self.isActiveWindow():
            QApplication.alert(self)

    # ---- startup ------------------------------------------------------ #

    def startup(self) -> None:
        self.ensure_account_name()
        self.show_telemetry_notice()
        self.reload_library()
        self.refresh_library()
        if self.settings.get("Check for updates on startup", True):
            self.check_updates(manual=False)

    def refresh_library(self) -> None:
        self.set_status("Syncing library…")
        self._show_progress(True, busy=True)
        self.act_refresh.setEnabled(False)
        self.run_task(sync_library, self._on_synced)

    def _on_synced(self, _result, err) -> None:
        self.act_refresh.setEnabled(True)
        if self.active is None:
            self._show_progress(False)
        if err:
            if not self.games:
                QMessageBox.critical(
                    self, "Can't reach the server",
                    f"Bandit couldn't download the game list and has no cached copy.\n\n{err}")
            self.set_status("Offline — showing the cached library.")
            return
        self.set_status("Library is up to date.")
        self.reload_library()

    @staticmethod
    def _fetch_latest_tag() -> str:
        r = requests.get(GITHUB_LATEST, timeout=10)
        r.raise_for_status()
        return r.json()["tag_name"]

    def check_updates(self, manual: bool) -> None:
        def done(tag, err) -> None:
            if err or not tag:
                if manual:
                    QMessageBox.warning(self, "Check for Updates", "Couldn't reach GitHub to check for updates.")
                return
            if version_tuple(tag) > version_tuple(VERSION):
                if QMessageBox.question(
                    self, "Update available",
                    f"Version {tag} is available (you have {VERSION}).\n\nOpen the download page?",
                ) == QMessageBox.StandardButton.Yes:
                    webbrowser.open(RELEASES_PAGE, new=2)
            elif manual:
                QMessageBox.information(self, "Check for Updates", f"Bandit {VERSION} is up to date.")

        self.run_task(self._fetch_latest_tag, done)

    def show_about(self) -> None:
        QMessageBox.about(
            self, "About Bandit",
            f"<b>Bandit Game Launcher</b><br>Version {VERSION}<br><br>"
            "Built with PyQt6 by FelixBand.")

    def ensure_account_name(self) -> None:
        name = (self.settings.get("Account name") or "").strip()
        if not name:
            text, ok = QInputDialog.getText(
                self, "Create Username",
                "Enter a username to use in games.\nYou can change it later in Settings.")
            name = text.strip() if ok else ""
        self.set_account_name(name)

    def set_account_name(self, name: str) -> None:
        name = name.strip() or default_account_name()
        self.settings.set("Account name", name)
        write_account_name_files(name)

    def show_telemetry_notice(self) -> None:
        if not self.settings.get("_first_launch", False):
            return
        QMessageBox.information(
            self, "Telemetry Notice",
            "Bandit collects anonymized telemetry data including:\n"
            "• Your PC username\n• Your IP address\n• Which games you download\n\n"
            "This helps me understand usage patterns.\n\n"
            "You can turn this off anytime in Settings.")
        self.settings.set("_first_launch", False)

    # ---- library / model --------------------------------------------- #

    def reload_library(self) -> None:
        self.manifests = {OS: Manifest(OS)}
        if HAS_WINDOWS_LAYER:
            self.manifests["Windows"] = Manifest("Windows")
        self.games = load_catalog()
        self._installed_cache = self.store.installed_ids()
        self.compute_health()

        self.model.removeRows(0, self.model.rowCount())
        self._icon_cache.clear()
        self.row_of = {}
        for g in sorted(self.games.values(), key=lambda g: g.name.lower()):
            items = []
            for c in range(len(HEADERS)):
                it = QStandardItem()
                it.setEditable(False)
                if c in (C_SIZE, C_TIME):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == C_FAV:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                items.append(it)
            items[C_NAME].setData(g.id, ROLE_ID)
            self.row_of[g.id] = self.model.rowCount()
            self.model.appendRow(items)
        self.update_rows()
        self._reselect()

    def compute_health(self) -> None:
        self.health = {}
        for gid in self._installed_cache:
            section, path = self.store.find(gid)
            m = self.manifests.get(section or "")
            exe = m.executables.get(gid) if m else None
            self.health[gid] = True if not (path and exe) else \
                os.path.exists(os.path.normpath(os.path.join(path, exe)))

    def state_for(self, game: Game) -> str:
        a = self.active
        if a and a[1] == game.id:
            return "downloading" if a[0] == "install" else "working"
        if self.proc is not None and self.proc_game and self.proc_game.id == game.id:
            return "running"
        if any(j.game.id == game.id for j in self.queue):
            return "queued"
        return "installed" if self.is_installed(game) else "available"

    def status_text(self, game: Game) -> str:
        st = self.state_for(game)
        if st == "running":
            return "Running"
        if st == "downloading":
            return "Installing…"
        if st == "working":
            return "Working…"
        if st == "queued":
            pos = next(i for i, j in enumerate(self.queue) if j.game.id == game.id) + 1
            return f"Queued ({pos})"
        if st == "installed":
            return "Installed" if self.health.get(game.id, True) else "Needs repair"
        return ""

    def icon_for(self, game: Game, installed: bool) -> QIcon:
        key = (game.id, installed)
        icon = self._icon_cache.get(key)
        if icon is None:
            pm = None
            if game.steam_appid:
                src = self.art.get(game.steam_appid, "header")
                if src is not None:
                    pm = square_icon_pixmap(src)
            if pm is None:
                pm = letter_pixmap(game.name)
            if not installed:
                pm = dimmed(pm)
            icon = self._icon_cache[key] = QIcon(pm)
        return icon

    def on_art_ready(self, appid: str, kind: str) -> None:
        if kind == "header":
            for g in self.games.values():
                if g.steam_appid == appid and g.id in self.row_of:
                    self._icon_cache.pop((g.id, True), None)
                    self._icon_cache.pop((g.id, False), None)
                    self.model.item(self.row_of[g.id], C_NAME).setIcon(self.icon_for(g, self.is_installed(g)))
        sel = self.selected_game()
        if sel and sel.steam_appid == appid:
            self.refresh_selection()

    def open_steam_page(self) -> None:
        g = self.selected_game()
        if g and g.steam_appid:
            webbrowser.open(f"https://store.steampowered.com/app/{g.steam_appid}")

    def eventFilter(self, obj, event) -> bool:
        if obj is self.list.viewport() and event.type() == QEvent.Type.Leave:
            self.heart.hover_row = -1
            self.list.viewport().update()
        return super().eventFilter(obj, event)

    def _on_entered(self, idx: QModelIndex) -> None:
        self.heart.hover_row = idx.row()
        self.list.viewport().update()

    def _on_clicked(self, idx: QModelIndex) -> None:
        if idx.column() == C_FAV:
            gid = idx.sibling(idx.row(), C_NAME).data(ROLE_ID)
            self._set_fav(gid, gid not in self.meta.favorites)

    def dim_brush(self) -> QBrush:
        """Text colour blended toward the background, so it adapts to light and dark themes."""
        pal = QApplication.palette()
        fg, bg = pal.color(QPalette.ColorRole.Text), pal.color(QPalette.ColorRole.Base)
        t = 0.45  # how far toward the background
        return QBrush(QColor(
            round(fg.red() * (1 - t) + bg.red() * t),
            round(fg.green() * (1 - t) + bg.green() * t),
            round(fg.blue() * (1 - t) + bg.blue() * t)))

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "row_of"):
            self._icon_cache.clear()
            self.update_rows()  # re-tint after a light/dark switch
        super().changeEvent(event)

    def update_rows(self) -> None:
        dim = self.dim_brush()
        for g in self.games.values():
            row = self.row_of.get(g.id)
            if row is None:
                continue
            it = [self.model.item(row, c) for c in range(len(HEADERS))]
            fav = g.id in self.meta.favorites
            last = self.meta.last_played.get(g.id, 0)
            secs = self.meta.playtime.get(g.id, 0)
            status = self.status_text(g)

            it[C_FAV].setData(fav, ROLE_FAV)
            it[C_FAV].setData(0 if fav else 1, ROLE_SORT)
            it[C_FAV].setToolTip("Remove from favorites" if fav else "Add to favorites")
            it[C_NAME].setIcon(self.icon_for(g, self.is_installed(g)))
            it[C_NAME].setText(g.name)
            it[C_NAME].setData(g.name.lower(), ROLE_SORT)
            it[C_NAME].setData(self.is_installed(g), ROLE_INSTALLED)
            it[C_NAME].setData(fav, ROLE_FAV)
            it[C_NAME].setData(bool(last), ROLE_RECENT)
            it[C_NAME].setData(g.mp, ROLE_MP)
            it[C_STATUS].setText(status)
            it[C_STATUS].setData(status, ROLE_SORT)
            it[C_SIZE].setText(format_size(g.size) if g.size is not None else "—")
            it[C_SIZE].setData(g.size if g.size is not None else -1, ROLE_SORT)
            it[C_MP].setText(MP_LABELS.get(g.mp, MP_LABELS["0"])[0])
            it[C_MP].setData(int(g.mp), ROLE_SORT)
            it[C_LAST].setText(format_when(last) if last else "—")
            it[C_LAST].setData(last, ROLE_SORT)
            it[C_TIME].setText(format_playtime(secs))
            it[C_TIME].setData(secs, ROLE_SORT)
            # Not-installed games are dimmed (selection colours still win when selected).
            for item in it:
                if self.is_installed(g):
                    item.setData(None, Qt.ItemDataRole.ForegroundRole)  # back to the theme's text colour
                else:
                    item.setForeground(dim)
        self.proxy.invalidateFilter()
        self.count_label.setText(f"{len(self.games)} games · {len(self._installed_cache)} installed")
        self.refresh_selection()

    def refresh_installed(self) -> None:
        self._installed_cache = self.store.installed_ids()
        self.compute_health()
        self.update_rows()

    def _reselect(self) -> None:
        if self.selected_id:
            for r in range(self.proxy.rowCount()):
                idx = self.proxy.index(r, C_NAME)
                if idx.data(ROLE_ID) == self.selected_id:
                    self.list.setCurrentIndex(idx)
                    return
        self.selected_id = None
        self.list.clearSelection()
        self.list.setCurrentIndex(QModelIndex())
        self.refresh_selection()

    def _on_search(self, text: str) -> None:
        self.proxy.needle = text.strip().lower()
        self.proxy.invalidateFilter()
        self._reselect()

    def _on_filters(self) -> None:
        self.proxy.mode = self.show_combo.currentData()
        self.proxy.mp = self.mp_combo.currentData()
        self.proxy.invalidateFilter()
        self._reselect()

    def _on_current_changed(self, current: QModelIndex, _prev: QModelIndex) -> None:
        if current.isValid():
            self.selected_id = current.sibling(current.row(), C_NAME).data(ROLE_ID)
            self.refresh_selection()

    def _on_activated(self, idx: QModelIndex) -> None:
        game = self.games.get(idx.sibling(idx.row(), C_NAME).data(ROLE_ID))
        if game and self.state_for(game) == "installed":
            self.play(game)

    def pick_random(self) -> None:
        n = self.proxy.rowCount()
        if not n:
            QMessageBox.information(self, "Random Game", "No games to pick from with the current filters.")
            return
        idx = self.proxy.index(random.randrange(n), C_NAME)
        self.list.setCurrentIndex(idx)
        self.list.scrollTo(idx)

    # ---- selection: details panel + action states --------------------- #

    def refresh_selection(self) -> None:
        game = self.selected_game()
        busy = self.active is not None
        if not game:
            self.stack.setCurrentIndex(0)
            for a in (self.act_primary, self.act_fav, self.act_args, self.act_steam, self.act_browse, self.act_move,
                      self.act_shortcut, self.act_repair, self.act_uninstall, self.act_locate):
                a.setEnabled(False)
            self.act_primary.setText("Play")
            return

        st = self.state_for(game)
        installed = self.is_installed(game)
        label, desc = MP_LABELS.get(game.mp, MP_LABELS["0"])
        section, path = self.store.find(game.id) if installed else (None, None)
        secs = self.meta.playtime.get(game.id, 0)
        last = self.meta.last_played.get(game.id, 0)
        args = self.meta.launch_args.get(game.id, "")
        graphics_backend = self.meta.graphics_backend.get(game.id, "")

        self.stack.setCurrentIndex(1)
        self.d_title.setText(game.name)
        self.f_status.setText(self.status_text(game) or "Not installed")
        self.f_size.setText(format_size(game.size))
        self.f_mp.setText(f"{label} — {desc}")
        if HAS_WINDOWS_LAYER:
            if OS in game.sources:
                self.f_platform.setText(f"Native {NATIVE_NAME}" + (" (Windows build also available)"
                                                                   if "Windows" in game.sources else ""))
            else:
                self.f_platform.setText(f"Windows (runs through {COMPAT_LAYER})")
        self.form.setRowVisible(self.f_platform, HAS_WINDOWS_LAYER)
        self.f_location.setText(path or "—")
        self.f_played.setText(format_playtime(secs))
        self.f_last.setText(format_when(last) if last else "Never")
        self.f_updated.setText(self._game_update_text(game))
        self.f_args.setText(args or "—")
        self.f_graphics.setText(graphics_backend or "Default")
        self.form.setRowVisible(self.f_location, installed)
        self.form.setRowVisible(self.f_graphics, OS == "Darwin")

        text, enabled = {
            "downloading": ("Cancel Download", True),
            "working": ("Working…", False),
            "running": ("Quit Game", True),
            "installed": ("▶ Play", True),
            "queued": ("Remove from Queue", True),
            "available": ("Add to Queue" if busy else "⇩ Install", True),
        }[st]
        self.act_primary.setText(text)
        self.act_primary.setEnabled(enabled)
        self.btn_primary.setText(text)
        self.btn_primary.setEnabled(enabled)

        idle_installed = st == "installed" and not busy
        self.act_uninstall.setEnabled(idle_installed)
        self.btn_uninstall.setEnabled(idle_installed)
        self.btn_uninstall.setVisible(installed)
        self.act_locate.setEnabled(not installed and not busy)
        self.act_repair.setEnabled(idle_installed or (st == "installed" and busy))
        self.act_move.setEnabled(idle_installed)
        self.act_browse.setEnabled(installed)
        self.act_shortcut.setEnabled(installed)
        self.act_args.setEnabled(True)
        self.act_fav.setEnabled(True)
        fav = game.id in self.meta.favorites
        self.act_fav.setChecked(fav)

        appid = game.steam_appid
        self.act_steam.setEnabled(bool(appid))
        self.banner.setVisible(bool(appid))
        if appid:
            hero = self.art.get(appid, "hero") or self.art.get(appid, "header")
            self.banner.set_art(hero, self.art.get(appid, "logo"))

    def _game_update_text(self, game: Game) -> str:
        self.f_updated.setToolTip("")
        if game.id in self._game_update_dates:
            timestamp = self._game_update_dates[game.id]
            return format_when(timestamp) if timestamp else "Unavailable"
        if game.id in self._game_update_errors:
            self.f_updated.setToolTip(self._game_update_errors[game.id])
            return "Could not check"

        if game.id not in self._game_update_pending:
            self._game_update_pending.add(game.id)
            self.run_task(
                lambda: game_last_updated(game),
                lambda timestamp, error, gid=game.id: self._on_game_update_checked(gid, timestamp, error),
            )
        return "Checking…"

    def _on_game_update_checked(self, game_id: str, timestamp: int | None, error: Exception | None) -> None:
        self._game_update_pending.discard(game_id)
        if error:
            self._game_update_errors[game_id] = str(error)
            game = self.games.get(game_id)
            if game:
                self.set_status(f"Couldn't check the Bandit update date for {game.name}: {error}")
        else:
            self._game_update_dates[game_id] = timestamp
        if self.selected_id == game_id:
            self.refresh_selection()

    def _on_context_menu(self, pos) -> None:
        idx = self.list.indexAt(pos)
        if not idx.isValid():
            return
        self.list.setCurrentIndex(idx)
        menu = QMenu(self)
        menu.addAction(self.act_primary)
        menu.addAction(self.act_fav)
        menu.addAction(self.act_args)
        menu.addSeparator()
        menu.addAction(self.act_locate)
        if self.is_installed(self.selected_game()):
            menu.addSeparator()
            for a in (self.act_browse, self.act_move, self.act_shortcut, self.act_repair):
                menu.addAction(a)
            menu.addSeparator()
            menu.addAction(self.act_uninstall)
        menu.exec(self.list.viewport().mapToGlobal(pos))

    # ---- favorites / launch options ---------------------------------- #

    def set_favorite(self, on: bool) -> None:
        if self.selected_id:
            self._set_fav(self.selected_id, on)

    def _set_fav(self, game_id: str, on: bool) -> None:
        (self.meta.favorites.add if on else self.meta.favorites.discard)(game_id)
        self.meta.save()
        self.update_rows()
        if self.proxy.mode == "favorites":
            self._reselect()

    def edit_launch_options(self) -> None:
        game = self.selected_game()
        if not game:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Launch Options — {game.name}")
        args_edit = QLineEdit(self.meta.launch_args.get(game.id, ""))
        form = QFormLayout()
        form.addRow("Command-line arguments:", args_edit)
        if OS == "Darwin":
            backend_combo = QComboBox()
            backend_combo.addItem("Default", "")
            for backend_option in ("d3dmetal", "dxvk", "dxmt", "wined3d"):
                backend_combo.addItem(backend_option, backend_option)
            backend_combo.addItem("Other…", None)
            backend_other = QLineEdit()
            backend_other.setPlaceholderText("Enter a graphics backend")
            saved_backend = self.meta.graphics_backend.get(game.id, "")
            saved_index = backend_combo.findData(saved_backend)
            if saved_index < 0:
                saved_index = backend_combo.findData(None)
                backend_other.setText(saved_backend)
            backend_combo.setCurrentIndex(saved_index)
            winemsync_check = QCheckBox("Enabled")
            winemsync_check.setChecked(self.meta.winemsync.get(game.id, True))
            mtl_hud_check = QCheckBox("Enabled")
            mtl_hud_check.setChecked(self.meta.mtl_hud_enabled.get(game.id, False))
            form.addRow("CrossOver graphics backend:", backend_combo)
            form.addRow("", backend_other)
            form.addRow("MSync:", winemsync_check)
            form.addRow("Metal HUD (Peformance overlay):", mtl_hud_check)
            form.setRowVisible(backend_other, backend_combo.currentData() is None)
            backend_combo.currentIndexChanged.connect(
                lambda _index: form.setRowVisible(backend_other, backend_combo.currentData() is None))
            note = QLabel("These options apply to Windows games launched through CrossOver on macOS.")
        elif OS == "Linux":
            proton_wined3d_check = QCheckBox("Enabled")
            proton_wined3d_check.setChecked(self.meta.proton_use_wined3d.get(game.id, False))
            form.addRow("Use WineD3D (PROTON_USE_WINED3D):", proton_wined3d_check)
            note = QLabel("Use WineD3D instead of DXVK for compatibility with older graphics cards.")
        else:
            note = None
        if note:
            note.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addLayout(form)
        if note:
            layout.addWidget(note)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        args = args_edit.text().strip()
        if args:
            self.meta.launch_args[game.id] = args
        else:
            self.meta.launch_args.pop(game.id, None)
        if OS == "Darwin":
            backend_option = backend_combo.currentData()
            backend = backend_other.text().strip() if backend_option is None else backend_option
            if backend:
                self.meta.graphics_backend[game.id] = backend
            else:
                self.meta.graphics_backend.pop(game.id, None)
            self.meta.winemsync[game.id] = winemsync_check.isChecked()
            self.meta.mtl_hud_enabled[game.id] = mtl_hud_check.isChecked()
        elif OS == "Linux":
            self.meta.proton_use_wined3d[game.id] = proton_wined3d_check.isChecked()
        self.meta.save()
        self.refresh_selection()

    # ---- primary action ---------------------------------------------- #

    def on_primary(self) -> None:
        game = self.selected_game()
        if not game:
            return
        st = self.state_for(game)
        if st == "downloading":
            self.cancel_active()
        elif st == "running":
            self.quit_game()
        elif st == "installed":
            self.play(game)
        elif st == "queued":
            self.queue = [j for j in self.queue if j.game.id != game.id]
            self.set_status(f"Removed {game.name} from the queue.")
            self.update_rows()
        elif st == "available":
            self.request_install(game)

    def cancel_active(self) -> None:
        if isinstance(self.worker, DownloadWorker):
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.dl_detail.setText("Cancelling…")

    # ---- centered download panel -------------------------------------- #

    def dl_show(self, name: str) -> None:
        self.dl_title.setText(f"Downloading — {name}")
        self.dl_bar.setRange(0, 1000)
        self.dl_bar.setValue(0)
        self.dl_pct.setText("0.0%")
        self.dl_detail.setText("Starting…")
        self._sync_dl_pad()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.show()
        self.dl_panel.show()

    def dl_busy(self, title: str, name: str) -> None:
        self.dl_title.setText(f"{title} — {name}")
        self.dl_bar.setRange(0, 0)
        self.dl_pct.setText("")
        self.dl_detail.setText("")
        self.cancel_btn.hide()
        self._sync_dl_pad()
        self.dl_panel.show()

    def _sync_dl_pad(self) -> None:
        self.dl_pad.setFixedWidth(self.cancel_btn.sizeHint().width())

    def dl_hide(self) -> None:
        self.dl_panel.hide()
        self.dl_bar.setRange(0, 1000)
        self.dl_bar.setValue(0)

    # ---- install queue ------------------------------------------------ #

    def request_install(self, game: Game, repair: bool = False) -> None:
        """Ask the questions (version, location, space) now, then queue the download."""
        if self.state_for(game) in ("downloading", "queued"):
            return

        if repair:
            source, dest = self.store.find(game.id)
            if not source or not dest:
                QMessageBox.critical(self, "Repair", "Could not find installation information.")
                return
        else:
            source = OS
            if HAS_WINDOWS_LAYER:
                if OS in game.sources and "Windows" in game.sources:
                    box = QMessageBox(self)
                    box.setWindowTitle("Which version?")
                    box.setText(f"This game has a {NATIVE_NAME} and a Windows version. "
                                "Which would you like to install?")
                    native = box.addButton(f"Native {NATIVE_NAME} (recommended)", QMessageBox.ButtonRole.AcceptRole)
                    win = box.addButton(f"Windows (needs {COMPAT_LAYER})", QMessageBox.ButtonRole.AcceptRole)
                    box.addButton(QMessageBox.StandardButton.Cancel)
                    box.exec()
                    clicked = box.clickedButton()
                    if clicked is win:
                        source = "Windows"
                    elif clicked is not native:
                        return
                elif "Windows" in game.sources:
                    source = "Windows"

            # macOS keeps native .app games in /Applications; Windows builds go beside Bandit's data
            dest = base_dest = WIN_GAMES_FOLDER if (OS == "Darwin" and source == "Windows") else GAMES_FOLDER
            if self.settings.get("Ask where to install games to", False):
                dest = QFileDialog.getExistingDirectory(self, "Choose install folder", base_dest)
                if not dest:
                    return
            os.makedirs(dest, exist_ok=True)

            if game.size is not None:
                free = shutil.disk_usage(dest).free
                if free < game.size and QMessageBox.question(
                    self, "Not enough space",
                    f"This game needs {format_size(game.size)} but only {format_size(free)} is free.\n"
                    "Continue anyway?",
                ) != QMessageBox.StandardButton.Yes:
                    return

        manifest = self.manifests.get(source)
        folder = manifest.first_folder(game.id) if manifest else None
        preexisting = repair or (bool(folder) and os.path.exists(os.path.join(dest, folder)))
        self.queue.append(Job(game, source, dest, folder, preexisting, repair))
        self.update_rows()
        self._pump()

    def _pump(self) -> None:
        if self.active is None and self.queue:
            self._start_job(self.queue.pop(0))
        else:
            self.update_rows()

    def _start_job(self, job: Job) -> None:
        game = job.game
        send_telemetry(self.settings, "download_started", game)
        w = DownloadWorker(f"{BASE_URL}/{job.source}/{game.id}.tar.gz", job.dest, game.name, parent=self)
        w.result.connect(lambda ok, msg, j=job: self._on_install_done(j, ok, msg))
        self._start_download(w, ("install", game.id))

    def _start_download(self, w: DownloadWorker, active: tuple[str, str | None]) -> None:
        self.worker, self.active = w, active
        w.progress.connect(self._on_progress)
        self.set_status("")
        self.dl_show(w.label)
        w.start()
        self.update_rows()

    def _on_progress(self, frac: float, text: str) -> None:
        lines = text.split("\n")
        if len(lines) > 1:  # known size: percentage + "speed • time left"
            self.dl_bar.setRange(0, 1000)
            self.dl_bar.setValue(int(frac * 1000))
            self.dl_pct.setText(f"{frac * 100:.1f}%")
            self.dl_detail.setText(lines[1])
        else:  # unknown size: busy bar + bytes so far
            self.dl_bar.setRange(0, 0)
            self.dl_pct.setText("")
            self.dl_detail.setText(text.split(": ", 1)[-1])

    def _finish_download(self) -> None:
        w = self.worker
        self.worker, self.active = None, None
        self.dl_hide()
        if w:
            w.wait(2000)
            w.deleteLater()

    def _on_install_done(self, job: Job, ok: bool, msg: str) -> None:
        game = job.game
        self._finish_download()
        if ok:
            self.store.add(job.source, game.id, job.dest)
            self.set_status(f"{game.name} {'repaired' if job.repair else 'installed'}.")
            send_telemetry(self.settings, "game_installed", game)
            self._alert()
        else:
            if job.folder and not job.preexisting:  # drop the half-extracted folder
                shutil.rmtree(os.path.join(job.dest, job.folder), ignore_errors=True)
            self.set_status("Download cancelled." if msg == "cancelled" else "Download failed.")
            if msg != "cancelled":
                QMessageBox.warning(self, "Download failed", f"Failed to install {game.name}:\n{msg}")
        self.refresh_installed()
        self._pump()

    def repair(self) -> None:
        game = self.selected_game()
        if not game or not self.is_installed(game):
            return
        if QMessageBox.question(
            self, "Verify / Repair",
            f"Bandit will re-download {game.name} over the existing files to fix anything missing "
            f"or damaged ({format_size(game.size)}).\n\nContinue?",
        ) == QMessageBox.StandardButton.Yes:
            self.request_install(game, repair=True)

    # ---- play --------------------------------------------------------- #

    def play(self, game: Game) -> None:
        if self.proc is not None:
            QMessageBox.information(self, "Game already running", "Quit the running game before launching another.")
            return
        section, install_path = self.store.find(game.id)
        manifest = self.manifests.get(section or "")
        exe_rel = manifest.executables.get(game.id) if manifest else None
        if not section or not install_path or not exe_rel:
            QMessageBox.critical(self, "Error", "Unable to locate the installed game.")
            return
        game_path = os.path.normpath(os.path.join(install_path, exe_rel))

        reqs = manifest.prereqs.get(game.id)
        if OS == "Windows" and reqs and not self.prereqs.done(game.id):
            self._install_prereqs(game, section, install_path, manifest, reqs, game_path)
        else:
            self._launch(game, section, game_path)

    def _install_prereqs(self, game, section, install_path, manifest, reqs, game_path) -> None:
        folder = manifest.first_folder(game.id) or ""
        cmds = []
        for req in reqs:
            full = os.path.normpath(os.path.join(install_path, folder, req["path"]))
            cmds.append(f'& "{full}" {req["command"]}' if req.get("command") else f'& "{full}"')
        script = "; ".join(cmds)
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        ps = (f"Start-Process powershell -ArgumentList '-NoProfile -EncodedCommand {encoded}' "
              "-Verb RunAs -Wait")

        def work():
            return subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True, check=True)

        def done(_res, err) -> None:
            self.active = None
            self.dl_hide()
            self.set_status("")
            if err:
                detail = getattr(err, "stderr", "") or str(err)
                QMessageBox.critical(self, "Prerequisite installation failed", detail)
                self.update_rows()
                self._pump()
                return
            self.prereqs.mark(game.id)
            QMessageBox.information(self, "Success", "All prerequisites installed.")
            self.update_rows()
            self._launch(game, section, game_path)
            self._pump()

        self.active = ("prereq", game.id)
        self.set_status("Approve the administrator prompt to continue.")
        self.dl_busy("Installing prerequisites", game.name)
        self.update_rows()
        self.run_task(work, done)

    def _launch(self, game: Game, section: str, game_path: str) -> None:
        try:
            raw_args = self.meta.launch_args.get(game.id, "")
            try:
                args = shlex.split(raw_args, posix=(OS != "Windows")) if raw_args else []
            except ValueError as e:
                QMessageBox.warning(self, "Launch Options", f"Couldn't parse the launch options:\n{e}")
                return
            proc = None
            self.proc_mac_app = None
            self.proc_cx = None
            self.proc_cx_waiting = False
            workdir = os.path.dirname(game_path)

            if OS == "Darwin" and section == "Windows":
                cx = self._ensure_crossover(then=lambda: self.play(game))
                if cx is None:
                    return
                write_account_name_files(self.settings.account_name)  # the prefix may be new
                env = crossover_env(
                    cx,
                    self.meta.graphics_backend.get(game.id, ""),
                    self.meta.winemsync.get(game.id, True),
                    self.meta.mtl_hud_enabled.get(game.id, False),
                )
                log_path = os.path.join(USER_DATA, "crossover.log")
                with open(log_path, "w") as log:
                    proc = subprocess.Popen([cx.loader] + wine_target(game_path) + args, cwd=workdir, env=env,
                                            stdout=log, stderr=subprocess.STDOUT)
                self.proc_cx = (cx, env)
            elif OS == "Darwin":
                if game_path.endswith(".app"):
                    cmd = ["open", "-W", game_path] + (["--args"] + args if args else [])
                    proc = subprocess.Popen(cmd, cwd=workdir)
                    self.proc_mac_app = (game_path, os.path.splitext(os.path.basename(game_path))[0])
                elif os.path.exists(game_path):
                    proc = subprocess.Popen([game_path] + args, cwd=workdir)
            elif OS == "Linux" and section == "Windows":
                proton = self._ensure_proton(then=lambda: self.play(game))
                if not proton:
                    return
                ext = os.path.splitext(game_path)[1].lower()
                if ext in (".bat", ".cmd"):
                    cmd = [proton, "run", "cmd.exe", "/c", "call", game_path] + args
                elif ext == ".vbs":
                    cmd = [proton, "run", "wscript.exe", game_path] + args
                else:
                    cmd = [proton, "run", game_path] + args
                proc = subprocess.Popen(
                    cmd, cwd=workdir,
                    env=proton_env(self.meta.proton_use_wined3d.get(game.id, False)))
            else:
                if OS == "Linux" and not os.access(game_path, os.X_OK):
                    try:
                        os.chmod(game_path, os.stat(game_path).st_mode | 0o111)
                    except OSError:
                        pass
                flags = subprocess.CREATE_NEW_PROCESS_GROUP if OS == "Windows" else 0
                ext = os.path.splitext(game_path)[1].lower()
                if OS == "Windows" and ext in (".bat", ".cmd"):
                    cmd = ["cmd.exe", "/d", "/c", "call", game_path] + args
                elif OS == "Windows" and ext == ".vbs":
                    cmd = ["wscript.exe", game_path] + args
                else:
                    cmd = [game_path] + args
                proc = subprocess.Popen(cmd, cwd=workdir, creationflags=flags)

            if proc is None:
                QMessageBox.critical(self, "Error", "The game's executable could not be found.")
                return
            self.proc, self.proc_game = proc, game
            self.proc_started = time.time()
            self.meta.last_played[game.id] = int(self.proc_started)
            self.meta.save()
            self.set_status(f"{game.name} is running.")
            send_telemetry(self.settings, "game_launched", game)
            self.update_rows()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to launch the game:\n{e}")

    def _ensure_proton(self, then) -> str | None:
        binary = find_proton_binary()
        if binary:
            return binary
        if self.active:
            QMessageBox.information(self, "Download in progress",
                                    "Please wait for the current task to finish before launching a Windows game.")
            return None
        if QMessageBox.question(
            self, "Download Proton-GE?",
            "This game needs Proton-GE to run on Linux. Download the latest release now?",
        ) != QMessageBox.StandardButton.Yes:
            return None
        w = DownloadWorker(latest_proton_ge_url, PROGRAM_DATA, "Proton-GE", fixed_folder="Proton-GE", parent=self)

        def done(ok: bool, msg: str) -> None:
            self._finish_download()
            if ok:
                send_telemetry(self.settings, "proton_ge_installed")
                self.set_status("Proton-GE downloaded.")
                then()
            else:
                self.set_status("Download cancelled." if msg == "cancelled" else "Download failed.")
                if msg != "cancelled":
                    QMessageBox.warning(self, "Proton-GE", f"Download failed:\n{msg}")
            self.update_rows()
            self._pump()

        w.result.connect(done)
        self._start_download(w, ("proton", None))
        return None

    # ---- CrossOver setup (macOS twin of _ensure_proton) ---------------- #

    def _ensure_crossover(self, then) -> CrossOver | None:
        """Return a ready-to-use CrossOver, or None after starting whatever it still needs
        (locating it, installing Rosetta, creating the prefix) and arranging for then() to run."""
        if self.active:
            QMessageBox.information(self, "Task in progress",
                                    "Please wait for the current task to finish before launching a Windows game.")
            return None
        cx = find_crossover(self.settings.get("CrossOver path", ""))
        if cx is None:
            self._offer_crossover(then)
            return None
        if not cx.arm64 and is_apple_silicon() and not rosetta_installed():
            self._install_rosetta(then)
            return None
        if not prefix_ready():
            self._create_prefix(cx, then)
            return None
        return cx

    def _offer_crossover(self, then) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("CrossOver required")
        box.setText("Windows games run on your Mac through CrossOver, which Bandit can't download for you. "
                    "CrossOver is made by CodeWeavers (paid, with a free trial).\n\n"
                    "Install it and try again, or point Bandit at your copy.")
        get = box.addButton("Get CrossOver…", QMessageBox.ButtonRole.AcceptRole)
        loc = box.addButton("Locate CrossOver…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is get:
            webbrowser.open(CROSSOVER_DOWNLOAD_PAGE, new=2)
        elif clicked is loc and self.locate_crossover():
            then()

    def locate_crossover(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(self, "Select CrossOver", "/Applications", "Applications (*.app)")
        if not path:
            return False
        if crossover_from_app(path) is None:
            QMessageBox.warning(self, "Locate CrossOver",
                                "That doesn't look like a CrossOver installation Bandit can use.")
            return False
        self.settings.set("CrossOver path", path)
        self.set_status(f"Using {os.path.basename(path)}.")
        return True

    def _run_setup(self, kind: str, title: str, name: str, fn, on_ok, fail_title: str) -> None:
        """Run a long setup step off the UI thread with the centered busy panel (like a download)."""
        self.active = (kind, None)
        self.set_status("")
        self.dl_busy(title, name)
        self.update_rows()

        def done(_res, err) -> None:
            self.active = None
            self.dl_hide()
            if err:
                self.set_status("")
                QMessageBox.warning(self, fail_title, str(err))
            else:
                on_ok()
            self.update_rows()
            self._pump()

        self.run_task(fn, done)

    def _install_rosetta(self, then) -> None:
        if QMessageBox.question(
            self, "Install Rosetta?",
            "CrossOver needs Apple's Rosetta 2 on this Mac. Install it now? (You'll be asked for your password.)",
        ) != QMessageBox.StandardButton.Yes:
            return

        def work() -> None:
            r = subprocess.run(
                ["osascript", "-e", 'do shell script "/usr/sbin/softwareupdate --install-rosetta '
                                    '--agree-to-license" with administrator privileges'],
                capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "The Rosetta installation didn't complete.")

        def ok() -> None:
            self.set_status("Rosetta installed.")
            then()

        self._run_setup("rosetta", "Installing", "Rosetta 2", work, ok, "Rosetta")

    def _create_prefix(self, cx: CrossOver, then) -> None:
        def ok() -> None:
            write_account_name_files(self.settings.account_name)
            send_telemetry(self.settings, "crossover_prefix_created")
            self.set_status("Windows environment ready.")
            then()

        self._run_setup("prefix", "Setting up CrossOver", "first launch only",
                        lambda: create_prefix(cx), ok, "CrossOver")

    # ---- running game ------------------------------------------------- #

    def _game_finished(self) -> None:
        game = self.proc_game
        if game and self.proc_started:
            elapsed = int(time.time() - self.proc_started)
            if elapsed >= 1:
                self.meta.playtime[game.id] = self.meta.playtime.get(game.id, 0) + elapsed
                self.meta.save()
        self.proc, self.proc_game, self.proc_mac_app, self.proc_started = None, None, None, 0.0
        self.proc_cx = None
        self.proc_cx_waiting = False
        send_telemetry(self.settings, "game_exited", game)

    def quit_game(self) -> None:
        proc = self.proc
        if proc is None:
            return
        self._terminate(proc)
        self._game_finished()
        self.set_status("Game closed.")
        self.update_rows()

    def _terminate(self, proc: subprocess.Popen) -> None:
        if self.proc_cx:  # take down everything running in the prefix, not just the loader
            cx, env = self.proc_cx
            try:
                subprocess.run([cx.server, "-k"], env=env, capture_output=True, timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        if OS == "Darwin" and self.proc_mac_app:
            path, name = self.proc_mac_app
            for cmd in (["osascript", "-e", f'tell application "{name}" to quit'], ["pkill", "-f", path]):
                try:
                    subprocess.run(cmd, capture_output=True, text=True)
                except OSError:
                    pass
        if OS == "Windows" and proc.poll() is None:
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, text=True)
            except OSError:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    def _poll_process(self) -> None:
        if self.proc is not None and self.proc.poll() is not None:
            if self.proc_cx and not self.proc_cx_waiting:
                # Wait until launch has completed before watching wineserver, avoiding a startup race.
                cx, env = self.proc_cx
                try:
                    self.proc = subprocess.Popen([cx.server, "-w"], env=env,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.proc_cx_waiting = True
                    return
                except OSError as e:
                    QMessageBox.warning(self, "Game tracking",
                                        f"The game launched, but Bandit couldn't track it reliably:\n{e}")
                    self.proc_cx = None
            name = self.proc_game.name if self.proc_game else "Game"
            self._game_finished()
            self.set_status(f"{name} exited.")
            self.update_rows()

    # ---- uninstall / move / browse / shortcut ------------------------- #

    def _install_info(self, game: Game):
        section, path = self.store.find(game.id)
        manifest = self.manifests.get(section or "")
        folder = manifest.first_folder(game.id) if manifest else None
        return section, path, manifest, folder

    @staticmethod
    def _existing_install_root(selected_dir: str, manifest: Manifest, game_id: str) -> str | None:
        executable = manifest.executables.get(game_id)
        if not executable:
            return None
        parts = executable.replace("\\", "/").split("/")
        folder, relative_executable = parts[0], parts[1:]
        selected_dir = os.path.abspath(selected_dir)
        candidates = [selected_dir]

        if relative_executable and os.path.basename(selected_dir).casefold() == folder.casefold():
            candidates.append(os.path.dirname(selected_dir))

        for root in candidates:
            if os.path.exists(os.path.join(root, *parts)):
                return root

        with os.scandir(selected_dir) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False) and os.path.exists(os.path.join(entry.path, *parts)):
                    return entry.path
        return None

    def locate_existing_installation(self) -> None:
        game = self.selected_game()
        if not game or self.is_installed(game) or self.active:
            return

        selected_dir = QFileDialog.getExistingDirectory(
            self, f"Locate {game.name}", GAMES_FOLDER)
        if not selected_dir:
            return

        sources = [source for source in (OS, "Windows") if source in game.sources]
        try:
            for source in sources:
                manifest = self.manifests.get(source)
                if manifest is None:
                    continue
                install_root = self._existing_install_root(selected_dir, manifest, game.id)
                if install_root:
                    self.store.add(source, game.id, install_root)
                    self.set_status(f"Found existing {game.name} installation.")
                    self.refresh_installed()
                    return
        except OSError as e:
            QMessageBox.warning(self, "Locate Existing Installation",
                                f"Could not inspect the selected folder:\n{e}")
            return

        QMessageBox.information(
            self, "Game Not Found",
            f"Couldn't find the expected game launcher for {game.name} in that folder or its "
            "immediate subfolders. Select the game folder or the folder containing it.")

    def uninstall(self) -> None:
        game = self.selected_game()
        if not game or self.active:
            return
        section, install_path, _m, folder = self._install_info(game)
        if not section or not install_path or not folder:
            QMessageBox.critical(self, "Error", "Could not find installation information for this game.")
            return
        full = os.path.join(install_path, folder)
        if QMessageBox.question(
            self, "Uninstall",
            f"Are you sure you want to uninstall {game.name}?\n\nThis will delete:\n{full}",
        ) != QMessageBox.StandardButton.Yes:
            return

        self.active = ("uninstall", game.id)
        self.set_status("")
        self.dl_busy("Uninstalling", game.name)
        self.update_rows()

        def work():
            shutil.rmtree(full)

        def done(_res, err) -> None:
            self.active = None
            self.dl_hide()
            if err:
                QMessageBox.warning(self, "Error",
                                    f"Failed to delete the game folder:\n{err}\n\nRemoving the entry anyway.")
            self.store.remove(section, game.id)
            self.prereqs.clear(game.id)
            remove_desktop_shortcut(game.name)
            send_telemetry(self.settings, "game_uninstalled", game)
            self.set_status(f"{game.name} uninstalled.")
            self.refresh_installed()
            self._pump()

        self.run_task(work, done)

    def move_game(self) -> None:
        game = self.selected_game()
        if not game:
            return
        if self.active:
            QMessageBox.information(self, "Move Game", "Please wait for the current task to finish.")
            return
        if self.proc_game and self.proc_game.id == game.id:
            QMessageBox.information(self, "Move Game", "Quit the game before moving it.")
            return
        section, install_path, _m, folder = self._install_info(game)
        if not section or not install_path or not folder:
            QMessageBox.critical(self, "Move Game", "Could not determine the current install location.")
            return
        source = os.path.normpath(os.path.join(install_path, folder))
        if not os.path.exists(source):
            QMessageBox.critical(self, "Move Game", f"Game folder not found:\n{source}")
            return
        target_parent = QFileDialog.getExistingDirectory(self, "Move game to…", install_path)
        if not target_parent:
            return
        target_parent = os.path.normpath(target_parent)
        if os.path.abspath(target_parent) == os.path.abspath(install_path):
            QMessageBox.information(self, "Move Game", "The game is already in that folder.")
            return
        target = os.path.join(target_parent, os.path.basename(source))
        replace = os.path.exists(target)
        if replace and QMessageBox.question(
            self, "Move Game",
            f"A folder named '{os.path.basename(source)}' already exists there. Replace it?",
        ) != QMessageBox.StandardButton.Yes:
            return

        self.active = ("move", game.id)
        self.set_status("")
        self.dl_busy("Moving", game.name)
        self.update_rows()

        def work():
            if replace:
                shutil.rmtree(target)
            shutil.move(source, target_parent)

        def done(_res, err) -> None:
            self.active = None
            self.dl_hide()
            if err:
                self.set_status(f"Failed to move game: {err}")
            else:
                self.store.add(section, game.id, target_parent)
                self.set_status(f"Moved {game.name}.")
            self.refresh_installed()
            self._pump()

        self.run_task(work, done)

    def browse_location(self) -> None:
        game = self.selected_game()
        if not game:
            return
        _s, install_path, _m, folder = self._install_info(game)
        if not install_path or not folder:
            return
        path = os.path.join(install_path, folder)
        if not os.path.exists(path):
            QMessageBox.warning(self, "Browse File Location", f"Folder not found:\n{path}")
            return
        if OS == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        elif OS == "Darwin":
            subprocess.run(["open", "-R", path])
        else:
            subprocess.run(["xdg-open", path])

    def make_shortcut(self) -> None:
        game = self.selected_game()
        if not game:
            return
        section, install_path, manifest, _f = self._install_info(game)
        exe_rel = manifest.executables.get(game.id) if manifest else None
        if not section or not install_path or not exe_rel:
            QMessageBox.critical(self, "Error", "Could not find installation information for this game.")
            return
        exe = os.path.normpath(os.path.join(install_path, exe_rel))
        if not os.path.exists(exe):
            QMessageBox.warning(self, "Executable Missing", f"Executable not found:\n{exe}")
            return
        icon = None
        icon_rel = manifest.icons.get(game.id)
        if icon_rel:
            icon = os.path.join(install_path, icon_rel.lstrip("/"))
        try:
            if OS == "Darwin" and section == "Windows":
                cx = find_crossover(self.settings.get("CrossOver path", ""))
                if cx is None:
                    QMessageBox.warning(self, "CrossOver not found",
                                        "Bandit couldn't find CrossOver, which this game needs. "
                                        "Use File ▸ Locate CrossOver… and try again.")
                    return
                create_crossover_shortcut(game.name, exe, icon, cx)
            else:
                create_desktop_shortcut(game.name, exe, icon, via_proton=(OS == "Linux" and section == "Windows"))
            QMessageBox.information(self, "Shortcut Created", f"Desktop shortcut created for {game.name}.")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Failed to create shortcut:\n{e}")

    # ---- disk usage --------------------------------------------------- #

    def show_disk_usage(self) -> None:
        entries = []
        for gid in self._installed_cache:
            g = self.games.get(gid)
            _s, path, _m, folder = self._install_info(g) if g else (None, None, None, None)
            if g and path and folder:
                entries.append((g.name, os.path.join(path, folder)))
        if not entries:
            QMessageBox.information(self, "Disk Usage", "No games are installed.")
            return
        self.set_status("Measuring installed games…")
        self._show_progress(True, busy=True)

        def work():
            return sorted(((n, dir_size(p)) for n, p in entries), key=lambda e: -e[1])

        def done(result, err) -> None:
            if self.active is None:
                self._show_progress(False)
            self.set_status("")
            if err:
                QMessageBox.warning(self, "Disk Usage", str(err))
                return
            dlg = QDialog(self)
            dlg.setWindowTitle("Disk Usage")
            dlg.resize(420, 360)
            tree = QTreeWidget()
            tree.setHeaderLabels(["Game", "Size on disk"])
            tree.setRootIsDecorated(False)
            tree.setAlternatingRowColors(True)
            total = 0
            for name, size in result:
                total += size
                item = QTreeWidgetItem([name, format_size(size)])
                item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                tree.addTopLevelItem(item)
            tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            try:
                free = format_size(shutil.disk_usage(GAMES_FOLDER).free)
            except OSError:
                free = "unknown"
            summary = QLabel(f"Total: {format_size(total)}  ·  Free on install drive: {free}")
            box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            box.rejected.connect(dlg.reject)
            lay = QVBoxLayout(dlg)
            lay.addWidget(tree)
            lay.addWidget(summary)
            lay.addWidget(box)
            dlg.exec()

        self.run_task(work, done)

    # ---- UI scale ------------------------------------------------------ #

    def on_scale_changed(self) -> None:
        """Re-derive everything that was sized explicitly rather than from the app font."""
        self.d_title.setFont(scaled_font(1.5, bold=True))
        self.dl_title.setFont(scaled_font(1.0, bold=True))
        self.dl_pct.setFont(scaled_font(1.3, bold=True))
        fm = self.fontMetrics()
        em = fm.horizontalAdvance("M")
        self.progress.setFixedWidth(em * 16)
        self.count_label.setMinimumWidth(em * 17)
        self.btn_primary.setMinimumWidth(em * 10)
        self.dl_col.setMaximumWidth(em * 48)
        self.stack.setMinimumWidth(em * 22)
        self.list.setMinimumWidth(em * 34)
        self._sync_dl_pad()
        side = int(fm.height() * 1.9)
        self.list.setIconSize(QSize(side, side))
        header = self.list.header()
        header.setSectionResizeMode(C_FAV, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(C_FAV, int(em * 3))
        for c in (C_STATUS, C_SIZE, C_MP, C_LAST, C_TIME):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.list.doItemsLayout()

    def zoom(self, delta: int) -> None:
        cur = clamp_scale(self.settings.get("UI scale", UI_SCALE_DEFAULT))
        new = UI_SCALE_DEFAULT if delta == 0 else clamp_scale(cur + delta)
        self.settings.set("UI scale", new)
        apply_ui_scale(new)
        self.on_scale_changed()
        self.set_status(f"Interface scale: {new}%")

    # ---- settings / close -------------------------------------------- #

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name, flags = dlg.values()
            for key, value in flags.items():
                self.settings.data[key] = value
            self.settings.data["UI scale"] = dlg.scale_slider.value()
            self.settings.save()
            self.set_account_name(name)

    def closeEvent(self, event) -> None:
        if isinstance(self.worker, DownloadWorker) and self.worker.isRunning():
            if QMessageBox.question(
                self, "Download in progress", "A download is still running. Cancel it and quit?",
            ) != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.queue.clear()
            self.worker.cancel()
            self.worker.wait(5000)
        if self.proc is not None:
            self._game_finished()  # bank the playtime so far
        for t in list(self._tasks):
            t.wait(2000)
        self.art.shutdown()
        self.qs.setValue("geometry", self.saveGeometry())
        self.qs.setValue("splitter", self.splitter.saveState())
        self.qs.setValue("header", self.list.header().saveState())
        self.qs.setValue("show_filter", self.show_combo.currentData())
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Bandit")
    app.setOrganizationName("Bandit")
    app.setApplicationVersion(VERSION)
    apply_ui_scale(read_json(SETTINGS_PATH, {}).get("UI scale", UI_SCALE_DEFAULT))
    # No custom style or stylesheet: Qt uses the platform's native look (and dark mode).

    for icon_file in ("icon.ico", "icon.png"):
        path = resource_path(icon_file)
        if os.path.exists(path):
            app.setWindowIcon(QIcon(path))
            break

    error = ensure_program_data()
    if error:
        QMessageBox.critical(None, "Bandit", error)
        return 1

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
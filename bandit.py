import sys
import requests
import re
import json
import gzip
import tarfile
import io
import os
import subprocess
import time
import platform
import shutil
import ntpath
import webbrowser
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote, quote
from plyer import notification
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QMenu, QGraphicsOpacityEffect, QStyledItemDelegate 
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QTimer

isWindows = platform.system() == 'Windows'
isMacOS = platform.system() == 'Darwin'
isLinux = platform.system() == 'Linux'

OS = platform.system()

version = "1.6.0"

# --- PROTON CONFIGURATION (Linux Only) ---
PROTON_GE_VERSION = "GE-Proton10-28"
PROTON_DOWNLOAD_URL = f"https://github.com/GloriousEggroll/proton-ge-custom/releases/download/{PROTON_GE_VERSION}/{PROTON_GE_VERSION}.tar.gz"
# Install Proton to ~/.local/share/bandit/Proton-GE
PROTON_INSTALL_DIR = os.path.expanduser(f"~/.local/share/banditgamelauncher/{PROTON_GE_VERSION}")
PROTON_EXECUTABLE = os.path.join(PROTON_INSTALL_DIR, "proton")
# The Prefix requested by user
PROTON_PFX = os.path.expanduser("~/protonpfx")

# --- CONFIGURATION FILE PATH FIX ---
if isWindows:
    CONFIG_BASE = os.path.expandvars("%APPDATA%")
    CONFIG_DIR = os.path.join(CONFIG_BASE, "BanditGameLauncher")
elif isMacOS:
    CONFIG_BASE = os.path.expanduser("~/Library/Application Support")
    CONFIG_DIR = os.path.join(CONFIG_BASE, "BanditGameLauncher")
elif isLinux:
    CONFIG_BASE = os.path.expanduser("~/.config")
    CONFIG_DIR = os.path.join(CONFIG_BASE, "banditgamelauncher")
else:
    CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

os.makedirs(CONFIG_DIR, exist_ok=True)
saved_paths_file = os.path.join(CONFIG_DIR, "saved_paths.json")

# Make a window
app = QApplication(sys.argv)
app.setApplicationName("Bandit - Game Launcher")
app.setWindowIcon(QIcon('icon.png'))
window = QWidget()
window.setWindowTitle(f"Bandit - Game Launcher v{version}")
window.setGeometry(100, 100, 800, 600)
layout = QVBoxLayout()
window.setLayout(layout)

class OpacityDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.installed_games = set() 

    def paint(self, painter, option, index):
        game_title_with_emoji = index.data(Qt.ItemDataRole.DisplayRole)
        game_title = game_title_with_emoji[2:].strip() if game_title_with_emoji else ""
        
        # Remove the 🪟 prefix for comparison on Linux
        if isLinux and game_title.startswith("🪟 "):
            game_title = game_title[:-10].strip()

        if game_title in self.installed_games:
            painter.setOpacity(1.0)
        else:
            painter.setOpacity(0.4)

        super().paint(painter, option, index)
        painter.setOpacity(1.0)

    def set_installed_games(self, games):
        self.installed_games = set(games)

# Global dictionary to track which OS a game belongs to (Crucial for Linux running Windows games)
# Format: { "game_id": "Windows" } or { "game_id": "Linux" }
game_origin_os = {}
game_available_versions = {}

def _fetch_remote(path, as_json=False, timeout=10, default=None, os_override=None):
    """
    Fetches data from the server.
    os_override: If set, fetches from that OS folder instead of the current system OS.
    """
    target_os = os_override if os_override else OS
    url = f"https://thuis.felixband.nl/bandit/{target_os}/{path}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        if as_json:
            return resp.json()
        return [line for line in resp.text.splitlines() if line.strip()]
    except Exception as e:
        print(f"Failed fetching {url}: {e}")
        if default is not None:
            return default
        return {} if as_json else []

def download_game_list():
    global game_origin_os, game_available_versions

    # reset tracking
    game_available_versions = {}

    # 1. Fetch Native Games
    native_list = _fetch_remote("list.txt", as_json=False, default=[])

    for line in native_list:
        parts = line.split('|')
        if len(parts) > 1:
            game_id = parts[1]
            game_origin_os[game_id] = OS
            game_available_versions.setdefault(game_id, set()).add(OS)

    # 2. If Linux, also fetch Windows games
    if isLinux:
        windows_list = _fetch_remote(
            "list.txt",
            as_json=False,
            default=[],
            os_override="Windows"
        )

        existing_ids = set(game_origin_os.keys())

        for line in windows_list:
            parts = line.split('|')
            if len(parts) > 1:
                game_id = parts[1]

                # Always record Windows availability
                game_available_versions.setdefault(game_id, set()).add("Windows")

                # Only add to display list if Linux version does not exist
                if game_id not in existing_ids:
                    native_list.append(line)
                    game_origin_os[game_id] = "Windows"

    return native_list

def download_executable_paths():
    """
    Returns executable paths per OS.
    Format:
    {
        "Linux":   { game_id: "path/to/game.x86_64" },
        "Windows": { game_id: "path/to/game.exe" },
        "Darwin":  { ... }
    }
    """
    paths = {}

    # Native OS paths
    paths[OS] = _fetch_remote("executable_paths.json", as_json=True, default={})

    # On Linux, also fetch Windows paths
    if isLinux:
        paths["Windows"] = _fetch_remote(
            "executable_paths.json",
            as_json=True,
            default={},
            os_override="Windows"
        )

    return paths

def download_icon_paths():
    """
    Returns icon paths per OS.
    Same structure as executable_paths.
    """
    paths = {}

    # Native OS
    paths[OS] = _fetch_remote("icon_paths.json", as_json=True, default={})

    # Linux also needs Windows icons for Proton games
    if isLinux:
        paths["Windows"] = _fetch_remote(
            "icon_paths.json",
            as_json=True,
            default={},
            os_override="Windows"
        )

    return paths

def download_prereq_paths(os_override=None):
    """Fetch prerequisite paths for a specific OS"""
    target_os = os_override if os_override else OS
    return _fetch_remote("prereq_paths.json", as_json=True, default={}, os_override=target_os)

# Load or migrate saved_paths
if not os.path.exists(saved_paths_file):
    saved_paths = {}
    with open(saved_paths_file, 'w') as f:
        json.dump(saved_paths, f)
else:
    try:
        with open(saved_paths_file, 'r') as f:
            saved_paths = json.load(f)
            
        # Check if old format (flat dictionary) and convert to new format
        if saved_paths and not any(key in saved_paths for key in ["Windows", "Linux", "Darwin"]):
            print("Migrating old saved_paths format to new format...")
            migrated_saved_paths = {}
            for os_name in ["Windows", "Linux", "Darwin"]:
                migrated_saved_paths[os_name] = {}
            
            # Move old entries to current OS
            for game_id, path in saved_paths.items():
                migrated_saved_paths[OS][game_id] = path
            
            saved_paths = migrated_saved_paths
            
            # Save migrated format
            with open(saved_paths_file, 'w') as f:
                json.dump(saved_paths, f, indent=2)
            
            print("Migration completed successfully.")
    except Exception as e:
        print(f"Error loading saved_paths: {e}")
        saved_paths = {}

# Initialize OS keys if they don't exist
for os_name in ["Windows", "Linux", "Darwin"]:
    if os_name not in saved_paths:
        saved_paths[os_name] = {}

def parse_game_entry(selected_game_entry):
    fields = selected_game_entry.split('|')
    data = {
        'display_name': fields[0],
        'game_id': fields[1],
        'size_in_bytes': fields[2],
        'multiplayer_status': fields[3] if len(fields) > 3 else '0'
    }
    return data

def sort_game_list(game_list):
    return sorted(game_list, key=lambda x: x.split('|')[0].lower())

icon_paths = download_icon_paths()

executable_paths = download_executable_paths()
game_list = download_game_list() # This now populates game_origin_os
game_list = sort_game_list(game_list)

game_list_widget = QListWidget()
font = QFont()
if isMacOS:
    font.setPointSize(16)
else:
    font.setPointSize(12)
game_list_widget.setFont(font)

delegate = OpacityDelegate(game_list_widget)
game_list_widget.setItemDelegate(delegate)

def update_installed_opacity():
    installed_display_names = []
    
    for game in game_list:
        game_data = parse_game_entry(game)
        game_id = game_data['game_id']
        display_name = game_data['display_name']
        
        # Check if game is installed for any OS (for Linux, show as installed if either Linux or Windows version is installed)
        is_installed = False
        
        if isLinux:
            # On Linux, a game is considered installed if either Linux or Windows version is installed
            is_installed = (game_id in saved_paths["Linux"]) or (game_id in saved_paths["Windows"])
        else:
            # On other OSes, only check current OS
            is_installed = game_id in saved_paths[OS]
        
        if is_installed:
            installed_display_names.append(display_name)
    
    delegate.set_installed_games(installed_display_names)
    game_list_widget.viewport().update()

update_installed_opacity()

# Track which OS version to download for each game on Linux
linux_download_choice = {}  # {game_id: "Linux" or "Windows"}

for game in game_list:
    game_data = parse_game_entry(game)
    display_name = game_data['display_name']
    game_id = game_data['game_id']
    multiplayer_status = game_data['multiplayer_status']
    
    # On Linux, add (Windows) prefix for Windows games
    if isLinux and game_origin_os.get(game_id) == "Windows":
        display_name = f"🪟 {display_name}"
    
    if multiplayer_status == '0':
        display_name = "🔴 " + display_name
    elif multiplayer_status == '1':
        display_name = "🟠 " + display_name
    elif multiplayer_status == '2':
        display_name = "🟢 " + display_name
    elif multiplayer_status == '3':
        display_name = "🟩 " + display_name

    game_list_widget.addItem(display_name)

layout.addWidget(game_list_widget)

download_play_button = QPushButton("Download/Play")
layout.addWidget(download_play_button)

uninstall_button = QPushButton("Uninstall")
layout.addWidget(uninstall_button)

percentage_label = QLabel("Not currently downloading")
layout.addWidget(percentage_label)

size_label = QLabel("No game selected")
layout.addWidget(size_label)

multiplayer_status_label = QLabel("🔴 Singleplayer/Local only | 🟠 LAN Multiplayer | 🟢 Online Multiplayer (other Bandit users) | 🟩 Online Multiplayer (Official servers)")
layout.addWidget(multiplayer_status_label)

currently_downloading_game = ""
currently_downloading = False
download_cancel_requested = False
_current_download_response = None

def check_for_updates():
    try:
        response = requests.get("https://api.github.com/repos/FelixBand/Bandit/releases/latest", timeout=10)
        response.raise_for_status()
        json_data = response.json()
        if json_data["tag_name"] > version:
            reply = QMessageBox.question(None, 'Download update?', "A new update is available: " + json_data["tag_name"] + ". You're running version " + version + ". Would you like to update?", 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.Yes)

            if reply == QMessageBox.StandardButton.Yes:
                url = "https://github.com/FelixBand/Bandit/releases/latest"
                try:
                    webbrowser.open(url, new=2)
                except Exception:
                    pass
                QTimer.singleShot(500, app.quit)
                return
    except Exception as e:
        print(f"An error occurred while checking for updates: {e}")

check_for_updates()

def on_game_selected():
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        size_label.setText("No game selected")
        download_play_button.setEnabled(False)
        uninstall_button.setEnabled(False)
        return

    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']
    size_in_bytes = game_data['size_in_bytes']
    multiplayer_status = game_data['multiplayer_status']
    
    # Check if game is installed (for current OS or for Linux users, either Linux or Windows version)
    is_installed = False
    if isLinux:
        is_installed = (game_id in saved_paths["Linux"]) or (game_id in saved_paths["Windows"])
    else:
        is_installed = game_id in saved_paths[OS]

    if currently_downloading and currently_downloading_game != game_id and not is_installed:
        download_play_button.setEnabled(False)
    else:
        download_play_button.setEnabled(True)

    if is_installed:
        uninstall_button.setEnabled(True)
        download_play_button.setText("Play")
    else:
        uninstall_button.setEnabled(False)
        download_play_button.setText("Download")

    if currently_downloading_game == game_id:
        download_play_button.setText("Cancel Download")

    try:
        size_in_bytes = int(size_in_bytes)
        if size_in_bytes >= 1_000_000_000:
            size_in_gb = size_in_bytes / 1_000_000_000
            size_label.setText(f"Size of {display_name}: {size_in_gb:.2f} GB")
        else:
            size_in_mb = size_in_bytes / 1_000_000
            size_label.setText(f"Size of {display_name}: {size_in_mb:.2f} MB")
    except ValueError:
        size_label.setText(f"Size of {display_name}: N/A")

    if multiplayer_status == '0':
        multiplayer_status_label.setText("Multiplayer Status: 🔴 Singleplayer/Local only")
    elif multiplayer_status == '1':
        multiplayer_status_label.setText("Multiplayer Status: 🟠 LAN Multiplayer")
    elif multiplayer_status == '2':
        multiplayer_status_label.setText("Multiplayer Status: 🟢 Online Multiplayer (Bandit users)")
    elif multiplayer_status == '3':
        multiplayer_status_label.setText("Multiplayer Status: 🟩 Online Multiplayer (Official servers)")

game_list_widget.currentRowChanged.connect(on_game_selected)

def show_context_menu(position):
    menu = QMenu()
    browse_action = menu.addAction("Browse File Location")
    move_action = menu.addAction("Move Game to Another Location")
    shortcut_action = menu.addAction("Create Desktop Shortcut")
    action = menu.exec(game_list_widget.viewport().mapToGlobal(position))
    if action == browse_action:
        browse_file_location()
    elif action == move_action:
        move_game()
    elif action == shortcut_action:
        create_desktop_shortcut()

game_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
game_list_widget.customContextMenuRequested.connect(show_context_menu)

def get_game_folder_path(game_id, installed_os):
    """Get the full path to the game folder (first folder of executable path)"""
    if installed_os not in saved_paths or game_id not in saved_paths[installed_os]:
        return None
    
    game_install_path = saved_paths[installed_os][game_id]
    executable_relative_path = executable_paths.get(installed_os, {}).get(game_id, "")
    
    if not executable_relative_path:
        return game_install_path
    
    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""
    
    if first_folder in ("..", "", ".", "/", "\\"):
        return game_install_path
    
    return os.path.join(game_install_path, first_folder)

def move_game():
    """Move a game installation to another location"""
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        return
    
    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    game_id = game_data['game_id']
    display_name = game_data['display_name']
    
    # Find which OS version is installed
    installed_os = None
    if isLinux:
        if game_id in saved_paths["Linux"]:
            installed_os = "Linux"
        elif game_id in saved_paths["Windows"]:
            installed_os = "Windows"
    else:
        if game_id in saved_paths[OS]:
            installed_os = OS
    
    if installed_os is None:
        QMessageBox.warning(window, "Not Installed", f"{display_name} is not installed.")
        return
    
    # Get current game folder path
    current_game_folder = get_game_folder_path(game_id, installed_os)
    if not current_game_folder or not os.path.exists(current_game_folder):
        QMessageBox.warning(window, "Error", f"Cannot find game folder for {display_name}.")
        return
    
    # Get parent directory of current game folder
    current_parent = os.path.dirname(current_game_folder)
    
    # Ask for new location
    new_parent = QFileDialog.getExistingDirectory(
        window, 
        f"Select New Location for {display_name} ({installed_os} version)",
        current_parent
    )
    
    if not new_parent:
        return  # User cancelled
    
    # Check if destination is same as source
    if os.path.normpath(new_parent) == os.path.normpath(current_parent):
        QMessageBox.information(window, "Same Location", "Game is already in the selected location.")
        return
    
    # Get the folder name (last part of current_game_folder)
    folder_name = os.path.basename(current_game_folder)
    new_game_folder = os.path.join(new_parent, folder_name)
    
    # Check if destination already exists
    if os.path.exists(new_game_folder):
        reply = QMessageBox.question(
            window, 
            "Folder Exists",
            f"The folder '{folder_name}' already exists at the destination.\n\n"
            "Do you want to replace it? (This will delete the existing folder)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.path.isdir(new_game_folder):
                shutil.rmtree(new_game_folder)
            else:
                os.remove(new_game_folder)
        except Exception as e:
            QMessageBox.critical(window, "Error", f"Failed to remove existing folder: {e}")
            return
    
    # Check available disk space in destination
    try:
        game_size = get_folder_size(current_game_folder)
        free_space = get_free_disk_space(new_parent)
        
        if game_size > free_space:
            size_gb = game_size / (1024**3)
            free_gb = free_space / (1024**3)
            QMessageBox.warning(
                window,
                "Insufficient Disk Space",
                f"Not enough disk space to move game.\n\n"
                f"Game size: {size_gb:.2f} GB\n"
                f"Available space: {free_gb:.2f} GB\n\n"
                "Please choose a different location with more free space."
            )
            return
    except Exception as e:
        print(f"Error checking disk space: {e}")
        # Continue anyway
    
    # Confirm move
    reply = QMessageBox.question(
        window,
        "Confirm Move",
        f"Move {display_name} ({installed_os} version) from:\n\n"
        f"{current_game_folder}\n\n"
        f"to:\n\n"
        f"{new_game_folder}?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    
    if reply != QMessageBox.StandardButton.Yes:
        return
    
    # Perform the move
    try:
        percentage_label.setText(f"Moving {display_name}...")
        QApplication.processEvents()
        
        # Create parent directory if it doesn't exist
        os.makedirs(new_parent, exist_ok=True)
        
        # Move the folder
        shutil.move(current_game_folder, new_game_folder)
        
        # Update saved_paths - new path is the parent directory (where the game folder is located)
        saved_paths[installed_os][game_id] = new_parent
        
        # Save the updated paths
        with open(saved_paths_file, 'w') as f:
            json.dump(saved_paths, f, indent=2)

        # Recreate desktop shortcut if it existed
        had_shortcut = desktop_shortcut_exists(display_name)

        if had_shortcut:
            remove_desktop_shortcut(display_name)
            create_desktop_shortcut()

        
        percentage_label.setText(f"Moved {display_name} successfully!")
        QMessageBox.information(window, "Success", f"{display_name} has been moved successfully.")
        
        # Update UI
        update_installed_opacity()
        
    except Exception as e:
        QMessageBox.critical(window, "Move Failed", f"Failed to move game: {e}")
        percentage_label.setText("Move failed")

def get_folder_size(folder_path):
    """Calculate total size of a folder in bytes"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder_path):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                try:
                    total_size += os.path.getsize(filepath)
                except (OSError, PermissionError):
                    pass
    return total_size

def get_free_disk_space(path):
    """Get free disk space for a given path in bytes"""
    if isWindows:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(path), 
            None, 
            None, 
            ctypes.pointer(free_bytes)
        )
        return free_bytes.value
    else:
        stat = shutil.disk_usage(path)
        return stat.free

def check_disk_space(path, required_bytes):
    """Check if there's enough disk space at the given path"""
    try:
        free_space = get_free_disk_space(path)
        # Add 10% buffer for extraction overhead
        required_with_buffer = required_bytes * 1.1
        return free_space >= required_with_buffer, free_space
    except Exception as e:
        print(f"Error checking disk space: {e}")
        return True, 0  # Assume enough space if we can't check

# --- PROTON INSTALLATION LOGIC ---
def install_proton_ge():
    """Downloads and extracts Proton GE."""
    global currently_downloading, _current_download_response, download_cancel_requested
    
    print(f"Starting Proton-GE download from {PROTON_DOWNLOAD_URL}")
    percentage_label.setText("Downloading Proton-GE... (This may take a while)")
    QApplication.processEvents()

    currently_downloading = True
    download_cancel_requested = False
    
    try:
        os.makedirs(PROTON_INSTALL_DIR, exist_ok=True)
        
        # We need to extract strip-components=1 logic essentially, 
        # but Python tarfile extracts what's inside. 
        # Usually GE releases contain a folder "GE-Proton8-25". 
        # We want that contents inside PROTON_INSTALL_DIR.
        
        with requests.get(PROTON_DOWNLOAD_URL, stream=True, timeout=(5, 30)) as response:
            _current_download_response = response
            if response.status_code == 200:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded_size = 0
                
                # Reusing the read counter logic
                class ReadCounter:
                    def __init__(self, raw, on_bytes):
                        self.raw = raw
                        self.on_bytes = on_bytes
                        self.decode_content = getattr(raw, "decode_content", False)

                    def read(self, size=-1):
                        if download_cancel_requested: raise IOError("Download cancelled")
                        data = self.raw.read(size)
                        if data:
                            try:
                                self.on_bytes(len(data))
                            except Exception: pass
                        if download_cancel_requested: raise IOError("Download cancelled")
                        return data

                    def readable(self): return True
                    def close(self): 
                        try: return self.raw.close()
                        except: pass

                def on_bytes(n):
                    nonlocal downloaded_size
                    downloaded_size += n
                    if total_size:
                        percent_done = (downloaded_size / total_size) * 100
                        percentage_label.setText(f"Downloading Proton-GE: {percent_done:.2f}%")
                    else:
                        percentage_label.setText(f"Downloading Proton-GE: {downloaded_size} bytes")
                    QApplication.processEvents()

                fileobj = response.raw
                fileobj.decode_content = True
                wrapped = ReadCounter(fileobj, on_bytes)

                try:
                    # Extract to a temporary folder first to handle directory structure
                    temp_extract_path = os.path.join(CONFIG_DIR, "temp_proton")
                    if os.path.exists(temp_extract_path): shutil.rmtree(temp_extract_path)
                    os.makedirs(temp_extract_path, exist_ok=True)

                    with tarfile.open(fileobj=wrapped, mode='r|gz') as tar:
                        tar.extractall(path=temp_extract_path)
                    
                    # Move files from temp/GE-ProtonX to actual install dir
                    # Find the inner folder
                    extracted_roots = os.listdir(temp_extract_path)
                    if extracted_roots:
                        inner_folder = os.path.join(temp_extract_path, extracted_roots[0])
                        # Move content to PROTON_INSTALL_DIR
                        if os.path.isdir(inner_folder):
                            for item in os.listdir(inner_folder):
                                s = os.path.join(inner_folder, item)
                                d = os.path.join(PROTON_INSTALL_DIR, item)
                                if os.path.exists(d):
                                    if os.path.isdir(d): shutil.rmtree(d)
                                    else: os.remove(d)
                                shutil.move(s, d)
                    
                    shutil.rmtree(temp_extract_path)
                    
                    print("Proton-GE installed successfully.")
                    percentage_label.setText("Proton-GE installed successfully.")
                    return True

                except IOError:
                    percentage_label.setText("Proton-GE download cancelled.")
                    return False
            else:
                QMessageBox.critical(window, "Error", f"Failed to download Proton. HTTP {response.status_code}")
                return False
    except Exception as e:
        print(f"Error installing Proton: {e}")
        QMessageBox.critical(window, "Error", f"Error installing Proton: {e}")
        return False
    finally:
        _current_download_response = None
        currently_downloading = False


def get_effective_game_os(game_id):
    """
    Returns the OS that should be used for launching the game,
    respecting the user's Linux/Windows choice.
    """
    if isLinux and game_id in linux_download_choice:
        return linux_download_choice[game_id]
    return game_origin_os.get(game_id)

def download_and_play_game():
    global currently_downloading_game, currently_downloading, saved_paths, download_cancel_requested, _current_download_response

    download_cancel_requested = False
    _current_download_response = None

    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game to download/play.")
        return

    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']

    # --- LAUNCH LOGIC ---
    # Check if game is installed (for current OS or for Linux users, either Linux or Windows version)
    is_installed = False
    installed_os = None
    
    if isLinux:
        if game_id in saved_paths["Linux"]:
            is_installed = True
            installed_os = "Linux"
        elif game_id in saved_paths["Windows"]:
            is_installed = True
            installed_os = "Windows"
    else:
        if game_id in saved_paths[OS]:
            is_installed = True
            installed_os = OS
    
    if is_installed:
        print(f"Launching game {display_name}...")
        
        if installed_os not in executable_paths or game_id not in executable_paths[installed_os]:
            QMessageBox.critical(
                window,
                "Error",
                f"Executable path for {display_name} ({installed_os}) not found."
            )
            return

        executable_relative_path = executable_paths[installed_os][game_id]

        game_install_path = saved_paths[installed_os][game_id]
        game_exec_full_path = os.path.join(game_install_path, executable_relative_path)
        
        if not os.path.exists(game_exec_full_path):
            QMessageBox.critical(window, "Error", f"Executable not found at:\n{game_exec_full_path}")
            return
        
        # Prerequisites check - Use the installed OS to get the correct prerequisites
        prereq_paths = download_prereq_paths(installed_os)
        if game_id in prereq_paths and prereq_paths[game_id]:
            install_prerequisites(installed_os)  # Pass the installed OS to install_prerequisites

        try:
            # --- LINUX + WINDOWS GAME (PROTON) HANDLING ---
            if isLinux and installed_os == "Windows":
                # Check if Proton exists
                if not os.path.exists(PROTON_EXECUTABLE):
                    reply = QMessageBox.question(window, "Proton Missing", 
                                                 "This is a Windows game. To play it on Linux, you need Proton-GE.\n\n"
                                                 "Do you want to download and install it now?",
                                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if reply == QMessageBox.StandardButton.Yes:
                        success = install_proton_ge()
                        if not success: return # Abort launch if install failed
                    else:
                        return # Abort launch

                print(f"Launching {display_name} via Proton...")
                
                # Ensure prefix dir exists
                os.makedirs(PROTON_PFX, exist_ok=True)
                
                # Setup Environment
                env = os.environ.copy()
                env["STEAM_COMPAT_DATA_PATH"] = PROTON_PFX
                env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = PROTON_PFX
                env["WINEDLLOVERRIDES"] = "dinput8,d3d9,version,steamoverlay64,winmm=n,b" # This is for games that inject DLLs to load mods
                
                # Command: ./proton run "game.exe"
                cmd = [PROTON_EXECUTABLE, "run", game_exec_full_path]
                subprocess.Popen(cmd, env=env)
                
            elif isWindows:
                # Windows native
                subprocess.Popen([f"{game_exec_full_path}"], cwd=os.path.join(game_install_path, os.path.dirname(executable_relative_path)), shell=True)
            elif isLinux and installed_os == "Linux":
                # Linux native
                subprocess.Popen([game_exec_full_path], cwd=os.path.dirname(game_exec_full_path))
            elif isMacOS:
                subprocess.Popen(['open', '-a', f"{game_exec_full_path}"])
            
            print(f"Launched {display_name} successfully.")
        except Exception as e:
            QMessageBox.critical(window, "Launch Failed", f"Failed to launch {display_name}: {e}")
        return

    # --- DOWNLOAD LOGIC ---
    if currently_downloading_game == game_id:
        cancel_download(game_id)
        currently_downloading_game = ""
        on_game_selected()
        return

    # On Linux, ask which OS version to download if both are available
    download_os = OS  # Default to current OS
    
    if isLinux:
        game_os = game_origin_os.get(game_id, OS)
        
        # If game is available for both OSes, ask the user
        if game_os == "Linux":
            # Game is Linux native, but could also have Windows version
            # Check if Windows version exists in the list
            available = game_available_versions.get(game_id, set())
            has_windows_version = ("Windows" in available) and ("Linux" in available)
            
            if has_windows_version:
                msg = QMessageBox(window)
                msg.setWindowTitle("Choose Version")
                msg.setText(
                    f"Which version of '{display_name}' would you like to download?"
                )
                msg.setInformativeText(
                    "Linux: Native Linux version (recommended)\n"
                    "Windows: Windows version (requires Proton)"
                )

                linux_btn = msg.addButton("Linux (Recommended)", QMessageBox.ButtonRole.AcceptRole)
                windows_btn = msg.addButton("Windows (Proton)", QMessageBox.ButtonRole.DestructiveRole)
                cancel_btn = msg.addButton(QMessageBox.StandardButton.Cancel)

                msg.setDefaultButton(linux_btn)
                msg.exec()

                clicked = msg.clickedButton()

                if clicked == linux_btn:
                    download_os = "Linux"
                elif clicked == windows_btn:
                    download_os = "Windows"
                    linux_download_choice[game_id] = "Windows"
                else:
                    return  # user cancelled
            else:
                download_os = "Linux"
        elif game_os == "Windows":
            # Game is Windows-only
            download_os = "Windows"
            linux_download_choice[game_id] = "Windows"

    # Set up download directory - FIXED: Use the correct default path
    if isWindows:
        default_download_dir = os.path.join(os.path.expandvars("%USERPROFILE%"), ".banditgamelauncher", "games")
        os.makedirs(default_download_dir, exist_ok=True)
        download_path = default_download_dir
    elif isMacOS:
        default_download_dir = os.path.join(os.path.expanduser("~"), "Bandit Game Launcher", "games")
        os.makedirs(default_download_dir, exist_ok=True)
        download_path = default_download_dir
    elif isLinux:
        default_download_dir = os.path.join(os.path.expanduser("~"), ".banditgamelauncher", "games")
        os.makedirs(default_download_dir, exist_ok=True)
        download_path = default_download_dir

    selected_parent = QFileDialog.getExistingDirectory(window, "Select Download Directory", download_path)
    if not selected_parent: return

    # Check disk space before proceeding with download
    try:
        game_size = int(game_data['size_in_bytes'])
        has_space, free_space = check_disk_space(selected_parent, game_size)
        
        if not has_space:
            game_size_gb = game_size / (1024**3)
            free_space_gb = free_space / (1024**3)
            required_gb = game_size * 1.1 / (1024**3)  # With 10% buffer
            
            reply = QMessageBox.warning(
                window,
                "Insufficient Disk Space",
                f"Warning: Not enough disk space for {display_name}.\n\n"
                f"Game size: {game_size_gb:.2f} GB\n"
                f"Available space: {free_space_gb:.2f} GB\n"
                f"Required (with buffer): {required_gb:.2f} GB\n\n"
                "Downloading may fail or cause system issues.\n"
                "Do you want to continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
    except ValueError:
        pass  # Size not available, skip check

    target_dir = os.path.join(selected_parent)
    os.makedirs(target_dir, exist_ok=True)

    currently_downloading_game = game_id
    on_game_selected()

    print(f"Downloading {display_name} ({download_os} version) to {target_dir}")
    currently_downloading = True
    success = download_game(game_id, target_dir, display_name, download_os)

    if success:
        percentage_label.setText(f"Downloaded {display_name} ({download_os} version) successfully!")
        saved_paths[download_os][game_id] = target_dir
        try:
            with open(saved_paths_file, 'w') as f:
                json.dump(saved_paths, f, indent=2)
        except Exception as e:
            print(f"Failed to write saved_paths: {e}")
        update_installed_opacity()
    else:
        percentage_label.setText(f"Download of {display_name} cancelled or failed.")

    currently_downloading = False
    currently_downloading_game = ""
    on_game_selected()
    update_installed_opacity()

def download_game(game_id, download_path, display_name=None, target_os=None):
    global download_cancel_requested, _current_download_response, currently_downloading_game, currently_downloading
    
    # Determine URL based on target OS
    if target_os is None:
        target_os = game_origin_os.get(game_id, OS)  # default to game's origin OS if unknown
    
    url = f"https://thuis.felixband.nl/bandit/{target_os}/{game_id}.tar.gz"
    
    success = False
    try:
        with requests.get(url, stream=True, timeout=(5, 30)) as response:
            _current_download_response = response
            if response.status_code == 200:
                total_size = int(response.headers.get("Content-Length", 0))
                if not total_size:
                    try:
                        game_entry = next((game for game in game_list if parse_game_entry(game)['game_id'] == game_id), None)
                        if game_entry: total_size = int(parse_game_entry(game_entry)['size_in_bytes'])
                    except: total_size = 0

                downloaded_size = 0
                
                class ReadCounter:
                    def __init__(self, raw, on_bytes):
                        self.raw = raw
                        self.on_bytes = on_bytes
                        self.decode_content = getattr(raw, "decode_content", False)
                    def read(self, size=-1):
                        if download_cancel_requested: raise IOError("Download cancelled")
                        data = self.raw.read(size)
                        if data:
                            try: self.on_bytes(len(data))
                            except: pass
                        if download_cancel_requested: raise IOError("Download cancelled")
                        return data
                    def readable(self): return True
                    def close(self): 
                        try: return self.raw.close()
                        except: pass

                def on_bytes(n):
                    nonlocal downloaded_size
                    downloaded_size += n
                    if total_size:
                        percent_done = (downloaded_size / total_size) * 100
                        os_label = f"({target_os})" if isLinux and target_os != OS else ""
                        percentage_label.setText(f"Downloading {display_name} {os_label}: {percent_done:.2f}% complete")
                    else:
                        percentage_label.setText(f"Downloading {display_name}: {downloaded_size} bytes")
                    QApplication.processEvents()

                fileobj = response.raw
                fileobj.decode_content = True
                wrapped = ReadCounter(fileobj, on_bytes)

                try:
                    with tarfile.open(fileobj=wrapped, mode='r|gz') as tar:
                        for member in tar:
                            if download_cancel_requested: raise IOError("Download cancelled")
                            tar.extract(member, path=download_path)
                    success = True
                except IOError:
                    pass
    except Exception as e:
        if not download_cancel_requested: print(f"Error downloading {game_id}: {e}")
    finally:
        _current_download_response = None
        currently_downloading = False
        currently_downloading_game = ""
        QApplication.processEvents()

    return success

download_play_button.clicked.connect(download_and_play_game)

def cancel_download(game_id):
    global download_cancel_requested, _current_download_response, currently_downloading, currently_downloading_game
    download_cancel_requested = True
    try:
        if _current_download_response: _current_download_response.close()
    except: pass
    currently_downloading = False
    currently_downloading_game = ""
    percentage_label.setText("Download cancelled")
    QApplication.processEvents()

def remove_desktop_shortcut(display_name):
    desktop = get_desktop_path()
    safe_name = sanitize_filename(display_name)

    candidates = []

    if isWindows:
        candidates.extend([
            os.path.join(desktop, f"{safe_name}.lnk"),
            os.path.join(desktop, f"{safe_name}.url"),
        ])
    elif isMacOS:
        candidates.append(os.path.join(desktop, safe_name))  # Finder alias
    elif isLinux:
        candidates.append(os.path.join(desktop, f"{safe_name}.desktop"))

    for path in candidates:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            print(f"Failed to remove shortcut {path}: {e}")

def desktop_shortcut_exists(display_name):
    desktop = get_desktop_path()
    safe_name = sanitize_filename(display_name)

    paths = []

    if isWindows:
        paths.extend([
            os.path.join(desktop, f"{safe_name}.lnk"),
            os.path.join(desktop, f"{safe_name}.url"),
        ])
    elif isMacOS:
        paths.append(os.path.join(desktop, safe_name))
    elif isLinux:
        paths.append(os.path.join(desktop, f"{safe_name}.desktop"))

    return any(os.path.exists(p) for p in paths)

def uninstall_game():
    global saved_paths
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1: return
    
    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    game_id = game_data['game_id']
    display_name = game_data['display_name']

    # Find which OS version is installed
    installed_os = None
    if isLinux:
        if game_id in saved_paths["Linux"]:
            installed_os = "Linux"
        elif game_id in saved_paths["Windows"]:
            installed_os = "Windows"
    else:
        if game_id in saved_paths[OS]:
            installed_os = OS
    
    if installed_os is None: return

    game_install_path = saved_paths[installed_os][game_id]
    executable_relative_path = executable_paths.get(installed_os, {}).get(game_id, "")
    
    if not executable_relative_path:
        # Fallback just to remove from list if path missing
        del saved_paths[installed_os][game_id]
        with open(saved_paths_file, 'w') as f: json.dump(saved_paths, f, indent=2)
        on_game_selected()
        update_installed_opacity()
        return

    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""

    if first_folder in ("..", "", ".", "/", "\\"): return

    base_path = os.path.realpath(game_install_path)
    uninstall_path = os.path.realpath(os.path.join(base_path, first_folder))
    
    # Simple safety check
    if os.path.commonpath([base_path, uninstall_path]) != base_path: return
    
    if not os.path.exists(uninstall_path):
         del saved_paths[installed_os][game_id]
         with open(saved_paths_file, 'w') as f: json.dump(saved_paths, f, indent=2)
         on_game_selected()
         update_installed_opacity()
         return

    confirm = QMessageBox.question(
        window,
        "Confirm Uninstall",
        f"Are you sure you want to uninstall {display_name} ({installed_os} version)?\n\nThis will delete:\n{uninstall_path}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if confirm != QMessageBox.StandardButton.Yes: return

    try:
        shutil.rmtree(uninstall_path)
        remove_desktop_shortcut(display_name)
        del saved_paths[installed_os][game_id]
        with open(saved_paths_file, 'w') as f: json.dump(saved_paths, f, indent=2)
        QMessageBox.information(window, "Uninstalled", f"{display_name} ({installed_os} version) uninstalled.")
        on_game_selected()
        update_installed_opacity()
        percentage_label.setText(f"Uninstalled {display_name} ({installed_os})")
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Uninstall failed: {e}")

def install_prerequisites(game_os=None):
    """Install prerequisites for the selected game.
    
    Args:
        game_os: The OS for which to install prerequisites (e.g., "Windows" or "Linux").
                 If None, uses the game's origin OS from game_origin_os.
    """
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1: return

    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    game_id = game_data['game_id']
    display_name = game_data['display_name']

    # Find which OS version is installed
    installed_os = None
    if isLinux:
        if game_id in saved_paths["Linux"]:
            installed_os = "Linux"
        elif game_id in saved_paths["Windows"]:
            installed_os = "Windows"
    else:
        if game_id in saved_paths[OS]:
            installed_os = OS
    
    if installed_os is None:
        # If not installed yet, use provided game_os or get from game_origin_os
        if game_os is None:
            game_os = game_origin_os.get(game_id, OS)
        installed_os = game_os

    # Fetch prerequisites for the correct OS
    prereq_paths = download_prereq_paths(installed_os)
    
    if game_id not in prereq_paths or not prereq_paths[game_id]: 
        return

    # Get the installation path for this OS version
    if installed_os not in saved_paths or game_id not in saved_paths[installed_os]:
        QMessageBox.warning(window, "Not Installed", f"{display_name} ({installed_os} version) is not installed.")
        return
    
    game_install_path = saved_paths[installed_os][game_id]
    executable_relative_path = executable_paths.get(installed_os, {}).get(game_id, "")
    
    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""
    
    game_base_folder = os.path.realpath(os.path.join(game_install_path, first_folder))
    marker_path = os.path.join(game_base_folder, "prerequisites_installed.txt")
    if os.path.exists(marker_path):
        percentage_label.setText(f"Prerequisites already installed for {display_name} ({installed_os}).")
        return

    prereqs = prereq_paths[game_id]
    reply = QMessageBox.question(window, "Install Prerequisites", f"Install {len(prereqs)} prerequisites for {display_name} ({installed_os} version)?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes: return

    percentage_label.setText(f"Installing prerequisites for {display_name} ({installed_os})...")
    QApplication.processEvents()

    for prereq in prereqs:
        rel_path = prereq.get("path", "")
        cmd_args = prereq.get("command", "")
        if not rel_path: continue

        full_path = os.path.join(game_base_folder, rel_path.lstrip("/").lstrip("\\"))
        installer_dir = os.path.dirname(full_path)

        try:
            # Check if we need to run via Proton (Windows game on Linux)
            if isLinux and installed_os == "Windows":
                print(f"Running Windows prerequisite via Proton: {full_path}")
                env = os.environ.copy()
                env["STEAM_COMPAT_DATA_PATH"] = PROTON_PFX
                env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = PROTON_PFX
                # Proton "run" command for the installer
                cmd = [PROTON_EXECUTABLE, "run", full_path] + cmd_args.split()
                subprocess.run(cmd, env=env, check=True)
            else:
                # Native installation
                subprocess.run([full_path] + cmd_args.split(), cwd=installer_dir, shell=True, check=True)
                
            print(f"Installed: {full_path}")
        except Exception as e:
            print(f"Failed prereq {full_path}: {e}")

        time.sleep(1)
        QApplication.processEvents()

    try:
        with open(marker_path, "w") as f: f.write("Prerequisites installed.\n")
    except: pass
    
    percentage_label.setText(f"Finished prerequisites for {display_name} ({installed_os}).")
    QMessageBox.information(window, "Done", f"Prerequisites installed.")

def browse_file_location():
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1: return
    selected_game_entry = game_list[selected_game_index]
    game_id = parse_game_entry(selected_game_entry)['game_id']
    
    # Find which OS version is installed
    installed_os = None
    if isLinux:
        if game_id in saved_paths["Linux"]:
            installed_os = "Linux"
        elif game_id in saved_paths["Windows"]:
            installed_os = "Windows"
    else:
        if game_id in saved_paths[OS]:
            installed_os = OS
    
    if installed_os is None: return
    
    path = saved_paths[installed_os][game_id]
    exe_path = executable_paths.get(installed_os, {}).get(game_id, "")
    
    # Logic to find folder
    parts = exe_path.replace("\\", "/").split("/")
    first = parts[0] if parts else ""
    target = os.path.join(path, first)
    
    if os.path.exists(target):
        if isWindows:
            os.startfile(target)
        elif isMacOS:
            subprocess.run(["open", "-R", target])
        elif isLinux:
            subprocess.run(["xdg-open", target])

def get_desktop_path():
    """Return the current user's Desktop folder path (best-effort across OSes)."""
    home = os.path.expanduser("~")
    # macOS/Windows default
    desktop = os.path.join(home, "Desktop")

    # Linux: try to read XDG user dirs
    if isLinux:
        try:
            config = os.path.join(home, ".config", "user-dirs.dirs")
            if os.path.exists(config):
                with open(config, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("XDG_DESKTOP_DIR"):
                            val = line.split("=")[1].strip().strip('"')
                            val = val.replace("$HOME", home)
                            desktop = os.path.expandvars(val)
                            break
        except Exception:
            pass
    return desktop

def sanitize_filename(name):
    """
    Make a string safe for use as a filename on all OSes.
    """
    # Remove emojis and leading status icons if present
    name = re.sub(r'^[^\w\s]+', '', name).strip()

    # Replace illegal filename characters
    name = re.sub(r'[\\/:*?"<>|]', '_', name)

    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()

    # Windows: no trailing dots or spaces
    name = name.rstrip('. ')

    # Fallback name
    return name if name else "Game"

def create_desktop_shortcut():
    """Create a desktop shortcut/alias/link for the currently selected game."""
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game first.")
        return

    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    game_id = game_data['game_id']
    display_name = game_data['display_name']
    safe_name = sanitize_filename(display_name)


    # Determine which installed OS version to use (same logic used elsewhere)
    installed_os = None
    if isLinux:
        if game_id in saved_paths["Linux"]:
            installed_os = "Linux"
        elif game_id in saved_paths["Windows"]:
            installed_os = "Windows"
    else:
        if game_id in saved_paths[OS]:
            installed_os = OS

    if installed_os is None:
        QMessageBox.warning(window, "Not Installed", f"{display_name} is not installed.")
        return

    # Resolve executable relative path and full path
    executable_relative_path = executable_paths.get(installed_os, {}).get(game_id, "")
    game_install_path = saved_paths[installed_os][game_id]
    game_exec_full_path = os.path.join(game_install_path, executable_relative_path) if executable_relative_path else game_install_path
    game_exec_full_path = os.path.normpath(game_exec_full_path)

    icon_path = resolve_icon_path(installed_os, game_id, game_install_path)

    if not os.path.exists(game_exec_full_path):
        QMessageBox.warning(window, "Executable Missing", f"Executable not found:\n{game_exec_full_path}")
        return

    desktop = get_desktop_path()
    os.makedirs(desktop, exist_ok=True)

    try:
        if isWindows:
            # Prefer win32com if available to create a real .lnk
            try:
                from win32com.client import Dispatch
                shortcut_path = os.path.join(desktop, f"{safe_name}.lnk")
                shell = Dispatch('WScript.Shell')
                shortcut = shell.CreateShortCut(shortcut_path)
                shortcut.Targetpath = game_exec_full_path
                shortcut.WorkingDirectory = os.path.dirname(game_exec_full_path)
                shortcut.IconLocation = icon_path if icon_path else game_exec_full_path
                shortcut.save()
            except Exception:
                # Fallback to .url which also works as a clickable link
                url_path = os.path.join(desktop, f"{safe_name}.url")
                with open(url_path, "w", encoding="utf-8") as f:
                    f.write("[InternetShortcut]\n")
                    f.write("URL=file:///" + game_exec_full_path.replace("\\", "/") + "\n")

                    icon_src = icon_path if icon_path else game_exec_full_path
                    f.write("IconFile=" + icon_src + "\n")
                    f.write("IconIndex=0\n")


        elif isMacOS:
            # Make a Finder alias using AppleScript
            # The alias will be created on the desktop
            # Use POSIX paths
            as_cmd = (
                f'tell application "Finder" to make alias file to '
                f'(POSIX file "{game_exec_full_path}") '
                f'at (POSIX file "{desktop}") '
                f'with properties {{name:"{safe_name}"}}'
            )

            subprocess.run(["osascript", "-e", as_cmd], check=False)

            if icon_path:
                copy_icon_cmd = f'''
                set src to POSIX file "{icon_path}"
                set dst to POSIX file "{os.path.join(desktop, display_name)}"
                tell application "Finder"
                    set icon of dst to icon of src
                end tell
                '''
                subprocess.run(["osascript", "-e", copy_icon_cmd], check=False)


        elif isLinux:
            desktop_file = os.path.join(desktop, f"{safe_name}.desktop")
            exec_cmd = None

            if installed_os == "Windows":
                if os.path.exists(PROTON_EXECUTABLE):
                    exec_cmd = (
                        f'STEAM_COMPAT_DATA_PATH={PROTON_PFX} '
                        f'STEAM_COMPAT_CLIENT_INSTALL_PATH={PROTON_PFX} '
                        f'WINEDLLOVERRIDES="dinput8,d3d9,version,steamoverlay64,winmm=n,b" '
                        f'"{PROTON_EXECUTABLE}" run "{game_exec_full_path}"'
                    )
                else:
                    exec_cmd = f'xdg-open "{game_exec_full_path}"'
            else:
                exec_cmd = f'"{game_exec_full_path}"'

            if not exec_cmd:
                raise RuntimeError("Failed to build Exec command for Linux shortcut")

            desktop_entry = [
                "[Desktop Entry]",
                f"Name={display_name}",
                f"Exec={exec_cmd}",
                "Type=Application",
                f"Path={os.path.dirname(game_exec_full_path)}",
                f"Icon={icon_path if icon_path else os.path.splitext(game_exec_full_path)[0]}",
                "Terminal=false"
            ]
            with open(desktop_file, "w", encoding="utf-8") as f:
                f.write("\n".join(desktop_entry))
            # Make it executable
            try:
                os.chmod(desktop_file, 0o755)
            except Exception:
                pass

        QMessageBox.information(window, "Shortcut Created", f"Desktop shortcut created for {display_name}.")
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to create shortcut: {e}")

def resolve_icon_path(installed_os, game_id, game_install_path):
    rel_icon = icon_paths.get(installed_os, {}).get(game_id)
    if not rel_icon:
        return None

    icon_full = os.path.normpath(os.path.join(game_install_path, rel_icon))
    return icon_full if os.path.exists(icon_full) else None

uninstall_button.clicked.connect(uninstall_game)

def handle_close_event(event):
    if currently_downloading:
        reply = QMessageBox.warning(window, "Downloading", "Quit and cancel download?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.No: event.ignore()
        else: 
            cancel_download(currently_downloading_game)
            event.accept()
    else: event.accept()

window.closeEvent = handle_close_event
window.show()
sys.exit(app.exec())
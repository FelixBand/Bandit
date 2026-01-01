import sys
import requests
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

version = "1.3.1"

# --- PROTON CONFIGURATION (Linux Only) ---
PROTON_GE_VERSION = "GE-Proton10-27"
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
    global game_origin_os
    
    # 1. Fetch Native Games
    native_list = _fetch_remote("list.txt", as_json=False, default=[])
    
    # Register native games
    for line in native_list:
        parts = line.split('|')
        if len(parts) > 1:
            game_origin_os[parts[1]] = OS

    # 2. If Linux, also fetch Windows games
    if isLinux:
        windows_list = _fetch_remote("list.txt", as_json=False, default=[], os_override="Windows")
        
        # Merge lists, but prefer Native (Linux) if a game ID exists in both
        existing_ids = set(game_origin_os.keys())
        
        for line in windows_list:
            parts = line.split('|')
            if len(parts) > 1:
                g_id = parts[1]
                if g_id not in existing_ids:
                    # It's a Windows-only game, add it
                    native_list.append(line)
                    game_origin_os[g_id] = "Windows"
    
    return native_list

def download_executable_paths():
    # Fetch Native paths
    paths = _fetch_remote("executable_paths.json", as_json=True, default={})
    
    # If Linux, merge Windows paths for the Windows games
    if isLinux:
        win_paths = _fetch_remote("executable_paths.json", as_json=True, default={}, os_override="Windows")
        # Update dict, but keep existing (native) keys if they exist
        for k, v in win_paths.items():
            if k not in paths:
                paths[k] = v
    return paths

def download_prereq_paths(os_override=None):
    """Fetch prerequisite paths for a specific OS"""
    target_os = os_override if os_override else OS
    return _fetch_remote("prereq_paths.json", as_json=True, default={}, os_override=target_os)

if not os.path.exists(saved_paths_file):
    with open(saved_paths_file, 'w') as f:
        json.dump({}, f)

try:
    with open(saved_paths_file, 'r') as f:
        saved_paths = json.load(f)
except Exception:
    saved_paths = {}

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
    installed_display_names = [
        parse_game_entry(game)['display_name']
        for game in game_list
        if parse_game_entry(game)['game_id'] in saved_paths
    ]
    delegate.set_installed_games(installed_display_names)
    game_list_widget.viewport().update()

update_installed_opacity()

for game in game_list:
    game_data = parse_game_entry(game)
    display_name = game_data['display_name']
    multiplayer_status = game_data['multiplayer_status']
    
    # Visual indicator for Windows games on Linux? 
    # Optional: You could add " (Win)" to display name, but OpacityDelegate might need adjustment.
    # For now, we keep it clean.

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

    if currently_downloading and currently_downloading_game != game_id and game_id not in saved_paths:
        download_play_button.setEnabled(False)
    else:
        download_play_button.setEnabled(True)

    if game_id in saved_paths:
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
    action = menu.exec(game_list_widget.viewport().mapToGlobal(position))
    if action == browse_action:
        browse_file_location()

game_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
game_list_widget.customContextMenuRequested.connect(show_context_menu)

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
    if game_id in saved_paths:
        print(f"Launching game {display_name}...")
        
        if game_id not in executable_paths:
            QMessageBox.critical(window, "Error", f"Executable path for {display_name} not found.")
            return
        
        executable_relative_path = executable_paths[game_id]
        game_install_path = saved_paths[game_id]
        game_exec_full_path = os.path.join(game_install_path, executable_relative_path)
        
        if not os.path.exists(game_exec_full_path):
            QMessageBox.critical(window, "Error", f"Executable not found at:\n{game_exec_full_path}")
            return
        
        # Prerequisites check - Use the game's origin OS to get the correct prerequisites
        game_os = game_origin_os.get(game_id, OS)
        prereq_paths = download_prereq_paths(game_os)
        if game_id in prereq_paths and prereq_paths[game_id]:
            install_prerequisites(game_os)  # Pass the game's OS to install_prerequisites

        try:
            # --- LINUX + WINDOWS GAME (PROTON) HANDLING ---
            if isLinux and game_origin_os.get(game_id) == "Windows":
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
                
                # Command: ./proton run "game.exe"
                # cwd needs to be the Proton directory for some versions, or the game dir? 
                # Proton usually prefers being run from its own dir or absolute path.
                
                cmd = [PROTON_EXECUTABLE, "run", game_exec_full_path]
                
                # We do NOT change CWD to the game folder here, Proton handles that via the run command usually.
                # However, some games rely on CWD. 
                # The user's script: STEAM... ./proton run "$1"
                # implies we invoke proton. Proton "run" verb usually sets up the environment and runs the exe.
                
                subprocess.Popen(cmd, env=env)
                
            elif isWindows:
                # Windows native
                subprocess.Popen([f"{game_exec_full_path}"], cwd=os.path.join(game_install_path, os.path.dirname(executable_relative_path)), shell=True)
            elif isLinux:
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

    if isWindows:
        os.makedirs(os.path.join(os.path.expandvars("%USERPROFILE%"), ".banditgamelauncher", "games"), exist_ok=True)
        download_path = os.path.join(os.path.expandvars("%USERPROFILE%"), ".banditgamelauncher", "games")
    elif isMacOS:
        os.makedirs(os.path.join(os.path.expanduser("~"), "Bandit Game Launcher", "games"), exist_ok=True)
        download_path = os.path.join(os.path.expanduser("~"), "Bandit Game Launcher", "games")
    elif isLinux:
        os.makedirs(os.path.join(os.path.expanduser("~"), ".banditgamelauncher", "games"), exist_ok=True)
        download_path = os.path.join(os.path.expanduser("~"), ".banditgamelauncher", "games")

    selected_parent = QFileDialog.getExistingDirectory(window, "Select Download Directory", download_path)
    if not selected_parent: return

    target_dir = os.path.join(selected_parent)
    os.makedirs(target_dir, exist_ok=True)

    currently_downloading_game = game_id
    on_game_selected()

    print(f"Downloading {display_name} to {target_dir}")
    currently_downloading = True
    success = download_game(game_id, target_dir, display_name)

    if success:
        percentage_label.setText("Downloaded " + display_name + " successfully!")
        saved_paths[game_id] = target_dir
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

def download_game(game_id, download_path, display_name=None):
    global download_cancel_requested, _current_download_response, currently_downloading_game, currently_downloading
    
    # Determine URL based on origin OS
    origin = game_origin_os.get(game_id, OS) # default to current OS if unknown
    url = f"https://thuis.felixband.nl/bandit/{origin}/{game_id}.tar.gz"
    
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
                        percentage_label.setText(f"Downloading {display_name}: {percent_done:.2f}% complete")
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

def uninstall_game():
    global saved_paths
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1: return
    
    selected_game_entry = game_list[selected_game_index]
    game_data = parse_game_entry(selected_game_entry)
    game_id = game_data['game_id']
    display_name = game_data['display_name']

    if game_id not in saved_paths: return

    game_install_path = saved_paths[game_id]
    executable_relative_path = executable_paths.get(game_id, "")
    
    if not executable_relative_path:
        # Fallback just to remove from list if path missing
        del saved_paths[game_id]
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
         del saved_paths[game_id]
         with open(saved_paths_file, 'w') as f: json.dump(saved_paths, f, indent=2)
         on_game_selected()
         update_installed_opacity()
         return

    confirm = QMessageBox.question(
        window,
        "Confirm Uninstall",
        f"Are you sure you want to uninstall {display_name}?\n\nThis will delete:\n{uninstall_path}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if confirm != QMessageBox.StandardButton.Yes: return

    try:
        shutil.rmtree(uninstall_path)
        del saved_paths[game_id]
        with open(saved_paths_file, 'w') as f: json.dump(saved_paths, f, indent=2)
        QMessageBox.information(window, "Uninstalled", f"{display_name} uninstalled.")
        on_game_selected()
        update_installed_opacity()
        percentage_label.setText("Uninstalled " + display_name)
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

    # Use provided game_os or get from game_origin_os
    if game_os is None:
        game_os = game_origin_os.get(game_id, OS)

    # Fetch prerequisites for the correct OS
    prereq_paths = download_prereq_paths(game_os)
    
    if game_id not in prereq_paths or not prereq_paths[game_id]: 
        return

    game_install_path = saved_paths[game_id]
    executable_relative_path = executable_paths.get(game_id, "")
    
    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""
    
    game_base_folder = os.path.realpath(os.path.join(game_install_path, first_folder))
    marker_path = os.path.join(game_base_folder, "prerequisites_installed.txt")
    if os.path.exists(marker_path):
        percentage_label.setText(f"Prerequisites already installed for {display_name}.")
        return

    prereqs = prereq_paths[game_id]
    reply = QMessageBox.question(window, "Install Prerequisites", f"Install {len(prereqs)} prerequisites for {display_name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    if reply != QMessageBox.StandardButton.Yes: return

    percentage_label.setText(f"Installing prerequisites for {display_name}...")
    QApplication.processEvents()

    for prereq in prereqs:
        rel_path = prereq.get("path", "")
        cmd_args = prereq.get("command", "")
        if not rel_path: continue

        full_path = os.path.join(game_base_folder, rel_path.lstrip("/").lstrip("\\"))
        installer_dir = os.path.dirname(full_path)

        try:
            # Check if we need to run via Proton (Windows game on Linux)
            if isLinux and game_os == "Windows":
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
    
    percentage_label.setText(f"Finished prerequisites for {display_name}.")
    QMessageBox.information(window, "Done", f"Prerequisites installed.")

def browse_file_location():
    # (Same as before, abbreviated for space)
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1: return
    selected_game_entry = game_list[selected_game_index]
    game_id = parse_game_entry(selected_game_entry)['game_id']
    if game_id not in saved_paths: return
    
    path = saved_paths[game_id]
    exe_path = executable_paths.get(game_id, "")
    # ... logic to find folder ...
    parts = exe_path.replace("\\", "/").split("/")
    first = parts[0] if parts else ""
    target = os.path.join(path, first)
    
    if isWindows: os.startfile(target)
    elif isMacOS: subprocess.run(["open", "-R", target])
    elif isLinux: subprocess.run(["xdg-open", target])

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
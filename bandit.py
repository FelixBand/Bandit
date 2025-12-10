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

# Force OS to Windows for testing/compilation consistency if needed, 
# but rely on dynamic check for pathing below
# OS = "Windows" 

version = "1.3.0"

# --- CONFIGURATION FILE PATH FIX (Addressing Permission/Sync Issues) ---
# Determine a safe, user-writable directory for configuration files (like saved_paths.json)
# This fixes permission issues when installed in Program Files or a Mac App Bundle.

if isWindows:
    # Use %APPDATA% for configuration data on Windows
    CONFIG_BASE = os.path.expandvars("%APPDATA%")
    CONFIG_DIR = os.path.join(CONFIG_BASE, "BanditGameLauncher")
elif isMacOS:
    # Use Application Support on macOS
    CONFIG_BASE = os.path.expanduser("~/Library/Application Support")
    CONFIG_DIR = os.path.join(CONFIG_BASE, "BanditGameLauncher")
elif isLinux:
    # Use ~/.config on Linux (following XDG Base Directory Specification)
    CONFIG_BASE = os.path.expanduser("~/.config")
    CONFIG_DIR = os.path.join(CONFIG_BASE, "banditgamelauncher")
else:
    # Fallback (should not happen, but safe)
    CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure the configuration directory exists
os.makedirs(CONFIG_DIR, exist_ok=True)

# Define the new, safe path for the configuration file
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
        self.installed_games = set()  # use a set for faster lookups

    def paint(self, painter, option, index):
        game_title_with_emoji = index.data(Qt.ItemDataRole.DisplayRole)
        # Strip emoji prefix to get the clean display name for lookup
        game_title = game_title_with_emoji[2:].strip() if game_title_with_emoji else ""

        if game_title in self.installed_games:
            painter.setOpacity(1.0)  # Fully opaque for installed
        else:
            painter.setOpacity(0.4)  # 40% opacity for not installed

        super().paint(painter, option, index)
        painter.setOpacity(1.0)  # Reset opacity for next paint

    def set_installed_games(self, games):
        self.installed_games = set(games)

# Make list of games downloaded from https://thuis.felixband.nl/bandit/{OS}/list.txt
# {OS} is Windows, Linux, or Darwin
# Entry of list.txt is one game per line, and looks as such:
# Display Name|game_id|Size in bytes (number)|multiplayer_status

def _fetch_remote(path, as_json=False, timeout=10, default=None):
    url = f"https://thuis.felixband.nl/bandit/{OS}/{path}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        if as_json:
            return resp.json()
        # return non-empty lines for plain text lists
        return [line for line in resp.text.splitlines() if line.strip()]
    except Exception as e:
        print(f"Failed fetching {url}: {e}")
        if default is not None:
            return default
        return {} if as_json else []

def download_game_list():
    return _fetch_remote("list.txt", as_json=False, default=[])

def download_executable_paths():
    return _fetch_remote("executable_paths.json", as_json=True, default={})

def download_prereq_paths():
    return _fetch_remote("prereq_paths.json", as_json=True, default={})

# Make a new saved_paths.json file if it doesn't exist
if not os.path.exists(saved_paths_file):
    with open(saved_paths_file, 'w') as f:
        json.dump({}, f)

# Load saved paths into a dict so we can check installed games
try:
    with open(saved_paths_file, 'r') as f:
        saved_paths = json.load(f)
except Exception:
    saved_paths = {}

# --- GAME DATA PARSING & ACCESS UTILITY (Addressing Repetitive Code) ---

def parse_game_entry(selected_game_entry):
    """Parses a game entry string into a dictionary."""
    fields = selected_game_entry.split('|')
    data = {
        'display_name': fields[0],
        'game_id': fields[1],
        'size_in_bytes': fields[2],
        'multiplayer_status': fields[3] if len(fields) > 3 else '0'
    }
    return data

# Sort the list alphabetically by display name
def sort_game_list(game_list):
    return sorted(game_list, key=lambda x: x.split('|')[0].lower())

executable_paths = download_executable_paths()

game_list = download_game_list()
game_list = sort_game_list(game_list)
game_list_widget = QListWidget()

font = QFont()
if isMacOS:
    font.setPointSize(16)
else:
    font.setPointSize(12)
game_list_widget.setFont(font)

# Create and assign delegate
delegate = OpacityDelegate(game_list_widget)
game_list_widget.setItemDelegate(delegate)

def update_installed_opacity():
    """Refresh which games are shown as installed (100% opacity)."""
    installed_display_names = [
        parse_game_entry(game)['display_name']
        for game in game_list
        if parse_game_entry(game)['game_id'] in saved_paths
    ]
    delegate.set_installed_games(installed_display_names)
    game_list_widget.viewport().update()

update_installed_opacity()

# Now we populate the list with only display names
for game in game_list:
    game_data = parse_game_entry(game)
    display_name = game_data['display_name']
    multiplayer_status = game_data['multiplayer_status']

    # Prefix multiplayer status to the display name. 0 = red circle emoji, 1 = orange circle emoji, 2 = yellow circle emoji 3 = green circle emoji

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

# Now we add a button to download/play the selected game. Download and play should be 1 button, depending on if the game is already downloaded or not.
download_play_button = QPushButton("Download/Play")
layout.addWidget(download_play_button)

uninstall_button = QPushButton("Uninstall")
layout.addWidget(uninstall_button)

# Percentage label
percentage_label = QLabel("Not currently downloading")
layout.addWidget(percentage_label)

size_label = QLabel("No game selected")
layout.addWidget(size_label)

multiplayer_status_label = QLabel("🔴 Singleplayer/Local only | 🟠 LAN Multiplayer | 🟢 Online Multiplayer (other Bandit users) | 🟩 Online Multiplayer (Official servers)")
layout.addWidget(multiplayer_status_label)

currently_downloading_game = ""
currently_downloading = False
# add cancellation globals
download_cancel_requested = False
_current_download_response = None

def check_for_updates():
    try:
        response = requests.get("https://api.github.com/repos/FelixBand/Bandit/releases/latest", timeout=10)
        response.raise_for_status()  # Check if the request was successful
        json_data = response.json()
        print("newest release: " + json_data["tag_name"])
        print("current version: " + version)
        if json_data["tag_name"] > version:
            reply = QMessageBox.question(None, 'Download update?', "A new update is available: " + json_data["tag_name"] + ". You're running version " + version + ". Would you like to update?", 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.Yes)

            if reply == QMessageBox.StandardButton.Yes:
                url = "https://github.com/FelixBand/Bandit/releases/latest"
                try:
                    webbrowser.open(url, new=2)  # open in a new tab if possible
                except Exception:
                    pass
                # give the browser a short moment to start before quitting the app
                QTimer.singleShot(500, app.quit)
                return

    except Exception as e:
        print(f"An error occurred while checking for updates: {e}")

check_for_updates()

# When a game is selected, show its size in GB, unless under 1 GB, then show in MB.
def on_game_selected():
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        size_label.setText("No game selected")
        download_play_button.setEnabled(False)
        uninstall_button.setEnabled(False)
        return

    selected_game_entry = game_list[selected_game_index]
    # Use utility function to access data
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']
    size_in_bytes = game_data['size_in_bytes']
    multiplayer_status = game_data['multiplayer_status']


    # Enable Download/Play button only if no other download is in progress
    if currently_downloading and currently_downloading_game != game_id and game_id not in saved_paths:
        download_play_button.setEnabled(False)
    else:
        download_play_button.setEnabled(True)

    # Enable or disable Uninstall button based on installation state
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

    # Show multiplayer status, not as number but as the emoji and description
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

# Enable right-click context menu
game_list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
game_list_widget.customContextMenuRequested.connect(show_context_menu)

def download_and_play_game():
    global currently_downloading_game, currently_downloading, saved_paths, download_cancel_requested, _current_download_response

    # reset cancel flag when starting a new download
    download_cancel_requested = False
    _current_download_response = None

    # get selected game first
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game to download/play.")
        currently_downloading = False
        return

    selected_game_entry = game_list[selected_game_index]
    # Use utility function to access data
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']
    size_in_bytes = game_data['size_in_bytes']
    multiplayer_status = game_data['multiplayer_status']

    # If already installed -> launch
    if game_id in saved_paths:
        print(f"Launching game {display_name}...")

        # This should launch the game executable.
        # We need to know the executable path, which is in executable_paths.json
        # An entry looks like this: # "game_id": "gamename/game.exe"
        # We need to join that with the saved path for this game.
        if game_id not in executable_paths:
            QMessageBox.critical(window, "Error", f"Executable path for {display_name} not found.")
            return
        
        executable_relative_path = executable_paths[game_id]
        print(executable_relative_path)
        game_install_path = saved_paths[game_id]
        print(game_install_path)
        game_exec_full_path = os.path.join(game_install_path, executable_relative_path)
        print(game_exec_full_path)
        print("IMPORTANT" + os.path.join(game_install_path, os.path.dirname(executable_relative_path)))
        if not os.path.exists(game_exec_full_path):
            QMessageBox.critical(window, "Error", f"Executable for {display_name} not found at expected location:\n{game_exec_full_path}")
            return
        
        # If the game is run for the first time, install prerequisites automatically.
        # This is done by checking if a file called "prerequisites_installed.txt" exists in the game folder.
        # Only install prerequisites if they exist for this game
        prereq_paths = download_prereq_paths()
        if game_id in prereq_paths and prereq_paths[game_id]:
            print(f"Installing prerequisites for {display_name}...")
            install_prerequisites()
        else:
            print(f"No prerequisites for {display_name}, skipping.")


        try:
            if isWindows:
                # cwd needs to be the directory of the executable
                # This needs to be the folder in which the executable file is located. So FOR EXAMPLE, in the case of The Sims 4 that would mean:
                # "The Sims 4/Game/Bin/TS4_x64.exe"
                # So the "Bin" folder.
                # This ensures the game starts correctly and any DLL injections (mods) work properly.
                try:
                    game_process = subprocess.Popen([f"{game_exec_full_path}"], cwd=os.path.join(game_install_path, os.path.dirname(executable_relative_path)), shell=True)
                except Exception as e:
                    print(f"Error launching executable: {e}")
            elif isLinux:
                subprocess.Popen([game_exec_full_path], cwd=os.path.dirname(game_exec_full_path))
            elif isMacOS:
                game_process = subprocess.Popen(['open', '-a', f"{game_exec_full_path}"])
            print(f"Launched {display_name} successfully.")
        except Exception as e:
            QMessageBox.critical(window, "Launch Failed", f"Failed to launch {display_name}: {e}")
        return

    # If it is currently downloading, cancel the download
    if currently_downloading_game == game_id:
        print(f"Cancelling download for {display_name}...")
        currently_downloading = False
        # call cancel with the actual game id before clearing state
        cancel_download(game_id)
        currently_downloading_game = ""
        on_game_selected()
        return

    # determine default download path by OS
    # Make the folder if it doesn't exist
    if isWindows:
        # Use %USERPROFILE%\.banditgamelauncher\games as the default download folder
        os.makedirs(os.path.join(os.path.expandvars("%USERPROFILE%"), ".banditgamelauncher", "games"), exist_ok=True)
        download_path = os.path.join(os.path.expandvars("%USERPROFILE%"), ".banditgamelauncher", "games")
    elif isMacOS:
        os.makedirs(os.path.join(os.path.expanduser("~"), "Bandit Game Launcher", "games"), exist_ok=True)
        download_path = os.path.join(os.path.expanduser("~"), "Bandit Game Launcher", "games")
    elif isLinux:
        os.makedirs(os.path.join(os.path.expanduser("~"), ".banditgamelauncher", "games"), exist_ok=True)
        download_path = os.path.join(os.path.expanduser("~"), ".banditgamelauncher", "games")

    # Ask user where to save the game
    # Default is the download_path determined above in "games" folder.
    selected_parent = QFileDialog.getExistingDirectory(window, "Select Download Directory", download_path)
    if not selected_parent:
        currently_downloading = False
        return

    # Create a folder for this game inside the selected directory and use that as the target.
    # The target_dir is the selected_parent, since the game is expected to extract its first-level folder there.
    target_dir = os.path.join(selected_parent)
    os.makedirs(target_dir, exist_ok=True)

    currently_downloading_game = game_id
    on_game_selected()

    print(f"Downloading {display_name} to {target_dir}")
    currently_downloading = True
    success = download_game(game_id, target_dir, display_name)

    if success:
        print(f"Finished downloading {display_name}")
        percentage_label.setText("Downloaded " + display_name + " successfully!")

        # Save to saved_paths.json only if download succeeded
        # Use the corrected global path
        try:
            # Re-read in case another process changed it (though unlikely)
            if os.path.exists(saved_paths_file):
                with open(saved_paths_file, 'r') as f:
                    # Update global saved_paths
                    saved_paths = json.load(f)
            else:
                saved_paths = {}
        except Exception:
            saved_paths = {}

        saved_paths[game_id] = target_dir
        try:
            with open(saved_paths_file, 'w') as f:
                json.dump(saved_paths, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            print(f"Saved game path to {saved_paths_file}")
        except Exception as e:
            print(f"Failed to write saved_paths.json: {e}")

        update_installed_opacity()
    else:
        print(f"Download of {display_name} failed or cancelled.")
        percentage_label.setText(f"Download of {display_name} cancelled.")


    currently_downloading = False
    currently_downloading_game = ""
    # refresh UI state after finishing
    on_game_selected()
    update_installed_opacity()

def download_game(game_id, download_path, display_name=None):
    global download_cancel_requested, _current_download_response, currently_downloading_game, currently_downloading
    url = f"https://thuis.felixband.nl/bandit/{OS}/{game_id}.tar.gz"
    success = False  # ✅ track if download actually succeeded
    try:
        with requests.get(url, stream=True, timeout=(5, 30)) as response:
            _current_download_response = response
            if response.status_code == 200:
                # Try to fetch the actual Content-Length from the server (compressed .tar.gz size)
                total_size = int(response.headers.get("Content-Length", 0))

                # Fallback if Content-Length is missing or invalid
                if not total_size:
                    try:
                        # Fall back to the size listed in list.txt
                        # Use utility function for safer access
                        game_entry = next((game for game in game_list if parse_game_entry(game)['game_id'] == game_id), None)
                        if game_entry:
                             total_size = int(parse_game_entry(game_entry)['size_in_bytes'])
                        else:
                            total_size = 0
                    except Exception:
                        total_size = 0

                downloaded_size = 0
                chunk_size = 8192  # 8 KB

                # Wrap the response.raw so we can track bytes as tarfile reads them.
                class ReadCounter:
                    def __init__(self, raw, on_bytes):
                        self.raw = raw
                        self.on_bytes = on_bytes
                        # tarfile checks decode_content attribute sometimes
                        self.decode_content = getattr(raw, "decode_content", False)

                    def read(self, size=-1):
                        # If a cancel was requested, raise to abort tar extraction/read loop
                        if download_cancel_requested:
                            raise IOError("Download cancelled")

                        data = self.raw.read(size)
                        if data:
                            try:
                                self.on_bytes(len(data))
                            except Exception:
                                pass

                        # If cancel requested after a read, raise to stop further processing
                        if download_cancel_requested:
                            raise IOError("Download cancelled")
                        return data

                    def readable(self):
                        return True

                    def close(self):
                        try:
                            return self.raw.close()
                        except Exception:
                            pass

                def on_bytes(n):
                    nonlocal downloaded_size
                    downloaded_size += n
                    if total_size:
                        percent_done = (downloaded_size / total_size) * 100
                        print(f"{downloaded_size} of {total_size}")
                        percentage_label.setText(f"Downloading {display_name}: {percent_done:.2f}% complete")
                    else:
                        percentage_label.setText(f"Downloading {display_name}: {downloaded_size} bytes")
                    # Make UI update immediately
                    QApplication.processEvents()

                # prepare wrapped fileobj and extract into download_path
                fileobj = response.raw
                fileobj.decode_content = True  # handle gzip decoding automatically
                wrapped = ReadCounter(fileobj, on_bytes)

                try:
                    with tarfile.open(fileobj=wrapped, mode='r|gz') as tar:
                        for member in tar:
                            if download_cancel_requested:
                                raise IOError("Download cancelled")
                            # tar.extract will read member data via our wrapped fileobj,
                            # so on_bytes will be called as data is streamed and the UI updated.
                            tar.extract(member, path=download_path)
                    print(f"\nGame {game_id} downloaded and extracted to {download_path}")
                    success = True  # Success
                except IOError as e:
                    # Cancellation or IO abort
                    print(f"Download cancelled or aborted: {e}")
                    percentage_label.setText(f"Download cancelled: {game_id}")
                    # best-effort cleanup: close response (context manager will handle)
                    return
            else:
                print(f"Failed to download game {game_id}. Status code: {response.status_code}")
    except Exception as e:
        # network errors, timeouts, or cancellation propagated here
        if download_cancel_requested:
            print(f"Download cancelled: {e}")
            percentage_label.setText(f"Download cancelled: {game_id}")
        else:
            print(f"Error downloading {game_id}: {e}")
    finally:
        # clear current response ref and reset flags as appropriate
        _current_download_response = None
        currently_downloading = False
        currently_downloading_game = ""
        QApplication.processEvents()

    return success  # return whether download succeeded

download_play_button.clicked.connect(download_and_play_game)

def cancel_download(game_id):
    global download_cancel_requested, _current_download_response, currently_downloading, currently_downloading_game
    download_cancel_requested = True
    # Close the HTTP response socket to attempt to unblock any read
    try:
        if _current_download_response is not None:
            try:
                _current_download_response.close()
            except Exception:
                pass
            _current_download_response = None
    except Exception as e:
        print(f"Failed to close response during cancel: {e}")

    currently_downloading = False
    currently_downloading_game = ""
    print(f"Download of {game_id} cancelled.")
    percentage_label.setText("Download cancelled")
    QApplication.processEvents()

def uninstall_game():
    global saved_paths
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game to uninstall.")
        return
    
    selected_game_entry = game_list[selected_game_index]
    # Use utility function to access data
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']
    size_in_bytes = game_data['size_in_bytes']
    multiplayer_status = game_data['multiplayer_status']


    if game_id not in saved_paths:
        QMessageBox.warning(window, "Not Installed", f"{display_name} is not installed.")
        return

    if game_id not in executable_paths:
        QMessageBox.critical(window, "Error", f"Executable path for {display_name} not found.")
        return

    game_install_path = saved_paths[game_id]
    executable_relative_path = executable_paths[game_id]

    # Normalize and sanitize the executable path
    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""

    # Prevent malformed paths
    if first_folder in ("..", "", ".", "/", "\\"):
        QMessageBox.critical(window, "Unsafe Path", f"Refusing to uninstall {display_name}: unsafe path detected.")
        return

    # Resolve absolute paths
    base_path = os.path.realpath(game_install_path)
    uninstall_path = os.path.realpath(os.path.join(base_path, first_folder))

    # Safety: don't allow uninstall if base_path is a root drive or filesystem root
    def is_root_path(p):
        ap = os.path.abspath(p)
        drive, tail = os.path.splitdrive(ap)
        return (tail == os.sep) or (tail in ("\\", "/")) or (ap == os.sep)

    if is_root_path(base_path):
        QMessageBox.critical(window, "Unsafe Uninstall", "Refusing to uninstall from a system/root location.")
        return

    # Ensure uninstall_path is inside game_install_path using commonpath
    try:
        if os.path.commonpath([base_path, uninstall_path]) != base_path:
            QMessageBox.critical(window, "Unsafe Uninstall", "Uninstall path escapes the game directory. Aborting for safety.")
            return
    except Exception:
        QMessageBox.critical(window, "Unsafe Uninstall", "Unable to validate uninstall path. Aborting for safety.")
        return

    # If the installation subpath does not exist, still remove the saved_paths entry so user can clear the listing.
    if not os.path.exists(uninstall_path):
        # remove entry and persist
        try:
            if game_id in saved_paths:
                del saved_paths[game_id]
                # Use the corrected global path
                with open(saved_paths_file, 'w') as f:
                    json.dump(saved_paths, f, indent=2)
            QMessageBox.information(window, "Uninstalled", f"No installation folder found for {display_name}.\nRemoved from launcher records.")
            on_game_selected()
            update_installed_opacity()
        except Exception as e:
            QMessageBox.critical(window, "Error", f"Failed to remove saved path for {display_name}:\n{e}")
        return

    # Confirm with user before removing real files
    confirm = QMessageBox.question(
        window,
        "Confirm Uninstall",
        f"Are you sure you want to uninstall {display_name}?\n\nThis will delete:\n{uninstall_path}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )

    if confirm != QMessageBox.StandardButton.Yes:
        return

    try:
        shutil.rmtree(uninstall_path)
        # Remove from saved_paths and update JSON
        if game_id in saved_paths:
            del saved_paths[game_id]
            # Use the corrected global path
            with open(saved_paths_file, 'w') as f:
                json.dump(saved_paths, f, indent=2)

        QMessageBox.information(window, "Uninstalled", f"{display_name} has been uninstalled successfully.")
        on_game_selected()
        update_installed_opacity()
        percentage_label.setText("Uninstalled " + display_name + " successfully.")

    except Exception as e:
        QMessageBox.critical(window, "Uninstall Failed", f"Failed to uninstall {display_name}:\n{e}")

# When the user clicks the "Install Prerequisites" button, we check if the selected game has any prerequisites listed.
# If so, we download and run each installer with the specified command line arguments.
# The path is of course the path to the game in saved_paths.json + the first folder of the executable path + the prereq path.
# So for example, "C:/Games/GTAIV/Installers/DirectX_jun2008/DXSetup.exe"
# The prereqs should run in order as listed in the JSON file.
# Preferrably on Windows, Bandit asks for admin rights once in order to run all the installers without having to ask again.

def install_prerequisites():
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game first.")
        return

    selected_game_entry = game_list[selected_game_index]
    # Use utility function to access data
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']


    if game_id not in saved_paths:
        QMessageBox.warning(window, "Game Not Installed", f"{display_name} must be installed before installing prerequisites.")
        return

    prereq_paths = download_prereq_paths()
    if game_id not in prereq_paths or not prereq_paths[game_id]:
        # Do nothing if no prereqs
        return

    game_install_path = saved_paths[game_id]
    executable_relative_path = executable_paths.get(game_id, "")
    if not executable_relative_path:
        QMessageBox.critical(window, "Error", f"Executable path for {display_name} not found.")
        return

    # Get the first folder name from the executable path (e.g., "RaceDriver3")
    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""

    if first_folder in ("..", "", ".", "/", "\\"):
        QMessageBox.critical(window, "Unsafe Path", "Invalid game path structure. Aborting.")
        return

    base_path = os.path.realpath(game_install_path)
    game_base_folder = os.path.realpath(os.path.join(base_path, first_folder))

    # Skip installing if prerequisites_installed.txt already exists
    marker_path = os.path.join(game_base_folder, "prerequisites_installed.txt")
    if os.path.exists(marker_path):
        print(f"Skipping prerequisites for {display_name}: marker file found at {marker_path}")
        percentage_label.setText(f"Prerequisites already installed for {display_name}.")
        return

    prereqs = prereq_paths[game_id]

    reply = QMessageBox.question(
        window,
        "Install Prerequisites",
        f"This will install {len(prereqs)} prerequisite(s) for {display_name}.\n\nContinue?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    if reply != QMessageBox.StandardButton.Yes:
        return

    percentage_label.setText(f"Installing prerequisites for {display_name}... Please wait.")
    QApplication.processEvents()

    for prereq in prereqs:
        rel_path = prereq.get("path", "")
        cmd_args = prereq.get("command", "")
        if not rel_path:
            continue

        full_path = os.path.join(game_base_folder, rel_path.lstrip("/").lstrip("\\"))
        full_path = os.path.realpath(full_path)

        # Safety check: prevent directory traversal
        try:
            if os.path.commonpath([game_base_folder, full_path]) != game_base_folder:
                QMessageBox.warning(window, "Unsafe Path", f"Skipping unsafe path: {full_path}")
                continue
        except Exception:
            QMessageBox.warning(window, "Unsafe Path", f"Could not validate path: {full_path}")
            continue

        if not os.path.exists(full_path):
            QMessageBox.warning(window, "Missing Installer", f"Installer not found:\n{full_path}")
            continue

        installer_dir = os.path.dirname(full_path)
        percentage_label.setText(f"Running: {os.path.basename(full_path)}")
        QApplication.processEvents()

        try:
            subprocess.run(
                [full_path] + cmd_args.split(),
                cwd=installer_dir,
                shell=True,
                check=True
            )
            print(f"Successfully installed: {full_path}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to install: {full_path} -> {e}")
            QMessageBox.warning(window, "Prerequisite Failed", f"Failed to run {os.path.basename(full_path)}:\n{e}")
        except Exception as e:
            print(f"Error launching {full_path}: {e}")
            QMessageBox.warning(window, "Prerequisite Error", f"Error launching {os.path.basename(full_path)}:\n{e}")

        time.sleep(1)
        QApplication.processEvents()

        # Create marker file so we don't reinstall next time
    try:
        marker_path = os.path.join(game_base_folder, "prerequisites_installed.txt")
        with open(marker_path, "w") as f:
            f.write("Prerequisites installed successfully.\n")
        print(f"Created prerequisites marker: {marker_path}")
    except Exception as e:
        print(f"Failed to create prerequisites marker file: {e}")


    percentage_label.setText(f"Finished installing prerequisites for {display_name}.")
    QMessageBox.information(window, "Done", f"All prerequisites for {display_name} have been executed.")

def browse_file_location():
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game first.")
        return

    selected_game_entry = game_list[selected_game_index]
    # Use utility function to access data
    game_data = parse_game_entry(selected_game_entry)
    display_name = game_data['display_name']
    game_id = game_data['game_id']

    if game_id not in saved_paths:
        QMessageBox.warning(window, "Game Not Installed", f"{display_name} is not installed.")
        return

    game_install_path = saved_paths[game_id]
    executable_relative_path = executable_paths.get(game_id, "")
    if not executable_relative_path:
        QMessageBox.warning(window, "Missing Executable", f"Executable path for {display_name} not found.")
        return

    # Normalize and safely extract the first folder from the executable path
    normalized_path = os.path.normpath(executable_relative_path).lstrip(os.sep).lstrip("\\")
    parts = normalized_path.split(os.sep) if os.sep in normalized_path else normalized_path.split("\\")
    first_folder = parts[0] if parts else ""

    if first_folder in ("..", "", ".", "/", "\\"):
        QMessageBox.warning(window, "Invalid Path", "Invalid game folder structure.")
        return

    # Final folder to open
    target_folder = os.path.realpath(os.path.join(game_install_path, first_folder))

    if not os.path.exists(target_folder):
        QMessageBox.warning(window, "Folder Not Found", f"The folder for {display_name} does not exist:\n{target_folder}")
        return

    try:
        if isWindows:
            # Windows: open the folder normally
            os.startfile(target_folder)
        elif isMacOS:
            # macOS: open Finder and highlight (select) the folder
            subprocess.run(["open", "-R", target_folder])
        elif isLinux:
            subprocess.run(["xdg-open", target_folder])
        else:
            QMessageBox.warning(window, "Unsupported OS", "This feature is not supported on your operating system.")
    except Exception as e:
        QMessageBox.critical(window, "Error", f"Failed to open file location:\n{e}")




uninstall_button.clicked.connect(uninstall_game)

def handle_close_event(event):
    global currently_downloading, currently_downloading_game

    if currently_downloading:
        reply = QMessageBox.warning(
            window,
            "Download in Progress",
            "A download is still in progress.\n\n"
            "If you close the launcher now, the download will be cancelled.\n\n"
            "Do you really want to quit?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.No:
            event.ignore()
            return
        else:
            print("User confirmed quit — cancelling active download.")
            cancel_download(currently_downloading_game)
            event.accept()
    else:
        event.accept()

# Attach the close event handler to the window
window.closeEvent = handle_close_event


# Show the window
window.show()
sys.exit(app.exec())
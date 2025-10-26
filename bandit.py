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

#OS = "Windows"

version = "1.0.0"

# Make a window
app = QApplication(sys.argv)
app.setApplicationName("Bandit - Game Launcher")
app.setWindowIcon(QIcon('icon.png'))
window = QWidget()
window.setWindowTitle("Bandit - Game Launcher")
window.setGeometry(100, 100, 800, 600)
layout = QVBoxLayout()
window.setLayout(layout)

class OpacityDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.installed_games = set()  # use a set for faster lookups

    def paint(self, painter, option, index):
        game_title = index.data(Qt.ItemDataRole.DisplayRole)
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
# Display Name|game_id|Size in bytes (number)

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
saved_paths_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_paths.json")
if not os.path.exists(saved_paths_file):
    with open(saved_paths_file, 'w') as f:
        json.dump({}, f)

# Load saved paths into a dict so we can check installed games
try:
    with open(saved_paths_file, 'r') as f:
        saved_paths = json.load(f)
except Exception:
    saved_paths = {}

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
        game.split('|')[0]
        for game in game_list
        if game.split('|')[1] in saved_paths
    ]
    delegate.set_installed_games(installed_display_names)
    game_list_widget.viewport().update()

update_installed_opacity()

# Make the list 50% opacity, for games that are not downloaded yet.
# We check saved_paths.json to see if the game is downloaded.

# Now we populate the list with only display names.
for game in game_list:
    display_name = game.split('|')[0]
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
    # Now we check if the selected game is downloaded or not, and change the download/play button text accordingly.
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        size_label.setText("No game selected")
        return

    # get the selected entry and its game_id
    selected_game_entry = game_list[selected_game_index]
    display_name, game_id, size_in_bytes = selected_game_entry.split('|')

    # check saved_paths (keys are game_id)
    if game_id in saved_paths:
        download_play_button.setText("Play")
    else:
        download_play_button.setText("Download")

    print(f"Currently downloading: {currently_downloading_game} versus {game_id}")
    if currently_downloading_game == game_id:
        download_play_button.setText("Cancel Download")

    # Make downloading other games disabled when one is downloading
    # Play is always enabled for installed games
    if currently_downloading and currently_downloading_game != game_id and game_id not in saved_paths:
        download_play_button.setEnabled(False)
    else:
        download_play_button.setEnabled(True)

    size_in_bytes = int(size_in_bytes) # Tell the user the size of the game (uncompressed)
    if size_in_bytes >= 1_000_000_000:  # 1 GB
        size_in_gb = size_in_bytes / 1_000_000_000
        size_label.setText(f"Size of {display_name}: {size_in_gb:.2f} GB")
    else:
        size_in_mb = size_in_bytes / 1_000_000
        size_label.setText(f"Size of {display_name}: {size_in_mb:.2f} MB")

game_list_widget.currentRowChanged.connect(on_game_selected)

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
    display_name, game_id, size_in_bytes = selected_game_entry.split('|')

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
        prereq_flag_file = os.path.join(game_install_path, os.path.dirname(executable_relative_path), "prerequisites_installed.txt")
        if not os.path.exists(prereq_flag_file):
            print(f"Installing prerequisites for {display_name}...")
            install_prerequisites()
            # Create the flag file to avoid reinstalling next time
            try:
                with open(prereq_flag_file, 'w') as f:
                    f.write("Prerequisites installed.")
            except Exception as e:
                print(f"Failed to create prerequisites flag file: {e}")


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
    target_dir = os.path.join(selected_parent)
    os.makedirs(target_dir, exist_ok=True)

    currently_downloading_game = game_id
    on_game_selected()

    print(f"Downloading {display_name} to {target_dir}")
    currently_downloading = True
    download_game(game_id, target_dir)

    print(f"Finished downloading {display_name}")
    percentage_label.setText("Downloaded " + display_name + " successfully!")

    # In the same directory where this .py script is located, we make an entry in a file called "saved_paths.json"
    # That tracks where the games are saved.
    saved_paths_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_paths.json")
    try:
        if os.path.exists(saved_paths_file):
            with open(saved_paths_file, 'r') as f:
                saved_paths = json.load(f)
        else:
            saved_paths = {}
    except Exception:
        # corrupted or unreadable JSON -> start fresh
        saved_paths = {}

    # record the chosen path for this game and persist immediately
    saved_paths[game_id] = target_dir
    try:
        with open(saved_paths_file, 'w') as f:
            json.dump(saved_paths, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        print(f"Saved game path to {saved_paths_file}")
    except Exception as e:
        print(f"Failed to write saved_paths.json: {e}")

    currently_downloading = False
    currently_downloading_game = ""
    # refresh UI state after finishing
    on_game_selected()
    update_installed_opacity()

def download_game(game_id, download_path):
    global download_cancel_requested, _current_download_response, currently_downloading_game, currently_downloading
    url = f"https://thuis.felixband.nl/bandit/{OS}/{game_id}.tar.gz"
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
                        total_size = int([game.split('|')[2] for game in game_list if game.split('|')[1] == game_id][0])
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
    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game to uninstall.")
        return
    
    selected_game_entry = game_list[selected_game_index]
    display_name, game_id, size_in_bytes = selected_game_entry.split('|')

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
            with open(saved_paths_file, 'w') as f:
                json.dump(saved_paths, f, indent=2)

        QMessageBox.information(window, "Uninstalled", f"{display_name} has been uninstalled successfully.")
        on_game_selected()
        update_installed_opacity()

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
    display_name, game_id, _ = selected_game_entry.split('|')

    if game_id not in saved_paths:
        QMessageBox.warning(window, "Game Not Installed", f"{display_name} must be installed before installing prerequisites.")
        return

    prereq_paths = download_prereq_paths()
    if game_id not in prereq_paths or not prereq_paths[game_id]:
        QMessageBox.information(window, "No Prerequisites", f"No prerequisites listed for {display_name}.")
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

    percentage_label.setText(f"Finished installing prerequisites for {display_name}.")
    QMessageBox.information(window, "Done", f"All prerequisites for {display_name} have been executed.")




uninstall_button.clicked.connect(uninstall_game)

# Show the window
window.show()
sys.exit(app.exec())
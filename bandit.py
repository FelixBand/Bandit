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
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote, quote
from plyer import notification
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QMenu, QGraphicsOpacityEffect, QStyledItemDelegate 
from PyQt6.QtCore import QThread, pyqtSignal, Qt

isWindows = platform.system() == 'Windows'
isMacOS = platform.system() == 'Darwin'
isLinux = platform.system() == 'Linux'

OS = platform.system()

#OS = "Windows"

version = "0.6.0"

# Make a window
app = QApplication(sys.argv)
app.setApplicationName("Bandit - Game Launcher")
app.setWindowIcon(QIcon('icon.png'))
window = QWidget()
window.setWindowTitle("Bandit - Game Launcher")
window.setGeometry(100, 100, 800, 600)
layout = QVBoxLayout()
window.setLayout(layout)

# Make list of games downloaded from https://thuis.felixband.nl/bandit/{OS}/list.txt
# {OS} is Windows, Linux, or Darwin
# Entry of list.txt is one game per line, and looks as such:
# Display Name|game_id|Size in bytes (number)

def download_game_list():
    url = f"https://thuis.felixband.nl/bandit/{OS}/list.txt"
    response = requests.get(url)
    if response.status_code == 200:
        game_list = response.text.splitlines()
        return game_list
    return []

def download_executable_paths():
    url = f"https://thuis.felixband.nl/bandit/{OS}/executable_paths.json"
    response = requests.get(url)
    if response.status_code == 200:
        try:
            executable_paths = response.json()
            return executable_paths
        except Exception:
            return {}

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

    size_in_bytes = int(size_in_bytes)
    if size_in_bytes >= 1_073_741_824:  # 1 GB
        size_in_gb = size_in_bytes / 1_073_741_824
        size_label.setText(f"Size of {display_name}: {size_in_gb:.2f} GB")
    else:
        size_in_mb = size_in_bytes / 1_048_576
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
            elif isMacOS or isLinux:
                subprocess.Popen([game_exec_full_path], cwd=os.path.dirname(game_exec_full_path))
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

def download_game(game_id, download_path):
    global download_cancel_requested, _current_download_response, currently_downloading_game, currently_downloading
    url = f"https://thuis.felixband.nl/bandit/{OS}/{game_id}.tar.gz"
    try:
        with requests.get(url, stream=True, timeout=(5, 30)) as response:
            _current_download_response = response
            if response.status_code == 200:
                total_size = int([game.split('|')[2] for game in game_list if game.split('|')[1] == game_id][0])
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
                        percentage_label.setText(f"Downloading {game_id}: {percent_done:.2f}% complete")
                    else:
                        percentage_label.setText(f"Downloading {game_id}: {downloaded_size} bytes")
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
    # This should uninstall the currently selected game.
    # It should show a confirmation dialog first.
    return


# Show the window
window.show()
sys.exit(app.exec())
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

OS = "Windows"

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

game_list = download_game_list()
game_list_widget = QListWidget()
# Now we populate the list with only display names.
for game in game_list:
    display_name = game.split('|')[0]
    game_list_widget.addItem(display_name)

layout.addWidget(game_list_widget)

# Now we add a button to download/play the selected game. Download and play should be 1 button, depending on if the game is already downloaded or not.
download_play_button = QPushButton("Download/Play")
layout.addWidget(download_play_button)

# Percenrtage label
percentage_label = QLabel("Not currently downloading")
layout.addWidget(percentage_label)

def download_and_play_game():
    # When downloading the game, a prompt should appear asking where to save the game.
    # The default location is depending on the OS:
    # Windows: %USERPROFILE%/.banditgamelauncher/games/
    # MacOS: ~/Bandit Game Launcher/games/
    # Linux: ~/.banditgamelauncher/games/

    # When the game gets downloaded, it should download in chunks and show a progress bar.
    # We do NOT want the tar.gz do download and then have to extract, because that takes up double the space.
    # Instead, we want to stream the download and extract at the same time.
    
    print("Gonna download")

    selected_game_index = game_list_widget.currentRow()
    if selected_game_index == -1:
        QMessageBox.warning(window, "No Game Selected", "Please select a game to download/play.")
        return
    
    selected_game_entry = game_list[selected_game_index]
    display_name, game_id, size_in_bytes = selected_game_entry.split('|')

    # Now we need to determine the download path
    if isWindows:
        download_path = os.path.join(os.path.expandvars("%USERPROFILE%"), ".banditgamelauncher", "games", game_id)
    elif isMacOS:
        download_path = os.path.join(os.path.expanduser("~"), "Bandit Game Launcher", "games", game_id)
    elif isLinux:
        download_path = os.path.join(os.path.expanduser("~"), ".banditgamelauncher", "games", game_id)

    # Ask user where to save the game
    selected_parent = QFileDialog.getExistingDirectory(window, "Select Download Directory", os.path.dirname(download_path))
    if not selected_parent:
        return

    # Create a folder for this game inside the selected directory and use that as the target.
    target_dir = os.path.join(selected_parent)
    os.makedirs(target_dir, exist_ok=True)

    print(f"Downloading {display_name} to {target_dir}")
    download_game(game_id, target_dir)

    print(f"Finished downloading {display_name}")
    percentage_label.setText("Downloaded " + display_name + " successfully!")

def download_game(game_id, download_path):
    url = f"https://thuis.felixband.nl/bandit/{OS}/{game_id}.tar.gz"
    with requests.get(url, stream=True) as response:
        if response.status_code == 200:
            total_size = int([game.split('|')[2] for game in game_list if game.split('|')[1] == game_id][0])
            downloaded_size = 0
            chunk_size = 8192  # 8 KB

            # Open the tarfile directly from the streamed HTTP response
            fileobj = response.raw
            fileobj.decode_content = True  # handle gzip decoding automatically
            with tarfile.open(fileobj=fileobj, mode='r|gz') as tar:
                for member in tar:
                    tar.extract(member, path=os.path.dirname(download_path))
                    downloaded_size += member.size
                    percent_done = (downloaded_size / total_size) * 100
                    print(f"Downloading {game_id}: {percent_done:.2f}% complete", end='\r')
                    percentage_label.setText(f"Downloading {game_id}: {percent_done:.2f}% complete")
                    QApplication.processEvents()
            print(f"\nGame {game_id} downloaded and extracted to {download_path}")
        else:
            print(f"Failed to download game {game_id}. Status code: {response.status_code}")

download_play_button.clicked.connect(download_and_play_game)


# Show the window
window.show()
sys.exit(app.exec())
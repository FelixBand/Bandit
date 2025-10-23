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
from plyer import notification
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QTabWidget, QMenu, QGraphicsOpacityEffect, QStyledItemDelegate
from PyQt6.QtCore import QThread, pyqtSignal, Qt

isWindows = platform.system() == 'Windows'
isMacOS = platform.system() == 'Darwin'
isLinux = platform.system() == 'Linux'
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
    url = f"https://thuis.felixband.nl/bandit/{platform.system()}/list.txt"
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

def download_and_play_game():
    # When downloading the game, a prompt should appear asking where to save the game.
    # The default location is depending on the OS:
    # Windows: %USERPROFILE%/.banditgamelauncher/games/
    # MacOS: ~/Bandit Game Launcher/games/
    # Linux: ~/.banditgamelauncher/games/

    # When the game gets downloaded, it should download in chunks and show a progress bar.
    # We do NOT want the tar.gz do download and then have to extract, because that takes up double the space.
    # Instead, we want to stream the download and extract at the same time.

    # Try to avoid error: QThread: Destroyed while thread '' is still running

    print("hello")
    

download_play_button.clicked.connect(download_and_play_game)


# Show the window
window.show()
sys.exit(app.exec())
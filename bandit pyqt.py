import sys
import urllib.parse
import urllib.request
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

class OpacityDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.installed_games = []

    def paint(self, painter, option, index):
        game_title = index.data(Qt.ItemDataRole.DisplayRole)
        if game_title in self.installed_games: # If the currently selected game is found in saved_paths.json
            painter.setOpacity(1.0)  # Fully opaque
        else:
            painter.setOpacity(0.5)  # 50% opaque

        super().paint(painter, option, index)
        painter.setOpacity(1.0)  # Reset opacity for other widgets

    def set_installed_games(self, games):
        self.installed_games = games

class DownloadThread(QThread):
    downloadCancelled = pyqtSignal()
    progressChanged = pyqtSignal(float)
    extractionComplete = pyqtSignal()

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.cancelled = False

    def run(self):
        try:
            response = urllib.request.urlopen(self.url)
            total_size = int(response.headers['Content-Length'])
            downloaded_size = 0
            chunk_size = 4096
            start_time = time.time()  # Record start time
            with tarfile.open(fileobj=response, mode="r:gz") as tar:
                for member in tar:
                    tar.extract(member, self.save_path)
                    downloaded_size += member.size
                    percentage = min((downloaded_size / total_size) * 100, 100)  # Ensure progress doesn't exceed 100%

                    print(f"Downloaded {downloaded_size} of {total_size}")

                    self.progressChanged.emit(percentage)

                    # Update downloaded bytes
                    self.downloaded_bytes = downloaded_size

                    if self.cancelled:
                        break

            if self.cancelled:
                print("Download cancelled.")
                self.downloadCancelled.emit()
                return

            print("Extraction complete.")
            self.extractionComplete.emit()
        except Exception as e:
            print(f"An error occurred: {e}")

def get_first_folder_in_path(game_title):
    with open(executable_paths_file, 'r') as file:
        executable_paths = json.load(file)
        executable_path = executable_paths.get(game_title, '')

    # Check if the path contains slashes
    if '/' in executable_path:
        # Split the path by '/'
        path_components = executable_path.split('/')
        # Get the first folder in the path
        first_folder = path_components[0]
    else:
        # Return the full path if it doesn't contain slashes
        first_folder = executable_path

    return first_folder

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.version = "0.2.0"
        self.setWindowTitle(f"Bandit - Game Downloader v{self.version}")
        self.setWindowIcon(QIcon("icon.ico"))  # Set the window icon
        self.setGeometry(100, 100, 800, 800)

        self.favorites = []
        self.favorites_file = os.path.join(app_data_dir, 'favorites.json')
        self.load_favorites()

        self.initUI()

    def initUI(self):
        layout = QVBoxLayout(self)
        self.tabWidget = QTabWidget()
        self.allListWidget = QListWidget()
        self.favoritesListWidget = QListWidget()
        self.tabWidget.addTab(self.allListWidget, "All")
        self.tabWidget.addTab(self.favoritesListWidget, "Favorites")

        self.allListWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.allListWidget.customContextMenuRequested.connect(self.show_context_menu)
        self.allListWidget.itemSelectionChanged.connect(self.selection_changed)  # Connect signal


        self.favoritesListWidget.itemSelectionChanged.connect(self.favorite_selection_changed)
        self.favoritesListWidget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.favoritesListWidget.customContextMenuRequested.connect(self.show_context_menu)
        self.favoritesListWidget.itemSelectionChanged.connect(self.selection_changed)  # Connect signal

        self.tabWidget.tabBarClicked.connect(self.clear_selection) # Deselect game when changing tabs!!!

        font = self.allListWidget.font()
        if isMacOS:
            font.setPointSize(16)
        else:
            font.setPointSize(11)  # Adjust the font size as needed

        self.allListWidget.setFont(font)

        font = self.favoritesListWidget.font()
        if isMacOS:
            font.setPointSize(16)
        else:
            font.setPointSize(11)  # Adjust the font size as needed
        self.favoritesListWidget.setFont(font)

        layout.addWidget(self.tabWidget)
        self.setLayout(layout)

        buttonLayout = QVBoxLayout()

        self.downloadButton = QPushButton("Download")
        self.downloadButton.clicked.connect(self.download_game)
        self.downloadButton.setEnabled(False)
        buttonLayout.addWidget(self.downloadButton)

        self.cancelButton = QPushButton("Cancel Download")
        self.cancelButton.clicked.connect(self.cancel_download)
        self.cancelButton.setEnabled(False)
        buttonLayout.addWidget(self.cancelButton)

        self.uninstallButton = QPushButton("Uninstall")
        self.uninstallButton.clicked.connect(self.uninstall_game)
        self.uninstallButton.setEnabled(False)
        buttonLayout.addWidget(self.uninstallButton)

        self.installRedistributablesButton = QPushButton("Install Redistributables")
        self.installRedistributablesButton.clicked.connect(self.install_redistributables)
        self.installRedistributablesButton.setEnabled(False)
        buttonLayout.addWidget(self.installRedistributablesButton)

        self.playButton = QPushButton("Play!")
        self.playButton.clicked.connect(self.play_game)
        self.playButton.setEnabled(False)
        buttonLayout.addWidget(self.playButton)

        self.progressLabel = QLabel()
        buttonLayout.addWidget(self.progressLabel)

        self.speedLabel = QLabel()  # Add speedLabel attribute
        buttonLayout.addWidget(self.speedLabel)  # Add speedLabel widget to layout

        self.sizeLabel = QLabel()  # Add sizeLabel attribute
        buttonLayout.addWidget(self.sizeLabel)  # Add sizeLabel widget to layout

        layout.addLayout(buttonLayout)

        self.load_items()
        self.selection_changed()  # Update button states based on initial selection

        self.game_downloading = None

    def clear_selection(self):
        self.allListWidget.clearSelection()
        self.favoritesListWidget.clearSelection()

    def favorite_selection_changed(self):
        selected_game = self.favoritesListWidget.currentItem().text()
        if selected_game:
            self.selection_changed()

    def show_context_menu(self, position):
        current_tab = self.tabWidget.currentIndex()
        if current_tab == 0:
            listWidget = self.allListWidget
        else:
            listWidget = self.favoritesListWidget

        selected_items = listWidget.selectedItems()
        if not selected_items:
            return

        selected_game = selected_items[0].text()
        contextMenu = QMenu(self)

        if selected_game in self.favorites:
            favoriteAction = contextMenu.addAction("Unfavorite")
            favoriteAction.triggered.connect(lambda: self.toggle_favorite(selected_game, False))
        else:
            favoriteAction = contextMenu.addAction("Favorite")
            favoriteAction.triggered.connect(lambda: self.toggle_favorite(selected_game, True))

        contextMenu.exec(listWidget.mapToGlobal(position))

    def toggle_favorite(self, game, favorite):
        if favorite:
            if game not in self.favorites:
                self.favorites.append(game)
        else:
            if game in self.favorites:
                self.favorites.remove(game)

        self.save_favorites()
        self.refresh_favorites_list()

    def save_favorites(self):
        with open(self.favorites_file, 'w') as file:
            json.dump(self.favorites, file)

    def refresh_favorites_list(self):
        self.favoritesListWidget.clear()
        for game in self.favorites:
            self.favoritesListWidget.addItem(game)

    def load_favorites(self):
        if os.path.exists(self.favorites_file):
            with open(self.favorites_file, 'r') as file:
                self.favorites = json.load(file)

    def install_redistributables(self):
        selected_game = self.allListWidget.currentItem().text()

        # Check if selected game exists in saved_paths
        with open(saved_paths_file, 'r') as saved_paths_file_obj:
            saved_paths = json.load(saved_paths_file_obj)
            if selected_game in saved_paths:
                save_path = saved_paths[selected_game]

                # Get the first folder in the game's path
                first_folder = get_first_folder_in_path(selected_game)

                # Read redistributable paths for the selected game
                with open(redist_paths_file, 'r') as file:
                    redist_paths = json.load(file)
                    if selected_game in redist_paths:
                        redistributables = redist_paths[selected_game]
                        for redistributable in redistributables:
                            redistributable_path = redistributable.get("path", "")
                            redistributable_command = redistributable.get("command", "")
                            
                            # Construct the full path to the redistributable
                            full_path = os.path.join(save_path, first_folder, redistributable_path.lstrip('/'))
                            # print(f"1:{save_path} 2:{first_folder} 3:{redistributable_path}")
                            print(f"Full redist install path: {full_path}")

                            # Install the redistributable
                            try:
                                subprocess.run([full_path, redistributable_command], cwd=os.path.join(save_path, first_folder), shell=True, check=True)
                                print(f"Successfully installed: {redistributable_path}")
                            except subprocess.CalledProcessError as e:
                                print(f"Failed to install: {redistributable_path}. Error: {e}")

                            self.progressLabel.setText("Redistributables installed!")
                    else:
                        print(f"No redistributables found for {selected_game}.")
            else:
                print(f"No saved path found for {selected_game}.")

    def selection_changed(self):
        selected_game = self.get_selected_game()
        if selected_game:
            self.update_size_label(selected_game)

            with open(saved_paths_file, 'r') as file:
                saved_paths = json.load(file)
                if selected_game in saved_paths:
                    if not selected_game == self.game_downloading:
                        self.playButton.setEnabled(True)
                        self.uninstallButton.setEnabled(True)

                    with open(redist_paths_file, 'r') as redist_file:
                        redist_paths = json.load(redist_file)
                        if selected_game in redist_paths and not selected_game == self.game_downloading: # If the selected game is in redist_paths and not downloading that game:
                            self.installRedistributablesButton.setEnabled(True)
                        else:
                            self.installRedistributablesButton.setEnabled(False)

                    game_size = self.get_game_size(selected_game)
                    if game_size:
                        self.sizeLabel.setText(f"Game size: {game_size}")
                    else:
                        self.sizeLabel.setText("Game size: Unknown")
                else:
                    if self.game_downloading == None:
                        self.downloadButton.setEnabled(True)
                    self.playButton.setEnabled(False)
                    self.uninstallButton.setEnabled(False)
                    self.installRedistributablesButton.setEnabled(False)
        else:
            self.downloadButton.setEnabled(False)
            self.playButton.setEnabled(False)
            self.uninstallButton.setEnabled(False)
            self.installRedistributablesButton.setEnabled(False)

    def get_selected_game(self):
        current_tab = self.tabWidget.currentIndex()
        if current_tab == 0:
            selected_items = self.allListWidget.selectedItems()
        else:
            selected_items = self.favoritesListWidget.selectedItems()

        if selected_items:
            return selected_items[0].text()
        return None

    def update_size_label(self, game_title):
        # Get the size of the selected game
        game_size = self.get_game_size(game_title)
        # Update the size label
        self.sizeLabel.setText(f"Game size: {game_size}")

    def get_game_size(self, game_title):
        try:
            # Try to read the list from the local file
            with open(list_file, 'r') as file:
                items = file.read().split('\n')
                items = [item.split('|') for item in items if item.strip()]  # Split by pipe
                # Print all items for debugging
                #print("All items in list.txt:")
                #for item in items:
                    #print(item)
                # Search for the game title and return its size
                for item in items:
                    if item[0] == game_title:
                        if len(item) >= 3:
                            return item[2]  # Return the size if available
                        else:
                            return "Unknown"  # Return "Unknown" if size is missing
        except Exception as e:
            print(f"An error occurred while retrieving the size of {game_title}: {e}")
            return "Unknown"  # Return "Unknown" if an error occurs
        
    def update_installed_games(self):  
        try:
            with open(saved_paths_file, 'r') as file:
                saved_paths = json.load(file)
                installed_games = list(saved_paths.keys())

            # Create a single delegate instance
            delegate = OpacityDelegate(self.allListWidget)
            delegate.set_installed_games(installed_games)

            # Apply the delegate to both list widgets
            self.allListWidget.setItemDelegate(delegate)
            self.favoritesListWidget.setItemDelegate(delegate)

            # Refresh allListWidget to apply the new delegate
            for index in range(self.allListWidget.count()):
                item = self.allListWidget.item(index)
                item.setData(Qt.ItemDataRole.DisplayRole, item.text())  # Fix this line

            # Refresh favoritesListWidget to apply the new delegate
            for index in range(self.favoritesListWidget.count()):
                item = self.favoritesListWidget.item(index)
                item.setData(Qt.ItemDataRole.DisplayRole, item.text())  # Fix this line

        except Exception as e:
            print(f"An error occurred while updating installed games: {e}")

    def load_items(self):
        try:
            with open(list_file, 'r') as file:
                items = file.read().split('\n')
                items = [item.split('|') for item in items if item.strip()]
                items.sort()

                installed_games = []
                for item in items:
                    game_title = item[0]
                    self.allListWidget.addItem(game_title)  # Ensure this line uses allListWidget
                    setattr(self, game_title.replace(' ', '_'), item[1] + '.tar.gz')

                    if self.is_game_installed(game_title):
                        installed_games.append(game_title)

                # Set the custom delegate
                self.update_installed_games()

            self.refresh_favorites_list()
        except Exception as e:
            print(f"An error occurred while loading items: {e}")

    def is_game_installed(self, game):
        try:
            with open(saved_paths_file, 'r') as file:
                saved_paths = json.load(file)
                return game in saved_paths
        except Exception as e:
            print(f"An error occurred while checking if the game is installed: {e}")
            return False
        
    def download_game(self):
        # Disable the Uninstall button while the download is in progress
        self.uninstallButton.setEnabled(False)

        current_tab_index = self.tabWidget.currentIndex()
        if current_tab_index == 0:  # All tab is active
            selected_game = self.allListWidget.currentItem().text()
        else:  # Favorites tab is active
            selected_game = self.favoritesListWidget.currentItem().text()

        # Disable the UI while downloading to prevent issues (for now)
        # self.allListWidget.setEnabled(False)
        # self.favoritesListWidget.setEnabled(False)
        # current_index = self.tabWidget.currentIndex()
        # for i in range(self.tabWidget.count()):
        #     if i != current_index:
        #         self.tabWidget.setTabEnabled(i, False)

        selected_game_file = getattr(self, selected_game.replace(' ', '_'))
        selected_game_url = f"https://thuis.felixband.nl/bandit/{platform.system()}/{selected_game_file}"
        save_path = QFileDialog.getExistingDirectory(None, "Select Download Location", games_folder)
        if save_path:
            self.game_downloading = selected_game # This is the currently downloading game title.
            self.downloadButton.setEnabled(False)
            self.cancelButton.setEnabled(True)
            self.thread = DownloadThread(selected_game_url, save_path)
            self.thread.progressChanged.connect(self.update_progress)
            self.thread.extractionComplete.connect(self.extraction_complete)
            self.thread.downloadCancelled.connect(self.on_download_cancelled)
            self.thread.start()
            self.start_time = time.time()  # Record start time
            self.downloaded_bytes = 0  # Initialize downloaded bytes

            # Save the selected save path to saved_paths.json
            with open(saved_paths_file, 'r+') as file:
                data = json.load(file)
                data[selected_game] = save_path
                file.seek(0)
                json.dump(data, file, indent=4)

        self.update_installed_games() # Update opacities

    def on_download_cancelled(self):
        self.downloadButton.setEnabled(True)
        self.uninstallButton.setEnabled(True)
        if hasattr(self, 'thread'):
            save_path = self.thread.save_path
            # Remove the partially downloaded file/folder
            print(self.game_downloading)
            self.delete_game(self.game_downloading)
            self.game_downloading = None # Current game being downloaded: None

    def update_progress(self, progress):
        progress_int = int(progress)  # Convert progress to an integer
        if progress_int >= 0 and progress_int < 100:  # Check for valid progress values
            self.progressLabel.setText(f"Download Progress: {progress:.2f}%")
            # Calculate download speed
            elapsed_time = time.time() - self.start_time
            if elapsed_time > 0:
                download_speed = self.thread.downloaded_bytes / (elapsed_time * 1024 * 1024)  # Convert bytes to MB/s
                self.speedLabel.setText(f"Download Speed: {download_speed:.2f} MB/s")
            # Update taskbar progress with the integer value
            # if isWindows:
                # self.taskbar_progress.setValue(progress_int)
        elif progress_int == 100:  # Check for completion
            self.progressLabel.setText("Extracting...")

    def extraction_complete(self):
        self.game_downloading = None

        self.progressLabel.setText("Done!")
        self.downloadButton.setEnabled(True)
        self.cancelButton.setEnabled(False)
        self.playButton.setEnabled(True)
        # Hide taskbar progress
        # if isWindows:
        #     self.taskbar_progress.hide()
        
        # Ensure the current item is not None before accessing its text
        selected_item = self.allListWidget.currentItem()
        if selected_item is not None:
            selected_game = selected_item.text()
            notification_text = f"{selected_game} has successfully installed!"
            
            # Uncomment the notification line if it's fixed or provide an alternative method
            try:
                self.show_notification(notification_text)  # Check if this works without crashing
            except Exception as e:
                print(f"Failed to show notification: {e}")
            
            self.uninstallButton.setEnabled(True)
        else:
            print("No game is selected.")


    def cancel_download(self):
        if hasattr(self, 'thread'):
            save_path = self.thread.save_path
            self.thread.cancelled = True
            self.cancelButton.setEnabled(False)
            self.progressLabel.setText("Download Canceled.")
            # Remove the partially downloaded file/folder
            #if os.path.exists(save_path):
            #    os.remove(save_path)

    def show_notification(self, text):
        # Display desktop notification
        notification_title = "Bandit - Game Downloader"
        notification.notify(
            title=notification_title,
            message=text,
            #app_icon="icon.ico",  # Path to the application icon
            timeout=10  # Notification duration in seconds (optional)
        )

    def play_game(self):
        # Disable the Uninstall button while the game is being played
        self.uninstallButton.setEnabled(False)

        selected_game = self.allListWidget.currentItem().text()
        # Read the executable path from executable_paths.json
        with open(executable_paths_file, 'r') as file:
            executable_paths = json.load(file)
            executable_path = executable_paths[selected_game]
        # Read the saved path from saved_paths.json
        with open(saved_paths_file, 'r') as file:
            saved_paths = json.load(file)
            save_path = saved_paths[selected_game]

        # Get the first folder in the game's path
        first_folder = get_first_folder_in_path(selected_game)
        if not first_folder:
            print("Error: No folder found in the game's path.")
            return

        # Launch the game executable
        if isWindows:
            try:
                game_process = subprocess.Popen([f"{save_path}/{executable_path}"], cwd=os.path.join(save_path, first_folder), shell=True)
            except Exception as e:
                print(f"Error launching executable: {e}")

        elif isMacOS:
            game_process = subprocess.Popen(['open', '-a', f"{save_path}/{first_folder}/{executable_path}"])

        
    def uninstall_game(self):
        selected_game = self.get_selected_game()
        self.delete_game(selected_game)

    def delete_game(self, game):
        # Read the saved path from saved_paths.json
        with open(saved_paths_file, 'r') as file:
            saved_paths = json.load(file)
            save_path = saved_paths[game]
        
        # Get the first folder in the game's path
        first_folder = get_first_folder_in_path(game)
        game_path = os.path.join(save_path, first_folder)
        
        # Check if the path is correct and prompt for confirmation
        confirm_message = f"Are you sure you want to uninstall {game}? This will delete: {game_path}"
        reply = QMessageBox.question(self, 'Confirmation', confirm_message, 
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                    QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(game_path) and not first_folder == None or first_folder != '': # A pretty important check that makes sure it does not delete the parent folder.
                    shutil.rmtree(game_path) # scary
                    print(f"Deleted folder: {game_path}")
                else:
                    print(f"The path {game_path} does not exist, removing instance from saved_paths.json")
                # Remove the title from saved_paths.json
                saved_paths.pop(game, None)
                
                # Update saved_paths.json
                with open(saved_paths_file, 'w') as file:
                    json.dump(saved_paths, file, indent=4)

                self.progressLabel.setText(f"{game} has been uninstalled.")
            except Exception as e:
                print(f"An error occurred while uninstalling the game: {e}")
        else:
            print("Uninstallation cancelled.")
        
        # Clear the selection and disable buttons
        self.allListWidget.clearSelection()
        self.downloadButton.setEnabled(False)
        self.playButton.setEnabled(False)
        self.uninstallButton.setEnabled(False)
        self.installRedistributablesButton.setEnabled(False)

        self.update_installed_games() # Update opacities

def sync_file(url, local_file):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            with open(local_file, 'wb') as file:
                file.write(response.read())
    except Exception as e:
        print(f"An error occurred while syncing {local_file}: {e}")

def sync_files():
    sync_file(f"https://thuis.felixband.nl/bandit/{platform.system()}/redist_paths.json", redist_paths_file)
    sync_file(f"https://thuis.felixband.nl/bandit/{platform.system()}/executable_paths.json", executable_paths_file)
    sync_file(f"https://thuis.felixband.nl/bandit/{platform.system()}/list.txt", list_file)

if __name__ == '__main__':
    # Get the directory for application-specific data
    if platform.system() == 'Windows':
        app_data_dir = os.path.expandvars(r"%userprofile%\\.banditgamedownloader")
    elif platform.system() == 'Darwin':  # macOS
        app_data_dir = os.path.expanduser("~/Library/Application Support/Bandit Game Downloader") # Ensure the directory exists

    if not os.path.exists(app_data_dir):
        os.makedirs(app_data_dir)
    # Paths for local files
    list_file = os.path.join(app_data_dir, 'list.txt')
    saved_paths_file = os.path.join(app_data_dir, 'saved_paths.json')
    executable_paths_file = os.path.join(app_data_dir, 'executable_paths.json')
    redist_paths_file = os.path.join(app_data_dir, 'redist_paths.json') # Define path for redist_paths.json
    print(app_data_dir) # I'm going insane

    # Create saved_paths.json if it doesn't exist
    if not os.path.exists(saved_paths_file):
        with open(saved_paths_file, 'w') as file:
            json.dump({}, file)

    games_folder = os.path.join(app_data_dir, "games") # Create games folder if it doesn't exist
    if not os.path.exists(games_folder):
        os.makedirs(games_folder)
        print(f"Created folder: {games_folder}")
    else:
        print(f"Folder already exists: {games_folder}")

    sync_files() # Sync redist_paths.json and list.txt from the specified URL

    app = QApplication(sys.argv)
    app.setStyle('fusion')
    mainWindow = MainWindow()
    mainWindow.show()
    sys.exit(app.exec())
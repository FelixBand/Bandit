import customtkinter as ctk
import tkinter as tk  # native
import platform
import os
import json
import requests
import subprocess
import tarfile
import threading
import shutil

app = ctk.CTk()

version = "2.0.0"
debug = False

def download_file(url, location=".", timeout = 10):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status() # crash if download failed
    filename = url.split("/")[-1]
    with open(f"{location}/{filename}", "w") as f:
        f.write(response.text)

    return filename

# window properties
app.title(f"Bandit - Game Launcher v{version}")
app.minsize(300, 400)
app.geometry("650x700+50+50") # 50 padding

# App data locations
if platform.system() == "Windows":
    bandit_appdata = f"{os.getenv('APPDATA')}/BanditGameLauncher"
    if not os.path.exists(bandit_appdata):
        os.makedirs(bandit_appdata)
elif platform.system() == "Darwin": # MacOS
    bandit_appdata = f"{os.path.expanduser('~')}/Library/Application Support/BanditGameLauncher"
    if not os.path.exists(bandit_appdata):
        os.makedirs(bandit_appdata)
elif platform.system() == "Linux":
    bandit_appdata = f"{os.path.expanduser('~')}/.config/BanditGameLauncher"
    if not os.path.exists(bandit_appdata):
        os.makedirs(bandit_appdata)

# Game install locations.
# I want system wide installs, so every user on a PC can use the same games.
if platform.system() == "Windows":
    bandit_install_location = os.path.join(os.getenv("PROGRAMDATA"), "BanditGameLauncher")
    if not os.path.exists(bandit_install_location):
        print("Creating system-wide folder...")
        try:
            os.makedirs(os.path.join(bandit_install_location, "Games"))
        except Exception as e:
            print(f"Failed to create system-wide folder: {e}")
            exit(1)
        if not os.path.exists(bandit_install_location):
            print("Failed to create system-wide folder. Please run this program as administrator.")
            exit(1)
else:
    bandit_install_location = "/usr/local/share/BanditGameLauncher"
    # same for osx and linux
    print('check if exists')
    if not os.path.exists(bandit_install_location):
        print('create')
        # visual sudo prompt using pkexec. combine two commands so the user doesn't have to enter their password twice
        subprocess.run(["pkexec", "sh", "-c", f"mkdir {os.path.join(bandit_install_location, 'Games')} && chmod 777 {bandit_install_location}"])
        # if fails, exit
        if not os.path.exists(bandit_install_location):
            print("Failed to create system-wide folder. Please run this program as root or with sudo.")
            exit(1)

if debug:
    OS = "Windows"
else:
    OS = platform.system()

# Download necessary files!    
download_file(f"https://thuis.felixband.nl/bandit/{OS}/list.txt", bandit_appdata)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/executable_paths.json", bandit_appdata)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/prereq_paths.json", bandit_appdata)

# if it doesn't exist, make local file to store installed games in
try:
    open(f"{bandit_appdata}/installed_games.json", "r")
except FileNotFoundError:
    with open(f"{bandit_appdata}/installed_games.json", "w") as f:
        f.write('{"Windows": {}, "Linux": {}, "Darwin": {}}') # empty json object

# installed_games.json format:
# {
#     "Windows/Linux/Darwin": {
#         "game_id": "/path/to/game/parent/directory"
#     }
# }
installedGames = []

def refresh_installed_games():
    global installedGames
    installedGames = [] # Reset the list so we don't append to old data
    with open(f"{bandit_appdata}/installed_games.json", "r") as f:
        installed_games = json.load(f)
        for game_id in installed_games[OS]:
            installedGames.append(game_id)

refresh_installed_games()

gameList = tk.Listbox(
    app,
    font=(None, 14),
    bg="#1b1b1b",       # dark background
    fg="white",         # text color
    selectbackground="#444",  # selected item background
    selectforeground="white",
    highlightthickness=0,     # removes ugly border
    bd=0                     # removes border
)

gameList.pack(fill=tk.BOTH, expand=1, padx=10, pady=10)

rawlist = []
gameNames = []
gameIDs = []
gameSizes = []
gameMPstatus = []

for line in open(f"{bandit_appdata}/list.txt", "r").readlines():
    rawlist.append(line.strip()) # strip removes newline (\n) character, which you always want, duh??
    # here I turn the raw .txt file into an array.
rawlist.sort() # Sort alphabetically

for line in rawlist:
    gameNames.append(line.split("|")[0])
    gameIDs.append(line.split("|")[1])
    # From here on, null safety in case of missing data
    try:
        gameSizes.append(line.split("|")[2])
    except IndexError:
        gameSizes.append("Unknown")
    try:
        gameMPstatus.append(line.split("|")[3])
    except IndexError:
        gameMPstatus.append("Unknown")

def make_game_list():
    for game_name in gameNames:
        if gameIDs[gameNames.index(game_name)] not in installedGames:
            gameList.insert(tk.END, game_name)
            gameList.itemconfig(tk.END, fg="gray50") # gray out uninstalled games
        else:
            gameList.insert(tk.END, game_name)

make_game_list()

currently_downloading = False
currently_downloading_game = None

selected_game = None
def on_game_select(event):
    global selected_game
    selected_game = gameList.curselection()[0] # [0] is for getting the first and only selected item, since curselection() returns multiple indices of something??
    if gameIDs[selected_game] in installedGames:
        ipButton.config(text="Play")
        ipButton.config(state=tk.NORMAL)
        uninstallButton.config(state=tk.NORMAL)
    else:
        ipButton.config(text="Install")
        uninstallButton.config(state=tk.DISABLED)
        if not currently_downloading:
            ipButton.config(state=tk.NORMAL)
        else:
            ipButton.config(state=tk.DISABLED)
    print(f"{selected_game}: name: {gameNames[selected_game]} id: {gameIDs[selected_game]} size: {gameSizes[selected_game]} multiplayer: {gameMPstatus[selected_game]}") # debug info

gameList.bind("<<ListboxSelect>>", on_game_select)

def download_game(game_id):
    global currently_downloading
    currently_downloading = True
    url = f"https://thuis.felixband.nl/bandit/{OS}/{game_id}.tar.gz"
    bandit_install_location

    try:
        with requests.get(url, stream=True, timeout=10) as response:
            response.raise_for_status()

            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0

            class ProgressFile:
                def __init__(self, raw):
                    self.raw = raw

                def read(self, size=-1):
                    nonlocal downloaded
                    data = self.raw.read(size)
                    if data:
                        downloaded += len(data)
                        if total_size:
                            percent = (downloaded / total_size) * 100
                            print(f"\rDownloading {game_id}: {percent:.2f}%", end="")
                            progress.set(percent)
                        else:
                            print(f"\rDownloading {game_id}: {downloaded} bytes", end="")
                    return data

                def readable(self):
                    return True

            wrapped = ProgressFile(response.raw)

            with tarfile.open(fileobj=wrapped, mode="r|gz") as tar:
                tar.extractall(path=os.path.join(bandit_install_location, "Games"))

        print(f"\n{game_id} installed successfully.")
        progress.set(0)
        return True

    except Exception as e:
        print(f"\nFailed to install {game_id}: {e}")
        progress.set(0)
        return False
        


def install_or_play():
    if gameIDs[selected_game] in installedGames:
        # play the game
        print(f'Launching {selected_game}!')
        # installation path from installed_games.json + executable path from executable_paths.json
        with open(f"{bandit_appdata}/installed_games.json", "r") as f:
            installed_games = json.load(f)
            game_path = installed_games[OS][gameIDs[selected_game]]
        with open(f"{bandit_appdata}/executable_paths.json", "r") as f:
            executable_paths = json.load(f)
            game_path = f"{game_path}/{executable_paths[gameIDs[selected_game]]}"

            try:
                # RUN GAME with subprocess. Important to set the working directory to the game's directory. We need to do this by concatenating the first directory of the executable path to the install path.
                subprocess.Popen(game_path, cwd=os.path.dirname(game_path))
            except Exception as e:
                tk.messagebox.showerror("Error", f"Failed to launch the game. Error: {e}")
    else:
        # install the game
        currently_downloading_game = selected_game
        print(f"Installing {selected_game}")
        ipButton.config(state=tk.DISABLED)

        def task():
            success = download_game(gameIDs[selected_game])

            def after():
                ipButton.config(state=tk.NORMAL)

                if success:
                    # update installed_games.json
                    with open(f"{bandit_appdata}/installed_games.json", "r") as f:
                        installed_games = json.load(f)

                    installed_games[OS][gameIDs[currently_downloading_game]] = os.path.join(bandit_install_location, "Games")

                    with open(f"{bandit_appdata}/installed_games.json", "w") as f:
                        json.dump(installed_games, f, indent=4)

                    # refresh UI
                    gameList.delete(0, tk.END)
                    refresh_installed_games()
                    make_game_list()
                    currently_downloading = False
                else:
                    tk.messagebox.showerror("Error", "Failed to install the game.")
                    currently_downloading = False

            # safely update UI from main thread
            app.after(0, after)

        threading.Thread(target=task, daemon=True).start()

def get_first_folder_in_executable_path(game_id):
    with open(f"{bandit_appdata}/executable_paths.json", "r") as f:
        executable_paths = json.load(f)
        exec_path = executable_paths[game_id]
        first_folder = exec_path.split("/")[0] # get the first folder in the path
        return first_folder


def uninstall_game():
    print('gonna nuke')
    with open(f"{bandit_appdata}/installed_games.json", "r") as f:
        installed_games = json.load(f)
    game_id = gameIDs[selected_game]
    full_game_path = os.path.join(installed_games[OS][game_id], get_first_folder_in_executable_path(game_id))
    # Ask for confirmation
    if not tk.messagebox.askyesno("Confirm Uninstall", f"Are you sure you want to uninstall {selected_game}? This will delete: {full_game_path}"):
        return
    try:
        shutil.rmtree(full_game_path) # remove the game's folder and all its contents
        del installed_games[OS][game_id] # remove from installed_games.json
        with open(f"{bandit_appdata}/installed_games.json", "w") as f:
            json.dump(installed_games, f, indent=4)
        # refresh UI
        gameList.delete(0, tk.END)
        refresh_installed_games()
        make_game_list()
        print(f'nuke successful. Deleted {full_game_path}')
    except Exception as e:
        tk.messagebox.showerror("Error", f"Failed to uninstall the game. Error: {e}")

# Download/play button
ipButton = tk.Button(
    app,
    text="Install/Play",
    font=(None, 14),
    command=install_or_play
)
ipButton.pack(fill="x",pady=10, padx=20)
ipButton.config(state=tk.DISABLED)

uninstallButton = tk.Button(
    app,
    text="Uninstall",
    font=(None, 14),
    command=uninstall_game
)
uninstallButton.pack(fill="x",pady=10, padx=20)
uninstallButton.config(state=tk.DISABLED)

# Progress bar. span the progress bar across the whole window with some padding
progress = tk.DoubleVar()
progressBar = tk.ttk.Progressbar(app, variable=progress, maximum=100)
progressBar.pack(fill="x", expand=False, padx=20, pady=10)


app.mainloop() # Up and away!
import customtkinter as ctk
import tkinter as tk  # native
import platform
import os
import json
import requests
import subprocess

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
app.geometry("600x800+50+50") # 50 padding

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
    if not os.path.exists("C:/ProgramData/BanditGameLauncher"):
        # UAC prompt, create folder and grant permissions
        subprocess.run(["powershell", "-Command", "Start-Process", "cmd", "-Verb", "RunAs", "-ArgumentList", "'/c', 'mkdir C:/ProgramData/BanditGameLauncher && icacls C:/ProgramData/BanditGameLauncher /grant *S-1-1-0:(OI)(CI)F'"])
        if not os.path.exists("C:/ProgramData/BanditGameLauncher"):
            print("Failed to create system-wide folder. Please run this program as administrator.")
            exit(1)
else:
    # same for osx and linux
    print('check if exists')
    if not os.path.exists("/usr/local/share/BanditGameLauncher"):
        print('create')
        # visual sudo prompt using pkexec. combine two commands so the user doesn't have to enter their password twice
        subprocess.run(["pkexec", "sh", "-c", "mkdir /usr/local/share/BanditGameLauncher && chmod 777 /usr/local/share/BanditGameLauncher"])
        # if fails, exit
        if not os.path.exists("/usr/local/share/BanditGameLauncher"):
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
    with open(f"{bandit_appdata}/installed_games.json", "r") as f:
        installed_games = json.load(f)
        for game_id in installed_games[OS]:
            installedGames.append(game_id)

refresh_installed_games()

gameList = tk.Listbox(app, font=(None, 14)) # Don't care about font, so "None" and 14 font size
gameList.pack(fill=tk.BOTH, expand=1, padx=10, pady=10) # expand means fill the whole window instead of just using the space it needs

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

for game_name in gameNames:
    gameList.insert(tk.END, game_name)

# Download/play button
ipButton = tk.Button(app, text="Install/Play", font=(None, 14))
ipButton.pack(pady=10)
ipButton.config(state=tk.DISABLED)

selected_game = None
def on_game_select(event):
    global selected_game
    selected_game = gameList.curselection()[0] # [0] is for getting the first and only selected item, since curselection() returns multiple indices of something??
    ipButton.config(state=tk.NORMAL)
    if gameIDs[selected_game] in installedGames:
        ipButton.config(text="Play")
    else:
        ipButton.config(text="Install")
    print(f"{selected_game}: name: {gameNames[selected_game]} id: {gameIDs[selected_game]} size: {gameSizes[selected_game]} multiplayer: {gameMPstatus[selected_game]}") # debug info

gameList.bind("<<ListboxSelect>>", on_game_select)

def install_or_play():
    if gameIDs[selected_game] in installedGames:
        # play the game
        print(f'Launching {selected_game}!')
    else:
        # install the game
        print(f"Installing {selected_game}")

ipButton.bind("<Button-1>", lambda event: install_or_play()) # <Button-1> = lmb, <Button-2> = mmb, <Button-3> = rmb

app.mainloop() # Up and away!
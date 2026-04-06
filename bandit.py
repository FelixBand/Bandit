import tkinter as tk
import platform
import os
import json
import requests
import subprocess

app = tk.Tk()

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
    bandit_path = f"{os.getenv("APPDATA")}/BanditGameLauncher"
    if not os.path.exists(bandit_path):
        os.makedirs(bandit_path)
elif platform.system() == "Darwin": # MacOS
    bandit_path = f"{os.path.expanduser("~")}/Library/Application Support/BanditGameLauncher"
    if not os.path.exists(bandit_path):
        os.makedirs(bandit_path)
elif platform.system() == "Linux":
    bandit_path = f"{os.path.expanduser("~")}/.config/BanditGameLauncher"
    if not os.path.exists(bandit_path):
        os.makedirs(bandit_path)

if debug:
    OS = "Windows"
else:
    OS = platform.system()

# Download necessary files!    
download_file(f"https://thuis.felixband.nl/bandit/{OS}/list.txt", bandit_path)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/executable_paths.json", bandit_path)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/prereq_paths.json", bandit_path)

# if it doesn't exist, make local file to store installed games in
try:
    open(f"{bandit_path}/installed_games.json", "r")
except FileNotFoundError:
    with open(f"{bandit_path}/installed_games.json", "w") as f:
        f.write("{}") # empty json object

gameList = tk.Listbox(app, font=(None, 14)) # Don't care about font, so "None" and 14 font size
gameList.pack(fill=tk.BOTH, expand=1, padx=10, pady=10) # expand means fill the whole window instead of just using the space it needs

rawlist = []
gameNames = []
gameIDs = []
gameSizes = []
gameMPstatus = []

for line in open(f"{bandit_path}/list.txt", "r").readlines():
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

def install_or_play():
    print("Clicked!")

ipButton.bind("<Button-1>", lambda event: install_or_play()) # <Button-1> = lmb, <Button-2> = mmb, <Button-3> = rmb

def on_game_select(event):
    selected_index = gameList.curselection()[0] # [0] is for getting the first and only selected item, since curselection() returns multiple indices of something??
    ipButton.config(state=tk.NORMAL)
    print(f"{selected_index}: name: {gameNames[selected_index]} id: {gameIDs[selected_index]} size: {gameSizes[selected_index]} multiplayer: {gameMPstatus[selected_index]}") # debug info

gameList.bind("<<ListboxSelect>>", on_game_select)


app.mainloop() # Up and away!
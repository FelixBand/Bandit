import tkinter as tk
import platform
import requests

root = tk.Tk()

version = "2.0.0"

def download_file(url): # Add timeout timer
    local_filename = url.split('/')[-1]
    # NOTE the stream=True parameter below
    with requests.get(url, stream=True, timeout=10) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                #if chunk: 
                f.write(chunk)
    return local_filename

# window properties
root.title(f"Bandit - Game Launcher v{version}")
root.minsize(200, 200)
root.geometry("600x800+50+50")

download_file(f"https://thuis.felixband.nl/bandit/{platform.system()}/list.txt")

gameList = tk.Listbox(root)
# Resize the listbox to fit the window, but leave some padding for aesthetics and room at the bottom for buttons
gameList.pack(fill=tk.BOTH, expand=1, padx=10, pady=10)

for line in open("list.txt", "r").readlines():
    # Every line in list.txt has the format: "Game Name|ID|Size|MultiplayerStatus"
    game_name = line.split('|')[0] # 0 is the first one, aka the game name
    gameList.insert(tk.END, game_name)

gameList.pack() # pack means put it in the fuckin window. Do it. Pack it up


root.mainloop() # Up and away!
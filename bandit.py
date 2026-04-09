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
import time
import base64

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
app.minsize(450, 600)
app.geometry("650x700+50+50") # 50 padding
ctk.set_appearance_mode("dark")

if debug:
    OS = "Windows"
else:
    OS = platform.system()

# App data locations
if platform.system() == "Windows":
    bandit_userdata = f"{os.getenv('APPDATA')}/BanditGameLauncher"
    if not os.path.exists(bandit_userdata):
        os.makedirs(bandit_userdata)
elif platform.system() == "Darwin": # MacOS
    bandit_userdata = f"{os.path.expanduser('~')}/Library/Application Support/BanditGameLauncher"
    if not os.path.exists(bandit_userdata):
        os.makedirs(bandit_userdata)
elif platform.system() == "Linux":
    bandit_userdata = f"{os.path.expanduser('~')}/.config/BanditGameLauncher"
    if not os.path.exists(bandit_userdata):
        os.makedirs(bandit_userdata)

# System wide data + game install location.
if platform.system() == "Windows":
    bandit_program_data = os.path.join(os.getenv("PROGRAMDATA"), "BanditGameLauncher")
    if not os.path.exists(bandit_program_data):
        print("Creating system-wide folder...")
        try:
            os.makedirs(os.path.join(bandit_program_data, "Games"))
        except Exception as e:
            print(f"Failed to create system-wide folder: {e}")
            exit(1)
        if not os.path.exists(bandit_program_data):
            print("Failed to create system-wide folder. Please run this program as administrator.")
            exit(1)
elif platform.system() == "Linux":
    bandit_program_data = "/etc/BanditGameLauncher"
    # same for osx and linux
    print('check if exists')
    if not os.path.exists(bandit_program_data):
        print('create')
        # visual sudo prompt using pkexec. combine two commands so the user doesn't have to enter their password twice
        subprocess.run(["pkexec", "sh", "-c", f"mkdir {bandit_program_data} && mkdir {os.path.join(bandit_program_data, 'Games')} && chmod 777 {bandit_program_data} && chmod 777 {os.path.join(bandit_program_data, 'Games')}"])
        # if fails, exit
        if not os.path.exists(bandit_program_data):
            print("Failed to create system-wide folder. Please run this program as root or with sudo.")
            exit(1)
elif platform.system() == "Darwin":
    bandit_program_data = "/Library/Application Support/BanditGameLauncher"

    if not os.path.exists(bandit_program_data):
        print("Creating system-wide folder...")

        try:
            subprocess.run([
                "osascript",
                "-e",
                f'do shell script "mkdir -p \\"{bandit_program_data}\\" && chmod 777 \\"{bandit_program_data}\\"" with administrator privileges'
            ])
        except Exception as e:
            print(f"Failed to create system-wide folder: {e}")
            exit(1)

        if not os.path.exists(bandit_program_data):
            print("Failed to create system-wide folder. Please run this program as administrator.")
            exit(1)

if OS == "Darwin":
    bandit_games_folder = "/Applications" # on macOS, we dump the games in the Applcations folder. Way nicer.
else:
    bandit_games_folder = os.path.join(bandit_program_data, "Games")

# Download necessary files!    
download_file(f"https://thuis.felixband.nl/bandit/{OS}/list.txt", bandit_userdata)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/executable_paths.json", bandit_userdata)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/prereq_paths.json", bandit_userdata)

# if it doesn't exist, make local file to store installed games in
try:
    open(f"{bandit_program_data}/installed_games.json", "r")
except FileNotFoundError:
    with open(f"{bandit_program_data}/installed_games.json", "w") as f:
        f.write('{"Windows": {}, "Linux": {}, "Darwin": {}}')

try:
    open(f"{bandit_userdata}/installed_prereqs.json", "r")
except FileNotFoundError:
    with open(f"{bandit_userdata}/installed_prereqs.json", "w") as f:
        f.write('{}') # empty json object

# SETTINGS!!!!!!!!!!!!!1
try:
    open(f"{bandit_userdata}/settings.json", "r")
except FileNotFoundError:
    with open(f"{bandit_userdata}/settings.json", "w") as f:
        f.write('{"ask_install_path": false}')

# load and apply settings
with open(f"{bandit_userdata}/settings.json", "r") as f:
    settings = json.load(f)
    ask_install_path = settings.get("ask_install_path", False)

print(settings)

installedGames = []

installedPrereqs = set()

def refresh_installed_games():
    global installedGames
    installedGames = [] # Reset the list so we don't append to old data
    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
        installed_games = json.load(f)
        for game_id in installed_games[OS]:
            installedGames.append(game_id)

def refresh_installed_prereqs():
    global installedPrereqs
    installedPrereqs = set()
    with open(f"{bandit_userdata}/installed_prereqs.json", "r") as f:
        prereqs = json.load(f)
        for game_id in prereqs:
            installedPrereqs.add(game_id)

refresh_installed_games()
refresh_installed_prereqs()

def settings_clicked():
    # Open new window
    settings_window = ctk.CTkToplevel(app)
    settings_window.title("Bandit Settings")

settingsButton = ctk.CTkButton(app, text="⚙️", command=settings_clicked)
settingsButton.pack(pady=0, padx=0, anchor="ne")

if OS == "Darwin":
    fontSize = 18
else:
    fontSize = 14

if OS == "Windows":
    listfont = "Segoe UI"
else:
    listfont = None

# Game list: replace native Listbox with a CustomTkinter scrollable frame
# Each game will be a selectable `CTkButton` inside the scrollable frame.
game_list_frame = ctk.CTkScrollableFrame(app, corner_radius=6)
game_list_frame.pack(fill="both", expand=True, padx=10, pady=10)

# Store per-item widgets so we can update their appearance later
game_item_buttons = []

# Track selection index
selected_game = None
prev_selected = None

rawlist = []
gameNames = []
gameIDs = []
gameSizes = []
gameMPstatus = []

for line in open(f"{bandit_userdata}/list.txt", "r").readlines():
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
        gameMPstatus.append(line.split("|")[3].strip()) # STRIP to remove newline char otherwise chaos
    except IndexError:
        gameMPstatus.append("Unknown")
    

def make_game_list():
    # clear any existing items
    for btn in game_item_buttons:
        btn.destroy()
    game_item_buttons.clear()

    for index, game_name in enumerate(gameNames):
        try:
            if gameMPstatus[index] == "1":
                mpIcon = "🟠"
            elif gameMPstatus[index] == "2":
                mpIcon = "🟢"
            elif gameMPstatus[index] == "3":
                mpIcon = "🟩"
            else:
                mpIcon = "🔴"
        except IndexError:
            mpIcon = "🔴"

        btn = ctk.CTkButton(
            game_list_frame,
            text=mpIcon + game_name,
            anchor="w",
            fg_color="transparent",
            hover_color="#355486",
            command=lambda i=index: select_game(i),
            font=(listfont, fontSize)
        )
        btn.pack(fill="x", pady=2, padx=4)
        game_item_buttons.append(btn)

        # set initial text color based on installed state
        try:
            game_id = gameIDs[index]
            if game_id in installedGames:
                btn.configure(text_color="white")
            else:
                btn.configure(text_color="gray50")
        except Exception:
            pass

    # do one pass to ensure selection visuals are correct
    if selected_game is not None and 0 <= selected_game < len(game_item_buttons):
        game_item_buttons[selected_game].configure(fg_color="#444444")


def update_game_list_colors():
    for index, game_id in enumerate(gameIDs):
        try:
            btn = game_item_buttons[index]
        except IndexError:
            continue

        if game_id in installedGames:
            btn.configure(text_color="white")
        else:
            btn.configure(text_color="gray50")
        # visually mark selected
        if selected_game == index:
            btn.configure(fg_color="#444444")
        else:
            btn.configure(fg_color="transparent")

make_game_list()

currently_downloading = False
currently_downloading_game = None

selected_game = None

def select_game(index):
    global selected_game
    global selected_game, prev_selected
    selected_game = index

    # only update previous and current selection visuals to avoid looping all items
    try:
        if prev_selected is not None and 0 <= prev_selected < len(game_item_buttons):
            game_item_buttons[prev_selected].configure(fg_color="transparent")
    except Exception:
        pass

    try:
        if 0 <= selected_game < len(game_item_buttons):
            game_item_buttons[selected_game].configure(fg_color="#444444")
    except Exception:
        pass

    prev_selected = selected_game

    # update buttons depending on install/download state
    try:
        if gameIDs[selected_game] in installedGames:
            ipButton.configure(text="Play")
            ipButton.configure(state="normal")
            uninstallButton.configure(state="normal")
        else:
            ipButton.configure(text="Install")
            uninstallButton.configure(state="disabled")
            if not currently_downloading:
                ipButton.configure(state="normal")
            else:
                ipButton.configure(state="disabled")
        if currently_downloading and selected_game == currently_downloading_game:
            ipButton.configure(text="Cancel Download")
            ipButton.configure(state="normal")
    except Exception:
        pass

    print(f"{selected_game}: name: {gameNames[selected_game]} id: {gameIDs[selected_game]} size: {gameSizes[selected_game]} multiplayer: {gameMPstatus[selected_game]}")

    formatted_size = gameSizes[selected_game]
    if formatted_size != "Unknown":
        try:
            size_bytes = int(formatted_size)
            if size_bytes >= 1_000_000_000:
                formatted_size = f"{size_bytes / 1_000_000_000:.2f} GB"
            elif size_bytes >= 1_000_000:
                formatted_size = f"{size_bytes / 1_000_000:.2f} MB"
            elif size_bytes >= 1_000:
                formatted_size = f"{size_bytes / 1_000:.2f} KB"
            else:
                formatted_size = f"{size_bytes} bytes"
        except ValueError:
            pass

    formatted_mp_status = "🔴 This game is singleplayer and/or has local multiplayer only."
    if gameMPstatus[selected_game] == "1":
        formatted_mp_status = "🟠 This supports LAN multiplayer."
    elif gameMPstatus[selected_game] == "2":
        formatted_mp_status = "🟢 This supports online multiplayer with other Bandit users."
    elif gameMPstatus[selected_game] == "3":
        formatted_mp_status = "🟩 This game supports online multiplayer with anyone."

    gameInfoLabel.configure(text=f"{gameNames[selected_game]} — {formatted_size}\n{formatted_mp_status}")

def download_tar(game_id, destination = bandit_games_folder):
    global currently_downloading
    currently_downloading = True

    url = f"https://thuis.felixband.nl/bandit/{OS}/{game_id}.tar.gz"

    try:
        with requests.get(url, stream=True, timeout=10) as response:
            response.raise_for_status()

            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            start_time = time.time()

            class ProgressFile:
                def __init__(self, raw):
                    self.raw = raw

                def read(self, size=-1):
                    nonlocal downloaded
                    global currently_downloading

                    if not currently_downloading:
                        raise Exception("Download cancelled")

                    data = self.raw.read(size)

                    if not currently_downloading:
                        raise Exception("Download cancelled")

                    if data:
                        downloaded += len(data)

                        elapsed = time.time() - start_time
                        speed = downloaded / max(elapsed, 0.001) # bytes/sec

                        if total_size:
                            percent = (downloaded / total_size) * 100
                            remaining = total_size - downloaded
                            eta = remaining / speed if speed > 0 else 0

                            # Format speed
                            speed_kb = speed / 1024
                            speed_mb = speed_kb / 1024

                            # Update the speed and ETA display every second, to avoid jittery UI updates
                            if speed_mb >= 1:
                                speed_str = f"{speed_mb:.2f} MB/s"
                            else:
                                speed_str = f"{speed_kb:.2f} KB/s"

                            # Format ETA
                            if eta > 3600:
                                eta_str = time.strftime("%H hour(s) and %M minutes remaining", time.gmtime(eta))
                            elif eta > 60:
                                eta_str = time.strftime(str(int(eta / 60)) + " minute(s) remaining", time.gmtime(eta))
                            else:
                                eta_str = time.strftime("Less than a minute remaining", time.gmtime(eta))

                            print(
                                f"\rDownloading {game_id}: {percent:.2f}% | {speed_str} | ETA: {eta_str}",
                                end=""
                            )

                            # safe UI update
                            def update_ui():
                                progressBar.set(percent/100)
                                infoLabel.configure(
                                    text=f"Downloading {gameNames[currently_downloading_game]}: {percent:.2f}%\n{speed_str} • ETA {eta_str}"
                                )

                            app.after(0, update_ui)

                        else:
                            print(f"\rDownloading {game_id}: {downloaded} bytes", end="")

                    return data

                def readable(self):
                    return True

            wrapped = ProgressFile(response.raw)

            with tarfile.open(fileobj=wrapped, mode="r|gz") as tar:
                tar.extractall(path=destination)

        print(f"\n{game_id} installed successfully.")

        # Reset UI after success
        def finish_ui():
            progressBar.set(0)
            infoLabel.configure(text="Download complete!")
        
        app.after(0, finish_ui)

        return True

    except Exception as e:
        if str(e) == "Download cancelled":
            print("\nDownload cancelled.")

            def cancel_ui():
                progressBar.set(0)
                infoLabel.configure(text="Download cancelled.")

            app.after(0, cancel_ui)

            return False
        else:
            print(f"\nFailed to install {game_id}: {e}")

            def fail_ui():
                progressBar.set(0)
                infoLabel.configure(text="Download failed.")

            app.after(0, fail_ui)

            return False

    finally:
        currently_downloading = False        


def install_or_play():
    # if currently downloading & selected curr downloading game, cancel
    global currently_downloading, currently_downloading_game
    if currently_downloading and selected_game == currently_downloading_game:
        currently_downloading = False
        print("Cancelling download...")
        if selected_game is not None:
            select_game(selected_game)
    
    # if selected game is installed, play!
    elif gameIDs[selected_game] in installedGames:
        print(f'Launching {selected_game}!')
        # installation path from installed_games.json + executable path from executable_paths.json
        with open(f"{bandit_program_data}/installed_games.json", "r") as f:
            installed_games = json.load(f)
            game_path = installed_games[OS][gameIDs[selected_game]]
        with open(f"{bandit_userdata}/executable_paths.json", "r") as f:
            executable_paths = json.load(f)
            game_path = f"{game_path}/{executable_paths[gameIDs[selected_game]]}"

            # Install prerequisites
            with open(f"{bandit_userdata}/prereq_paths.json", "r") as f:
                prereq_paths = json.load(f)
                if gameIDs[selected_game] in prereq_paths and gameIDs[selected_game] not in installedPrereqs:
                    install_commands = []
                    for prereq in prereq_paths[gameIDs[selected_game]]:
                        # Normalize the path
                        full_path = os.path.normpath(f"{installed_games[OS][gameIDs[selected_game]]}/{get_first_folder_in_executable_path(gameIDs[selected_game])}/{prereq['path']}")
                        
                        # Run the prerequisite directly in PowerShell
                        if prereq["command"]:
                            cmd = f'& "{full_path}" {prereq["command"]}'
                        else:
                            cmd = f'& "{full_path}"'
                        install_commands.append(cmd)
                    
                    # Join commands with semicolons to make a single script
                    inner_script = "; ".join(install_commands)

                    if OS == "Windows" and install_commands:
                        try:
                            print("Requesting single UAC elevation...")
                            
                            # 1. PowerShell requires UTF-16LE encoding for its -EncodedCommand parameter
                            encoded_bytes = inner_script.encode('utf-16le')
                            encoded_script = base64.b64encode(encoded_bytes).decode('utf-8')
                            
                            # 2. PowerShell requires UTF-16LE encoding for its -EncodedCommand parameter
                            # 2. Pass the Base64 string to the elevated PowerShell. 
                            # No quote conflicts exist because the payload is just a block of letters and numbers!
                            ps_shell_command = f"Start-Process powershell -ArgumentList '-NoProfile -EncodedCommand {encoded_script}' -Verb RunAs -Wait"
                            
                            # 3. Execute and capture output
                            result = subprocess.run(["powershell", "-Command", ps_shell_command], capture_output=True, text=True, check=True)
                            
                            # Mark prereqs as installed
                            with open(f"{bandit_userdata}/installed_prereqs.json", "r") as f:
                                prereqs = json.load(f)
                            prereqs[gameIDs[selected_game]] = True
                            with open(f"{bandit_userdata}/installed_prereqs.json", "w") as f:
                                json.dump(prereqs, f, indent=4)
                            refresh_installed_prereqs()
                            
                            tk.messagebox.showinfo("Success", "All prerequisites installed.")
                            
                        except subprocess.CalledProcessError as e:
                            error_msg = f"Prerequisite installation failed.\nExit code: {e.returncode}\nStdout: {e.stdout}\nStderr: {e.stderr}"
                            print(error_msg)
                            tk.messagebox.showerror("Prerequisite Installation Failed", error_msg)
                            return False
                        except Exception as e:
                            error_msg = f"An error occurred: {e}"
                            print(error_msg)
                            tk.messagebox.showerror("Error", error_msg)
                            return False
                        

            try:
                # RUN GAME
                if OS == "Darwin":
                    subprocess.Popen(["open", game_path], cwd=os.path.dirname(game_path))
                else:
                    subprocess.Popen(game_path, cwd=os.path.dirname(game_path))
            except Exception as e:
                tk.messagebox.showerror("Error", f"Failed to launch the game. Error: {e}")
    else:
        # install the game
        currently_downloading_game = selected_game
        print(f"Installing {selected_game}")
        ipButton.configure(state="disabled")

        def task():
            if ask_install_path:
                game_destination = tk.filedialog.askdirectory()
            else:
                game_destination = bandit_games_folder
            success = download_tar(gameIDs[selected_game], game_destination)

            def after():
                ipButton.configure(state="normal")

                if success:
                    # update installed_games.json
                    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
                        installed_games = json.load(f)

                    installed_games[OS][gameIDs[currently_downloading_game]] = game_destination

                    with open(f"{bandit_program_data}/installed_games.json", "w") as f:
                        json.dump(installed_games, f, indent=4)

                    # refresh UI
                    refresh_installed_games()
                    update_game_list_colors()
                    if selected_game is not None:
                        select_game(selected_game)
                    currently_downloading = False
                else:
                    print("Failed to install the game for some reason")
                    currently_downloading = False

            # safely update UI from main thread
            app.after(0, after)

        threading.Thread(target=task, daemon=True).start()
        if selected_game is not None:
            select_game(selected_game)

def get_first_folder_in_executable_path(game_id):
    with open(f"{bandit_userdata}/executable_paths.json", "r") as f:
        executable_paths = json.load(f)
        exec_path = executable_paths[game_id]
        first_folder = exec_path.split("/")[0] # get the first folder in the path
        return first_folder


def uninstall_game():
    print('gonna nuke')
    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
        installed_games = json.load(f)
    game_id = gameIDs[selected_game]
    full_game_path = os.path.join(installed_games[OS][game_id], get_first_folder_in_executable_path(game_id))
    # Ask for confirmation
    if not tk.messagebox.askyesno("Confirm Uninstall", f"Are you sure you want to uninstall {gameNames[selected_game]}? This will delete: {full_game_path}"):
        return
    try:
        shutil.rmtree(full_game_path)
        print(f'nuke successful. Deleted {full_game_path}')
    except Exception as e:
        tk.messagebox.showerror(
            "Error",
            f"Failed to uninstall the game. Error: {e}. Removing installation entry anyway."
        )

    # Always run this part
    installed_games.get(OS, {}).pop(game_id, None)

    with open(f"{bandit_program_data}/installed_games.json", "w") as f:
        json.dump(installed_games, f, indent=4)

    # Handle prereqs
    with open(f"{bandit_userdata}/installed_prereqs.json", "r") as f:
        prereqs = json.load(f)

    if game_id in prereqs:
        del prereqs[game_id]
        with open(f"{bandit_userdata}/installed_prereqs.json", "w") as f:
            json.dump(prereqs, f, indent=4)
        refresh_installed_prereqs()

    # refresh UI
    refresh_installed_games()
    update_game_list_colors()
    infoLabel.configure(text="Game uninstalled successfully.")

    if selected_game is not None:
        select_game(selected_game)

gameInfoLabel = ctk.CTkLabel(app,
    text="Welcome to Bandit!\nSelect a game to get started.",
    anchor="w", justify="left",
    font=(None, 14)
)
gameInfoLabel.pack(fill="x", padx=20, pady=(0,10))

# Download/play button
ipButton = ctk.CTkButton(app,
    text="Install/Play",
    command=install_or_play,
    font=(None, 14)
)
ipButton.pack(fill="x", pady=10, padx=20)
ipButton.configure(state="disabled")

uninstallButton = ctk.CTkButton(app,
    text="Uninstall",
    command=uninstall_game,
    font=(None, 14)
)
uninstallButton.pack(fill="x", pady=10, padx=20)
uninstallButton.configure(state="disabled")

# Info label for download speed, percentage and ETA.
infoLabel = ctk.CTkLabel(app,
    text="",
    font=("Courier", 12),
    anchor="w",
)
infoLabel.pack(pady=10, padx=20)

progressBar = ctk.CTkProgressBar(app)
progressBar.set(0)
progressBar.pack(fill="x", expand=False, padx=20, pady=10)


app.mainloop() # Up and away!
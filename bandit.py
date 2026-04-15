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
import tempfile
import time
import base64
from PIL import Image, ImageTk
import sys
import webbrowser

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

def resource_path(relative_path):
    """ Get absolute path to resource (works for dev and PyInstaller) """
    try:
        base_path = sys._MEIPASS  # PyInstaller temp dir
    except AttributeError:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

if os.path.exists("icon.png"):
    app.iconphoto(True, ImageTk.PhotoImage(Image.open(resource_path("icon.png"))))

if OS == "Windows":
    app.iconbitmap(resource_path("icon.ico"))

# MP icon cache for asset images
mp_icon_images = {}

# some globals for later
rawlist = []
gameNames = []
gameIDs = []
gameSizes = []
gameMPstatus = []

installedGames = []

linux_game_ids = set()
windows_game_ids = set()

installedPrereqs = set()

# Store per-item widgets so we can update their appearance later
game_item_buttons = []
installed_game_item_buttons = []
installed_game_original_indices = []

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
        subprocess.run(["pkexec", "sh", "-c", f"mkdir {bandit_program_data} && mkdir {os.path.join(bandit_program_data, 'Games')} && mkdir {os.path.join(bandit_program_data, 'Windows')} && chmod 777 {bandit_program_data} && chmod 777 {os.path.join(bandit_program_data, 'Games')} && chmod 777 {os.path.join(bandit_program_data, 'Windows')}"])
        # if fails, exit
        if not os.path.exists(bandit_program_data):
            print("Failed to create system-wide folder. Please run this program as root or with sudo.")
            exit(1)

    pfxhome = f"{os.path.expanduser('~')}/.banditpfx/drive_c/users/steamuser"
    if not os.path.exists(f"{os.path.expanduser('~')}/.banditpfx"):
        subprocess.run(["sh", "-c", f"mkdir -p {os.path.expanduser('~')}/.banditpfx/drive_c/users/steamuser/AppData && ln -s {pfxhome}/AppData {os.path.expanduser('~')} &&ln -s {os.path.expanduser('~')}/Downloads {pfxhome} && ln -s {os.path.expanduser('~')}/Documents {pfxhome} && ln -s {os.path.expanduser('~')}/Desktop {pfxhome} && ln -s {os.path.expanduser('~')}/Music {pfxhome} && ln -s {os.path.expanduser('~')}/Pictures {pfxhome} && ln -s {os.path.expanduser('~')}/Videos {pfxhome}"])
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
download_file(f"https://thuis.felixband.nl/bandit/{OS}/list.txt", bandit_program_data)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/executable_paths.json", bandit_program_data)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/prereq_paths.json", bandit_program_data)
download_file(f"https://thuis.felixband.nl/bandit/{OS}/icon_paths.json", bandit_program_data)

if OS == "Linux":
    download_file(f"https://thuis.felixband.nl/bandit/Windows/list.txt", os.path.join(bandit_program_data, 'Windows'))
    download_file(f"https://thuis.felixband.nl/bandit/Windows/executable_paths.json", os.path.join(bandit_program_data, 'Windows'))
    download_file(f"https://thuis.felixband.nl/bandit/Windows/prereq_paths.json", os.path.join(bandit_program_data, 'Windows'))
    download_file(f"https://thuis.felixband.nl/bandit/Windows/icon_paths.json", os.path.join(bandit_program_data, 'Windows'))

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
        f.write('{"Ask where to install games to": false, "Enable Telemetry": true, "_first_launch": true}')

# load and apply settings
def apply_settings():
    global ask_install_path
    with open(f"{bandit_userdata}/settings.json", "r") as f:
        settings = json.load(f)
        ask_install_path = settings.get("Ask where to install games to", False)
        print(settings)

apply_settings()

def send_telemetry(event_type, game_id=None, game_name=None):
    """Send telemetry event to the telemetry server (non-blocking)"""
    def task():
        try:
            with open(f"{bandit_userdata}/settings.json", "r") as f:
                settings = json.load(f)
            
            if not settings.get("Enable Telemetry", True):
                return
            
            telemetry_data = {
                "event_type": event_type,
                "username": os.getenv("USER", os.getenv("USERNAME", "unknown")),
                "app_version": version,
            }
            if game_id:
                telemetry_data["game_id"] = game_id
            if game_name:
                telemetry_data["game_name"] = game_name

            endpoints = [
                "https://thuis.felixband.nl/api/telemetry",
                "http://thuis.felixband.nl:5001/api/telemetry"
            ]

            for url in endpoints:
                try:
                    response = requests.post(url, json=telemetry_data, timeout=5)
                    print(f"[TELEMETRY] Tried {url} - Status: {response.status_code}")
                    if response.status_code == 200:
                        return
                except Exception as e:
                    print(f"[TELEMETRY] Endpoint failed: {url} -> {type(e).__name__}: {e}")
                    continue

            print(f"[TELEMETRY ERROR] All telemetry endpoints failed for {event_type}")
        except Exception as e:
            print(f"[TELEMETRY ERROR] Failed to send {event_type}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    threading.Thread(target=task, daemon=True).start()

def show_telemetry_disclaimer():
    """Show telemetry disclaimer on first launch"""
    with open(f"{bandit_userdata}/settings.json", "r") as f:
        settings = json.load(f)
    
    if settings.get("_first_launch", False):
        result = tk.messagebox.showinfo(
            "Telemetry Notice",
            "Bandit collects anonymized telemetry data including:\n"
            "• Your PC username\n"
            "• Your IP address\n"
            "• Which games you download\n\n"
            "This helps me understand usage patterns.\n\n"
            "You can disable this anytime in Settings ⚙️"
        )
        
        # Mark first launch as complete
        settings["_first_launch"] = False
        with open(f"{bandit_userdata}/settings.json", "w") as f:
            json.dump(settings, f, indent=4)

def get_mp_icon(status):
    status = str(status) if status is not None else "0"
    if status not in {"1", "2", "3"}:
        status = "0"

    if status in mp_icon_images:
        return mp_icon_images[status]

    icon_size = globals().get("fontSize", 14) + 20

    for ext in ("svg", "png"):
        icon_file = resource_path(f"assets/mp{status}.{ext}")
        if os.path.exists(icon_file):
            try:
                img = Image.open(icon_file)
                img = img.convert("RGBA")
                img = img.resize((icon_size, icon_size), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                mp_icon_images[status] = photo
                return photo
            except Exception:
                continue

    mp_icon_images[status] = None
    return None

def make_installed_games_list():
    # clear old buttons
    for btn in installed_game_item_buttons:
        btn.destroy()
    installed_game_item_buttons.clear()
    installed_game_original_indices.clear()

    installed_items = []

    for index, game_id in enumerate(gameIDs):
        if game_id in installedGames:
            installed_items.append(
                (gameNames[index], game_id, index, gameMPstatus[index])
            )

    # sort alphabetically by name
    installed_items.sort(key=lambda x: x[0].lower())

    for game_name, game_id, index, mp_status in installed_items:

        mpIcon = get_mp_icon(mp_status)
        if isinstance(mpIcon, ImageTk.PhotoImage):
            btn = ctk.CTkButton(
                installed_games_frame,
                text=game_name,
                image=mpIcon,
                compound="left",
                anchor="w",
                fg_color="transparent",
                text_color="white",
                hover_color="#355486",
                command=lambda i=index: select_game(i),
                font=(listfont, fontSize)
            )
        else:
            btn = ctk.CTkButton(
                installed_games_frame,
                text=game_name,
                anchor="w",
                fg_color="transparent",
                text_color="white",
                hover_color="#355486",
                command=lambda i=index: select_game(i),
                font=(listfont, fontSize)
            )
        btn.pack(fill="x", pady=2, padx=4)
        btn.bind("<Button-3>", lambda e, i=index: show_context_menu(e, i))
        installed_game_item_buttons.append(btn)
        installed_game_original_indices.append(index)

def refresh_installed_games():
    global installedGames
    installedGames = [] # Reset the list so we don't append to old data
    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
        installed_games = json.load(f)
        for game_id in installed_games.get(OS, {}):
            installedGames.append(game_id)

        if OS == "Linux":
            for game_id in installed_games.get("Windows", {}):
                if game_id not in installedGames:
                    installedGames.append(game_id)

    make_installed_games_list()

def refresh_installed_prereqs():
    global installedPrereqs
    installedPrereqs = set()
    with open(f"{bandit_userdata}/installed_prereqs.json", "r") as f:
        prereqs = json.load(f)
        for game_id in prereqs:
            installedPrereqs.add(game_id)


def get_installed_game_info(game_id):
    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
        installed_games = json.load(f)

    if game_id in installed_games.get(OS, {}):
        return OS, installed_games[OS][game_id]

    if OS == "Linux":
        if game_id in installed_games.get("Windows", {}):
            return "Windows", installed_games["Windows"][game_id]
        if game_id in installed_games.get("Darwin", {}):
            return "Darwin", installed_games["Darwin"][game_id]

    return None, None


def get_executable_json_path(section=None):
    if section == "Windows" and OS == "Linux":
        return os.path.join(bandit_program_data, "Windows", "executable_paths.json")
    return os.path.join(bandit_program_data, "executable_paths.json")


def get_prereq_json_path(section=None):
    if section == "Windows" and OS == "Linux":
        return os.path.join(bandit_program_data, "Windows", "prereq_paths.json")
    return os.path.join(bandit_program_data, "prereq_paths.json")


def get_icon_json_path(section=None):
    if section == "Windows" and OS == "Linux":
        return os.path.join(bandit_program_data, "Windows", "icon_paths.json")
    return os.path.join(bandit_program_data, "icon_paths.json")


def get_first_folder_in_executable_path(game_id, section=None):
    with open(get_executable_json_path(section), "r") as f:
        executable_paths = json.load(f)
        exec_path = executable_paths[game_id]
        first_folder = exec_path.split("/")[0]
        return first_folder


def resolve_icon_path(game_id, install_path, section=None):
    try:
        with open(get_icon_json_path(section), "r") as f:
            icon_paths = json.load(f)
        if game_id in icon_paths:
            icon_rel = icon_paths[game_id].lstrip('/')
            return os.path.join(install_path, icon_rel)
    except Exception:
        pass
    return None


def _download_tar_from_response(response, destination, display_name):
    total_size = int(response.headers.get("Content-Length", 0))
    downloaded = 0
    start_time = time.time()

    last_ui_update = 0.0
    last_ui_percent = -1

    def should_update_ui(percent, now):
        nonlocal last_ui_update, last_ui_percent
        percent_int = int(percent)
        if percent_int != last_ui_percent:
            last_ui_percent = percent_int
            last_ui_update = now
            return True
        if now - last_ui_update >= 0.2:
            last_ui_update = now
            return True
        return False

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
                speed = downloaded / max(elapsed, 0.001)

                if total_size:
                    percent = (downloaded / total_size) * 100
                    remaining = total_size - downloaded
                    eta = remaining / speed if speed > 0 else 0

                    speed_kb = speed / 1024
                    speed_mb = speed_kb / 1024
                    if speed_mb >= 1:
                        speed_str = f"{speed_mb:.2f} MB/s"
                    else:
                        speed_str = f"{speed_kb:.2f} KB/s"

                    if eta > 3600:
                        eta_str = time.strftime("%H hour(s) and %M minutes remaining", time.gmtime(eta))
                    elif eta > 60:
                        eta_str = time.strftime(str(int(eta / 60)) + " minute(s) remaining", time.gmtime(eta))
                    else:
                        eta_str = time.strftime("Less than a minute remaining", time.gmtime(eta))

                    print(
                        f"\rDownloading {display_name}: {percent:.2f}% | {speed_str} | ETA: {eta_str}",
                        end=""
                    )

                    now = time.time()
                    if should_update_ui(percent, now):
                        def update_ui():
                            progressBar.set(percent / 100)
                            infoLabel.configure(
                                text=f"Downloading {display_name}: {percent:.2f}%\n{speed_str} • ETA {eta_str}"
                            )

                        app.after(0, update_ui)
                else:
                    print(f"\rDownloading {display_name}: {downloaded} bytes", end="")

            return data

        def readable(self):
            return True

    wrapped = ProgressFile(response.raw)
    with tarfile.open(fileobj=wrapped, mode="r|gz") as tar:
        tar.extractall(path=destination)

    print(f"\n{display_name} installed successfully.")

    def finish_ui():
        progressBar.set(0)
        infoLabel.configure(text="Download complete!")

    app.after(0, finish_ui)
    return True


def download_tar_url(url, destination, display_name="download"):
    global currently_downloading
    currently_downloading = True

    try:
        with requests.get(url, stream=True, timeout=10) as response:
            response.raise_for_status()
            return _download_tar_from_response(response, destination, display_name)
    except Exception as e:
        if str(e) == "Download cancelled":
            print("\nDownload cancelled.")

            def cancel_ui():
                progressBar.set(0)
                infoLabel.configure(text="Download cancelled.")

            app.after(0, cancel_ui)
            return False
        else:
            print(f"\nFailed to install {display_name}: {e}")

            def fail_ui():
                progressBar.set(0)
                infoLabel.configure(text="Download failed.")

            app.after(0, fail_ui)
            return False
    finally:
        currently_downloading = False


def get_latest_proton_ge_tarball_url():
    api_url = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest"
    response = requests.get(api_url, timeout=10)
    response.raise_for_status()
    release = response.json()

    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.endswith(".tar.gz"):
            return asset.get("browser_download_url")

    raise Exception("No Proton-GE tar.gz asset found on the latest release.")


def extract_tarball_to_fixed_folder(response, destination, fixed_name):
    with tempfile.TemporaryDirectory() as temp_dir:
        wrapped = response.raw
        with tarfile.open(fileobj=wrapped, mode="r|gz") as tar:
            tar.extractall(path=temp_dir)
            members = [m.name for m in tar.getmembers() if m.name and not m.name.startswith(".")]

        root_parts = [m.split("/", 1)[0] for m in members if "/" in m]
        root_dirs = [p for p in sorted(set(root_parts)) if p]

        if len(root_dirs) == 1:
            src_dir = os.path.join(temp_dir, root_dirs[0])
        else:
            src_dir = temp_dir

        target_dir = os.path.join(destination, fixed_name)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        os.makedirs(target_dir, exist_ok=True)

        for item in os.listdir(src_dir):
            shutil.move(os.path.join(src_dir, item), os.path.join(target_dir, item))

    return target_dir


def download_proton_ge(destination=None):
    destination = destination or bandit_program_data
    url = get_latest_proton_ge_tarball_url()

    global currently_downloading
    currently_downloading = True

    try:
        with requests.get(url, stream=True, timeout=10) as response:
            response.raise_for_status()

            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            start_time = time.time()

            last_ui_update = 0.0
            last_ui_percent = -1

            def should_update_ui(percent, now):
                nonlocal last_ui_update, last_ui_percent
                percent_int = int(percent)
                if percent_int != last_ui_percent:
                    last_ui_percent = percent_int
                    last_ui_update = now
                    return True
                if now - last_ui_update >= 0.2:
                    last_ui_update = now
                    return True
                return False

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
                        speed = downloaded / max(elapsed, 0.001)

                        if total_size:
                            percent = (downloaded / total_size) * 100
                            remaining = total_size - downloaded
                            eta = remaining / speed if speed > 0 else 0

                            speed_kb = speed / 1024
                            speed_mb = speed_kb / 1024
                            if speed_mb >= 1:
                                speed_str = f"{speed_mb:.2f} MB/s"
                            else:
                                speed_str = f"{speed_kb:.2f} KB/s"

                            if eta > 3600:
                                eta_str = time.strftime("%H hour(s) and %M minutes remaining", time.gmtime(eta))
                            elif eta > 60:
                                eta_str = time.strftime(str(int(eta / 60)) + " minute(s) remaining", time.gmtime(eta))
                            else:
                                eta_str = time.strftime("Less than a minute remaining", time.gmtime(eta))

                            print(
                                f"\rDownloading Proton-GE: {percent:.2f}% | {speed_str} | ETA: {eta_str}",
                                end=""
                            )

                            now = time.time()
                            if should_update_ui(percent, now):
                                def update_ui():
                                    progressBar.set(percent / 100)
                                    infoLabel.configure(
                                        text=f"Downloading Proton-GE: {percent:.2f}%\n{speed_str} • ETA {eta_str}"
                                    )

                                app.after(0, update_ui)
                        else:
                            print(f"\rDownloading Proton-GE: {downloaded} bytes", end="")

                    return data

                def readable(self):
                    return True

            wrapped = ProgressFile(response.raw)
            with tarfile.open(fileobj=wrapped, mode="r|gz") as tar:
                with tempfile.TemporaryDirectory() as temp_dir:
                    tar.extractall(path=temp_dir)
                    members = [m.name for m in tar.getmembers() if m.name and not m.name.startswith(".")]

                    root_parts = [m.split("/", 1)[0] for m in members if "/" in m]
                    root_dirs = [p for p in sorted(set(root_parts)) if p]

                    if len(root_dirs) == 1:
                        src_dir = os.path.join(temp_dir, root_dirs[0])
                    else:
                        src_dir = temp_dir

                    target_dir = os.path.join(destination, "Proton-GE")
                    if os.path.exists(target_dir):
                        shutil.rmtree(target_dir)
                    os.makedirs(target_dir, exist_ok=True)

                    for item in os.listdir(src_dir):
                        shutil.move(os.path.join(src_dir, item), os.path.join(target_dir, item))

        print("\nProton-GE installed successfully.")
        send_telemetry("proton_ge_installed")

        def finish_ui():
            progressBar.set(0)
            infoLabel.configure(text="Proton-GE download complete!")

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
            print(f"\nFailed to install Proton-GE: {e}")

            def fail_ui():
                progressBar.set(0)
                infoLabel.configure(text="Download failed.")

            app.after(0, fail_ui)
            return False
    finally:
        currently_downloading = False


def find_proton_binary():
    proton_dir = os.path.join(bandit_program_data, "Proton-GE")
    candidates = [
        os.path.join(proton_dir, "proton"),
        os.path.join(proton_dir, "dist", "proton"),
        os.path.join(proton_dir, "bin", "proton")
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def ensure_proton_installed():
    global currently_downloading, currently_downloading_game

    if find_proton_binary():
        return True

    if currently_downloading:
        tk.messagebox.showinfo(
            "Download in progress",
            "Please wait until the current download is complete before launching a Windows game."
        )
        return False

    if not tk.messagebox.askyesno(
        "Download Proton-GE?",
        "This game requires Proton-GE to run on Linux. Download the latest Proton-GE release now?"
    ):
        return False

    def proton_task():
        global currently_downloading, currently_downloading_game
        currently_downloading_game = None
        download_proton_ge()
        if selected_game is not None:
            app.after(0, lambda: select_game(selected_game))

    threading.Thread(target=proton_task, daemon=True).start()
    return False


def run_with_proton(executable_path, working_dir):
    proton_binary = find_proton_binary()
    if not proton_binary:
        if not ensure_proton_installed():
            return False
        proton_binary = find_proton_binary()
        if not proton_binary:
            tk.messagebox.showerror("Error", "Unable to locate the Proton-GE binary after download.")
            return False

    env = os.environ.copy()
    compat_path = os.path.expanduser("~/.banditpfx")
    env["STEAM_COMPAT_DATA_PATH"] = compat_path
    env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = compat_path
    env["WINEDLLOVERRIDES"] = "dinput8,winhttp,winmm=n,b"

    try:
        subprocess.Popen([proton_binary, "run", executable_path], cwd=working_dir, env=env)
        return True
    except Exception as e:
        tk.messagebox.showerror("Error", f"Failed to launch with Proton: {e}")
        return False


def tick_box(setting, value):
    with open(f"{bandit_userdata}/settings.json", "r") as f:
        settings = json.load(f)

    settings[setting] = value  # update the changed setting

    with open(f"{bandit_userdata}/settings.json", "w") as f:
        json.dump(settings, f, indent=4)

    print(f"{setting} set to {value}")

def settings_clicked():
    settings_window = ctk.CTkToplevel(app)
    settings_window.title("Bandit Settings")
    settings_window.protocol(
        "WM_DELETE_WINDOW",
        lambda: settings_closed(settings_window))
    with open(f"{bandit_userdata}/settings.json", "r") as f:
        settings = json.load(f)
    vars = {}
    for preference, value in settings.items():
        # Skip internal flags (starting with _)
        if preference.startswith("_"):
            continue
        var = tk.BooleanVar(value=value)
        vars[preference] = var

        checkbox = ctk.CTkCheckBox(
            master=settings_window,
            text=preference,
            variable=var,
            command=lambda p=preference, v=var: tick_box(p, v.get())
        )
        checkbox.pack(padx=20, pady=10)

def settings_closed(window):
    print('apply settings')
    apply_settings()
    window.destroy()

settingsButton = ctk.CTkButton(app,
    text="⚙️", width=40, height=40, fg_color="#5F5F5F", command=settings_clicked)

settingsButton.pack(pady=0, anchor="ne")

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
tabview = ctk.CTkTabview(app)
tabview.pack(fill="both", expand=True, padx=10, pady=10)
tabview.add("All Games")
tabview.add("Installed")

game_list_frame = ctk.CTkScrollableFrame(tabview.tab("All Games"))
game_list_frame.pack(fill="both", expand=True)

installed_games_frame = ctk.CTkScrollableFrame(tabview.tab("Installed"))
installed_games_frame.pack(fill="both", expand=True)

def _on_mousewheel(event):
    game_list_frame._parent_canvas.yview_scroll(int(-1*(event.delta/1)), "units")

# This shit is necessary to be able to scroll for some reason... Tk is kinda crappy
game_list_frame.bind_all("<MouseWheel>", _on_mousewheel)  # Windows & macOS
game_list_frame.bind_all("<Button-4>", lambda e: game_list_frame._parent_canvas.yview_scroll(-1, "units"))  # Linux scroll up
game_list_frame.bind_all("<Button-5>", lambda e: game_list_frame._parent_canvas.yview_scroll(1, "units"))   # Linux scroll down

# Track selection index
selected_game = None
prev_selected = None
prev_selected_installed = None

if OS == "Linux":
    seen_ids = set()
    # Load Linux games
    with open(f"{bandit_program_data}/list.txt", "r") as f:
        for line in f:
            line = line.strip()
            game_id = line.split("|")[1]

            rawlist.append(line)
            seen_ids.add(game_id)
            linux_game_ids.add(game_id)

    # Load Windows games
    with open(f"{bandit_program_data}/Windows/list.txt", "r") as f:
        for line in f:
            line = line.strip()
            game_id = line.split("|")[1]

            windows_game_ids.add(game_id)
            # only add if not already present
            if game_id not in seen_ids:
                rawlist.append(line)
                seen_ids.add(game_id)

    # sort alphabetically by game name
    rawlist.sort(key=lambda x: x.split("|")[0].lower())
else: # Do it normally
    for line in open(f"{bandit_program_data}/list.txt", "r").readlines():
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

refresh_installed_games()
refresh_installed_prereqs()

def make_game_list():
    # clear any existing items
    for btn in game_item_buttons:
        btn.destroy()
    game_item_buttons.clear()

    for index, game_name in enumerate(gameNames):
        mpIcon = get_mp_icon(gameMPstatus[index])

        if isinstance(mpIcon, ImageTk.PhotoImage):
            btn = ctk.CTkButton(
                game_list_frame,
                text=game_name,
                image=mpIcon,
                compound="left",
                anchor="w",
                fg_color="transparent",
                hover_color="#355486",
                command=lambda i=index: select_game(i),
                font=(listfont, fontSize)
            )
        else:
            btn = ctk.CTkButton(
                game_list_frame,
                text=game_name,
                anchor="w",
                fg_color="transparent",
                hover_color="#355486",
                command=lambda i=index: select_game(i),
                font=(listfont, fontSize)
            )
        btn.pack(fill="x", pady=2, padx=4)
        btn.bind("<Button-3>", lambda e, i=index: show_context_menu(e, i))
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

def format_size(size_in_bytes):
    if size_in_bytes != "Unknown":
        try:
            if size_in_bytes >= 1_000_000_000:
                formatted_size = f"{size_in_bytes / 1_000_000_000:.2f} GB"
            elif size_in_bytes >= 1_000_000:
                formatted_size = f"{size_in_bytes / 1_000_000:.2f} MB"
            elif size_in_bytes >= 1_000:
                formatted_size = f"{size_in_bytes / 1_000:.2f} KB"
            else:
                formatted_size = f"{size_in_bytes} bytes"
            return formatted_size
        except ValueError:
            pass

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

    # Handle installed games list selection
    try:
        if prev_selected_installed is not None and 0 <= prev_selected_installed < len(installed_game_item_buttons):
            installed_game_item_buttons[prev_selected_installed].configure(fg_color="transparent")
    except Exception:
        pass

    if gameIDs[selected_game] in installedGames:
        try:
            installed_index = installed_game_original_indices.index(selected_game)
            installed_game_item_buttons[installed_index].configure(fg_color="#444444")
            prev_selected_installed = installed_index
        except ValueError:
            prev_selected_installed = None
    else:
        prev_selected_installed = None

    # update buttons depending on install/download state
    try:
        if gameIDs[selected_game] in installedGames:
            ipButton.configure(text="Play")
            ipButton.configure(state="normal")
            uninstallButton.configure(state="normal")
            if currently_downloading and selected_game != currently_downloading_game:
                ipButton.configure(state="disabled")
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

    formatted_mp_status = "Singleplayer or local multiplayer only."
    if gameMPstatus[selected_game] == "1":
        formatted_mp_status = "LAN multiplayer supported."
    elif gameMPstatus[selected_game] == "2":
        formatted_mp_status = "Online multiplayer with other Bandit users supported."
    elif gameMPstatus[selected_game] == "3":
        formatted_mp_status = "Online multiplayer with anyone supported."

    gameInfoLabel.configure(text=f"{gameNames[selected_game]} — {format_size(int(gameSizes[selected_game]))}\n{formatted_mp_status}")

def show_context_menu(event, index):
    menu = tk.Menu(app, tearoff=0)
    menu.add_command(label="Browse file location", command=lambda: browse_location(index))
    menu.add_command(label="Move game", command=lambda: move_game(index))
    menu.add_command(label="Create desktop shortcut", command=lambda: create_shortcut(index))
    menu.post(event.x_root, event.y_root)


def move_game(game_index):
    global currently_downloading

    game_id = gameIDs[game_index]
    if game_id not in installedGames:
        tk.messagebox.showerror("Move Game", "This game is not installed.")
        return

    if currently_downloading:
        tk.messagebox.showinfo(
            "Busy",
            "Please wait until the current download or move is complete before moving a game."
        )
        return

    section, install_path = get_installed_game_info(game_id)
    if not section or not install_path:
        tk.messagebox.showerror("Move Game", "Could not determine the current install location.")
        return

    game_folder = get_first_folder_in_executable_path(game_id, section)
    source_path = os.path.normpath(os.path.join(install_path, game_folder))
    if not os.path.exists(source_path):
        tk.messagebox.showerror("Move Game", f"Game folder not found:\n{source_path}")
        return

    target_parent = ctk.filedialog.askdirectory(initialdir=install_path)
    if not target_parent:
        return

    target_parent = os.path.normpath(target_parent)
    if os.path.abspath(target_parent) == os.path.abspath(install_path):
        tk.messagebox.showinfo("Move Game", "The game is already located in that folder.")
        return

    target_path = os.path.join(target_parent, os.path.basename(source_path))
    if os.path.exists(target_path):
        if not tk.messagebox.askyesno(
            "Move Game",
            f"A folder named '{os.path.basename(source_path)}' already exists in the destination. Replace it?"
        ):
            return
        try:
            shutil.rmtree(target_path)
        except Exception as e:
            tk.messagebox.showerror("Move Game", f"Failed to remove existing destination folder:\n{e}")
            return

    currently_downloading = True
    progressBar.set(0)
    infoLabel.configure(text=f"Moving {gameNames[game_index]}...")

    def task():
        try:
            shutil.move(source_path, target_parent)
            with open(f"{bandit_program_data}/installed_games.json", "r") as f:
                installed_games = json.load(f)
            if section not in installed_games:
                installed_games[section] = {}
            installed_games[section][game_id] = target_parent
            with open(f"{bandit_program_data}/installed_games.json", "w") as f:
                json.dump(installed_games, f, indent=4)

            def done_ui():
                progressBar.set(1)
                infoLabel.configure(text=f"Moved {gameNames[game_index]} successfully.")
                refresh_installed_games()
                update_game_list_colors()
                if selected_game is not None:
                    select_game(selected_game)

            app.after(0, done_ui)
        except Exception as e:
            def fail_ui():
                infoLabel.configure(text=f"Failed to move game: {e}")
                refresh_installed_games()
                update_game_list_colors()
                if selected_game is not None:
                    select_game(selected_game)
            app.after(0, fail_ui)
        finally:
            global currently_downloading
            currently_downloading = False

    threading.Thread(target=task, daemon=True).start()


def browse_location(game_index):
    if gameIDs[game_index] in installedGames:
        section, install_path = get_installed_game_info(gameIDs[game_index])
        if not section or not install_path:
            return
        game_path = f"{install_path}/{get_first_folder_in_executable_path(gameIDs[game_index], section)}"
        print(game_path)

        if os.path.exists(game_path):
            if OS == "Windows":
                os.startfile(game_path)
            elif OS == "Darwin":
                subprocess.run(["open", "-R", game_path])
            elif OS == "Linux":
                subprocess.run(["xdg-open", game_path])

def sanitize_filename(name):
    return "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()

# NOTE: resolve_icon_path is defined earlier with support for Windows section files.

def get_desktop_path():
    if OS == "Windows":
        try:
            from ctypes import wintypes, windll, create_unicode_buffer
            CSIDL_DESKTOPDIRECTORY = 0x10
            buf = create_unicode_buffer(wintypes.MAX_PATH)
            windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf)
            desktop = buf.value
            if os.path.isdir(desktop):
                return desktop
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Desktop")

def remove_desktop_shortcut(display_name):
    desktop = get_desktop_path()
    safe_name = sanitize_filename(display_name)
    candidates = []
    if OS == "Windows":
        candidates = [f"{safe_name}.lnk", f"{safe_name}.url", f"{display_name}.lnk", f"{display_name}.url"]
    elif OS == "Darwin":
        candidates = [safe_name, display_name]
    else:
        candidates = [f"{safe_name}.desktop", f"{display_name}.desktop"]

    for candidate in candidates:
        path = os.path.join(desktop, candidate)
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

def create_shortcut(game_index):
    if gameIDs[game_index] in installedGames:
        game_id = gameIDs[game_index]
        display_name = gameNames[game_index]
        safe_name = sanitize_filename(display_name)

        section, game_install_path = get_installed_game_info(game_id)
        if not section or not game_install_path:
            tk.messagebox.showerror("Error", "Could not find installation information for this game.")
            return

        # Resolve executable relative path and full path
        with open(get_executable_json_path(section), "r") as f:
            executable_paths = json.load(f)
        executable_relative_path = executable_paths.get(game_id, "")
        game_exec_full_path = os.path.join(game_install_path, executable_relative_path) if executable_relative_path else game_install_path
        game_exec_full_path = os.path.normpath(game_exec_full_path)

        icon_path = resolve_icon_path(game_id, game_install_path, section)

        if not os.path.exists(game_exec_full_path):
            tk.messagebox.showwarning("Executable Missing", f"Executable not found:\n{game_exec_full_path}")
            return

        desktop = get_desktop_path()
        os.makedirs(desktop, exist_ok=True)

        try:
            if OS == "Windows":
                # Prefer win32com if available to create a real .lnk
                try:
                    from win32com.client import Dispatch
                    shortcut_path = os.path.join(desktop, f"{safe_name}.lnk")
                    shell = Dispatch('WScript.Shell')
                    shortcut = shell.CreateShortCut(shortcut_path)
                    shortcut.Targetpath = game_exec_full_path
                    shortcut.WorkingDirectory = os.path.dirname(game_exec_full_path)
                    shortcut.IconLocation = icon_path if icon_path else game_exec_full_path
                    shortcut.save()
                except Exception:
                    # Fallback to .url which also works as a clickable link
                    url_path = os.path.join(desktop, f"{safe_name}.url")
                    with open(url_path, "w", encoding="utf-8") as f:
                        f.write("[InternetShortcut]\n")
                        f.write("URL=file:///" + game_exec_full_path.replace("\\", "/") + "\n")
                        icon_src = icon_path if icon_path else game_exec_full_path
                        f.write("IconFile=" + icon_src + "\n")
                        f.write("IconIndex=0\n")

            elif OS == "Darwin":
                # Make a Finder alias using AppleScript
                as_cmd = (
                    f'tell application "Finder" to make alias file to '
                    f'(POSIX file "{game_exec_full_path}") '
                    f'at (POSIX file "{desktop}") '
                    f'with properties {{name:"{safe_name}"}}'
                )
                subprocess.run(["osascript", "-e", as_cmd], check=False)

                if icon_path:
                    copy_icon_cmd = f'''
                    set src to POSIX file "{icon_path}"
                    set dst to POSIX file "{os.path.join(desktop, safe_name)}"
                    tell application "Finder"
                        set icon of dst to icon of src
                    end tell
                    '''
                    subprocess.run(["osascript", "-e", copy_icon_cmd], check=False)

            else:  # Linux
                desktop_file = os.path.join(desktop, f"{safe_name}.desktop")
                exec_cmd = f'"{game_exec_full_path}"'

                desktop_entry = [
                    "[Desktop Entry]",
                    f"Name={display_name}",
                    f"Exec={exec_cmd}",
                    "Type=Application",
                    f"Path={os.path.dirname(game_exec_full_path)}",
                    f"Icon={icon_path if icon_path else os.path.splitext(game_exec_full_path)[0]}",
                    "Terminal=false"
                ]
                with open(desktop_file, "w", encoding="utf-8") as f:
                    f.write("\n".join(desktop_entry))
                try:
                    os.chmod(desktop_file, 0o755)
                except Exception:
                    pass

            tk.messagebox.showinfo("Shortcut Created", f"Desktop shortcut created for {display_name}.")
        except Exception as e:
            tk.messagebox.showerror("Error", f"Failed to create shortcut: {e}")

def download_tar(game_id, destination = bandit_games_folder, source_os=None):
    source_os = source_os or OS
    url = f"https://thuis.felixband.nl/bandit/{source_os}/{game_id}.tar.gz"
    display_name = None
    if currently_downloading_game is not None and 0 <= currently_downloading_game < len(gameNames):
        display_name = gameNames[currently_downloading_game]
    else:
        display_name = game_id
    return download_tar_url(url, destination, display_name)


def install_or_play():
    # if currently downloading & selected curr downloading game, cancel
    global currently_downloading, currently_downloading_game
    if currently_downloading and selected_game == currently_downloading_game:
        currently_downloading = False
        print("Cancelling download...")
        if selected_game is not None:
            select_game(selected_game)
        return
    if currently_downloading and selected_game != currently_downloading_game:
        tk.messagebox.showinfo(
            "Busy",
            "Please wait until the current download or move is complete."
        )
        return
    
    # if selected game is installed, play!
    elif gameIDs[selected_game] in installedGames:
        print(f'Launching {selected_game}!')
        section, install_path = get_installed_game_info(gameIDs[selected_game])
        if not section or not install_path:
            tk.messagebox.showerror("Error", "Unable to locate the installed game path.")
            return

        with open(get_executable_json_path(section), "r") as f:
            executable_paths = json.load(f)
            game_path = f"{install_path}/{executable_paths[gameIDs[selected_game]]}"

            # Install prerequisites
            with open(get_prereq_json_path(section), "r") as f:
                prereq_paths = json.load(f)
                if gameIDs[selected_game] in prereq_paths and gameIDs[selected_game] not in installedPrereqs:
                    install_commands = []
                    for prereq in prereq_paths[gameIDs[selected_game]]:
                        # Normalize the path
                        full_path = os.path.normpath(f"{install_path}/{get_first_folder_in_executable_path(gameIDs[selected_game], section)}/{prereq['path']}")
                        
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
                elif OS == "Linux" and section == "Windows":
                    if not ensure_proton_installed():
                        return
                    if run_with_proton(game_path, os.path.dirname(game_path)):
                        send_telemetry("game_launched", game_id=gameIDs[selected_game], game_name=gameNames[selected_game])
                        return
                    tk.messagebox.showerror("Error", "Failed to run the Windows game with Proton.")
                else:
                    subprocess.Popen(game_path, cwd=os.path.dirname(game_path))
                send_telemetry("game_launched", game_id=gameIDs[selected_game], game_name=gameNames[selected_game])
            except Exception as e:
                tk.messagebox.showerror("Error", f"Failed to launch the game. Error: {e}")
    else:
        # install the game
        currently_downloading = True
        currently_downloading_game = selected_game
        print(f"Installing {selected_game}")
        ipButton.configure(state="disabled")

        install_source_os = OS
        if OS == "Linux":
            game_id = gameIDs[selected_game]
            if game_id in windows_game_ids and game_id not in linux_game_ids:
                install_source_os = "Windows"
            elif game_id in linux_game_ids and game_id in windows_game_ids:
                print("There is a Linux AND Windows version of this game.")
                if not tk.messagebox.askyesno(
                    "Which version?",
                    "This game has a Linux AND a Windows version. Which one would you prefer to install?\n\nYes = Native Linux version (recommended)\nNo = Windows version (requires Proton)"
                ):
                    install_source_os = "Windows"

        def task():
            global currently_downloading, currently_downloading_game

            if ask_install_path:
                game_destination = ctk.filedialog.askdirectory(initialdir=bandit_games_folder)
                if not game_destination:
                    currently_downloading = False
                    currently_downloading_game = None
                    app.after(0, lambda: select_game(selected_game))
                    return
            else:
                game_destination = bandit_games_folder

            print(f'space left: {shutil.disk_usage(game_destination).free} vs game size: {int(gameSizes[selected_game])}')
            if shutil.disk_usage(game_destination).free < int(gameSizes[selected_game]):
                print('no space!')
                if not tk.messagebox.askyesno("Not enough space!", f"This game is {format_size(int(gameSizes[selected_game]))} bytes big, and you only have {format_size(shutil.disk_usage(game_destination).free)} GB of space left!\nIn case this is wrong, would you like to continue downloading this game anyway?"):
                    currently_downloading = False
                    currently_downloading_game = None
                    app.after(0, lambda: select_game(selected_game))
                    return

            success = download_tar(gameIDs[selected_game], game_destination, source_os=install_source_os)

            def after():
                ipButton.configure(state="normal")

                if success:
                    # update installed_games.json
                    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
                        installed_games = json.load(f)

                    if install_source_os not in installed_games:
                        installed_games[install_source_os] = {}
                    installed_games[install_source_os][gameIDs[currently_downloading_game]] = game_destination

                    with open(f"{bandit_program_data}/installed_games.json", "w") as f:
                        json.dump(installed_games, f, indent=4)

                    # refresh UI
                    refresh_installed_games()
                    update_game_list_colors()
                    if selected_game is not None:
                        select_game(selected_game)
                    send_telemetry("game_installed", game_id=gameIDs[currently_downloading_game], game_name=gameNames[currently_downloading_game])
                    currently_downloading = False
                else:
                    print("Failed to install the game for some reason")
                    currently_downloading = False

            # safely update UI from main thread
            app.after(0, after)

        threading.Thread(target=task, daemon=True).start()
        if selected_game is not None:
            select_game(selected_game)

def uninstall_game():
    print('gonna nuke')
    game_id = gameIDs[selected_game]
    section, install_path = get_installed_game_info(game_id)
    if not section or not install_path:
        tk.messagebox.showerror("Error", "Could not find installation information for this game.")
        return

    full_game_path = os.path.join(install_path, get_first_folder_in_executable_path(game_id, section))
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

    # remove desktop shortcut if it exists
    remove_desktop_shortcut(gameNames[selected_game])

    with open(f"{bandit_program_data}/installed_games.json", "r") as f:
        installed_games = json.load(f)

    installed_games.get(section, {}).pop(game_id, None)

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
    send_telemetry("game_uninstalled", game_id=game_id, game_name=gameNames[selected_game])
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

search_buffer = ""
last_key_time = 0

def key_pressed(event):
    global search_buffer, last_key_time

    # Ignore modifier keys and non-printable characters
    if not event.char or not event.char.isprintable():
        return

    current_time = time.time()
    
    # If it's been more than 1 second since the last keypress, reset the search buffer
    if current_time - last_key_time > 1.0:
        search_buffer = ""

    search_buffer += event.char.lower()
    last_key_time = current_time

    current_tab = tabview.get()

    if current_tab == "All Games":
        for index, name in enumerate(gameNames):
            if name.lower().startswith(search_buffer):
                select_game(index)
                
                # Scroll to the selected item (calculate percentage down the list)
                fraction = index / max(1, len(gameNames))
                game_list_frame._parent_canvas.yview_moveto(fraction)
                break
                
    elif current_tab == "Installed":
        # Reconstruct the sorted installed games list to match visual order
        installed_data = []
        for idx, gid in enumerate(gameIDs):
            if gid in installedGames:
                installed_data.append((gameNames[idx], idx))
                
        # Sort exactly how make_installed_games_list() does
        installed_data.sort(key=lambda x: x[0].lower())

        for visual_index, (name, original_index) in enumerate(installed_data):
            if name.lower().startswith(search_buffer):
                select_game(original_index)
                
                # Scroll to the selected item based on its position in the Installed tab
                fraction = visual_index / max(1, len(installed_data))
                installed_games_frame._parent_canvas.yview_moveto(fraction)
                break

# Bind all key presses on the app window to the handler
app.bind_all("<Key>", key_pressed)

def check_for_updates():
    try:
        response = requests.get("https://api.github.com/repos/FelixBand/Bandit/releases/latest", timeout=10)
        response.raise_for_status()
        json_data = response.json()
        if json_data["tag_name"] > version:

            if tk.messagebox.askyesno('Download update?', "A new update is available: " + json_data["tag_name"] + ". You're running version " + version + ". Would you like to update?"):
                try:
                    webbrowser.open("https://github.com/FelixBand/Bandit/releases/latest", new=2)
                    exit()
                except Exception:
                    pass
    except Exception as e:
        print(f"An error occurred while checking for updates: {e}")

check_for_updates()

show_telemetry_disclaimer()

app.mainloop() # Up and away!
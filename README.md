# Bandit

With this app, you can download and play games hosted on my dedicated file server.

Per-game options are available from **Launch Options…**. CrossOver graphics, MSync, and Metal HUD
options are shown on macOS. On Linux, enable **Use WineD3D** to set `PROTON_USE_WINED3D=1` for
compatibility with older graphics cards; it is off by default.

# Compiling

To compile the app I use PyInstaller.
Other dependencies are tkinter and customtkinter; the framework for the GUI, pillow, used to render images and requests, for downloading data over HTTP.

You can get these using pip with the following commands:

```
pip install customtkinter
pip install pillow
pip install pyinstaller
pip install requests
```

Then, to compile the app itself, use `compile-for-windows.bat` for Windows and `compile-for-unix.sh` for macOS or Linux. After compiling, the app can be found in the `dist` folder. On Windows, you can build a setup wizard using Inno Setup, which you can get [here](https://jrsoftware.org/isinfo.php).

After installing that, you can build a setup for Windows using `make-windows-setup.iss`. The compiled installer can then be found in the `Compiled Setup` directory.

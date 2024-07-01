# Bandit

With this app, you can download games and extract them on the fly from my dedicated file server.

# Compiling

To compile the app, the dependency Pyinstaller is used.
Other dependencies are PyQt6; the framework for the GUI and plyer, used to display notifications.

You can get these using pip with the following commands:
`pip install PyQt6`
`pip install plyer`
`pip install pyinstaller`

Then, to compile the app itself, use `compile for windows.bat` for Windows and `compile for macos.sh` for macOS. After compiling, the app can be found in the `dist` folder. On Windows, you can build a setup wizard using Inno Setup, which you can get here: https://jrsoftware.org/isinfo.php

After installing that, you can build a setup for Windows using `make windows setup.iss`. The compiled installer can then be found in the `Compiled Installer` directory.

I am experimenting.
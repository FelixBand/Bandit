rd /s /q build
rd /s /q dist
pyinstaller --windowed --icon=icon.ico -n Bandit "bandit pyqt.py"
rm -rf build
rm -rf dist
pyinstaller --windowed --icon=icon.icns --add-data "icon.png:." -n Bandit bandit.py

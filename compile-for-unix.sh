rm -rf build
rm -rf dist
pyinstaller --onefile --windowed \
  --icon=icon.icns \
  --add-data "assets:assets" \
  --add-data "icon.png:." \
  -n Bandit bandit.py
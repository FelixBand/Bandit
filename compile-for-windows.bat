rd /s /q build
rd /s /q dist
pyinstaller --windowed ^
  --icon=icon.ico ^
  --add-data "assets;assets" ^
  --add-data "icon.ico;." ^
  --add-data "icon.png;." ^
  -n Bandit bandit.py
pause
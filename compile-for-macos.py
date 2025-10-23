from setuptools import setup

APP = ['bandit.py']
DATA_FILES = []
OPTIONS = {
    # turn off Carbon-dependent stuff
    "argv_emulation": False,
    # optional: set your .icns app icon here
    "iconfile": "Resources/Bandit.icns",
    # include PyQt6 dynamically loaded libs
    "packages": ["PyQt6"],
    # make sure frameworks don’t get stripped out
    "includes": ["sip", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets"],
}

setup(
    app=APP,
    name="Bandit",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)


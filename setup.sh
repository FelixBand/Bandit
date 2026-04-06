#!/bin/bash

APP_NAME="BanditGameLauncher"
SYSTEM_FOLDER="/usr/local/share/$APP_NAME"

# Function to check if running as root
is_root() {
    [ "$(id -u)" -eq 0 ]
}

# Linux
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if ! is_root; then
        # Ask for password using graphical pkexec (like GUI sudo)
        pkexec bash "$0"
        exit
    fi
fi

# macOS
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! is_root; then
        # Use AppleScript GUI prompt for password
        echo "Requesting admin privileges..."
        /usr/bin/osascript <<EOT
            do shell script "/bin/bash $0" with administrator privileges
EOT
        exit
    fi
fi

# Create the system folder
mkdir -p "$SYSTEM_FOLDER"
# Make the folder writable by all users (optional: you can give ownership to a specific group/user)
chmod 777 "$SYSTEM_FOLDER"

echo "System-wide folder created at $SYSTEM_FOLDER"
#!/usr/bin/env bash
###########################################################################
# Setup script for testing AndrOBD with Bluetooth on Linux
# Usage: sudo ./setup_bluetooth_linux.sh
###########################################################################

set -e

echo "=========================================="
echo "ELM327 Emulator - Bluetooth Setup (Linux)"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

echo "Installing Bluetooth tools..."
apt-get update
apt-get install -y bluez

echo ""
echo "Setting up RFCOMM device..."
mknod -m 666 /dev/rfcomm0 c 216 0 2>/dev/null || echo "RFCOMM device already exists"
chown $SUDO_USER /dev/rfcomm0

echo ""
echo "Starting Bluetooth service..."
service bluetooth restart

echo ""
echo "Adding Serial Port profile..."
sdptool add --channel=1 SP

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Run bluetoothctl to pair your Android device:"
echo "   bluetoothctl"
echo "   [bluetooth]# power on"
echo "   [bluetooth]# agent on"
echo "   [bluetooth]# default-agent"
echo "   [bluetooth]# discoverable on"
echo "   [bluetooth]# pairable on"
echo ""
echo "2. Pair from your Android device"
echo ""
echo "3. Start the emulator (as regular user):"
echo "   rfcomm watch /dev/rfcomm0 1 python3 -m elm -P /dev/rfcomm0 -l -s car"
echo ""
echo "4. Configure AndrOBD:"
echo "   - Connection type: Bluetooth"
echo "   - Select your computer"
echo "   - Connect"
echo "=========================================="

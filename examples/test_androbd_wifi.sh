#!/usr/bin/env bash
###########################################################################
# Quick start script for testing AndrOBD with WiFi/Network connection
# Usage: ./test_androbd_wifi.sh [port]
###########################################################################

set -e

PORT=${1:-35000}
SCENARIO="car"

echo "=========================================="
echo "ELM327 Emulator - AndrOBD WiFi Test Setup"
echo "=========================================="
echo ""

# Check if elm is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Get IP address
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    IP=$(hostname -I | awk '{print $1}')
elif [[ "$OSTYPE" == "darwin"* ]]; then
    IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
else
    echo "Warning: Unknown OS, please find your IP address manually"
    IP="YOUR_IP_ADDRESS"
fi

echo "Starting ELM327 emulator..."
echo "  Scenario: $SCENARIO"
echo "  Port: $PORT"
echo "  IP Address: $IP"
echo ""
echo "=========================================="
echo "AndrOBD Configuration:"
echo "=========================================="
echo "  1. Open AndrOBD on your Android device"
echo "  2. Go to Settings"
echo "  3. Connection type: Network (WiFi)"
echo "  4. IP Address: $IP"
echo "  5. Port: $PORT"
echo "  6. Click Connect"
echo "=========================================="
echo ""
echo "Press Ctrl+C to stop the emulator"
echo ""

# Start the emulator
python3 -m elm -s "$SCENARIO" -n "$PORT"

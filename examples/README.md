# AndrOBD Testing Examples

This directory contains example scripts and utilities for testing AndrOBD applications with the ELM327-emulator.

## Quick Start Scripts

### WiFi/Network Testing

#### Linux/macOS:
```bash
./test_androbd_wifi.sh
# Or with custom port:
./test_androbd_wifi.sh 8080
```

#### Windows:
```cmd
test_androbd_wifi.bat
REM Or with custom port:
test_androbd_wifi.bat 8080
```

### Bluetooth Testing (Linux)

Setup Bluetooth (run once):
```bash
sudo ./setup_bluetooth_linux.sh
```

Then follow the on-screen instructions to pair and start the emulator.

## Python Examples

### Simple Connection Test
```bash
python3 test_androbd_simple.py
```

Starts the emulator and displays connection information. Useful for verifying basic connectivity.

### Dynamic Driving Simulation
```bash
python3 test_androbd_dynamic.py
```

Simulates a realistic driving scenario with:
- Variable vehicle speed (0-120 km/h)
- Changing engine RPM (800-4000)
- Dynamic engine load (20-80%)

Great for testing real-time data display and graphing in AndrOBD.

## Usage Notes

1. **Firewall Configuration**: Ensure your firewall allows connections on the chosen port (default: 35000)

2. **Network Discovery**: Make sure your Android device and computer are on the same network

3. **Testing Tips**:
   - Start with `test_androbd_simple.py` to verify basic connectivity
   - Use `test_androbd_dynamic.py` to test real-time data updates
   - Monitor the emulator console for debugging information

4. **Customization**:
   - Edit the scripts to change scenarios (car, mt05, etc.)
   - Modify port numbers as needed
   - Adjust simulation parameters in Python scripts

## Troubleshooting

If AndrOBD can't connect:

1. **Check network connectivity**:
   ```bash
   # From Android device, ping your computer
   ping <computer-ip>
   ```

2. **Verify emulator is running**:
   ```bash
   netstat -an | grep 35000
   ```

3. **Test with telnet first**:
   ```bash
   telnet <computer-ip> 35000
   ATZ  # Should respond with ELM version
   ```

4. **Check firewall** (Linux):
   ```bash
   sudo ufw allow 35000/tcp
   ```

5. **Check firewall** (Windows):
   - Windows Security → Firewall → Allow an app
   - Add Python to allowed apps

## See Also

- [TESTING_ANDROBD.md](../TESTING_ANDROBD.md) - Comprehensive testing guide
- [README.md](../README.md) - Main documentation
- [Examples in main README](../README.md#testing-obd-ii-applications)

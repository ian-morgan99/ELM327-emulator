# Testing AndrOBD Applications with ELM327-emulator

This guide explains how to use **ELM327-emulator** as a test harness to simulate v-link OBDII wireless or Bluetooth adapters for testing AndrOBD and similar Android OBD-II applications.

## Overview

**ELM327-emulator** fully supports simulating wireless OBDII adapters through:
- **WiFi/TCP networking** - Simulates WiFi OBD-II adapters like v-link
- **Bluetooth** - Simulates Bluetooth OBD-II adapters
- **Serial communication** - For USB/serial adapters

This makes it an ideal test harness for developing and testing Android OBD-II applications without needing a physical vehicle or OBD-II adapter.

## Quick Start for AndrOBD Testing

### Option 1: WiFi/Network Testing (Recommended for AndrOBD)

This is the easiest method for testing AndrOBD applications, as it works with any device on your local network.

#### On Linux/macOS:

1. **Start the emulator with WiFi interface:**
   ```bash
   python3 -m elm -s car -n 35000
   ```
   
   This starts the emulator on port 35000 (the standard port for many WiFi OBD-II adapters).

2. **Configure AndrOBD:**
   - Open AndrOBD on your Android device
   - Go to Settings → Connection type → Select "Network (WiFi)"
   - Enter your computer's IP address (e.g., `192.168.1.100`)
   - Set port to `35000`
   - Connect

3. **Find your computer's IP address:**
   ```bash
   # Linux
   ip addr show | grep inet
   
   # macOS
   ifconfig | grep inet
   ```

#### On Windows:

1. **Start the emulator:**
   ```cmd
   python -m elm -s car -n 35000
   ```

2. **Find your IP address:**
   ```cmd
   ipconfig
   ```
   Look for "IPv4 Address" under your active network adapter.

3. **Configure firewall:**
   - Allow Python through Windows Firewall on port 35000
   - Or temporarily disable firewall for testing

4. **Configure AndrOBD as described above**

### Option 2: Bluetooth Testing

Bluetooth testing allows you to simulate real-world Bluetooth OBD-II adapters.

#### On Linux:

1. **Install Bluetooth tools:**
   ```bash
   sudo apt-get install bluez
   ```

2. **Pair your Android device:**
   ```bash
   bluetoothctl
   [bluetooth]# power on
   [bluetooth]# agent on
   [bluetooth]# default-agent
   [bluetooth]# discoverable on
   [bluetooth]# pairable on
   ```
   
   On your Android device, search for Bluetooth devices and pair with your computer.

3. **Setup RFCOMM:**
   ```bash
   sudo service bluetooth restart
   sdptool add --channel=1 SP
   sudo mknod -m 660 /dev/rfcomm0 c 216 0
   sudo chown $USER:$USER /dev/rfcomm0
   ```

4. **Start the emulator:**
   ```bash
   rfcomm watch /dev/rfcomm0 1 python3 -m elm -P /dev/rfcomm0 -l -s car
   ```

5. **Configure AndrOBD:**
   - Connection type: Bluetooth
   - Select your computer from the device list
   - Connect

**Note:** The `-l` option is important for Bluetooth as it handles newline characters correctly for mobile apps.

#### On Windows:

1. **Setup virtual Bluetooth COM port:**
   - Go to Settings → Bluetooth & other devices
   - More Bluetooth options → COM ports tab
   - Add → Incoming → OK
   - Note the COM port number (e.g., COM4)

2. **Pair your Android device:**
   - Make your PC discoverable
   - Pair from your Android device

3. **Start the emulator:**
   ```cmd
   python -m elm -p COM4 -l -s car
   ```

4. **Configure AndrOBD:**
   - Connection type: Bluetooth
   - Select your computer
   - Connect

## Available Scenarios

The emulator includes several pre-configured vehicle scenarios for testing:

### Default Scenario
```bash
python3 -m elm -s default -n 35000
```
Basic OBD-II PIDs for standard vehicles.

### Car Scenario (Toyota Auris Hybrid)
```bash
python3 -m elm -s car -n 35000
```
Comprehensive set of PIDs simulating a Toyota Auris Hybrid vehicle. **Recommended for testing.**

### MT05 Scenario
```bash
python3 -m elm -s mt05 -n 35000
```
Simulates a Delphi MT05 ECU (common in motorcycles and ATVs).

### Custom Scenarios
You can create custom scenarios or merge existing ones. See the main README for details on creating custom vehicle profiles.

## Testing Workflow

### 1. Start the Emulator
```bash
# WiFi interface on standard port
python3 -m elm -s car -n 35000

# Or use a custom port
python3 -m elm -s car -n 8080
```

### 2. Verify Connection

You can test the connection before connecting AndrOBD:

```bash
# Using telnet
telnet localhost 35000

# Try some commands:
ATZ          # Reset
ATI          # Get version
0100         # Supported PIDs
010C         # Engine RPM
010D         # Vehicle speed
```

### 3. Connect AndrOBD

Configure AndrOBD with your connection details and connect.

### 4. Monitor Emulator Activity

In the emulator console, you can:
- View all commands received from AndrOBD
- Check counters: `counters`
- Change log level: `loglevel debug`
- Test specific PIDs: `test 010C`
- Switch scenarios: `scenario mt05`

## Advanced Testing Features

### Simulating Dynamic Data

You can modify PID responses on the fly for testing edge cases:

```python
# Set vehicle speed to 100 km/h
emulator.answer['SPEED'] = '<header>7E8</header><size>03</size><subd>41 0D</subd><eval>"%.2X" % 100</eval><space /><writeln />'

# Set RPM to 3000
emulator.answer['RPM'] = '<header>7E8</header><size>04</size><subd>41 0C</subd><eval>"%.4X" % int(4 * 3000)</eval><space /><writeln />'

# Enable headers for testing
test ath1
test atsh7e0
```

### Simulating Connection Issues

```python
# Simulate intermittent connection
for i in range(10):
    emulator.scenario = "car" if i % 2 else "engineoff"
    print(emulator.scenario)
    time.sleep(10)

# Simulate slow responses
delay 2.0

# Simulate no data
emulator.answer['SPEED'] = '<writeln>NO DATA</writeln>'
```

### Testing Error Handling

```python
# Return specific error codes
emulator.answer['SPEED'] = '<writeln>BUS INIT:ERROR</writeln>'
emulator.answer['RPM'] = '<writeln>UNABLE TO CONNECT</writeln>'
```

## Batch Mode Testing

For automated testing, use batch mode:

```bash
#!/bin/bash
FILE=/tmp/elm$$
echo -e 'scenario car\nloglevel info' | python3 -m elm -n 35000 -b "${FILE}" &
EMUL_PID=$!

# Wait for emulator to start
sleep 2

# Run your automated tests here
# e.g., run AndrOBD tests via adb

# Cleanup
kill -INT "${EMUL_PID}"
rm "${FILE}"
```

## Troubleshooting

### AndrOBD Can't Connect (WiFi)

1. **Check firewall:**
   - Ensure port 35000 is open
   - Try temporarily disabling firewall

2. **Verify IP address:**
   - Use `ifconfig` (Linux/Mac) or `ipconfig` (Windows)
   - Make sure you're on the same network as your Android device

3. **Check emulator is running:**
   ```bash
   # Should see the port in use
   netstat -an | grep 35000
   ```

4. **Test with telnet first:**
   ```bash
   telnet <your-ip> 35000
   ```

### AndrOBD Can't Connect (Bluetooth)

1. **Ensure devices are paired:**
   - Check Bluetooth settings on both devices

2. **Check RFCOMM channel:**
   ```bash
   # Linux
   rfcomm
   ```

3. **Try with newline option:**
   - Add `-l` flag when starting emulator

4. **Check Bluetooth is not in use:**
   ```bash
   # Release if needed
   sudo rfcomm release 0
   ```

### Slow Response or Timeouts

1. **Reduce response delay:**
   ```python
   delay 0.1
   ```

2. **Enable fast mode:**
   ```bash
   python3 -m elm -s car -n 35000
   # Then in console:
   # test ate1  # Enable echo if needed
   ```

3. **Check network latency:**
   ```bash
   ping <your-computer-ip>
   ```

### No Data Returned

1. **Verify scenario is loaded:**
   ```python
   scenario car
   counters
   ```

2. **Check if PID is supported:**
   ```python
   test 0100  # Check supported PIDs
   ```

3. **Enable debug logging:**
   ```python
   loglevel debug
   ```

## Example Test Script

Here's a complete example for automated testing:

```python
#!/usr/bin/env python3
"""
Example script for automated AndrOBD testing
"""
from elm import Elm
import time

def main():
    # Start emulator with WiFi interface
    with Elm(net_port=35000) as emulator:
        print(f"Emulator started on port 35000")
        
        # Set scenario
        emulator.scenario = 'car'
        
        # Configure for testing
        emulator.counters['cmd_echo'] = True
        emulator.counters['cmd_linefeeds'] = True
        
        # Simulate dynamic data
        emulator.answer['SPEED'] = (
            '<exec>ECU_R_ADDR_E + " 03 41 0D " + '
            '"%.2X" % ((int(time.time()) % 200))</exec><writeln />'
        )
        
        print("Ready for AndrOBD connection...")
        print("Configure AndrOBD to connect to this device on port 35000")
        
        # Run for 5 minutes
        time.sleep(300)
        
        # Print statistics
        print("\nTest Statistics:")
        print(f"Total commands: {emulator.counters['commands']}")
        print(f"Scenario: {emulator.scenario}")

if __name__ == '__main__':
    main()
```

## Creating Custom Vehicle Profiles

To create a profile matching your specific test requirements:

1. **Use obd_dictionary to capture real vehicle data:**
   ```bash
   # If you have access to a real vehicle
   obd_dictionary -i /dev/ttyUSB0 -o my_vehicle.py -n my_vehicle
   ```

2. **Or create manually by editing obd_message.py**

3. **Merge with emulator:**
   ```python
   python3 -m elm
   merge my_vehicle
   scenario my_vehicle
   ```

## Integration with CI/CD

Example GitHub Actions workflow:

```yaml
name: Test AndrOBD with Emulator

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Install ELM327-emulator
        run: |
          pip install ELM327-emulator
      
      - name: Start emulator
        run: |
          python3 -m elm -s car -n 35000 -b /tmp/elm.log &
          sleep 2
      
      - name: Run AndrOBD tests
        run: |
          # Your test commands here
          curl http://localhost:35000 # or use your test framework
      
      - name: Stop emulator
        run: |
          pkill -INT -f "python3 -m elm"
```

## Resources

- **Main Documentation:** [README.md](README.md)
- **ELM327 Commands:** See README for full AT command reference
- **Python API:** For programmatic control, see README Python API section
- **AndrOBD:** https://github.com/fr3ts0n/AndrOBD
- **OBD-II PIDs:** https://en.wikipedia.org/wiki/OBD-II_PIDs

## Support

For issues or questions:
- GitHub Issues: https://github.com/Ircama/ELM327-emulator/issues
- Check existing documentation in README.md
- Review the plugin examples in `elm/plugins/`

## License

ELM327-emulator: CC BY-NC-SA 4.0

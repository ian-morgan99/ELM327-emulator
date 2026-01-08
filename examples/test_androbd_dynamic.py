#!/usr/bin/env python3
"""
Example Python script for automated AndrOBD testing with dynamic data simulation
"""

from elm import Elm
import time
import math

# Response format templates for dynamic values
SPEED_RESPONSE_TEMPLATE = (
    '<header>7E8</header><size>03</size><subd>41 0D</subd>'
    '<eval>"%.2X" % {value}</eval><space /><writeln />'
)

RPM_RESPONSE_TEMPLATE = (
    '<header>7E8</header><size>04</size><subd>41 0C</subd>'
    '<eval>"%.4X" % int(4 * {value})</eval><space /><writeln />'
)

ENGINE_LOAD_RESPONSE_TEMPLATE = (
    '<header>7E8</header><size>03</size><subd>41 04</subd>'
    '<eval>"%.2X" % int({value} * 2.55)</eval><space /><writeln />'
)

def simulate_driving():
    """Simulate a driving scenario with realistic changing values"""
    
    print("Starting ELM327 emulator for AndrOBD testing...")
    print("This will simulate a vehicle driving scenario with changing RPM and speed")
    print()
    
    with Elm(net_port=35000) as emulator:
        print("✓ Emulator started on port 35000")
        
        # Set the car scenario
        emulator.scenario = 'car'
        print(f"✓ Scenario set to: {emulator.scenario}")
        
        # Enable echo and linefeeds for better compatibility
        emulator.counters['cmd_echo'] = True
        emulator.counters['cmd_linefeeds'] = True
        print("✓ Echo and linefeeds enabled")
        
        print()
        print("=" * 60)
        print("READY FOR ANDROBD CONNECTION")
        print("=" * 60)
        print()
        print("AndrOBD Configuration:")
        print("  1. Connection type: Network (WiFi)")
        print("  2. IP Address: <your computer's IP>")
        print("  3. Port: 35000")
        print()
        print("The following values will change dynamically:")
        print("  - Vehicle Speed: 0-120 km/h (sine wave)")
        print("  - Engine RPM: 800-4000 rpm (sine wave)")
        print("  - Engine Load: 20-80%")
        print()
        print("Press Ctrl+C to stop")
        print("=" * 60)
        print()
        
        start_time = time.time()
        
        try:
            while True:
                elapsed = time.time() - start_time
                
                # Simulate realistic driving pattern using sine waves
                # Speed varies from 0 to 120 km/h over 60 second cycle
                speed = int(60 + 60 * math.sin(elapsed / 10))
                speed = max(0, min(255, speed))  # Clamp to valid range
                
                # RPM varies from 800 to 4000 over 45 second cycle
                rpm = int(2400 + 1600 * math.sin(elapsed / 7))
                rpm = max(0, min(16383, rpm))  # Clamp to valid range
                
                # Engine load varies from 20% to 80%
                load = int(50 + 30 * math.sin(elapsed / 12))
                load = max(0, min(255, load))
                
                # Update the emulator with dynamic values
                emulator.answer['SPEED'] = SPEED_RESPONSE_TEMPLATE.format(value=speed)
                
                emulator.answer['RPM'] = RPM_RESPONSE_TEMPLATE.format(value=rpm)
                
                emulator.answer['ENGINE_LOAD'] = ENGINE_LOAD_RESPONSE_TEMPLATE.format(value=load)
                
                # Print status every 5 seconds
                if int(elapsed) % 5 == 0 and elapsed - int(elapsed) < 0.1:
                    total_commands = emulator.counters.get('commands', 0)
                    print(f"[{int(elapsed):4d}s] "
                          f"Speed: {speed:3d} km/h | "
                          f"RPM: {rpm:4d} | "
                          f"Load: {load:2d}% | "
                          f"Commands: {total_commands:5d}")
                
                time.sleep(0.1)  # Update 10 times per second
                
        except KeyboardInterrupt:
            print()
            print()
            print("=" * 60)
            print("STOPPING EMULATOR")
            print("=" * 60)
            print()
            print("Test Statistics:")
            print(f"  Total runtime: {int(time.time() - start_time)} seconds")
            print(f"  Total commands processed: {emulator.counters.get('commands', 0)}")
            print(f"  Scenario: {emulator.scenario}")
            print()
            print("Emulator stopped successfully")

if __name__ == '__main__':
    simulate_driving()

#!/usr/bin/env python3
"""
Simple test script to verify AndrOBD connectivity
This script starts the emulator and waits for connections
"""

from elm import Elm
import time
import socket

def get_local_ip():
    """Get the local IP address"""
    try:
        # Create a socket to find local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Unable to determine IP"

def main():
    port = 35000
    ip = get_local_ip()
    
    print()
    print("=" * 70)
    print("  ELM327-emulator - AndrOBD Test Harness")
    print("=" * 70)
    print()
    print(f"Starting emulator on port {port}...")
    print()
    
    with Elm(net_port=port) as emulator:
        # Set scenario to car (Toyota Auris Hybrid simulation)
        emulator.scenario = 'car'
        
        print("✓ Emulator is running")
        print(f"✓ Scenario: {emulator.scenario}")
        print(f"✓ Network interface: {ip}:{port}")
        print()
        print("=" * 70)
        print("  Configure AndrOBD to connect:")
        print("=" * 70)
        print()
        print("  Connection Type:  Network (WiFi)")
        print(f"  IP Address:       {ip}")
        print(f"  Port:             {port}")
        print()
        print("=" * 70)
        print()
        print("Emulator is ready. Waiting for connections...")
        print("(Press Ctrl+C to stop)")
        print()
        
        try:
            # Monitor activity
            last_commands = 0
            while True:
                time.sleep(5)
                
                current_commands = emulator.counters.get('commands', 0)
                if current_commands != last_commands:
                    print(f"[Active] Commands processed: {current_commands}")
                    last_commands = current_commands
                    
        except KeyboardInterrupt:
            print()
            print()
            print("Stopping emulator...")
            print()
            print("Statistics:")
            print(f"  Total commands: {emulator.counters.get('commands', 0)}")
            print()
            print("Done!")

if __name__ == '__main__':
    main()

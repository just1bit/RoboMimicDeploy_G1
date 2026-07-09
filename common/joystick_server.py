#!/usr/bin/env python3
"""
DualSense HID Joystick Server
Reads raw HID input reports from DualSense PS5 controller and writes
parsed state to a temp file for consumption by the mjpython MuJoCo process.

Runs under NORMAL Python (NOT mjpython), so no thread conflicts.
Uses hidapi to bypass both SDL2 and Apple Game Controller Framework.

DualSense USB HID Input Report (Report ID 0x01):
  Byte 0:  Report ID (0x01)
  Byte 1:  Left Stick X  (0-255, center ~128)
  Byte 2:  Left Stick Y  (0-255, center ~128)
  Byte 3:  Right Stick X (0-255, center ~128)
  Byte 4:  Right Stick Y (0-255, center ~128)
  Byte 5:  L2 analog     (0-255)
  Byte 6:  R2 analog     (0-255)
  Byte 7:  Sequence number (ignored)
  Byte 8:  bits 0-3 = D-pad (0=N,1=NE,2=E,3=SE,4=S,5=SW,6=W,7=NW,8/15=center)
           bits 4-7 = Square(4)/Cross(5)/Circle(6)/Triangle(7)
  Byte 9:  bit 0 = L1, bit 1 = R1, bit 2 = L2 btn, bit 3 = R2 btn
           bit 4 = Share, bit 5 = Options, bit 6 = L3, bit 7 = R3
  Byte 10: bit 0 = PS, bit 1 = Touchpad, bit 2 = Mute
"""

import sys
import os
import json
import time
import signal
import tempfile
import atexit
import traceback

try:
    import hid
except ImportError:
    print("ERROR: hidapi not installed. Run: pip install hidapi", file=sys.stderr)
    sys.exit(1)

# --- Constants ---
VID = 0x054C
PID = 0x0CE6

STATE_FILE = "/tmp/dualsense_state.json"
STOP_FILE = "/tmp/dualsense_stop"

# --- Button bit mapping (DualSense HID → JoystickButton enum) ---
# JoystickButton values:
#   A=0(Cross), B=1(Circle), X=2(Square), Y=3(Triangle)
#   L1=4, R1=5, SELECT=6, START=7, L3=8, R3=9, HOME=10
#   UP=11, DOWN=12, LEFT=13, RIGHT=14

# Face buttons: byte 8, bits 4-7
FACE_BUTTON_MAP = {
    2: 4,  # Square (bit 4) → X=2? No wait...
}
# Actually let me map from (byte, bit) to JoystickButton enum:
BUTTON_MAP = {
    # Face buttons: byte 8 bits 4-7
    (8, 4): 2,   # Square □ → X=2 (JoystickButton.X)
    (8, 5): 0,   # Cross  × → A=0 (JoystickButton.A)
    (8, 6): 1,   # Circle ○ → B=1 (JoystickButton.B)
    (8, 7): 3,   # Triangle △ → Y=3 (JoystickButton.Y)
    # Shoulder/utility: byte 9 bits 0-7
    (9, 0): 4,   # L1 → L1=4
    (9, 1): 5,   # R1 → R1=5
    (9, 4): 6,   # Share → SELECT=6
    (9, 5): 7,   # Options → START=7
    (9, 6): 8,   # L3 → L3=8
    (9, 7): 9,   # R3 → R3=9
    # System: byte 10 bits 0-2
    (10, 0): 10,  # PS button → HOME=10
}

# Total button count (matches JoystickButton enum: 0-14 = 15 buttons)
BUTTON_COUNT = 15

# --- Axis mapping ---
# Axis index → HID byte and normalization
# Standard gamepad axis layout:
#   0: Left X, 1: Left Y, 2: Right X, 3: Right Y, 4: L2, 5: R2
AXIS_MAP = {
    0: (1, False),   # Left Stick X → byte 1, no inversion
    1: (2, False),   # Left Stick Y → byte 2 (deploy_mujoco negates this, HID raw: 0=up)
    2: (3, False),   # Right Stick X → byte 3, no inversion
    3: (4, True),    # Right Stick Y → byte 4, inverted
    4: (5, False),   # L2 analog → byte 5 (0-255 → 0.0-1.0)
    5: (6, False),   # R2 analog → byte 6 (0-255 → 0.0-1.0)
}
AXIS_COUNT = 6

# D-pad hat direction mapping (byte 8, bits 0-3)
# 0=N, 1=NE, 2=E, 3=SE, 4=S, 5=SW, 6=W, 7=NW, 8/15=center
DPAD_HAT_MAP = {
    0: (0, 1),    # N  → UP
    1: (1, 1),    # NE → UP+RIGHT
    2: (1, 0),    # E  → RIGHT
    3: (1, -1),   # SE → RIGHT+DOWN
    4: (0, -1),   # S  → DOWN
    5: (-1, -1),  # SW → LEFT+DOWN
    6: (-1, 0),   # W  → LEFT
    7: (-1, 1),   # NW → LEFT+UP
    8: (0, 0),    # center
    15: (0, 0),   # center (alternative)
}


def normalize_axis(raw_val, invert=False, is_trigger=False):
    """Normalize axis value from 0-255 range to -1.0..1.0 or 0.0..1.0."""
    if is_trigger:
        return max(0.0, min(1.0, raw_val / 255.0))
    else:
        # Convert 0-255 to -1.0..1.0 (center at ~127.5)
        val = (raw_val - 127.5) / 127.5
        val = max(-1.0, min(1.0, val))
        if invert:
            val = -val
        return val


def parse_report(data):
    """Parse a raw HID input report into button states, axis values, and hat direction."""
    if len(data) < 11:
        return None

    # Parse button states
    button_states = [False] * BUTTON_COUNT

    for (byte_idx, bit), btn_id in BUTTON_MAP.items():
        if byte_idx < len(data):
            button_states[btn_id] = bool(data[byte_idx] & (1 << bit))

    # Parse D-pad as both hat value and individual button presses
    dpad_val = data[8] & 0x0F if len(data) > 8 else 8
    hat = DPAD_HAT_MAP.get(dpad_val, (0, 0))

    # D-pad buttons (UP=11, DOWN=12, LEFT=13, RIGHT=14)
    if hat[1] == 1:
        button_states[11] = True  # UP
    if hat[1] == -1:
        button_states[12] = True  # DOWN
    if hat[0] == -1:
        button_states[13] = True  # LEFT
    if hat[0] == 1:
        button_states[14] = True  # RIGHT

    # Parse axis values
    axis_states = [0.0] * AXIS_COUNT
    for axis_idx, (byte_idx, invert) in AXIS_MAP.items():
        if byte_idx < len(data):
            is_trig = axis_idx >= 4
            axis_states[axis_idx] = normalize_axis(data[byte_idx], invert, is_trig)

    return {
        "buttons": button_states,
        "axes": axis_states,
        "hat": list(hat),
        "button_count": BUTTON_COUNT,
        "axis_count": AXIS_COUNT,
        "hat_count": 1,
    }


def write_state(state):
    """Atomically write state to temp file."""
    try:
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, 'w') as f:
            json.dump(state, f)
        os.rename(tmp_path, STATE_FILE)
    except Exception as e:
        print(f"[DualSense Server] Write error: {e}", flush=True)


def find_dualense():
    """Find DualSense HID device path (USB interface 3 or Bluetooth)."""
    devices = hid.enumerate(VID, PID)
    for d in devices:
        # USB: interface_number == 3
        if d.get('interface_number') == 3:
            return d['path']
    # Bluetooth: interface_number is -1, bus_type == 2
    for d in devices:
        if d.get('bus_type') == 2:
            return d['path']
    # Fallback to first device
    if devices:
        return devices[0]['path']
    return None


def cleanup():
    """Clean up temp files."""
    for f in [STATE_FILE, STATE_FILE + ".tmp", STOP_FILE]:
        try:
            os.unlink(f)
        except OSError:
            pass


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    # Remove any stale stop file from previous runs
    try:
        os.unlink(STOP_FILE)
    except OSError:
        pass

    # Write initial empty state
    empty_state = {
        "buttons": [False] * BUTTON_COUNT,
        "axes": [0.0] * AXIS_COUNT,
        "hat": [0, 0],
        "button_count": BUTTON_COUNT,
        "axis_count": AXIS_COUNT,
        "hat_count": 1,
        "connected": False,
    }
    write_state(empty_state)

    device = None
    last_ok = False

    print(f"[DualSense Server] Started. PID={os.getpid()}", flush=True)
    print(f"[DualSense Server] State file: {STATE_FILE}", flush=True)
    print(f"[DualSense Server] Searching for DualSense...", flush=True)

    try:
        while True:
            # Check for stop signal
            if os.path.exists(STOP_FILE):
                print("[DualSense Server] Stop signal received. Exiting.", flush=True)
                break

            # Try to connect/reconnect
            if device is None:
                path = find_dualense()
                if path is None:
                    if last_ok:
                        print("[DualSense Server] Controller disconnected. Waiting...", flush=True)
                        last_ok = False
                    empty_state["connected"] = False
                    write_state(empty_state)
                    time.sleep(1.0)
                    continue

                try:
                    device = hid.device()
                    device.open_path(path)
                    device.set_nonblocking(True)
                    print(f"[DualSense Server] Connected! path={path!r}", flush=True)
                except Exception as e:
                    print(f"[DualSense Server] Failed to open: {e}", flush=True)
                    device = None
                    time.sleep(1.0)
                    continue

            # Read HID report
            try:
                data = device.read(64, timeout_ms=100)
            except Exception:
                print("[DualSense Server] Read error. Reconnecting...", flush=True)
                try:
                    device.close()
                except Exception:
                    pass
                device = None
                time.sleep(0.5)
                continue

            if data is None or len(data) < 11:
                # No data available (non-blocking timeout)
                continue

            if not last_ok:
                print("[DualSense Server] Receiving data from controller.", flush=True)
                last_ok = True

            state = parse_report(bytes(data))
            if state is not None:
                state["connected"] = True
                write_state(state)

    except KeyboardInterrupt:
        print("\n[DualSense Server] Interrupted.", flush=True)
    except Exception:
        traceback.print_exc()
    finally:
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        cleanup()
        print("[DualSense Server] Stopped.", flush=True)


if __name__ == "__main__":
    main()

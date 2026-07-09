"""
Joystick client for MuJoCo simulation on macOS with DualSense PS5 controller.

This module replaces the original pygame-based joystick with a file-based
IPC approach that bypasses both SDL2 thread conflicts (mjpython puts Python
on a background thread) and Apple Game Controller Framework button remapping.

Architecture:
  joystick_server.py (runs under NORMAL python, reads raw HID via hidapi)
       │
       │  writes state to /tmp/dualsense_state.json (atomic)
       ▼
  joystick.py (this module, runs under mjpython, reads the file)

API is identical to the original pygame-based JoyStick class.
"""

import json
import os
import subprocess
import sys
import time
import signal
import atexit

from enum import IntEnum, unique

# --- State file path (must match joystick_server.py) ---
STATE_FILE = "/tmp/dualsense_state.json"
STOP_FILE = "/tmp/dualsense_stop"

# Path to normal Python (not mjpython). Must be the conda env python
# so that hidapi is available.
_NORMAL_PYTHON = "/opt/homebrew/Caskroom/miniconda/base/envs/robomimic/bin/python"


@unique
class JoystickButton(IntEnum):
    """Standard PlayStation/Xbox Layout"""
    A = 0       # PS: Cross(×), Xbox: A
    B = 1       # PS: Circle(○), Xbox: B
    X = 2       # PS: Square(□), Xbox: X
    Y = 3       # PS: Triangle(△), Xbox: Y
    L1 = 4      # Left Bumper (L1 on PS)
    R1 = 5      # Right Bumper (R1 on PS)
    SELECT = 6  # Select/Share button
    START = 7   # Start/Options button
    L3 = 8      # Left Stick Press
    R3 = 9      # Right Stick Press
    HOME = 10   # PS: PS Button, Xbox: Xbox Button
    UP = 11     # D-pad Up
    DOWN = 12   # D-pad Down
    LEFT = 13   # D-pad Left
    RIGHT = 14  # D-pad Right


class JoyStick:
    """Joystick interface that reads DualSense state from a file-based server.

    The server process (joystick_server.py) reads raw HID reports and
    writes parsed state to a JSON file. This client reads that file.

    Usage (identical to original pygame-based version):
        joystick = JoyStick()
        while running:
            joystick.update()
            if joystick.is_button_pressed(JoystickButton.START):
                ...
    """

    def __init__(self):
        self._server_proc = None
        self._button_count = 15
        self._axis_count = 6

        # Current state
        self._button_states = [False] * self._button_count
        self._button_pressed = [False] * self._button_count
        self._button_released = [False] * self._button_count
        self._axis_states = [0.0] * self._axis_count
        self._hat_states = [(0, 0)]
        self._connected = False

        # Track previous button states for edge detection
        self._prev_buttons = [False] * self._button_count

        # Clean up any stale stop file
        try:
            os.unlink(STOP_FILE)
        except OSError:
            pass

        # Start the HID server process
        self._start_server()

        # Register cleanup
        atexit.register(self._cleanup)

    def _start_server(self):
        """Start the joystick server subprocess using normal Python."""
        server_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "joystick_server.py"
        )

        try:
            self._server_proc = subprocess.Popen(
                [_NORMAL_PYTHON, server_script],
                stdout=None,       # inherit — server logs show in terminal
                stderr=None,
                start_new_session=True,
            )
            print(f"[JoyStick] Started server (PID={self._server_proc.pid})", flush=True)
        except Exception as e:
            print(f"[JoyStick] WARNING: Failed to start server: {e}", flush=True)
            print("[JoyStick] Controller input will not work.", flush=True)

        # Wait for server to produce first state
        waited = 0
        while waited < 50:  # 5 second timeout
            if os.path.exists(STATE_FILE):
                try:
                    with open(STATE_FILE, 'r') as f:
                        data = json.load(f)
                    if data.get("connected", False):
                        print(f"[JoyStick] Controller connected!", flush=True)
                        break
                except (json.JSONDecodeError, IOError):
                    pass
            time.sleep(0.1)
            waited += 1

        if waited >= 50:
            print("[JoyStick] WARNING: Controller not detected. "
                  "Is DualSense connected via USB?", flush=True)

    def _cleanup(self):
        """Stop the server process and clean up."""
        # Signal server to stop
        try:
            with open(STOP_FILE, 'w') as f:
                f.write("stop")
        except IOError:
            pass

        # Wait for server to exit
        if self._server_proc is not None:
            try:
                self._server_proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                try:
                    self._server_proc.kill()
                    self._server_proc.wait(timeout=1.0)
                except Exception:
                    pass

        # Remove temp files
        for f in [STATE_FILE, STATE_FILE + ".tmp", STOP_FILE]:
            try:
                os.unlink(f)
            except OSError:
                pass

    def _read_state(self):
        """Read the current state from the server's output file."""
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return None

    def update(self):
        """Read latest controller state from server and detect edges."""
        state = self._read_state()

        if state is None:
            if not hasattr(self, '_no_file_warned'):
                self._no_file_warned = True
                print(f"[JoyStick] Waiting for state file: {STATE_FILE}", flush=True)
            return

        self._connected = state.get("connected", False)
        buttons = state.get("buttons", [])

        if not buttons:
            return

        # Ensure arrays are the right size
        n_buttons = min(len(buttons), self._button_count)
        n_axes = min(len(state.get("axes", [])), self._axis_count)

        # Reset edge detection
        self._button_released = [False] * self._button_count

        # Detect button press edges
        for i in range(n_buttons):
            current = bool(buttons[i])
            self._button_pressed[i] = current

            # Rising edge = just pressed
            if current and not self._prev_buttons[i]:
                pass  # We don't track "pressed" edge separately from "is pressed"

            # Falling edge = just released
            if not current and self._prev_buttons[i]:
                self._button_released[i] = True

            self._button_states[i] = current
            self._prev_buttons[i] = current

        # Read axis values
        axes = state.get("axes", [])
        for i in range(n_axes):
            self._axis_states[i] = float(axes[i])

        # Read hat
        hat = state.get("hat", [0, 0])
        self._hat_states[0] = (int(hat[0]), int(hat[1])) if len(hat) >= 2 else (0, 0)

    def is_button_pressed(self, button_id):
        """Return True if the button is currently held down."""
        if 0 <= button_id < self._button_count:
            return self._button_states[button_id]
        return False

    def is_button_released(self, button_id):
        """Return True on the frame the button is released (falling edge)."""
        if 0 <= button_id < self._button_count:
            return self._button_released[button_id]
        return False

    def get_axis_value(self, axis_id):
        """Return current axis value (-1.0 to 1.0 for sticks, 0.0 to 1.0 for triggers)."""
        if 0 <= axis_id < self._axis_count:
            return self._axis_states[axis_id]
        return 0.0

    def get_hat_direction(self, hat_id=0):
        """Return D-pad direction as (x, y) tuple: (-1/0/1, -1/0/1)."""
        if 0 <= hat_id < len(self._hat_states):
            return self._hat_states[hat_id]
        return (0, 0)

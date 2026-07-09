"""
Joystick interface for MuJoCo simulation.

Supports two backends, selected automatically by platform:

  - **pygame** (Linux/Windows): Works with Xbox, PlayStation, and most
    standard gamepads via SDL2.
  - **hidapi** (macOS + mjpython): Reads DualSense PS5 raw HID reports via a
    subprocess. Necessary because mjpython puts Python on a background
    thread (conflicting with pygame's Cocoa main-thread requirement) and
    because Apple's Game Controller Framework remaps DualSense buttons.

Both backends expose the identical JoyStick / JoystickButton API.
"""

import os
import sys
from enum import IntEnum, unique


# ---------------------------------------------------------------------------
# Shared enum
# ---------------------------------------------------------------------------

@unique
class JoystickButton(IntEnum):
    """Standard PlayStation / Xbox Layout (same physical positions)."""
    A = 0       # PS: Cross(×),   Xbox: A
    B = 1       # PS: Circle(○),  Xbox: B
    X = 2       # PS: Square(□),  Xbox: X
    Y = 3       # PS: Triangle(△), Xbox: Y
    L1 = 4
    R1 = 5
    SELECT = 6   # PS: Share,      Xbox: View
    START = 7    # PS: Options,    Xbox: Menu
    L3 = 8       # Left stick press
    R3 = 9       # Right stick press
    HOME = 10
    UP = 11
    DOWN = 12
    LEFT = 13
    RIGHT = 14


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def _is_macos_mjpython():
    """True when running under mjpython on macOS (needs hidapi backend)."""
    return sys.platform == 'darwin' and 'MJPYTHON_BIN' in os.environ


# ---------------------------------------------------------------------------
# pygame backend (Linux / Windows / standard Python on macOS)
# ---------------------------------------------------------------------------

class _JoyStickPygame:
    """pygame-based joystick – works with Xbox, PS, and most gamepads."""

    def __init__(self):
        import pygame
        self._pygame = pygame
        pygame.init()
        pygame.joystick.init()

        if pygame.joystick.get_count() == 0:
            raise RuntimeError("No joystick connected!")

        self.joystick = pygame.joystick.Joystick(0)
        self.joystick.init()

        self.button_count = self.joystick.get_numbuttons()
        self.button_states = [False] * self.button_count
        self.button_pressed = [False] * self.button_count
        self.button_released = [False] * self.button_count

        self.axis_count = self.joystick.get_numaxes()
        self.axis_states = [0.0] * self.axis_count

        self.hat_count = self.joystick.get_numhats()
        self.hat_states = [(0, 0)] * self.hat_count

    def update(self):
        self._pygame.event.pump()
        self.button_released = [False] * self.button_count
        for i in range(self.button_count):
            current = self.joystick.get_button(i) == 1
            if self.button_states[i] and not current:
                self.button_released[i] = True
            self.button_states[i] = current
        for i in range(self.axis_count):
            self.axis_states[i] = self.joystick.get_axis(i)
        for i in range(self.hat_count):
            self.hat_states[i] = self.joystick.get_hat(i)

    def is_button_pressed(self, button_id):
        if 0 <= button_id < self.button_count:
            return self.button_states[button_id]
        return False

    def is_button_released(self, button_id):
        if 0 <= button_id < self.button_count:
            return self.button_released[button_id]
        return False

    def get_axis_value(self, axis_id):
        if 0 <= axis_id < self.axis_count:
            return self.axis_states[axis_id]
        return 0.0

    def get_hat_direction(self, hat_id=0):
        if 0 <= hat_id < self.hat_count:
            return self.hat_states[hat_id]
        return (0, 0)


# ---------------------------------------------------------------------------
# hidapi backend (macOS + mjpython, DualSense PS5 only)
# ---------------------------------------------------------------------------

class _JoyStickHID:
    """DualSense HID joystick — bypasses macOS GCD & mjpython thread issues.

    Spawns ``joystick_server.py`` as a subprocess (normal Python, not
    mjpython) to read raw DualSense HID reports.  State is communicated
    through an atomic JSON file at ``/tmp/dualsense_state.json``.
    """

    STATE_FILE = "/tmp/dualsense_state.json"
    STOP_FILE  = "/tmp/dualsense_stop"
    # Must use the conda env python so hidapi is importable.
    _NORMAL_PYTHON = "/opt/homebrew/Caskroom/miniconda/base/envs/robomimic/bin/python"

    def __init__(self):
        import json, subprocess, time, atexit

        self._server_proc = None
        self._button_count = 15
        self._axis_count = 6

        self._button_states   = [False] * self._button_count
        self._button_pressed  = [False] * self._button_count
        self._button_released = [False] * self._button_count
        self._axis_states = [0.0] * self._axis_count
        self._hat_states  = [(0, 0)]
        self._prev_buttons = [False] * self._button_count

        # Clean stale stop file
        try:
            os.unlink(self.STOP_FILE)
        except OSError:
            pass

        # Launch server
        server_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "joystick_server.py")
        try:
            self._server_proc = subprocess.Popen(
                [self._NORMAL_PYTHON, server_script],
                stdout=None, stderr=None,
                start_new_session=True,
            )
            print(f"[JoyStick] HID server started (PID={self._server_proc.pid})",
                  flush=True)
        except Exception as e:
            print(f"[JoyStick] WARNING: cannot start HID server: {e}", flush=True)
            return

        # Wait for server to connect to DualSense
        for _ in range(50):
            try:
                with open(self.STATE_FILE, 'r') as f:
                    if json.load(f).get("connected"):
                        print("[JoyStick] Controller connected!", flush=True)
                        break
            except (json.JSONDecodeError, IOError, FileNotFoundError):
                pass
            time.sleep(0.1)
        else:
            print("[JoyStick] WARNING: Controller not detected. "
                  "Is DualSense connected via USB?", flush=True)

        atexit.register(self._cleanup)

    # -- cleanup ----------------------------------------------------------

    def _cleanup(self):
        try:
            with open(self.STOP_FILE, 'w') as f:
                f.write("stop")
        except IOError:
            pass
        if self._server_proc is not None:
            try:
                self._server_proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._server_proc.kill()
                except Exception:
                    pass
        for f in (self.STATE_FILE, self.STATE_FILE + ".tmp", self.STOP_FILE):
            try:
                os.unlink(f)
            except OSError:
                pass

    # -- state I/O --------------------------------------------------------

    def _read_state(self):
        try:
            import json
            with open(self.STATE_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return None

    def update(self):
        state = self._read_state()
        if state is None:
            return
        buttons = state.get("buttons", [])
        if not buttons:
            return

        n_buttons = min(len(buttons), self._button_count)
        n_axes    = min(len(state.get("axes", [])), self._axis_count)

        self._button_released = [False] * self._button_count

        for i in range(n_buttons):
            cur = bool(buttons[i])
            if not cur and self._prev_buttons[i]:
                self._button_released[i] = True
            self._button_states[i] = cur
            self._prev_buttons[i] = cur

        axes = state.get("axes", [])
        for i in range(n_axes):
            self._axis_states[i] = float(axes[i])

        hat = state.get("hat", [0, 0])
        if len(hat) >= 2:
            self._hat_states[0] = (int(hat[0]), int(hat[1]))

    # -- public API (mirrors _JoyStickPygame) ----------------------------

    def is_button_pressed(self, button_id):
        if 0 <= button_id < self._button_count:
            return self._button_states[button_id]
        return False

    def is_button_released(self, button_id):
        if 0 <= button_id < self._button_count:
            return self._button_released[button_id]
        return False

    def get_axis_value(self, axis_id):
        if 0 <= axis_id < self._axis_count:
            return self._axis_states[axis_id]
        return 0.0

    def get_hat_direction(self, hat_id=0):
        if 0 <= hat_id < len(self._hat_states):
            return self._hat_states[hat_id]
        return (0, 0)


# ---------------------------------------------------------------------------
# Public class – auto-selects backend
# ---------------------------------------------------------------------------

JoyStick = _JoyStickHID if _is_macos_mjpython() else _JoyStickPygame

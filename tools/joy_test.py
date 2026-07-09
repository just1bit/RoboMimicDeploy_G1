#!/usr/bin/env python3
"""
DualSense Button Mapping Test
Connect DualSense via USB, run this script, press buttons.
Shows in real-time which buttons the code detects.
Ctrl+C to exit.
"""
import sys, os, time
import hid

VID, PID = 0x054C, 0x0CE6

# Label for each bit we care about
BUTTON_LABELS = {
    # Byte 8, bits 4-7 (face buttons)
    (8, 4): "Square □  (X=2)",
    (8, 5): "Cross ×   (A=0)",
    (8, 6): "Circle ○  (B=1)",
    (8, 7): "Triangle △(Y=3)",
    # Byte 9, bits 0-7 (shoulders / utility)
    (9, 0): "L1        (4)",
    (9, 1): "R1        (5)",
    (9, 2): "L2 btn",
    (9, 3): "R2 btn",
    (9, 4): "Share     (SEL=6)",
    (9, 5): "Options   (START=7)",
    (9, 6): "L3        (8)",
    (9, 7): "R3        (9)",
    # Byte 10, bits 0-2 (system)
    (10, 0): "PS Button (HOME=10)",
    (10, 1): "Touchpad",
    (10, 2): "Mute",
}

# D-pad labels (byte 8, bits 0-3)
DPAD_LABELS = {0: "N", 1: "NE", 2: "E", 3: "SE", 4: "S", 5: "SW", 6: "W", 7: "NW", 8: "CENTER", 15: "CENTER"}

AXIS_LABELS = {
    1: "Left X", 2: "Left Y", 3: "Right X", 4: "Right Y", 5: "L2 Trig", 6: "R2 Trig",
}


def open_dualsense():
    for d in hid.enumerate(VID, PID):
        if d.get('interface_number') == 3:
            dev = hid.device()
            dev.open_path(d['path'])
            dev.set_nonblocking(True)
            return dev
    for d in hid.enumerate(VID, PID):
        if d.get('bus_type') == 2:
            dev = hid.device()
            dev.open_path(d['path'])
            dev.set_nonblocking(True)
            return dev
    for d in hid.enumerate(VID, PID):
        dev = hid.device()
        dev.open_path(d['path'])
        dev.set_nonblocking(True)
        return dev
    return None


def main():
    dev = open_dualsense()
    if dev is None:
        print("DualSense not found! Connect via USB.")
        sys.exit(1)

    print("Press buttons on DualSense. Ctrl+C to exit.\n")

    try:
        while True:
            data = bytes(dev.read(64, timeout_ms=50))
            if len(data) < 11:
                continue

            # --- Find pressed buttons ---
            pressed = []
            for (byte_idx, bit), label in BUTTON_LABELS.items():
                if data[byte_idx] & (1 << bit):
                    pressed.append(label)

            # --- D-pad ---
            dpad = data[8] & 0x0F
            dpad_label = DPAD_LABELS.get(dpad, f"UNKNOWN({dpad})")

            # --- Axes ---
            axes = {}
            for byte_idx, name in AXIS_LABELS.items():
                raw = data[byte_idx]
                if byte_idx in (5, 6):  # L2/R2 triggers: 0-255 → 0.0-1.0
                    val = raw / 255.0
                    if val > 0.05:
                        axes[name] = f"{val:.2f}"
                else:  # sticks: 0-255 → -1.0..1.0 (center ~128)
                    val = (raw - 128) / 128.0
                    if abs(val) > 0.15:
                        axes[name] = f"{val:+.2f}"

            # --- Display ---
            os.system('clear')
            print("=== DualSense Button Test ===\n")
            print("BUTTONS:", ", ".join(pressed) if pressed else "(none)")
            print(f"D-PAD:   {dpad_label}")
            print("AXES:   ", ", ".join(f"{k}={v}" for k, v in axes.items()) if axes else "(centered)")
            print("\nCtrl+C to exit.")

            time.sleep(0.02)

    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        dev.close()


if __name__ == "__main__":
    main()

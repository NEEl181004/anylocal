"""
Input Handler for AnyLocal
Injects mouse clicks, cursor movement, scrolling, and keyboard keystrokes natively into Windows.
"""

import ctypes
import platform
import time

user32 = ctypes.windll.user32 if platform.system() == "Windows" else None

# Windows Mouse Event Flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

# Windows Key Event Flags
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Virtual-Key Codes
VK_MAP = {
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "pause": 0x13, "caps_lock": 0x14, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "page_up": 0x21, "page_down": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "print_screen": 0x2C, "insert": 0x2D, "delete": 0x2E,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C, "meta": 0x5B,
    "num_0": 0x60, "num_1": 0x61, "num_2": 0x62, "num_3": 0x63, "num_4": 0x64,
    "num_5": 0x65, "num_6": 0x66, "num_7": 0x67, "num_8": 0x68, "num_9": 0x69,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}

def attach_to_desktop():
    if user32:
        try:
            hDesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hDesk:
                user32.SetThreadDesktop(hDesk)
                user32.CloseDesktop(hDesk)
        except Exception:
            pass

class InputHandler:
    def __init__(self, screen_width=1920, screen_height=1080):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.enabled = True

    def set_resolution(self, width, height):
        self.screen_width = width
        self.screen_height = height

    def handle_mouse(self, data):
        """
        Processes mouse events from remote client:
        data: {'action': 'move'|'down'|'up'|'wheel'|'dblclick', 'x': norm_x, 'y': norm_y, 'btn': 'left'|'right'|'middle', 'delta': delta}
        Coordinates are normalized (0.0 to 1.0)
        """
        if not self.enabled or not user32:
            return

        attach_to_desktop()

        action = data.get("action")
        nx = max(0.0, min(1.0, data.get("x", 0.0)))
        ny = max(0.0, min(1.0, data.get("y", 0.0)))
        px = int(nx * self.screen_width)
        py = int(ny * self.screen_height)
        btn = data.get("btn", "left")

        # Move mouse position
        user32.SetCursorPos(px, py)

        if action == "move":
            return

        elif action == "down":
            if btn == "left":
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, px, py, 0, 0)
            elif btn == "right":
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, px, py, 0, 0)
            elif btn == "middle":
                user32.mouse_event(MOUSEEVENTF_MIDDLEDOWN, px, py, 0, 0)

        elif action == "up":
            if btn == "left":
                user32.mouse_event(MOUSEEVENTF_LEFTUP, px, py, 0, 0)
            elif btn == "right":
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, px, py, 0, 0)
            elif btn == "middle":
                user32.mouse_event(MOUSEEVENTF_MIDDLEUP, px, py, 0, 0)

        elif action == "dblclick":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, px, py, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, px, py, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, px, py, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, px, py, 0, 0)

        elif action == "wheel":
            delta = data.get("delta", 0)
            wheel_amount = int(delta * 120)
            user32.mouse_event(MOUSEEVENTF_WHEEL, px, py, wheel_amount, 0)

        elif action == "rel_move":
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            dx = int(data.get("dx", 0))
            dy = int(data.get("dy", 0))
            new_x = max(0, min(self.screen_width - 1, pt.x + dx))
            new_y = max(0, min(self.screen_height - 1, pt.y + dy))
            user32.SetCursorPos(new_x, new_y)

        elif action == "click":
            if btn == "left":
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, px, py, 0, 0)
                time.sleep(0.04)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, px, py, 0, 0)
            elif btn == "right":
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, px, py, 0, 0)
                time.sleep(0.04)
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, px, py, 0, 0)

    def handle_text(self, text):
        """
        Types a full string of text via unicode events (perfect for mobile keyboards).
        """
        if not self.enabled or not user32 or not text:
            return

        attach_to_desktop()
        for char in str(text):
            if char == "\n":
                user32.keybd_event(0x0D, 0, 0, 0)
                time.sleep(0.01)
                user32.keybd_event(0x0D, 0, KEYEVENTF_KEYUP, 0)
            elif char == "\t":
                user32.keybd_event(0x09, 0, 0, 0)
                time.sleep(0.01)
                user32.keybd_event(0x09, 0, KEYEVENTF_KEYUP, 0)
            else:
                code_point = ord(char)
                user32.keybd_event(0, code_point, KEYEVENTF_UNICODE, 0)
                time.sleep(0.005)
                user32.keybd_event(0, code_point, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

    def handle_keyboard(self, data):
        """
        Processes keyboard events:
        data: {'action': 'down'|'up', 'key': 'a', 'code': 65}
        """
        if not self.enabled or not user32:
            return

        attach_to_desktop()

        action = data.get("action")
        key_name = str(data.get("key", "")).lower()
        vk = VK_MAP.get(key_name)

        if vk is not None:
            if action == "down":
                user32.keybd_event(vk, 0, 0, 0)
            elif action == "up":
                user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        else:
            # Fallback for unicode character typing
            raw_char = data.get("key", "")
            if len(raw_char) == 1 and action == "down":
                code_unit = ord(raw_char)
                user32.keybd_event(0, code_unit, KEYEVENTF_UNICODE, 0)
                user32.keybd_event(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0)

    def trigger_shortcut(self, shortcut_name):
        """
        Triggers popular system shortcuts.
        """
        if not self.enabled or not user32:
            return

        attach_to_desktop()

        if shortcut_name in ("wake_unlock", "wake_display", "sign_in"):
            from .power_manager import dismiss_lock_screen
            dismiss_lock_screen()

        elif shortcut_name == "win":
            user32.keybd_event(0x5B, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(0x5B, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "alt_tab":
            user32.keybd_event(0x12, 0, 0, 0) # Alt down
            user32.keybd_event(0x09, 0, 0, 0) # Tab down
            time.sleep(0.05)
            user32.keybd_event(0x09, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "show_desktop": # Win + D
            user32.keybd_event(0x5B, 0, 0, 0)
            user32.keybd_event(0x44, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(0x44, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x5B, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "task_manager": # Ctrl + Shift + Esc
            user32.keybd_event(0x11, 0, 0, 0) # Ctrl
            user32.keybd_event(0x10, 0, 0, 0) # Shift
            user32.keybd_event(0x1B, 0, 0, 0) # Esc
            time.sleep(0.05)
            user32.keybd_event(0x1B, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x10, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "copy": # Ctrl + C
            user32.keybd_event(0x11, 0, 0, 0)
            user32.keybd_event(0x43, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(0x43, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "paste": # Ctrl + V
            user32.keybd_event(0x11, 0, 0, 0)
            user32.keybd_event(0x56, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(0x56, 0, KEYEVENTF_KEYUP, 0)
            user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "enter":
            user32.keybd_event(0x0D, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(0x0D, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "backspace":
            user32.keybd_event(0x08, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(0x08, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "esc":
            user32.keybd_event(0x1B, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(0x1B, 0, KEYEVENTF_KEYUP, 0)

        elif shortcut_name == "tab":
            user32.keybd_event(0x09, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(0x09, 0, KEYEVENTF_KEYUP, 0)


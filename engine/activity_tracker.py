"""
Local User Activity Tracker for AnyLocal
Detects physical mouse and keyboard usage by a local user on Windows.
Distinguishes real physical hardware events from remote injected events.
"""

import ctypes
from ctypes import wintypes
import platform
import threading
import time

user32 = ctypes.windll.user32 if platform.system() == "Windows" else None
kernel32 = ctypes.windll.kernel32 if platform.system() == "Windows" else None

WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13
LLMHF_INJECTED = 0x0001
LLKHF_INJECTED = 0x0010

HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]

class ActivityTracker:
    def __init__(self, idle_threshold=5.0):
        self.idle_threshold = idle_threshold
        self.enabled = True
        self.last_physical_activity = 0.0  # epoch time

        self.h_mouse = None
        self.h_kbd = None
        self.thread = None
        self.is_running = False

        self._c_mouse_proc = None
        self._c_kbd_proc = None

        if platform.system() == "Windows" and user32:
            self._start_hook_thread()

    def _mouse_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            try:
                struct = MSLLHOOKSTRUCT.from_address(lParam)
                # LLMHF_INJECTED is 0 only when a real physical human moved or clicked the mouse!
                if not (struct.flags & LLMHF_INJECTED):
                    self.last_physical_activity = time.time()
            except Exception:
                pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _kbd_proc(self, nCode, wParam, lParam):
        if nCode >= 0:
            try:
                struct = KBDLLHOOKSTRUCT.from_address(lParam)
                # LLKHF_INJECTED is 0 only when a real physical human pressed a key!
                if not (struct.flags & LLKHF_INJECTED):
                    self.last_physical_activity = time.time()
            except Exception:
                pass
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run_hook_loop(self):
        self._c_mouse_proc = HOOKPROC(self._mouse_proc)
        self._c_kbd_proc = HOOKPROC(self._kbd_proc)

        self.h_mouse = user32.SetWindowsHookExW(WH_MOUSE_LL, self._c_mouse_proc, None, 0)
        self.h_kbd = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._c_kbd_proc, None, 0)

        msg = wintypes.MSG()
        while self.is_running:
            # Message pump required for WH_MOUSE_LL and WH_KEYBOARD_LL
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.02)

        if self.h_mouse:
            user32.UnhookWindowsHookEx(self.h_mouse)
            self.h_mouse = None
        if self.h_kbd:
            user32.UnhookWindowsHookEx(self.h_kbd)
            self.h_kbd = None

    def _start_hook_thread(self):
        self.is_running = True
        self.thread = threading.Thread(target=self._run_hook_loop, daemon=True)
        self.thread.start()

    def is_local_user_active(self):
        """
        Returns True if the local physical user on Desktop 1 has used mouse or keyboard
        within the idle_threshold (e.g. 5 seconds).
        """
        if not self.enabled:
            return False
        return (time.time() - self.last_physical_activity) < self.idle_threshold

    def get_idle_seconds(self):
        return max(0.0, time.time() - self.last_physical_activity)

    def stop(self):
        self.is_running = False

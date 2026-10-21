"""
Power and Display Management for AnyLocal
Keeps Windows awake for remote access, wakes monitors from standby, and handles lock screen dismissal.
"""

import ctypes
import platform
import subprocess
import time

user32 = ctypes.windll.user32 if platform.system() == "Windows" else None
kernel32 = ctypes.windll.kernel32 if platform.system() == "Windows" else None

# Windows Thread Execution State Flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040

# Window Message Constants
HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
MONITOR_ON = -1

def keep_system_awake(enable=True):
    """
    Prevents Windows from entering S3 sleep or standby while AnyLocal is running.
    The physical monitor can turn off to save energy, but the CPU, Tailscale,
    and network sockets stay 100% active and reachable 24/7.
    """
    if not kernel32:
        return False
    try:
        if enable:
            kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
        else:
            kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        return True
    except Exception as e:
        print(f"[PowerManager] keep_system_awake error: {e}")
        return False

def wake_display_and_monitor():
    """
    Powers on the display monitor if it has turned off from idle timeout,
    and updates execution state to wake the Windows graphics subsystem.
    """
    if not user32 or not kernel32:
        return False
    try:
        # 1. Instruct Windows to power the display
        kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)

        # 2. Broadcast monitor power-on command
        user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, MONITOR_ON)

        # 3. Simulate a tiny mouse movement to wake hardware display drivers
        user32.mouse_event(0x0001, 1, 0, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(0x0001, -1, 0, 0, 0)
        return True
    except Exception as e:
        print(f"[PowerManager] wake_display error: {e}")
        return False

def dismiss_lock_screen():
    """
    Wakes display and sends a Space / Enter keystroke to dismiss the Windows lock
    screen wallpaper and bring up the user password/PIN input field.
    """
    if not user32:
        return False
    try:
        wake_display_and_monitor()
        time.sleep(0.08)

        # Attach to the active desktop (handles lock screen desktop)
        hDesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hDesk:
            user32.SetThreadDesktop(hDesk)
            user32.CloseDesktop(hDesk)

        # Tap Space key (VK_SPACE = 0x20)
        user32.keybd_event(0x20, 0, 0, 0) # Key Down
        time.sleep(0.05)
        user32.keybd_event(0x20, 0, 0x0002, 0) # Key Up
        return True
    except Exception as e:
        print(f"[PowerManager] dismiss_lock_screen error: {e}")
        return False

def configure_windows_never_sleep():
    """
    Configures Windows power plan to never sleep when plugged in (AC power).
    Runs via powercfg utility.
    """
    if platform.system() != "Windows":
        return False
    try:
        flags = 0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        subprocess.run(["powercfg", "/change", "standby-timeout-ac", "0"], creationflags=flags, timeout=5)
        return True
    except Exception as e:
        print(f"[PowerManager] powercfg error: {e}")
        return False

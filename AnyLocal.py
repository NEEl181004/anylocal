"""
AnyLocal Remote Desktop
A self-hosted, ultra-low-latency remote desktop tool for local Wi-Fi and cross-branch shop computers.
"""

import json
import os
import random
import string
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from PIL import Image, ImageTk
import qrcode

from engine.network_utils import get_network_interfaces, is_port_available, free_port
from engine.server import HostServer
from engine.client_viewer import ClientViewerWindow
from engine.power_manager import (
    keep_system_awake,
    configure_windows_never_sleep,
    wake_display_and_monitor,
    dismiss_lock_screen
)

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".anylocal_config.json")

APP_VERSION = "2.4.0"

def check_and_apply_auto_update():
    """
    Checks Render Cloud Server for updates silently in the background.
    If a new AnyLocal version is deployed to Render, it automatically downloads and updates
    the local .exe without the user having to delete and reinstall!
    """
    import urllib.request
    import subprocess

    time.sleep(4.0)
    server_urls = [
        "https://anylocal.onrender.com",
        "http://127.0.0.1:8765"
    ]
    for base_url in server_urls:
        try:
            req = urllib.request.Request(
                f"{base_url}/api/version",
                headers={"User-Agent": f"AnyLocal/{APP_VERSION}"}
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    remote_ver = data.get("version", APP_VERSION)
                    if remote_ver != APP_VERSION and getattr(sys, 'frozen', False):
                        download_url = data.get("download_url", "/download/AnyLocal.exe")
                        if not download_url.startswith("http"):
                            download_url = f"{base_url.rstrip('/')}/{download_url.lstrip('/')}"
                        
                        current_exe = sys.executable
                        exe_dir = os.path.dirname(current_exe)
                        temp_update_exe = os.path.join(exe_dir, "AnyLocal_update.exe")
                        
                        urllib.request.urlretrieve(download_url, temp_update_exe)
                        
                        bat_path = os.path.join(exe_dir, "_apply_update.bat")
                        bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
taskkill /f /im AnyLocal.exe >nul 2>&1
move /y "{temp_update_exe}" "{current_exe}" >nul
start "" "{current_exe}"
del "%~f0"
"""
                        with open(bat_path, "w") as bf:
                            bf.write(bat_content)
                        
                        flags = 0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                        subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=flags)
                        sys.exit(0)
                        return
                    return
        except Exception:
            continue

def generate_random_pin(length=6):
    return "".join(random.choices(string.digits, k=length))

def load_saved_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "unattended_enabled": False,
        "unattended_pin": "",
        "saved_branches": [
            {"name": "Branch 1 - Main Counter", "ip": "100.64.1.1", "port": 8765},
            {"name": "Branch 2 - Billing PC", "ip": "100.64.2.1", "port": 8765}
        ]
    }

def save_config(config_data):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def create_windows_shortcut(target_exe, shortcut_path, working_dir="", description="AnyLocal Remote Desktop"):
    """Creates a Windows .lnk shortcut using WScript.Shell without external libraries."""
    try:
        import subprocess
        ps_target = target_exe.replace("'", "''")
        ps_shortcut = shortcut_path.replace("'", "''")
        ps_dir = (working_dir or os.path.dirname(target_exe)).replace("'", "''")
        ps_cmd = (
            f"$w = New-Object -ComObject WScript.Shell; "
            f"$s = $w.CreateShortcut('{ps_shortcut}'); "
            f"$s.TargetPath = '{ps_target}'; "
            f"$s.WorkingDirectory = '{ps_dir}'; "
            f"$s.Description = '{description}'; "
            f"$s.Save()"
        )
        flags = 0x08000000 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd], creationflags=flags, timeout=8)
        return True
    except Exception as e:
        print(f"Failed to create shortcut: {e}")
        return False

def get_current_executable_path():
    """Returns the true executable path whether running as .exe or script."""
    import sys
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(__file__)

def get_startup_shortcut_path():
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        startup_dir = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        if os.path.isdir(startup_dir):
            return os.path.join(startup_dir, "AnyLocal.lnk")
    return None

def get_desktop_shortcut_path():
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    if desktop and os.path.isdir(desktop):
        return os.path.join(desktop, "AnyLocal.lnk")
    return None

def auto_ensure_desktop_shortcut():
    """Automatically ensures a Desktop shortcut exists on first run of the .exe."""
    try:
        import sys
        if getattr(sys, 'frozen', False):
            lnk = get_desktop_shortcut_path()
            if lnk and not os.path.exists(lnk):
                exe = get_current_executable_path()
                create_windows_shortcut(exe, lnk, os.path.dirname(exe))
    except Exception:
        pass

def create_tray_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(4, 4), (60, 60)], radius=16, fill=(2, 132, 199, 255))
    draw.rounded_rectangle([(14, 14), (50, 44)], radius=6, fill=(15, 23, 42, 255), outline=(255, 255, 255, 200), width=2)
    draw.rectangle([(28, 44), (36, 50)], fill=(203, 213, 225, 255))
    draw.rounded_rectangle([(22, 50), (42, 54)], radius=2, fill=(203, 213, 225, 255))
    return img

def ensure_autostart_registry():
    """Configures AnyLocal to automatically start with Windows on boot."""
    try:
        import winreg
        import sys
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.abspath(__file__)
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "AnyLocal", 0, winreg.REG_SZ, f'"{exe_path}" --background')
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Autostart registry error: {e}")
        return False

def ensure_startup_folder_shortcut():
    try:
        import sys
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
            startup_lnk = get_startup_shortcut_path()
            if startup_lnk and not os.path.exists(startup_lnk):
                create_windows_shortcut(exe_path, startup_lnk, os.path.dirname(exe_path), description="AnyLocal Auto-Start")
    except Exception:
        pass

def ensure_single_instance():
    """Terminates stale background AnyLocal processes so port 8765 is not blocked by ghosts."""
    try:
        import psutil
        current_pid = os.getpid()
        parent_pid = os.getppid() if hasattr(os, 'getppid') else None
        for proc in psutil.process_iter(['pid', 'name', 'ppid']):
            try:
                name = (proc.info['name'] or '').lower()
                pid = proc.info['pid']
                ppid = proc.info.get('ppid')
                if pid not in (current_pid, parent_pid) and ppid != current_pid and ('anylocal' in name):
                    print(f"[AnyLocal] Closing stale instance PID {pid}")
                    proc.kill()
            except Exception:
                pass
    except Exception as e:
        print(f"[AnyLocal] Single instance check error: {e}")

class AnyLocalApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AnyLocal - Cross-Branch & Local Remote Desktop")
        self.root.geometry("820x680")
        self.root.minsize(780, 620)
        self.root.configure(bg="#0f172a")

        # Guarantee single active host instance and clean port 8765
        ensure_single_instance()
        free_port(8765)

        self.config = load_saved_config()
        self.current_pin = generate_random_pin()
        self.server = None
        self.active_client_viewer = None
        self.reverse_session_info = None

        # Network details
        self.net_info = get_network_interfaces()

        self._apply_styles()
        self._build_ui()
        self._start_host_server()

        # Auto-ensure Desktop shortcut on launch
        auto_ensure_desktop_shortcut()

        # Auto-ensure Windows boot autostart
        ensure_autostart_registry()
        ensure_startup_folder_shortcut()

        # System tray icon (Keeps app hosting in background when [X] closed)
        self.tray_icon = None
        self._setup_system_tray()

        # Session timer updater
        self.session_timer_running = False

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Configure Notebook Tab Styling
        style.configure("TNotebook", background="#0f172a", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#1e293b",
            foreground="#94a3b8",
            padding=[20, 10],
            font=("Segoe UI", 10, "bold"),
            borderwidth=0
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#0284c7"), ("active", "#334155")],
            foreground=[("selected", "#ffffff"), ("active", "#f8fafc")]
        )

        style.configure("TFrame", background="#0f172a")

    def _build_ui(self):
        # Header Banner
        header = tk.Frame(self.root, bg="#1e293b", height=70)
        header.pack(fill=tk.X, side=tk.TOP)

        title_box = tk.Frame(header, bg="#1e293b")
        title_box.pack(side=tk.LEFT, padx=20, pady=12)

        lbl_app_name = tk.Label(
            title_box,
            text="⚡ AnyLocal",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 16, "bold")
        )
        lbl_app_name.pack(side=tk.LEFT)

        lbl_tag = tk.Label(
            title_box,
            text="PRO",
            bg="#0369a1",
            fg="#ffffff",
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=1
        )
        lbl_tag.pack(side=tk.LEFT, padx=8)

        lbl_subtitle = tk.Label(
            header,
            text=f"Host: {self.net_info['hostname']}",
            bg="#1e293b",
            fg="#94a3b8",
            font=("Segoe UI", 9)
        )
        lbl_subtitle.pack(side=tk.RIGHT, padx=14, pady=18)

        btn_updates = tk.Button(
            header,
            text="🔄 Updates & Server",
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
            command=self._show_update_modal
        )
        btn_updates.pack(side=tk.RIGHT, padx=6, pady=16)

        # Tab Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        # Tab 1: Share This PC (Host)
        self.tab_host = tk.Frame(self.notebook, bg="#0f172a")
        self.notebook.add(self.tab_host, text="  🖥️ Share This PC (Host)  ")
        self._build_host_tab()

        # Tab 2: Connect to Remote PC (Client)
        self.tab_client = tk.Frame(self.notebook, bg="#0f172a")
        self.notebook.add(self.tab_client, text="  🚀 Connect to Remote PC (Client)  ")
        self._build_client_tab()

        # Tab 3: Tailscale & Cross-Branch Guide
        self.tab_guide = tk.Frame(self.notebook, bg="#0f172a")
        self.notebook.add(self.tab_guide, text="  🌐 Cross-Branch Setup  ")
        self._build_guide_tab()

    def _build_host_tab(self):
        # Card 1: Connection Addresses
        card_addr = tk.Frame(self.tab_host, bg="#1e293b", padx=20, pady=16, relief=tk.FLAT)
        card_addr.pack(fill=tk.X, padx=10, pady=8)

        lbl_c1_title = tk.Label(
            card_addr,
            text="THIS COMPUTER'S NETWORK ADDRESSES",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 9, "bold")
        )
        lbl_c1_title.pack(anchor="w", pady=(0, 8))

        # Show Tailscale IP (for cross-branch)
        ts_ips = self.net_info.get("tailscale", [])
        if ts_ips:
            ts_frame = tk.Frame(card_addr, bg="#1e293b")
            ts_frame.pack(fill=tk.X, pady=4)
            tk.Label(
                ts_frame,
                text="🌐 Tailscale (Cross-Branch):",
                bg="#1e293b",
                fg="#f1f5f9",
                font=("Segoe UI", 10, "bold"),
                width=24,
                anchor="w"
            ).pack(side=tk.LEFT)
            self.lbl_ts_ip = tk.Label(
                ts_frame,
                text=f"{ts_ips[0]}:8765",
                bg="#0f172a",
                fg="#4ade80",
                font=("Consolas", 11, "bold"),
                padx=10,
                pady=4
            )
            self.lbl_ts_ip.pack(side=tk.LEFT, padx=6)
            tk.Button(
                ts_frame,
                text="Copy",
                bg="#334155",
                fg="#f1f5f9",
                relief=tk.FLAT,
                font=("Segoe UI", 9),
                command=lambda: self._copy_to_clipboard(f"{ts_ips[0]}")
            ).pack(side=tk.LEFT, padx=6)
        else:
            ts_frame = tk.Frame(card_addr, bg="#1e293b")
            ts_frame.pack(fill=tk.X, pady=4)
            tk.Label(
                ts_frame,
                text="🌐 Tailscale (Cross-Branch):",
                bg="#1e293b",
                fg="#94a3b8",
                font=("Segoe UI", 10),
                width=24,
                anchor="w"
            ).pack(side=tk.LEFT)
            tk.Label(
                ts_frame,
                text="Tailscale not detected (See 'Cross-Branch Setup' tab)",
                bg="#1e293b",
                fg="#facc15",
                font=("Segoe UI", 9, "italic")
            ).pack(side=tk.LEFT)

        # Show Local Wi-Fi IP
        loc_ips = self.net_info.get("local", [])
        loc_ip_str = loc_ips[0] if loc_ips else "127.0.0.1"
        loc_frame = tk.Frame(card_addr, bg="#1e293b")
        loc_frame.pack(fill=tk.X, pady=4)
        tk.Label(
            loc_frame,
            text="📶 Local Wi-Fi / LAN:",
            bg="#1e293b",
            fg="#f1f5f9",
            font=("Segoe UI", 10, "bold"),
            width=24,
            anchor="w"
        ).pack(side=tk.LEFT)
        self.lbl_loc_ip = tk.Label(
            loc_frame,
            text=f"{loc_ip_str}:8765",
            bg="#0f172a",
            fg="#38bdf8",
            font=("Consolas", 11, "bold"),
            padx=10,
            pady=4
        )
        self.lbl_loc_ip.pack(side=tk.LEFT, padx=6)
        tk.Button(
            loc_frame,
            text="Copy",
            bg="#334155",
            fg="#f1f5f9",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=lambda: self._copy_to_clipboard(f"{loc_ip_str}")
        ).pack(side=tk.LEFT, padx=6)

        # Card 2: Security & Verification PIN
        card_pin = tk.Frame(self.tab_host, bg="#1e293b", padx=20, pady=16)
        card_pin.pack(fill=tk.X, padx=10, pady=8)

        lbl_c2_title = tk.Label(
            card_pin,
            text="SECURITY & ACCESS VERIFICATION CODE",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 9, "bold")
        )
        lbl_c2_title.pack(anchor="w", pady=(0, 8))

        pin_display_frame = tk.Frame(card_pin, bg="#1e293b")
        pin_display_frame.pack(fill=tk.X, pady=6)

        tk.Label(
            pin_display_frame,
            text="One-Time Session PIN:",
            bg="#1e293b",
            fg="#cbd5e1",
            font=("Segoe UI", 10)
        ).pack(side=tk.LEFT, padx=(0, 10))

        self.lbl_pin_box = tk.Label(
            pin_display_frame,
            text=f"  {self.current_pin}  ",
            bg="#0284c7",
            fg="#ffffff",
            font=("Consolas", 16, "bold"),
            padx=12,
            pady=4
        )
        self.lbl_pin_box.pack(side=tk.LEFT, padx=6)

        tk.Button(
            pin_display_frame,
            text="🔄 New PIN",
            bg="#334155",
            fg="#ffffff",
            relief=tk.FLAT,
            command=self._generate_new_pin
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            pin_display_frame,
            text="📋 Copy PIN",
            bg="#334155",
            fg="#ffffff",
            relief=tk.FLAT,
            command=lambda: self._copy_to_clipboard(self.current_pin)
        ).pack(side=tk.LEFT, padx=6)

        # Unattended Access Mode (Permanent Password)
        unattend_frame = tk.Frame(card_pin, bg="#0f172a", padx=12, pady=10)
        unattend_frame.pack(fill=tk.X, pady=(12, 0))

        self.unattend_var = tk.BooleanVar(value=self.config.get("unattended_enabled", False))
        chk_unattend = tk.Checkbutton(
            unattend_frame,
            text="Enable Unattended Access (Permanent Password for Branch Shop PC)",
            variable=self.unattend_var,
            bg="#0f172a",
            fg="#f8fafc",
            selectcolor="#0f172a",
            activebackground="#0f172a",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9, "bold"),
            command=self._on_unattended_toggle
        )
        chk_unattend.pack(anchor="w")

        self.pwd_entry_frame = tk.Frame(unattend_frame, bg="#0f172a")
        self.pwd_entry_frame.pack(fill=tk.X, pady=(6, 0))

        tk.Label(
            self.pwd_entry_frame,
            text="Permanent Password:",
            bg="#0f172a",
            fg="#94a3b8",
            font=("Segoe UI", 9)
        ).pack(side=tk.LEFT, padx=(20, 8))

        self.entry_unattend_pwd = tk.Entry(
            self.pwd_entry_frame,
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 10),
            show="*",
            width=20
        )
        self.entry_unattend_pwd.insert(0, self.config.get("unattended_pin", ""))
        self.entry_unattend_pwd.pack(side=tk.LEFT, padx=4)

        self.pwd_visible = False
        self.btn_toggle_eye = tk.Button(
            self.pwd_entry_frame,
            text="👁️",
            bg="#334155",
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=4,
            command=self._toggle_pwd_visibility
        )
        self.btn_toggle_eye.pack(side=tk.LEFT, padx=2)

        self.entry_unattend_pwd.bind("<KeyRelease>", self._on_unattended_pwd_changed)
        self.entry_unattend_pwd.bind("<FocusOut>", self._on_unattended_pwd_changed)

        btn_save_pwd = tk.Button(
            self.pwd_entry_frame,
            text="Save Password",
            bg="#0284c7",
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 8, "bold"),
            command=self._save_unattended_password
        )
        btn_save_pwd.pack(side=tk.LEFT, padx=6)

        # Card 3: Live Session Status & Controls
        card_session = tk.Frame(self.tab_host, bg="#1e293b", padx=20, pady=16)
        card_session.pack(fill=tk.X, padx=10, pady=8)

        lbl_c3_title = tk.Label(
            card_session,
            text="ACTIVE CONNECTION & PERMISSIONS",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 9, "bold")
        )
        lbl_c3_title.pack(anchor="w", pady=(0, 8))

        sess_info_frame = tk.Frame(card_session, bg="#1e293b")
        sess_info_frame.pack(fill=tk.X, pady=4)

        self.lbl_client_status = tk.Label(
            sess_info_frame,
            text="⚪ No remote user connected (Waiting for connection...)",
            bg="#1e293b",
            fg="#94a3b8",
            font=("Segoe UI", 10)
        )
        self.lbl_client_status.pack(side=tk.LEFT)

        self.btn_disconnect_client = tk.Button(
            sess_info_frame,
            text="🛑 Disconnect User",
            bg="#ef4444",
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            state=tk.DISABLED,
            command=self._disconnect_remote_client
        )
        self.btn_disconnect_client.pack(side=tk.RIGHT, padx=(4, 0))

        self.btn_two_way_control = tk.Button(
            sess_info_frame,
            text="🔄 Control Remote PC (Two-Way)",
            bg="#059669",
            fg="white",
            activebackground="#047857",
            activeforeground="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            state=tk.DISABLED,
            command=self._start_two_way_control_from_host
        )
        self.btn_two_way_control.pack(side=tk.RIGHT, padx=4)

        # Permissions & Web Viewer link
        perm_frame = tk.Frame(card_session, bg="#1e293b")
        perm_frame.pack(fill=tk.X, pady=(10, 0))

        self.perm_control_var = tk.BooleanVar(value=True)
        chk_perm = tk.Checkbutton(
            perm_frame,
            text="Allow Full Mouse, Keyboard & App Access",
            variable=self.perm_control_var,
            bg="#1e293b",
            fg="#e2e8f0",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9),
            command=self._on_permission_toggle
        )
        chk_perm.pack(side=tk.LEFT)

        btn_open_browser = tk.Button(
            perm_frame,
            text="🌐 Open Web Viewer",
            bg="#334155",
            fg="#38bdf8",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=lambda: webbrowser.open(f"http://localhost:8765")
        )
        btn_open_browser.pack(side=tk.RIGHT, padx=4)

        btn_connect_phone = tk.Button(
            perm_frame,
            text="📱 Connect Phone (QR Code)",
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            command=self._show_mobile_qr_modal
        )
        btn_connect_phone.pack(side=tk.RIGHT, padx=4)

        # Extra Protection Controls: Mobile Access Toggle & Session Lock
        options_frame = tk.Frame(card_session, bg="#1e293b")
        options_frame.pack(fill=tk.X, pady=(6, 0))

        self.perm_mobile_var = tk.BooleanVar(value=True)
        chk_mobile = tk.Checkbutton(
            options_frame,
            text="📱 Allow Phone / Mobile Access",
            variable=self.perm_mobile_var,
            bg="#1e293b",
            fg="#e2e8f0",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9),
            command=self._on_mobile_perm_toggle
        )
        chk_mobile.pack(side=tk.LEFT, padx=(0, 16))

        self.perm_lock_var = tk.BooleanVar(value=True)
        chk_lock = tk.Checkbutton(
            options_frame,
            text="🔒 Exclusive Session Lock (Block 2nd device to prevent conflict)",
            variable=self.perm_lock_var,
            bg="#1e293b",
            fg="#e2e8f0",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9),
            command=self._on_lock_perm_toggle
        )
        chk_lock.pack(side=tk.LEFT)

        options_frame2 = tk.Frame(card_session, bg="#1e293b")
        options_frame2.pack(fill=tk.X, pady=(4, 0))

        self.perm_idle_var = tk.BooleanVar(value=True)
        chk_idle = tk.Checkbutton(
            options_frame2,
            text="👤 Local User Priority (Remote is View-Only while cashier/user operates this PC)",
            variable=self.perm_idle_var,
            bg="#1e293b",
            fg="#e2e8f0",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9),
            command=self._on_local_priority_toggle
        )
        chk_idle.pack(side=tk.LEFT)

        options_frame3 = tk.Frame(card_session, bg="#1e293b")
        options_frame3.pack(fill=tk.X, pady=(6, 0))

        startup_lnk = get_startup_shortcut_path()
        is_startup = bool(startup_lnk and os.path.exists(startup_lnk))
        self.start_on_boot_var = tk.BooleanVar(value=is_startup)
        chk_boot = tk.Checkbutton(
            options_frame3,
            text="🚀 Start with Windows (Auto-start in background on PC boot)",
            variable=self.start_on_boot_var,
            bg="#1e293b",
            fg="#e2e8f0",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9),
            command=self._on_startup_toggle
        )
        chk_boot.pack(side=tk.LEFT, padx=(0, 16))

        tk.Button(
            options_frame3,
            text="📌 Create Desktop Shortcut",
            bg="#334155",
            fg="#38bdf8",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            command=self._manual_create_desktop_shortcut
        ).pack(side=tk.LEFT)

        options_frame4 = tk.Frame(card_session, bg="#1e293b")
        options_frame4.pack(fill=tk.X, pady=(6, 0))

        self.stay_awake_var = tk.BooleanVar(value=True)
        chk_awake = tk.Checkbutton(
            options_frame4,
            text="⚡ Stay Awake 24/7 (Prevent PC Sleep & Keep Always Reachable)",
            variable=self.stay_awake_var,
            bg="#1e293b",
            fg="#e2e8f0",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            activeforeground="#38bdf8",
            font=("Segoe UI", 9),
            command=self._on_stay_awake_toggle
        )
        chk_awake.pack(side=tk.LEFT, padx=(0, 16))

        tk.Button(
            options_frame4,
            text="⚙️ Set Windows Sleep to 'Never'",
            bg="#334155",
            fg="#facc15",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            command=self._on_set_windows_never_sleep
        ).pack(side=tk.LEFT)

    def _build_client_tab(self):
        # Card 1: Connection Form
        card_conn = tk.Frame(self.tab_client, bg="#1e293b", padx=20, pady=20)
        card_conn.pack(fill=tk.X, padx=10, pady=8)

        lbl_c1_title = tk.Label(
            card_conn,
            text="CONNECT TO REMOTE BRANCH COMPUTER",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 9, "bold")
        )
        lbl_c1_title.pack(anchor="w", pady=(0, 14))

        # Remote IP / Host Input
        grid_frame = tk.Frame(card_conn, bg="#1e293b")
        grid_frame.pack(fill=tk.X)

        tk.Label(grid_frame, text="Remote IP / Tailscale IP:", bg="#1e293b", fg="#cbd5e1", font=("Segoe UI", 10), width=20, anchor="w").grid(row=0, column=0, pady=8, sticky="w")
        self.entry_remote_ip = tk.Entry(grid_frame, bg="#0f172a", fg="#ffffff", font=("Segoe UI", 11), width=26, insertbackground="white")
        self.entry_remote_ip.grid(row=0, column=1, pady=8, sticky="w")
        self.entry_remote_ip.insert(0, "127.0.0.1")

        tk.Label(grid_frame, text="Port:", bg="#1e293b", fg="#cbd5e1", font=("Segoe UI", 10), width=6, anchor="w").grid(row=0, column=2, padx=(12, 4), pady=8, sticky="w")
        self.entry_remote_port = tk.Entry(grid_frame, bg="#0f172a", fg="#ffffff", font=("Segoe UI", 11), width=8, insertbackground="white")
        self.entry_remote_port.grid(row=0, column=3, pady=8, sticky="w")
        self.entry_remote_port.insert(0, "8765")

        # Verification PIN Input
        tk.Label(grid_frame, text="Verification PIN / Password:", bg="#1e293b", fg="#cbd5e1", font=("Segoe UI", 10), width=20, anchor="w").grid(row=1, column=0, pady=8, sticky="w")
        self.entry_remote_pin = tk.Entry(grid_frame, bg="#0f172a", fg="#38bdf8", font=("Segoe UI", 11, "bold"), width=26, show="*", insertbackground="white")
        self.entry_remote_pin.grid(row=1, column=1, pady=8, sticky="w")

        # Show PIN Toggle
        self.show_pin_var = tk.BooleanVar(value=False)
        chk_show_pin = tk.Checkbutton(
            grid_frame,
            text="Show",
            variable=self.show_pin_var,
            bg="#1e293b",
            fg="#94a3b8",
            selectcolor="#1e293b",
            activebackground="#1e293b",
            font=("Segoe UI", 9),
            command=lambda: self.entry_remote_pin.config(show="" if self.show_pin_var.get() else "*")
        )
        chk_show_pin.grid(row=1, column=2, padx=6, pady=8, sticky="w")

        # Big Connect Button
        self.btn_connect = tk.Button(
            card_conn,
            text="🚀  CONNECT TO REMOTE PC",
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 12, "bold"),
            pady=10,
            command=self._start_client_connection
        )
        self.btn_connect.pack(fill=tk.X, pady=(16, 6))

        # Card 2: Saved Branch Presets
        card_branches = tk.Frame(self.tab_client, bg="#1e293b", padx=20, pady=16)
        card_branches.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        lbl_c2_title = tk.Label(
            card_branches,
            text="SAVED SHOP BRANCHES (1-CLICK QUICK CONNECT)",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 9, "bold")
        )
        lbl_c2_title.pack(anchor="w", pady=(0, 8))

        # Branch listbox
        list_frame = tk.Frame(card_branches, bg="#1e293b")
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox_branches = tk.Listbox(
            list_frame,
            bg="#0f172a",
            fg="#f1f5f9",
            selectbackground="#0284c7",
            selectforeground="#ffffff",
            font=("Segoe UI", 10),
            height=5,
            relief=tk.FLAT
        )
        self.listbox_branches.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox_branches.bind("<<ListboxSelect>>", self._on_branch_select)
        self.listbox_branches.bind("<Double-Button-1>", lambda e: self._start_client_connection())

        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.listbox_branches.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox_branches.config(yscrollcommand=scrollbar.set)

        # Branch action buttons
        branch_btn_frame = tk.Frame(card_branches, bg="#1e293b")
        branch_btn_frame.pack(fill=tk.X, pady=(10, 0))

        tk.Button(
            branch_btn_frame,
            text="➕ Save Current as Branch",
            bg="#334155",
            fg="#f1f5f9",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=self._save_current_as_branch
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            branch_btn_frame,
            text="🗑️ Remove Selected",
            bg="#334155",
            fg="#f87171",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=self._delete_selected_branch
        ).pack(side=tk.LEFT, padx=4)

        self._refresh_branches_listbox()

    def _build_guide_tab(self):
        guide_frame = tk.Frame(self.tab_guide, bg="#1e293b", padx=24, pady=20)
        guide_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        title = tk.Label(
            guide_frame,
            text="🌐 How to Connect Computers Across Different Shop Branches",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 12, "bold")
        )
        title.pack(anchor="w", pady=(0, 10))

        desc = (
            "Because your shop branches are on different Wi-Fi networks in different physical locations, "
            "you need a secure direct connection so they can talk to each other without paying for expensive cloud servers.\n\n"
            "We recommend Tailscale (100% Free, Encrypted, Zero-Configuration Peer-to-Peer Mesh):\n\n"
            "Step 1: Download & install Tailscale on each shop computer from https://tailscale.com\n"
            "Step 2: Sign in with the same account (e.g. your shop Google/Microsoft account) on all PCs.\n"
            "Step 3: Tailscale assigns each PC a permanent IP (e.g. 100.84.x.y) that never changes.\n"
            "Step 4: Open AnyLocal on both PCs! The Tailscale IP will appear automatically on the Host tab.\n"
            "Step 5: Type that 100.x.y.z IP and PIN into AnyLocal Client to connect with ultra-low latency!"
        )
        lbl_desc = tk.Label(
            guide_frame,
            text=desc,
            bg="#1e293b",
            fg="#cbd5e1",
            font=("Segoe UI", 10),
            justify=tk.LEFT,
            wraplength=720
        )
        lbl_desc.pack(anchor="w", pady=(0, 16))

        btn_open_tailscale = tk.Button(
            guide_frame,
            text="🌐 Download Tailscale (Official Website)",
            bg="#0284c7",
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            padx=12,
            pady=6,
            command=lambda: webbrowser.open("https://tailscale.com")
        )
        btn_open_tailscale.pack(anchor="w")

    def _start_host_server(self):
        unattend_pin = self.config.get("unattended_pin") if self.config.get("unattended_enabled") else None
        self.server = HostServer(port=8765, pin=self.current_pin, unattended_pin=unattend_pin)

        # Connect Server Callbacks to GUI
        self.server.on_client_connect = self._on_client_connected_callback
        self.server.on_client_disconnect = self._on_client_disconnected_callback
        self.server.on_reverse_connect_requested = self._handle_reverse_connect_request

        self.server.start()

    def _generate_new_pin(self):
        self.current_pin = generate_random_pin()
        self.lbl_pin_box.config(text=f"  {self.current_pin}  ")
        if self.server:
            self.server.set_pin(self.current_pin)

    def _toggle_pwd_visibility(self):
        self.pwd_visible = not getattr(self, 'pwd_visible', False)
        if self.pwd_visible:
            self.entry_unattend_pwd.config(show="")
            self.btn_toggle_eye.config(text="🙈")
        else:
            self.entry_unattend_pwd.config(show="*")
            self.btn_toggle_eye.config(text="👁️")

    def _on_unattended_pwd_changed(self, event=None):
        pwd = self.entry_unattend_pwd.get().strip()
        if self.unattend_var.get():
            self.config["unattended_pin"] = pwd
            save_config(self.config)
            if self.server:
                self.server.set_unattended_pin(pwd if pwd else None)

    def _on_unattended_toggle(self):
        enabled = self.unattend_var.get()
        pwd = self.entry_unattend_pwd.get().strip()
        self.config["unattended_enabled"] = enabled
        if enabled and pwd:
            self.config["unattended_pin"] = pwd
        save_config(self.config)
        if self.server:
            active_pwd = pwd if (enabled and pwd) else None
            self.server.set_unattended_pin(active_pwd)

    def _save_unattended_password(self):
        pwd = self.entry_unattend_pwd.get().strip()
        if not pwd:
            messagebox.showwarning("Empty Password", "Please enter a valid password.")
            return
        self.config["unattended_pin"] = pwd
        self.config["unattended_enabled"] = True
        self.unattend_var.set(True)
        save_config(self.config)
        if self.server:
            self.server.set_unattended_pin(pwd)
        messagebox.showinfo("Saved", f"Unattended permanent password saved successfully!\n\nPassword: {pwd}\nYou can now connect anytime using this password or the session PIN.")

    def _on_permission_toggle(self):
        allowed = self.perm_control_var.get()
        if self.server:
            self.server.set_control_allowed(allowed)

    def _on_mobile_perm_toggle(self):
        allowed = self.perm_mobile_var.get()
        if self.server:
            self.server.set_mobile_allowed(allowed)

    def _on_lock_perm_toggle(self):
        locked = self.perm_lock_var.get()
        if self.server:
            self.server.set_exclusive_lock(locked)

    def _on_local_priority_toggle(self):
        enabled = self.perm_idle_var.get()
        if self.server:
            self.server.set_local_priority(enabled)

    def _manual_create_desktop_shortcut(self):
        lnk = get_desktop_shortcut_path()
        if lnk:
            exe = get_current_executable_path()
            ok = create_windows_shortcut(exe, lnk, os.path.dirname(exe))
            if ok:
                messagebox.showinfo("Shortcut Created", f"Desktop shortcut created successfully!\n\nLocation: {lnk}")
            else:
                messagebox.showwarning("Shortcut Error", "Could not create desktop shortcut automatically.")

    def _on_startup_toggle(self):
        startup_lnk = get_startup_shortcut_path()
        if not startup_lnk:
            messagebox.showwarning("Error", "Could not locate Windows Startup folder.")
            return
        if self.start_on_boot_var.get():
            exe = get_current_executable_path()
            create_windows_shortcut(exe, startup_lnk, os.path.dirname(exe))
            messagebox.showinfo("Auto-Start Enabled", "AnyLocal will now automatically launch when this PC powers on.")
        else:
            if os.path.exists(startup_lnk):
                try:
                    os.remove(startup_lnk)
                except Exception:
                    pass
            messagebox.showinfo("Auto-Start Disabled", "AnyLocal removed from Windows Startup.")

    def _on_stay_awake_toggle(self):
        enabled = self.stay_awake_var.get()
        keep_system_awake(enabled)
        if enabled:
            messagebox.showinfo("24/7 Awake Enabled", "AnyLocal will prevent Windows from entering sleep/standby mode while running so remote devices can always connect.")
        else:
            messagebox.showinfo("Sleep Allowed", "AnyLocal has released the stay-awake lock.")

    def _on_set_windows_never_sleep(self):
        success = configure_windows_never_sleep()
        if success:
            messagebox.showinfo("Power Settings Updated", "Windows Standby/Sleep timer has been configured to 'Never' (timeout = 0) on AC power.")
        else:
            messagebox.showwarning("Notice", "Could not configure power settings automatically. Please check Windows Power & Sleep settings.")

    def _get_best_local_ip(self, remote_host):
        """Resolves local source IP that can reach remote_host (Tailscale, LAN, or localhost)."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((remote_host, 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            if self.net_info:
                return self.net_info[0]["ip"]
            return "127.0.0.1"

    def _launch_viewer(self, host, port, pin):
        """Launches ClientViewerWindow with reverse session credentials for AnyDesk-style Two-Way control."""
        if self.active_client_viewer:
            try:
                self.active_client_viewer.close()
            except Exception:
                pass

        self.btn_connect.config(state=tk.DISABLED, text="Connecting...")

        def on_close():
            self.btn_connect.config(state=tk.NORMAL, text="🚀  CONNECT TO REMOTE PC")
            self.active_client_viewer = None

        my_ip = self._get_best_local_ip(host)
        my_pin = self.config.get("unattended_pin") if (self.config.get("unattended_enabled") and self.config.get("unattended_pin")) else self.current_pin

        self.active_client_viewer = ClientViewerWindow(
            host=host,
            port=port,
            pin=pin,
            my_host_ip=my_ip,
            my_host_port=8765,
            my_host_pin=my_pin,
            on_close_callback=on_close
        )

    def _handle_reverse_connect_request(self, info):
        """Called when connected remote desktop clicks 'Switch Sides / Two-Way' in viewer."""
        target_host = info.get("host")
        target_port = info.get("port", 8765)
        target_pin = info.get("pin", "")
        device_name = info.get("device_name", "Remote PC")
        if not target_host or not target_pin:
            return

        def do_launch():
            print(f"[AnyLocal] Launching Two-Way session to {device_name} ({target_host}:{target_port})")
            self._launch_viewer(target_host, target_port, target_pin)
        self.root.after(0, do_launch)

    def _start_two_way_control_from_host(self):
        """Initiates Two-Way control directly from this host to the connected remote desktop."""
        if not self.reverse_session_info:
            messagebox.showinfo("Two-Way Info", "No reverse session information available from remote desktop.")
            return
        target_host = self.reverse_session_info.get("host")
        target_port = self.reverse_session_info.get("port", 8765)
        target_pin = self.reverse_session_info.get("pin", "")
        if not target_host or not target_pin:
            messagebox.showwarning("Two-Way Info", "Remote PC did not provide connection PIN for two-way control.")
            return
        self._launch_viewer(target_host, target_port, target_pin)

    def _on_client_connected_callback(self, client_ip, client_type="desktop", device_name="Remote Device", reverse_info=None):
        self.reverse_session_info = reverse_info
        def update():
            device_icon = "📱" if client_type == "mobile" else "🖥️"
            has_two_way = bool(client_type == "desktop" and reverse_info and reverse_info.get("pin"))
            two_way_badge = " [Two-Way Ready]" if has_two_way else ""
            self.lbl_client_status.config(
                text=f"🟢 {device_icon} {client_type.capitalize()} connected: {device_name} ({client_ip}){two_way_badge}",
                fg="#4ade80"
            )
            self.btn_disconnect_client.config(state=tk.NORMAL)
            if has_two_way:
                self.btn_two_way_control.config(state=tk.NORMAL)
            else:
                self.btn_two_way_control.config(state=tk.DISABLED)
        self.root.after(0, update)

    def _on_client_disconnected_callback(self):
        self.reverse_session_info = None
        def update():
            self.lbl_client_status.config(
                text="⚪ No remote user connected (Waiting for connection...)",
                fg="#94a3b8"
            )
            self.btn_disconnect_client.config(state=tk.DISABLED)
            self.btn_two_way_control.config(state=tk.DISABLED)
        self.root.after(0, update)

    def _disconnect_remote_client(self):
        if self.server:
            self.server.disconnect_client()

    def _copy_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("Copied", f"Copied to clipboard: {text}")

    def _start_client_connection(self):
        host = self.entry_remote_ip.get().strip()
        port_str = self.entry_remote_port.get().strip()
        pin = self.entry_remote_pin.get().strip()

        if not host:
            messagebox.showerror("Missing IP", "Please enter the remote computer's IP address.")
            return
        if not port_str.isdigit():
            messagebox.showerror("Invalid Port", "Please enter a valid numeric port (default: 8765).")
            return
        if not pin:
            messagebox.showerror("Missing PIN", "Please enter the verification PIN or unattended password.")
            return

        port = int(port_str)
        self._launch_viewer(host, port, pin)

    def _refresh_branches_listbox(self):
        self.listbox_branches.delete(0, tk.END)
        for b in self.config.get("saved_branches", []):
            self.listbox_branches.insert(tk.END, f"  🏬 {b['name']} ({b['ip']}:{b.get('port', 8765)})")

    def _on_branch_select(self, event):
        sel = self.listbox_branches.curselection()
        if sel:
            idx = sel[0]
            branches = self.config.get("saved_branches", [])
            if idx < len(branches):
                b = branches[idx]
                self.entry_remote_ip.delete(0, tk.END)
                self.entry_remote_ip.insert(0, b["ip"])
                self.entry_remote_port.delete(0, tk.END)
                self.entry_remote_port.insert(0, str(b.get("port", 8765)))
                self.entry_remote_pin.focus_set()

    def _save_current_as_branch(self):
        ip = self.entry_remote_ip.get().strip()
        port = int(self.entry_remote_port.get().strip() or 8765)
        if not ip:
            messagebox.showwarning("Missing IP", "Enter an IP address first.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Save Branch Preset")
        dialog.geometry("380x160")
        dialog.configure(bg="#1e293b")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Branch Name / Location:", bg="#1e293b", fg="#cbd5e1", font=("Segoe UI", 10)).pack(padx=16, pady=(16, 6), anchor="w")
        name_entry = tk.Entry(dialog, bg="#0f172a", fg="#ffffff", font=("Segoe UI", 10), width=32)
        name_entry.pack(padx=16, pady=4, fill=tk.X)
        name_entry.insert(0, f"Branch {len(self.config.get('saved_branches', [])) + 1}")
        name_entry.focus_set()

        def do_save():
            name = name_entry.get().strip()
            if name:
                self.config.setdefault("saved_branches", []).append({
                    "name": name,
                    "ip": ip,
                    "port": port
                })
                save_config(self.config)
                self._refresh_branches_listbox()
                dialog.destroy()

        tk.Button(dialog, text="Save Preset", bg="#0284c7", fg="white", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, command=do_save).pack(pady=14)

    def _delete_selected_branch(self):
        sel = self.listbox_branches.curselection()
        if not sel:
            return
        idx = sel[0]
        branches = self.config.get("saved_branches", [])
        if 0 <= idx < len(branches):
            del branches[idx]
            save_config(self.config)
            self._refresh_branches_listbox()

    def _show_mobile_qr_modal(self):
        modal = tk.Toplevel(self.root)
        modal.title("Connect Mobile Phone")
        modal.geometry("450x550")
        modal.configure(bg="#1e293b")
        modal.resizable(False, False)
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(
            modal,
            text="📱 Connect Phone to This PC",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Segoe UI", 13, "bold")
        ).pack(pady=(16, 4))

        tk.Label(
            modal,
            text="Scan this QR code with your phone camera or browser\nto operate this computer with touch, gestures & voice typing.",
            bg="#1e293b",
            fg="#94a3b8",
            font=("Segoe UI", 9),
            justify=tk.CENTER
        ).pack(pady=(0, 10))

        # Select IP: Tailscale or Local Wi-Fi
        ip_choices = []
        ts_ips = self.net_info.get("tailscale", [])
        loc_ips = self.net_info.get("local", [])
        if ts_ips:
            ip_choices.append((f"Tailscale (Cross-Branch): {ts_ips[0]}", ts_ips[0]))
        if loc_ips:
            ip_choices.append((f"Local Wi-Fi / LAN: {loc_ips[0]}", loc_ips[0]))
        if not ip_choices:
            ip_choices.append(("Localhost: 127.0.0.1", "127.0.0.1"))

        selected_ip = tk.StringVar(value=ip_choices[0][1])

        qr_label = tk.Label(modal, bg="#ffffff", padx=6, pady=6)
        qr_label.pack(pady=6)

        url_label = tk.Label(
            modal,
            text="",
            bg="#0f172a",
            fg="#4ade80",
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6,
            wraplength=400
        )
        url_label.pack(pady=4)

        def update_qr(*args):
            chosen_ip = selected_ip.get()
            phone_url = f"http://{chosen_ip}:8765#{self.current_pin}"
            url_label.config(text=phone_url)

            qr = qrcode.QRCode(box_size=5, border=2)
            qr.add_data(phone_url)
            qr.make(fit=True)
            pil_img = qr.make_image(fill_color="black", back_color="white")

            qr_img_tk = ImageTk.PhotoImage(pil_img)
            qr_label.config(image=qr_img_tk)
            qr_label.image = qr_img_tk

        if len(ip_choices) > 1:
            frame_picker = tk.Frame(modal, bg="#1e293b")
            frame_picker.pack(pady=4)
            for text, val in ip_choices:
                tk.Radiobutton(
                    frame_picker,
                    text=text,
                    value=val,
                    variable=selected_ip,
                    bg="#1e293b",
                    fg="#e2e8f0",
                    selectcolor="#0f172a",
                    activebackground="#1e293b",
                    activeforeground="#38bdf8",
                    font=("Segoe UI", 9),
                    command=update_qr
                ).pack(anchor="w")

        update_qr()

        # Mobile instructions list
        inst_frame = tk.Frame(modal, bg="#0f172a", padx=12, pady=8)
        inst_frame.pack(fill=tk.X, padx=20, pady=(6, 12))

        instructions = [
            "✓ No app download needed (opens directly in Chrome/Safari)",
            "✓ Trackpad Mode: Drag finger to move mouse, tap to click",
            "✓ Long Press for Right Click | ⌨️ Virtual Keyboard & Voice Typing",
            "✓ Right-Edge Scroll Strip: Slide finger to scroll up/down"
        ]
        for inst in instructions:
            tk.Label(
                inst_frame,
                text=inst,
                bg="#0f172a",
                fg="#cbd5e1",
                font=("Segoe UI", 8),
                anchor="w"
            ).pack(fill=tk.X, pady=1)

        tk.Button(
            modal,
            text="Close",
            bg="#334155",
            fg="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=16,
            command=modal.destroy
        ).pack(pady=(0, 10))

    def _show_update_modal(self):
        modal = tk.Toplevel(self.root)
        modal.title("AnyLocal - Updates & Server Settings")
        modal.geometry("520x600")
        modal.configure(bg="#0f172a")
        modal.resizable(False, False)
        modal.transient(self.root)
        modal.grab_set()

        hdr = tk.Frame(modal, bg="#1e293b", padx=20, pady=14)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="⚡ Updates & Cloud Server Settings", bg="#1e293b", fg="#38bdf8", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Configure 24/7 Render Relay & check for compiled updates.", bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 9)).pack(anchor="w")

        body = tk.Frame(modal, bg="#0f172a", padx=20, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        c1 = tk.Frame(body, bg="#1e293b", padx=14, pady=12)
        c1.pack(fill=tk.X, pady=(0, 10))
        tk.Label(c1, text="INSTALLED VERSION", bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(anchor="w")
        vrow = tk.Frame(c1, bg="#1e293b")
        vrow.pack(fill=tk.X, pady=(4, 0))
        tk.Label(vrow, text=f"v{APP_VERSION} (Shop Security Edition)", bg="#1e293b", fg="#38bdf8", font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        c2 = tk.Frame(body, bg="#1e293b", padx=14, pady=12)
        c2.pack(fill=tk.X, pady=(0, 10))
        tk.Label(c2, text="CLOUD SERVER & PC IDENTIFICATION", bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(anchor="w")

        tk.Label(c2, text="Render Cloud Server URL:", bg="#1e293b", fg="#e2e8f0", font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 2))
        entry_server = tk.Entry(c2, bg="#0f172a", fg="#ffffff", font=("Segoe UI", 10), insertbackground="white")
        entry_server.pack(fill=tk.X)
        entry_server.insert(0, self.config.get("cloud_server_url", "https://anylocal.onrender.com"))

        tk.Label(c2, text="PC / Counter Name (e.g. PC-A - Counter 1):", bg="#1e293b", fg="#e2e8f0", font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 2))
        entry_pc = tk.Entry(c2, bg="#0f172a", fg="#ffffff", font=("Segoe UI", 10), insertbackground="white")
        entry_pc.pack(fill=tk.X)
        entry_pc.insert(0, self.config.get("pc_name", f"Counter ({self.net_info['hostname']})"))

        btn_save = tk.Button(c2, text="💾 Save Configuration", bg="#0284c7", fg="#ffffff", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=10, pady=4)
        btn_save.pack(anchor="e", pady=(10, 0))

        c3 = tk.Frame(body, bg="#1e293b", padx=14, pady=12)
        c3.pack(fill=tk.BOTH, expand=True)
        tk.Label(c3, text="LIVE UPDATE STATUS", bg="#1e293b", fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(anchor="w")

        lbl_update_status = tk.Label(c3, text="Tap 'Check for Updates' to verify against your Render server.", bg="#1e293b", fg="#cbd5e1", font=("Segoe UI", 9), wraplength=440, justify=tk.LEFT)
        lbl_update_status.pack(anchor="w", pady=(8, 10))

        btn_apply_update = tk.Button(c3, text="🚀 Download & Install Update Now", bg="#16a34a", fg="#ffffff", font=("Segoe UI", 10, "bold"), relief=tk.FLAT, padx=14, pady=6)

        def on_save_config():
            self.config["cloud_server_url"] = entry_server.get().strip()
            self.config["pc_name"] = entry_pc.get().strip()
            save_config(self.config)
            lbl_update_status.config(text="✅ Configuration saved successfully!", fg="#22c55e")

        btn_save.config(command=on_save_config)

        def do_check_update():
            lbl_update_status.config(text="Connecting to Render server to check version...", fg="#38bdf8")
            modal.update()
            target_url = entry_server.get().strip().rstrip('/')
            try:
                import urllib.request
                req = urllib.request.Request(f"{target_url}/api/version", headers={"User-Agent": f"AnyLocal/{APP_VERSION}"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        r_ver = data.get("version", APP_VERSION)
                        if r_ver != APP_VERSION:
                            lbl_update_status.config(
                                text=f"🎉 New Update Available: v{r_ver}!\nChangelog: {', '.join(data.get('changelog', ['Latest updates']))}",
                                fg="#facc15"
                            )
                            btn_apply_update.pack(pady=8)
                            def do_apply():
                                lbl_update_status.config(text="Downloading update from Render & restarting...", fg="#38bdf8")
                                modal.update()
                                check_and_apply_auto_update()
                            btn_apply_update.config(command=do_apply)
                        else:
                            lbl_update_status.config(text=f"✅ You are up to date! Current version: v{APP_VERSION}", fg="#22c55e")
                    else:
                        lbl_update_status.config(text=f"⚠️ Server returned status {resp.status}.", fg="#f87171")
            except Exception as e:
                lbl_update_status.config(text=f"⚠️ Could not reach server at {target_url}\nError: {e}\n(Ensure Render service is active)", fg="#f87171")

        btn_check = tk.Button(c3, text="🔄 Check for Updates Now", bg="#0284c7", fg="#ffffff", font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12, pady=5, command=do_check_update)
        btn_check.pack(anchor="w")

        tk.Button(modal, text="Close", bg="#334155", fg="white", relief=tk.FLAT, font=("Segoe UI", 9), padx=16, command=modal.destroy).pack(pady=(0, 10))

    def _setup_system_tray(self):
        try:
            import pystray
            image = create_tray_image()
            menu = pystray.Menu(
                pystray.MenuItem("🖥️ Open AnyLocal", self._restore_from_tray, default=True),
                pystray.MenuItem("🟢 Status: Ready for Connections", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ Exit AnyLocal Completely", self._quit_completely)
            )
            self.tray_icon = pystray.Icon("AnyLocal", image, "AnyLocal Remote Desktop (Running in Background)", menu)
            self.tray_icon.run_detached()
        except Exception as e:
            print(f"System tray error: {e}")
            self.tray_icon = None

    def _restore_from_tray(self, icon=None, item=None):
        self.root.after(0, self._do_restore)

    def _do_restore(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_close_clicked(self):
        # Instead of quitting, hide window and keep running in background!
        self.root.withdraw()
        if self.tray_icon:
            try:
                self.tray_icon.notify(
                    "AnyLocal is running in the background. Remote devices can connect anytime.",
                    "AnyLocal Background Mode"
                )
            except Exception:
                pass

    def _quit_completely(self, icon=None, item=None):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        if self.server:
            self.server.stop()
        if self.active_client_viewer:
            try:
                self.active_client_viewer.close()
            except Exception:
                pass
        self.root.after(0, self.root.destroy)

def main():
    root = tk.Tk()
    app = AnyLocalApp(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close_clicked)

    # Start silent auto-updater thread (zero manual reinstall)
    threading.Thread(target=check_and_apply_auto_update, daemon=True).start()

    # If launched on Windows boot in background, hide window immediately
    if "--background" in sys.argv or "--minimized" in sys.argv:
        root.withdraw()

    root.mainloop()

if __name__ == "__main__":
    main()

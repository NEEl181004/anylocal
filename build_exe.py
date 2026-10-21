"""
Build Script to compile AnyLocal into a standalone Windows Executable (.exe)
"""

import os
import subprocess
import sys

def build():
    print("==================================================")
    print("Building AnyLocal Standalone Windows Executable...")
    print("==================================================")

    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=AnyLocal",
        "--noconsole",
        "--onefile",
        "--clean",
        "--add-data=web;web",
        "--hidden-import=engine.capture",
        "--hidden-import=engine.input_handler",
        "--hidden-import=engine.network_utils",
        "--hidden-import=engine.server",
        "--hidden-import=engine.client_viewer",
        "--hidden-import=engine.activity_tracker",
        "--hidden-import=engine.power_manager",
        "--hidden-import=websockets.asyncio.server",
        "--hidden-import=websockets.asyncio.client",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageTk",
        "--hidden-import=mss",
        "--hidden-import=pynput",
        "--hidden-import=qrcode",
        "--hidden-import=pystray",
        "--hidden-import=pystray._win32",
        "--hidden-import=psutil",
        "--hidden-import=engine.shop_auditor",
        "--hidden-import=win32gui",
        "--hidden-import=win32con",
        "--hidden-import=win32process",
        "--hidden-import=win32print",
        "--hidden-import=sqlite3",
        "AnyLocal.py"
    ]

    result = subprocess.run(cmd)
    if result.returncode == 0:
        exe_path = os.path.abspath("dist/AnyLocal.exe")
        print("\n==================================================")
        print(f"Build SUCCESSFUL!")
        print(f"Executable created at: {exe_path}")
        print("==================================================")
    else:
        print("\nBuild failed with return code:", result.returncode)

if __name__ == "__main__":
    build()

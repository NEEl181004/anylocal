# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['AnyLocal.py'],
    pathex=[],
    binaries=[],
    datas=[('web', 'web')],
    hiddenimports=['engine.capture', 'engine.input_handler', 'engine.network_utils', 'engine.server', 'engine.client_viewer', 'engine.activity_tracker', 'engine.power_manager', 'websockets.asyncio.server', 'websockets.asyncio.client', 'PIL.Image', 'PIL.ImageTk', 'mss', 'pynput', 'qrcode', 'pystray', 'pystray._win32', 'psutil', 'engine.shop_auditor', 'win32gui', 'win32con', 'win32process', 'win32print', 'sqlite3'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AnyLocal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

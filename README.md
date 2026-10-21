# ⚡ AnyLocal - High-Performance Self-Hosted Remote Desktop

**AnyLocal** is a lightweight, low-latency, self-hosted remote desktop software designed specifically for local Wi-Fi networks and multi-branch retail/shop environments without relying on third-party cloud hosting servers.

---

## 🌟 Key Features

1. **Ultra-Low Latency & High FPS**:
   - Native Windows desktop buffer capture via MSS + Direct GDI desktop attachment (~30-60 FPS).
   - In-flight frame flow control: Prevents network buffering delays, ensuring mouse cursor movement and typing feel instantaneous.
   - Configurable stream quality presets (Speed 50%, Balanced 65%, High 85%).

2. **Local User Priority & Automatic View-Only Mode**:
   - **Protection for Local Cashiers & Operators**: If someone is physically working at Desktop 1 (moving mouse or typing), any connected remote device (phone or desktop) is placed into **Screen View (View-Only Mode)**.
   - **No Ghost Clicks or Interruptions**: Remote clicks and keystrokes are blocked while the local user is active.
   - **Automatic Control Unlock**: As soon as Desktop 1 becomes idle for 5 seconds, full remote control is automatically granted. If the local user touches the mouse again, control is instantly revoked back to View-Only!

3. **Two-Way Bidirectional Desktop Communication (AnyDesk Style)**:
   - **Operate PC A from PC B and PC B from PC A**: When two computers connect, reverse session credentials (IP & PIN) are exchanged securely in the background.
   - **1-Click "🔄 Switch Sides / Two-Way"**: Clicking this button in the viewer toolbar instructs the remote PC to open a viewer window back to your PC.
   - **Host-Side 1-Click Reverse Control**: On the host machine's dashboard, click **"🔄 Control Remote PC (Two-Way)"** to launch a viewer to the connected PC instantly without typing any IP or PIN.
   - **Simultaneous Independent Desktop Control**: Both operators can operate each other's desktop side-by-side with zero collision or latency penalty.

4. **Phone Priority Takeover Over Idle Desktop**:
   - **Real-Time Remote Activity Monitoring**: AnyLocal monitors user input (mouse moves, clicks, keyboard typing, shortcuts) on the connected desktop session.
   - **Automatic Phone Access**: If a desktop client is connected and becomes **idle for >5 seconds** (no remote inputs), when you connect from your mobile phone (Android APK or mobile browser), the server **automatically disconnects the idle desktop and hands exclusive control to your phone immediately**.
   - **Graceful Notification**: The disconnected desktop receives a clean notice: *"Mobile Priority Takeover: Access transferred to Mobile Phone. Desktop was idle."*

5. **Secure Verification Code & Unattended Access**:
   - **Session PIN**: Generates a random 6-digit access code upon launch. No anonymous user can connect without this PIN.
   - **Unattended Mode**: Set a permanent shop password so you can connect to your remote branch PC anytime until it is turned off, even when no employee is present at the desk.
   - **Exclusive Session Locking**: Blocks simultaneous devices from controlling the same machine to eliminate race conditions.
   - **Host Control**: Active session monitor displays the connected remote device with a one-click **"🛑 Disconnect User"** kill switch.

6. **Full System & App Permissions**:
   - Full mouse control: Cursor movement, left-click, right-click, middle-click, double-click, drag-and-drop, and scroll wheel.
   - Full keyboard injection: All keys (letters, numbers, symbols, Enter, Tab, Esc, Backspace, Delete, arrows, F1-F12).
   - Quick action shortcuts: Windows Key (`⊞ Win`), Application Switcher (`⇥ Alt+Tab`), Task Manager (`⚙ TaskMgr`), and Fullscreen (`F11`).
   - Interacts with all Windows desktop software, POS systems, billing tools, and admin windows.

7. **Mobile Phone Control & Instant QR Code**:
   - **No App Download Needed**: Open Chrome or Safari on iPhone/Android and control the computer.
   - **Scan & Connect QR Code**: Click "📱 Connect Phone (QR Code)" on the PC screen to display an auto-connecting QR code.
   - **Laptop-Style Trackpad Mode**: Drag finger to glide the mouse pointer with smooth acceleration; tap to click; long-press for right-click.
   - **Mobile Text & Voice Typing**: Type or dictate using your phone's microphone to type directly into any PC application (Excel, Notepad, billing software).
   - **Pinch & Tap Zoom**: Zoom 1x / 1.5x / 2x into small desktop text and invoices with ease.
   - **Dedicated Scroll Strip**: Slide along the right edge of your phone screen for instant mouse wheel scrolling.

8. **Multi-Branch Shop Management**:
   - Saved Branches List: Save branch IP presets (e.g. "Branch 1 - Main Counter", "Branch 2 - Billing PC") for 1-click connection.

9. **24/7 Always Reachable & Remote Wake / Sign-In**:
   - **Continuous Stay-Awake & Away Mode**: Uses Win32 `SetThreadExecutionState` (`ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED`) to prevent Windows from entering deep sleep, keeping the network adapter, Tailscale, and AnyLocal server alive 24/7.
   - **Auto Display Wake**: When a phone or remote desktop connects, AnyLocal automatically sends `WM_SYSCOMMAND SC_MONITORPOWER` to wake physical monitors and the graphics subsystem.
   - **Remote Lock Screen Dismiss & PIN Sign-In**: Dismiss the Windows lock screen wallpaper with a single tap (`⚡ Wake / Sign-In` button) and type your Windows password or PIN directly into the Windows logon prompt to log in remotely.
   - **1-Click Sleep Config**: Host option to automatically configure Windows power plan standby timeout to 'Never' on AC power.

10. **Dual Viewer Support**:
   - **Native Desktop App**: Built-in responsive desktop window with real-time ping (ms) and FPS counter.
   - **Web Browser & Mobile Viewer**: Host runs an integrated web server on port `8765`. Connect from any PC, Mac, iPhone, iPad, or Android device.

11. **Portable Standalone Executable (`AnyLocal.exe`)**:
    - Packages into a single `.exe` file using PyInstaller. Run it on any Windows computer without installing Python.

---

## 🚀 Quick Start Guide

### Option A: Run Precompiled Windows Executable
Run the generated executable:
```cmd
dist\AnyLocal.exe
```

### Option B: Install Android APK on Mobile Phone
Copy and install the native Android APK directly onto your phone:
```cmd
dist\AnyLocal.apk
```
- Installs as a standalone native app called **AnyLocal** with a home screen shortcut.
- Includes **Address Book (My Computers)**, **Direct IP Connect (Tailscale/LAN)**, **Camera QR Scanner**, and **Magnifier Loupe**.

### Option C: Run via Python
```cmd
python AnyLocal.py
```

---

## 🌐 Connecting Across Different Shop Branches (Zero Hosting Fees)

Because different branches of your shop use different internet connections / Wi-Fi routers in different locations, their local IP addresses (`192.168.x.x`) do not talk to each other directly over the public internet without a virtual network.

We use **Tailscale** (100% Free, Secure WireGuard P2P Mesh Network):
- **Direct Peer-to-Peer**: Traffic travels directly between your shop computers with low latency, not through slow cloud servers.
- **No Port Forwarding Required**: Works behind firewalls and commercial router NATs.

### Step-by-Step Setup:
1. **Download Tailscale** on all your shop computers: [https://tailscale.com](https://tailscale.com)
2. **Sign In**: Sign in using your shop's Google/Microsoft account on each computer.
3. **Get Your Tailscale IPs**:
   - Each computer receives a permanent IP in the `100.x.y.z` range (e.g., `100.85.20.14`).
4. **Open AnyLocal**:
   - AnyLocal automatically detects the Tailscale IP and displays it under **"🌐 Tailscale (Cross-Branch)"** on the Host tab.
5. **Connect**:
   - From your central PC or laptop, open AnyLocal, switch to the **"Connect to Remote PC"** tab, enter the remote branch's Tailscale IP and PIN, and click **"🚀 Connect to Remote PC"**!

---

## 🚨 Shop Software Security & Real-Time Audit Engine (Strictly for Phone APK)

Silently monitors the billing software (**Quick Software** - Lugda Bazaar) in real time and broadcasts instant security alerts exclusively to your phone APK.

### 🛡️ 6 Monitored Security Events:
1. **Bill Saved & Printed**: Logs voucher number, total number of items, and final billing amount.
2. **Sales List Opened**: Alerts immediately whenever someone accesses the complete sales history window.
3. **Specific Bill Opened from List**: Logs the specific bill voucher number and details opened by staff.
4. **Product Deleted from Bill**: Captures the exact product removed from an active invoice, along with its barcode, price, and the `"Delete Row ?"` confirmation.
5. **Entire Bill Deleted**: Logs full bill cancellation details: bill number, items, barcodes, and original bill amount.
6. **Head Type Discount Applied**: Detects any discount entered into the invoice head, displaying the deducted discount amount, bill number, and original price.

### 🔒 Privacy & Per-PC Separation:
- **Strictly Invisible to Desktop Staff**: Alerts, popups, and audit records are **never shown on the desktop cash counter screen**. Cashiers will not see alerts or know auditing is active.
- **Separate Tracking for PC A & PC B**: The phone APK features filter pills (`All PCs`, `PC-A`, `PC-B`) so Counter 1 and Counter 2 records are tracked independently.
- **Automatic 3-Day Purge**: Alerts are stored in a dedicated database and automatically deleted after 72 hours (3 days).

---

## ☁️ 24/7 Render Cloud Server (Zero-Reinstall Updates & 24/7 Relay)

The `server/` directory contains a 24/7 cloud relay and audit server ready to deploy to Render:
- **No More Tailscale Disconnects**: Relays screen, control, and alerts 24/7 via WebSocket.
- **Zero-Reinstall Auto-Updates**: When new changes or updates are compiled to the server, `AnyLocal.exe` automatically detects the new version on startup, downloads the new build in the background, swaps the executable, and restarts in 2 seconds without you having to manually delete or reinstall `AnyLocal.exe`!

### Deploying to Render (1-Click):
1. Push this repository to your GitHub account (or link your existing Render account).
2. On Render Dashboard: Click **New +** -> **Web Service**.
3. Select your repository and set:
   - **Root Directory**: `server`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
4. Render provides your 24/7 live HTTPS/WSS URL (e.g. `https://anylocal-relay.onrender.com`).

---

## 📱 Mobile APK & Precision Touch Controls

The phone APK (`dist/AnyLocal.apk`) includes:
- **Reliable Tap Clicks**: Optimized touch jitter threshold (18px) and a guaranteed 40ms native click down/up hold for responsive registration on POS software buttons.
- **Mobile Keyboard & Voice Typing**: Full Unicode keystroke injection (`ord(char)`) with zero character corruption.
- **Floating Mobile Dock**:
  - `⏎ Enter`: Instant row submission or confirmation in Quick Software without opening the keyboard.
  - `⇥ Tab`: Jump to the next billing column (Barcode -> Qty -> Rate).
  - `❌ Esc`: Cancel active dialogs or close menus.
  - `⌨️ Type`: Open full keyboard and voice dictation drawer.
  - `🎯 Loupe`: Magnifier lens to aim accurately at tiny buttons.
  - `🚨 Alerts`: Direct shortcut to view live shop security alerts.

---

## 📁 Project Structure

```
Anyserver/
├── AnyLocal.py              # Main Application (Host + Client GUI + Auto-Updater)
├── build_exe.py            # Standalone PyInstaller build script
├── build_apk.py            # Standalone Android APK build & sign script
├── engine/
│   ├── capture.py          # Low-latency screen capture
│   ├── input_handler.py    # Windows mouse & Unicode keyboard injection
│   ├── network_utils.py    # Tailscale & Wi-Fi IP detection
│   ├── server.py           # WebSocket screen streamer, alert dispatcher & Web HTTP server
│   ├── client_viewer.py    # High-speed native desktop viewer GUI
│   ├── power_manager.py    # 24/7 stay-awake & remote lock-screen wake
│   └── shop_auditor.py     # Real-time Quick Software accounting & POS security engine
├── server/
│   ├── app.py              # 24/7 aiohttp cloud relay & SQLite audit database
│   ├── render.yaml         # Render blueprint configuration
│   ├── Procfile            # Deployment start command
│   └── requirements.txt    # Python dependencies for cloud deployment
├── web/
│   └── index.html          # Mobile-first Web Viewer & Security Alerts Feed
└── dist/
    ├── AnyLocal.exe        # Portable standalone Windows Executable
    └── AnyLocal.apk        # Standalone Android APK for owner's phone
```

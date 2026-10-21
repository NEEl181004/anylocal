"""
Host Server Engine for AnyLocal
Combines HTTP Web Viewer delivery and high-speed WebSocket screen/input streaming.
"""

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

from websockets.asyncio.server import serve, ServerConnection
from websockets.http11 import Request, Response
from websockets.datastructures import Headers

from .capture import ScreenCapturer
from .input_handler import InputHandler
from .activity_tracker import ActivityTracker
from .power_manager import keep_system_awake, wake_display_and_monitor, dismiss_lock_screen
from .network_utils import free_port
from .shop_auditor import get_shop_auditor

# Path to the web UI
def get_web_dir():
    import sys
    for candidate in [
        Path.cwd() / "web",
        Path(__file__).resolve().parent.parent / "web",
        Path(sys.executable).resolve().parent / "web" if getattr(sys, 'frozen', False) else None,
        Path(getattr(sys, '_MEIPASS', '')) / "web" if hasattr(sys, '_MEIPASS') else None,
        Path("C:/Users/Admin/Desktop/Anyserver/web")
    ]:
        if candidate and candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return Path(__file__).resolve().parent.parent / "web"

WEB_DIR = get_web_dir()
INDEX_HTML_PATH = WEB_DIR / "index.html"

class HostServer:
    def __init__(self, port=8765, pin="123456", unattended_pin=None):
        self.port = port
        self.pin = pin
        self.unattended_pin = unattended_pin
        self.allow_control = True
        self.allow_mobile = True
        self.exclusive_lock = True
        self.local_priority = True  # View-only when local physical user is active!

        self.server = None
        self.loop = None
        self.thread = None
        self.is_running = False

        self.capturer = ScreenCapturer(quality=65)
        self.input_handler = InputHandler()
        self.activity_tracker = ActivityTracker(idle_threshold=5.0)
        self.last_control_state_sent = None

        # Prevent Windows S3 Sleep / Standby while AnyLocal is hosting
        keep_system_awake(True)

        self.active_client_ws = None
        self.active_client_ip = None
        self.active_client_type = None
        self.active_device_name = None
        self.session_start_time = None
        self.last_remote_activity_time = 0.0
        self.reverse_session_info = None
        self.ack_event = asyncio.Event()

        # GUI Callbacks
        self.on_status_change = None
        self.on_client_connect = None
        self.on_client_disconnect = None
        self.on_reverse_connect_requested = None

        # Shop Software Real-Time Security Auditor
        self.auditor = get_shop_auditor()
        self.auditor.on_alert_callback = self._on_security_alert

    def _on_security_alert(self, alert_payload):
        """Dispatches real-time security alert down WebSocket to connected phone APK."""
        if self.active_client_ws and self.loop and self.active_client_type == "mobile":
            try:
                msg = json.dumps({
                    "type": "security_alert",
                    "alert": alert_payload
                })
                asyncio.run_coroutine_threadsafe(
                    self.active_client_ws.send(msg),
                    self.loop
                )
            except Exception:
                pass

    def set_pin(self, new_pin):
        self.pin = str(new_pin).strip()

    def set_unattended_pin(self, new_unattended_pin):
        self.unattended_pin = str(new_unattended_pin).strip() if new_unattended_pin else None

    def set_control_allowed(self, allowed):
        self.allow_control = allowed
        self.input_handler.enabled = allowed

    def set_mobile_allowed(self, allowed):
        self.allow_mobile = allowed

    def set_exclusive_lock(self, locked):
        self.exclusive_lock = locked

    def set_local_priority(self, enabled):
        self.local_priority = enabled
        self.activity_tracker.enabled = enabled

    def set_idle_threshold(self, seconds):
        self.activity_tracker.idle_threshold = max(1.0, float(seconds))

    def _http_handler(self, connection, request: Request):
        """
        Serves the Web Viewer HTML and PWA Manifest directly over HTTP on the same port.
        Passes WebSocket upgrade requests through to _ws_handler regardless of path!
        """
        # If this is a WebSocket upgrade handshake, pass through to _ws_handler
        upgrade_hdr = request.headers.get("Upgrade", "")
        if "websocket" in upgrade_hdr.lower() or request.path == "/ws":
            return None

        if request.path in ("/", "/index.html"):
            try:
                if INDEX_HTML_PATH.exists():
                    with open(INDEX_HTML_PATH, "rb") as f:
                        body = f.read()
                else:
                    body = b"<h1>AnyLocal Web Viewer Not Found</h1>"
                headers = Headers([
                    ("Content-Type", "text/html; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "no-cache")
                ])
                return Response(200, "OK", headers, body)
            except Exception as e:
                err = str(e).encode()
                return Response(500, "Internal Error", Headers(), err)
        elif request.path == "/manifest.json":
            manifest_path = WEB_DIR / "manifest.json"
            if manifest_path.exists():
                with open(manifest_path, "rb") as f:
                    body = f.read()
                headers = Headers([
                    ("Content-Type", "application/manifest+json; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    ("Cache-Control", "no-cache")
                ])
                return Response(200, "OK", headers, body)

        elif request.path.startswith("/api/alerts"):
            if request.method == "OPTIONS":
                headers = Headers([
                    ("Access-Control-Allow-Origin", "*"),
                    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
                    ("Access-Control-Allow-Headers", "*")
                ])
                return Response(200, "OK", headers, b"")

            try:
                import sqlite3
                offline_db = Path(os.path.expanduser("~")) / ".anylocal_alerts_offline.db"
                server_db = Path(__file__).resolve().parent.parent / "server" / "alerts.db"
                alerts = []

                if offline_db.exists():
                    conn = sqlite3.connect(str(offline_db))
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM offline_alerts ORDER BY created_timestamp DESC LIMIT 150")
                    rows = cur.fetchall()
                    alerts = [dict(r) for r in rows]
                    conn.close()
                elif server_db.exists():
                    conn = sqlite3.connect(str(server_db))
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    cur.execute("SELECT * FROM alerts ORDER BY created_timestamp DESC LIMIT 150")
                    rows = cur.fetchall()
                    alerts = [dict(r) for r in rows]
                    conn.close()

                body = json.dumps({"status": "ok", "count": len(alerts), "alerts": alerts}).encode("utf-8")
                headers = Headers([
                    ("Content-Type", "application/json; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    ("Access-Control-Allow-Origin", "*"),
                    ("Cache-Control", "no-cache")
                ])
                return Response(200, "OK", headers, body)
            except Exception as e:
                body = json.dumps({"status": "ok", "count": 0, "alerts": [], "error": str(e)}).encode("utf-8")
                headers = Headers([("Content-Type", "application/json"), ("Access-Control-Allow-Origin", "*")])
                return Response(200, "OK", headers, body)

        elif request.path.startswith("/api/pcs"):
            try:
                import sqlite3
                server_db = Path(__file__).resolve().parent.parent / "server" / "alerts.db"
                pcs = []
                if server_db.exists():
                    conn = sqlite3.connect(str(server_db))
                    cur = conn.cursor()
                    cur.execute("SELECT pc_id, pc_name, COUNT(*), MAX(created_at) FROM alerts GROUP BY pc_id")
                    for r in cur.fetchall():
                        pcs.append({"pc_id": r[0], "pc_name": r[1], "total_alerts": r[2], "last_activity": r[3]})
                    conn.close()
                body = json.dumps({"status": "ok", "pcs": pcs}).encode("utf-8")
                headers = Headers([("Content-Type", "application/json"), ("Access-Control-Allow-Origin", "*")])
                return Response(200, "OK", headers, body)
            except Exception:
                body = b'{"status":"ok","pcs":[]}'
                headers = Headers([("Content-Type", "application/json"), ("Access-Control-Allow-Origin", "*")])
                return Response(200, "OK", headers, body)

        elif request.path == "/api/version":
            body = json.dumps({"status": "ok", "version": "2.4.0", "name": "AnyLocal"}).encode("utf-8")
            headers = Headers([("Content-Type", "application/json"), ("Access-Control-Allow-Origin", "*")])
            return Response(200, "OK", headers, body)

        return None

    async def _ws_handler(self, ws: ServerConnection):
        """
        Handles incoming WebSocket remote desktop sessions with graceful conflict protection.
        """
        client_ip = ws.remote_address[0] if ws.remote_address else "Unknown"
        print(f"[Host] Incoming connection from {client_ip}")

        # Step 1: Authentication Phase
        authenticated = False
        client_type = "desktop"
        device_name = "Remote Device"

        try:
            auth_msg_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            auth_msg = json.loads(auth_msg_raw)
            if auth_msg.get("type") == "auth":
                client_pin = str(auth_msg.get("pin", "")).strip()
                client_type = str(auth_msg.get("client_type", "desktop")).lower()
                device_name = str(auth_msg.get("device_name", "Remote Device")).strip()
                reverse_host = auth_msg.get("reverse_host") or client_ip
                reverse_port = int(auth_msg.get("reverse_port", 8765))
                reverse_pin = str(auth_msg.get("reverse_pin", "")).strip()

                # Check if mobile connection is disabled on this PC
                if client_type == "mobile" and not self.allow_mobile:
                    await ws.send(json.dumps({
                        "type": "auth_fail",
                        "reason": "Mobile Access Blocked: This computer does not allow phone connections."
                    }))
                    await ws.close()
                    return

                # Check session PIN or unattended PIN
                valid_session = bool(self.pin and client_pin == self.pin)
                valid_unattended = bool(self.unattended_pin and client_pin == self.unattended_pin)
                if valid_session or valid_unattended:
                    authenticated = True
                    auth_type = "Session PIN" if valid_session else "Unattended Permanent Password"
                    print(f"[Host] Auth SUCCESS for {client_ip} ({client_type}) using {auth_type}")
                else:
                    print(f"[Host] Auth FAILED for {client_ip}: entered='{client_pin}', active_session_pin='{self.pin}', unattended_active={bool(self.unattended_pin)}")
                    await ws.send(json.dumps({
                        "type": "auth_fail",
                        "reason": "Invalid verification code. Check Session PIN or Unattended Password on Host PC."
                    }))
                    await ws.close()
                    return
            else:
                await ws.close()
                return
        except Exception as e:
            print(f"[Host] Auth error: {e}")
            await ws.close()
            return

        if not authenticated:
            return

        # Step 2: Session Priority & Conflict Handling
        if self.active_client_ws is not None and self.active_client_ws != ws:
            idle_sec = time.time() - self.last_remote_activity_time
            is_active_desktop = (self.active_client_type == "desktop")
            is_new_mobile = (client_type == "mobile")
            is_desktop_idle = (idle_sec >= 5.0)

            # Phone Priority Rule: If incoming device is a Mobile Phone, and active Desktop is idle (>5s),
            # disconnect Desktop and grant immediate priority access to Mobile Phone!
            if is_new_mobile and is_active_desktop and is_desktop_idle:
                print(f"[Host] Phone Priority Takeover: Idle desktop ({self.active_client_ip}, idle {idle_sec:.1f}s) disconnected for mobile client {client_ip}!")
                try:
                    await self.active_client_ws.send(json.dumps({
                        "type": "kicked",
                        "reason": f"Mobile Priority Takeover: Access transferred to Mobile Phone ({device_name}). Desktop was idle for {idle_sec:.0f}s."
                    }))
                    await self.active_client_ws.close()
                except Exception:
                    pass
                self.active_client_ws = None
                self.active_client_ip = None
                self.active_client_type = None
            elif self.exclusive_lock:
                active_desc = f"{self.active_client_type or 'Device'} ({self.active_client_ip})"
                print(f"[Host] Rejected {client_ip} because machine is busy with {active_desc}")
                await ws.send(json.dumps({
                    "type": "auth_fail",
                    "reason": f"Computer Busy: Currently controlled by {active_desc}. Simultaneous control is locked to prevent conflicts."
                }))
                await ws.close()
                return

        # If takeover allowed and old client exists, close old one
        if self.active_client_ws and self.active_client_ws != ws:
            try:
                await self.active_client_ws.close()
            except Exception:
                pass

        # Update Session State
        self.active_client_ws = ws
        self.active_client_ip = client_ip
        self.active_client_type = client_type
        self.active_device_name = device_name
        self.session_start_time = time.time()
        self.last_remote_activity_time = time.time()
        self.ack_event.set()

        # Wake physical monitor and graphics system upon connection
        wake_display_and_monitor()

        # Two-Way Desktop control information
        if client_type == "desktop" and reverse_pin:
            self.reverse_session_info = {
                "host": reverse_host,
                "port": reverse_port,
                "pin": reverse_pin,
                "device_name": device_name
            }
        else:
            self.reverse_session_info = None

        w, h = self.capturer.get_resolution()
        self.input_handler.set_resolution(w, h)

        # Notify GUI with client details and reverse session info
        if self.on_client_connect:
            self.on_client_connect(client_ip, client_type, device_name, self.reverse_session_info)

        # Send Auth Success
        await ws.send(json.dumps({
            "type": "auth_ok",
            "width": w,
            "height": h,
            "hostname": os.environ.get("COMPUTERNAME", "Remote-PC")
        }))

        # Concurrently run frame streaming and input message handling
        stream_task = asyncio.create_task(self._stream_screen_loop(ws))
        recv_task = asyncio.create_task(self._receive_input_loop(ws))

        done, pending = await asyncio.wait(
            [stream_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        # Session ended
        print(f"[Host] Client {client_ip} disconnected")
        self.active_client_ws = None
        self.active_client_ip = None
        self.active_client_type = None
        self.active_device_name = None
        self.session_start_time = None
        self.last_remote_activity_time = 0.0
        self.reverse_session_info = None

        if self.on_client_disconnect:
            self.on_client_disconnect()

    async def _stream_screen_loop(self, ws: ServerConnection):
        """
        Captures screen and sends JPEG frames with zero queue delay.
        Broadcasting real-time control state (View-Only vs Full Control).
        """
        target_frame_interval = 1.0 / 35.0  # ~35 FPS cap
        last_state_broadcast = 0.0

        while self.is_running and ws == self.active_client_ws:
            t0 = time.time()
            try:
                # 1. Periodic / Event-driven Control State Broadcast
                is_local_active = self.local_priority and self.activity_tracker.is_local_user_active()
                can_control = self.allow_control and not is_local_active

                if (can_control != self.last_control_state_sent) or (t0 - last_state_broadcast > 2.0):
                    self.last_control_state_sent = can_control
                    last_state_broadcast = t0
                    await ws.send(json.dumps({
                        "type": "control_state",
                        "can_control": can_control,
                        "is_view_only": not can_control,
                        "idle_seconds": round(self.activity_tracker.get_idle_seconds(), 1),
                        "reason": "Local user is actively working on Desktop" if is_local_active else "Desktop is Idle (Full Remote Control Active)"
                    }))

                # 2. Capture and stream frame
                frame_bytes = self.capturer.capture_frame()
                if frame_bytes:
                    await ws.send(frame_bytes)

                # Wait for ACK or small timeout (flow control)
                try:
                    await asyncio.wait_for(self.ack_event.wait(), timeout=0.08)
                    self.ack_event.clear()
                except asyncio.TimeoutError:
                    pass

                # Frame pacing
                elapsed = time.time() - t0
                sleep_time = target_frame_interval - elapsed
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                else:
                    await asyncio.sleep(0.002)

            except Exception as e:
                break

    async def _receive_input_loop(self, ws: ServerConnection):
        """
        Receives mouse, keyboard, shortcuts, and configuration messages.
        Enforces View-Only mode when a local user is actively working on the desktop!
        """
        async for msg_raw in ws:
            if isinstance(msg_raw, str):
                try:
                    data = json.loads(msg_raw)
                    msg_type = data.get("type")

                    if msg_type == "ack":
                        self.ack_event.set()
                        continue

                    if msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                        continue

                    if msg_type in ("request_two_way", "reverse_connect_request"):
                        r_host = data.get("host") or (self.reverse_session_info.get("host") if self.reverse_session_info else self.active_client_ip)
                        r_port = int(data.get("port") or (self.reverse_session_info.get("port", 8765) if self.reverse_session_info else 8765))
                        r_pin = data.get("pin") or (self.reverse_session_info.get("pin", "") if self.reverse_session_info else "")
                        print(f"[Host] Two-Way Control requested by remote client: {r_host}:{r_port}")
                        if self.on_reverse_connect_requested:
                            self.on_reverse_connect_requested({
                                "host": r_host,
                                "port": r_port,
                                "pin": r_pin,
                                "device_name": self.active_device_name or "Remote PC"
                            })
                        continue

                    if msg_type == "config":
                        if "quality" in data:
                            self.capturer.set_quality(data["quality"])
                        if "scale" in data:
                            self.capturer.set_scale(data["scale"])
                        continue

                    # Record remote activity for idle detection (phone priority takeover)
                    if msg_type in ("mouse", "key", "text", "shortcut"):
                        self.last_remote_activity_time = time.time()

                    # Local user activity check: If local cashier/operator is using the PC, block remote inputs!
                    is_local_busy = self.local_priority and self.activity_tracker.is_local_user_active()
                    if is_local_busy or not self.allow_control:
                        # Remote device is in View-Only mode! Reject input to protect local operations.
                        continue

                    # Full Remote Control execution
                    if msg_type == "mouse":
                        self.input_handler.handle_mouse(data)

                    elif msg_type == "text":
                        text_val = data.get("text")
                        if text_val:
                            self.input_handler.handle_text(text_val)

                    elif msg_type == "shortcut":
                        combo = data.get("combo")
                        if combo:
                            self.input_handler.trigger_shortcut(combo)

                    elif msg_type == "key":
                        self.input_handler.handle_keyboard(data)

                except Exception as e:
                    pass

    def disconnect_client(self):
        """
        Allows the host to kick off the currently connected remote user.
        """
        if self.active_client_ws and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.active_client_ws.close(),
                self.loop
            )

    def _run_server_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def main():
            try:
                self.server = await serve(
                    self._ws_handler,
                    host="0.0.0.0",
                    port=self.port,
                    process_request=self._http_handler,
                    max_size=10 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20
                )
            except OSError as e:
                print(f"[Host] Port {self.port} occupied ({e}). Reclaiming port...")
                free_port(self.port)
                await asyncio.sleep(0.5)
                self.server = await serve(
                    self._ws_handler,
                    host="0.0.0.0",
                    port=self.port,
                    process_request=self._http_handler,
                    max_size=10 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20
                )

            print(f"[Host] AnyLocal server running on port {self.port}")
            self.is_running = True
            if self.on_status_change:
                self.on_status_change("running")
            await self.server.wait_closed()

        try:
            self.loop.run_until_complete(main())
        except Exception as e:
            print(f"[Host] Server loop error: {e}")
        finally:
            self.is_running = False
            if self.on_status_change:
                self.on_status_change("stopped")

    def start(self):
        if self.is_running:
            return
        try:
            self.auditor.start()
        except Exception:
            pass
        self.thread = threading.Thread(target=self._run_server_thread, daemon=True)
        self.thread.start()

    def stop(self):
        self.is_running = False
        try:
            self.auditor.stop()
        except Exception:
            pass
        self.capturer.close()
        self.activity_tracker.stop()
        if self.server and self.loop:
            self.loop.call_soon_threadsafe(self.server.close)

"""
Client Viewer GUI for AnyLocal
High-speed native Windows Remote Desktop viewer with real-time mouse/keyboard control.
"""

import asyncio
import io
import json
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import socket
import websockets
from websockets.asyncio.client import connect

class ClientViewerWindow:
    def __init__(self, host, port, pin, my_host_ip=None, my_host_port=8765, my_host_pin=None, on_close_callback=None):
        self.host = host
        self.port = port
        self.pin = pin
        self.my_host_ip = my_host_ip
        self.my_host_port = my_host_port
        self.my_host_pin = my_host_pin
        self.on_close_callback = on_close_callback

        self.root = tk.Toplevel()
        self.root.title(f"AnyLocal Viewer - Connecting to {self.host}:{self.port}...")
        self.root.geometry("1100x700")
        self.root.minsize(640, 480)
        self.root.configure(bg="#0b0f19")

        # Connection State
        self.ws = None
        self.loop = None
        self.thread = None
        self.is_connected = False
        self.is_running = True

        self.remote_width = 1920
        self.remote_height = 1080
        self.remote_hostname = self.host
        self.current_img_tk = None
        self.is_view_only = False

        # Stats
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.current_fps = 0
        self.current_latency = 0
        self.last_ping_time = 0

        self._build_ui()
        self._bind_events()

        # Start networking thread
        self.thread = threading.Thread(target=self._run_network_loop, daemon=True)
        self.thread.start()

    def _build_ui(self):
        # Top Toolbar
        self.toolbar = tk.Frame(self.root, bg="#111827", height=42)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        # Connection / Stats Label
        self.lbl_stats = tk.Label(
            self.toolbar,
            text=f"🟢 Connecting to {self.host}...",
            bg="#111827",
            fg="#38bdf8",
            font=("Segoe UI", 10, "bold")
        )
        self.lbl_stats.pack(side=tk.LEFT, padx=12, pady=6)

        self.lbl_latency = tk.Label(
            self.toolbar,
            text="⚡ -- ms | 📺 0 FPS",
            bg="#111827",
            fg="#94a3b8",
            font=("Segoe UI", 9)
        )
        self.lbl_latency.pack(side=tk.LEFT, padx=8)

        # Right-side Action Buttons
        self.btn_disconnect = tk.Button(
            self.toolbar,
            text="Disconnect",
            bg="#ef4444",
            fg="white",
            activebackground="#dc2626",
            activeforeground="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            command=self.close
        )
        self.btn_disconnect.pack(side=tk.RIGHT, padx=10, pady=6)

        # Two-Way / Switch Sides Control Button (AnyDesk style)
        self.btn_two_way = tk.Button(
            self.toolbar,
            text="🔄 Switch Sides / Two-Way",
            bg="#059669",
            fg="white",
            activebackground="#047857",
            activeforeground="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            command=self._request_two_way_session
        )
        self.btn_two_way.pack(side=tk.RIGHT, padx=4)

        self.btn_fullscreen = tk.Button(
            self.toolbar,
            text="⛶ Fullscreen",
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="white",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=8,
            command=self._toggle_fullscreen
        )
        self.btn_fullscreen.pack(side=tk.RIGHT, padx=4)

        # Quick Shortcut Buttons
        self.btn_taskmgr = tk.Button(
            self.toolbar,
            text="⚙ TaskMgr",
            bg="#1e293b",
            fg="#e2e8f0",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=lambda: self._send_shortcut("task_manager")
        )
        self.btn_taskmgr.pack(side=tk.RIGHT, padx=4)

        self.btn_alttab = tk.Button(
            self.toolbar,
            text="⇥ Alt+Tab",
            bg="#1e293b",
            fg="#e2e8f0",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=lambda: self._send_shortcut("alt_tab")
        )
        self.btn_alttab.pack(side=tk.RIGHT, padx=4)

        self.btn_win = tk.Button(
            self.toolbar,
            text="⊞ Win",
            bg="#1e293b",
            fg="#e2e8f0",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            command=lambda: self._send_shortcut("win")
        )
        self.btn_wake = tk.Button(
            self.toolbar,
            text="⚡ Wake / Sign-In",
            bg="#f59e0b",
            fg="#0f172a",
            activebackground="#d97706",
            activeforeground="#0f172a",
            relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            command=lambda: self._send_shortcut("wake_unlock")
        )
        self.btn_wake.pack(side=tk.RIGHT, padx=4)

        self.btn_win.pack(side=tk.RIGHT, padx=4)

        # Main Screen Canvas
        self.canvas = tk.Canvas(
            self.root,
            bg="#020617",
            highlightthickness=0,
            cursor="crosshair"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

    def _bind_events(self):
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        # Mouse Events on Canvas
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", lambda e: self._on_mouse_click(e, "down", "left"))
        self.canvas.bind("<ButtonRelease-1>", lambda e: self._on_mouse_click(e, "up", "left"))
        self.canvas.bind("<ButtonPress-3>", lambda e: self._on_mouse_click(e, "down", "right"))
        self.canvas.bind("<ButtonRelease-3>", lambda e: self._on_mouse_click(e, "up", "right"))
        self.canvas.bind("<ButtonPress-2>", lambda e: self._on_mouse_click(e, "down", "middle"))
        self.canvas.bind("<ButtonRelease-2>", lambda e: self._on_mouse_click(e, "up", "middle"))
        self.canvas.bind("<Double-Button-1>", lambda e: self._on_mouse_click(e, "dblclick", "left"))
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        # Keyboard Events (focus canvas on hover/click)
        self.canvas.bind("<Enter>", lambda e: self.canvas.focus_set())
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set(), add="+")
        self.canvas.bind("<KeyPress>", self._on_key_down)
        self.canvas.bind("<KeyRelease>", self._on_key_up)

        # Window Resize
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Fullscreen Shortcut (F11)
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())

    def _toggle_fullscreen(self):
        is_fs = self.root.attributes("-fullscreen")
        self.root.attributes("-fullscreen", not is_fs)

    def _get_normalized_coords(self, event):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 0 or ch <= 0:
            return 0.0, 0.0

        # Calculate displayed image position with letterboxing
        aspect_remote = self.remote_width / self.remote_height
        aspect_canvas = cw / ch

        if aspect_canvas > aspect_remote:
            # Pillarbox (black bars left/right)
            img_h = ch
            img_w = int(ch * aspect_remote)
            offset_x = (cw - img_w) // 2
            offset_y = 0
        else:
            # Letterbox (black bars top/bottom)
            img_w = cw
            img_h = int(cw / aspect_remote)
            offset_x = 0
            offset_y = (ch - img_h) // 2

        rel_x = event.x - offset_x
        rel_y = event.y - offset_y

        norm_x = max(0.0, min(1.0, rel_x / max(1, img_w)))
        norm_y = max(0.0, min(1.0, rel_y / max(1, img_h)))
        return norm_x, norm_y

    def _on_mouse_move(self, event):
        if not self.is_connected or not self.ws or self.is_view_only:
            return
        nx, ny = self._get_normalized_coords(event)
        self._send_ws_json({
            "type": "mouse",
            "action": "move",
            "x": nx,
            "y": ny
        })

    def _on_mouse_click(self, event, action, btn):
        if not self.is_connected or not self.ws or self.is_view_only:
            return
        nx, ny = self._get_normalized_coords(event)
        self._send_ws_json({
            "type": "mouse",
            "action": action,
            "btn": btn,
            "x": nx,
            "y": ny
        })

    def _on_mouse_wheel(self, event):
        if not self.is_connected or not self.ws or self.is_view_only:
            return
        nx, ny = self._get_normalized_coords(event)
        delta = 1 if event.delta > 0 else -1
        self._send_ws_json({
            "type": "mouse",
            "action": "wheel",
            "delta": delta,
            "x": nx,
            "y": ny
        })

    def _map_tk_key(self, event):
        keysym = event.keysym.lower()
        mapping = {
            "return": "enter",
            "prior": "page_up",
            "next": "page_down",
            "control_l": "ctrl",
            "control_r": "ctrl",
            "shift_l": "shift",
            "shift_r": "shift",
            "alt_l": "alt",
            "alt_r": "alt",
            "win_l": "win",
            "win_r": "win",
            "caps_lock": "caps_lock"
        }
        return mapping.get(keysym, keysym)

    def _on_key_down(self, event):
        if not self.is_connected or self.is_view_only:
            return
        key_name = self._map_tk_key(event)
        self._send_ws_json({
            "type": "key",
            "action": "down",
            "key": key_name
        })

    def _on_key_up(self, event):
        if not self.is_connected or self.is_view_only:
            return
        key_name = self._map_tk_key(event)
        self._send_ws_json({
            "type": "key",
            "action": "up",
            "key": key_name
        })

    def _send_shortcut(self, shortcut):
        if self.is_connected and not self.is_view_only:
            self._send_ws_json({
                "type": "shortcut",
                "combo": shortcut
            })

    def _request_two_way_session(self):
        """
        Sends Two-Way control signal to Remote PC, instructing it to launch a viewer back to this PC.
        """
        if not self.is_connected or not self.ws:
            messagebox.showwarning("Not Connected", "Viewer must be connected to request Two-Way control.")
            return
        self._send_ws_json({
            "type": "request_two_way",
            "host": self.my_host_ip,
            "port": self.my_host_port,
            "pin": self.my_host_pin
        })
        messagebox.showinfo(
            "Two-Way Control Active",
            "Two-Way Control signal sent to Remote PC!\n\n"
            "The remote computer is opening a viewer to operate your desktop simultaneously.\n"
            "Both PCs can now control each other (AnyDesk style)."
        )

    def _send_ws_json(self, data):
        if self.ws and self.loop and self.is_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.ws.send(json.dumps(data)),
                    self.loop
                )
            except Exception:
                pass

    def _on_canvas_resize(self, event):
        pass

    def _update_frame(self, image_bytes):
        """
        Renders the decompressed frame onto the Tkinter Canvas.
        """
        try:
            pil_img = Image.open(io.BytesIO(image_bytes))
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()

            if cw > 50 and ch > 50:
                # Calculate scale maintaining aspect ratio
                aspect_remote = pil_img.width / pil_img.height
                aspect_canvas = cw / ch

                if aspect_canvas > aspect_remote:
                    target_h = ch
                    target_w = int(ch * aspect_remote)
                else:
                    target_w = cw
                    target_h = int(cw / aspect_remote)

                pil_img = pil_img.resize((target_w, target_h), Image.Resampling.BILINEAR)

            self.current_img_tk = ImageTk.PhotoImage(pil_img)
            self.canvas.delete("all")
            self.canvas.create_image(cw // 2, ch // 2, image=self.current_img_tk, anchor=tk.CENTER)

            # Send ACK for flow control
            self._send_ws_json({"type": "ack"})

            # Calculate FPS
            self.frame_count += 1
            now = time.time()
            if now - self.last_fps_time >= 1.0:
                self.current_fps = self.frame_count
                self.frame_count = 0
                self.last_fps_time = now
                self.lbl_latency.config(text=f"⚡ {self.current_latency} ms | 📺 {self.current_fps} FPS")

        except Exception as e:
            pass

    def _run_network_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        uri = f"ws://{self.host}:{self.port}/ws"

        async def client_coro():
            try:
                async with connect(uri, max_size=10*1024*1024) as ws:
                    self.ws = ws

                    # 1. Send authentication with reverse host info for Two-Way communication
                    await ws.send(json.dumps({
                        "type": "auth",
                        "pin": self.pin,
                        "client_type": "desktop",
                        "device_name": socket.gethostname(),
                        "reverse_host": self.my_host_ip,
                        "reverse_port": self.my_host_port,
                        "reverse_pin": self.my_host_pin
                    }))

                    # 2. Wait for auth response
                    resp_raw = await asyncio.wait_for(ws.recv(), timeout=6.0)
                    resp = json.loads(resp_raw)

                    if resp.get("type") == "auth_ok":
                        self.is_connected = True
                        self.remote_width = resp.get("width", 1920)
                        self.remote_height = resp.get("height", 1080)
                        hname = resp.get("hostname", self.host)

                        self.root.title(f"AnyLocal - Connected to {hname} ({self.host})")
                        self.lbl_stats.config(text=f"🟢 Connected: {hname}", fg="#4ade80")

                        # Start ping task
                        asyncio.create_task(self._ping_loop())

                        # Frame receiving loop
                        while self.is_running:
                            message = await ws.recv()
                            if isinstance(message, bytes):
                                self.root.after(0, self._update_frame, message)
                            elif isinstance(message, str):
                                data = json.loads(message)
                                if data.get("type") == "pong":
                                    latency = int((time.time() - self.last_ping_time) * 1000)
                                    self.current_latency = latency
                                elif data.get("type") == "kicked":
                                    reason = data.get("reason", "Session disconnected by host.")
                                    self.root.after(0, lambda r=reason: messagebox.showwarning("Session Transferred", r))
                                    self.close()
                                    return
                                elif data.get("type") == "control_state":
                                    is_vo = data.get("is_view_only", False)
                                    self.is_view_only = is_vo
                                    reason = data.get("reason", "")
                                    if is_vo:
                                        self.root.after(0, lambda r=reason: self.lbl_stats.config(
                                            text=f"👀 View-Only ({r})", fg="#f59e0b"
                                        ))
                                    else:
                                        self.root.after(0, lambda: self.lbl_stats.config(
                                            text=f"🟢 Control Active ({self.remote_hostname})", fg="#4ade80"
                                        ))
                    else:
                        reason = resp.get("reason", "Verification code incorrect.")
                        self.root.after(0, lambda r=reason: messagebox.showerror("Connection Failed", r))
                        self.close()

            except Exception as e:
                if self.is_running:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Connection Error",
                        f"Could not connect to {self.host}:{self.port}\n\nMake sure the remote PC has AnyLocal open and Tailscale/Wi-Fi is connected."
                    ))
                    self.close()

        async def _ping_loop():
            while self.is_running and self.is_connected and self.ws:
                self.last_ping_time = time.time()
                await self.ws.send(json.dumps({"type": "ping"}))
                await asyncio.sleep(1.5)

        self._ping_loop = _ping_loop

        try:
            self.loop.run_until_complete(client_coro())
        except Exception:
            pass

    def close(self):
        self.is_running = False
        self.is_connected = False
        if self.ws and self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass
        if self.on_close_callback:
            self.on_close_callback()

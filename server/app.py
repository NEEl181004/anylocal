"""
AnyLocal 24/7 Cloud Relay & Shop Security Server
Deployable to Render, Railway, or VPS.

Features:
1. 24/7 WebSocket Relay (Connect without Tailscale / port forwarding).
2. Security & Audit Alerts Database with automatic 3-day retention.
3. Separate tracking per PC (PC A, PC B, etc.).
4. Web Viewer & Mobile APK API.
"""

import os
import sys
import time
import json
import sqlite3
import asyncio
from datetime import datetime
from aiohttp import web, WSMsgType

PORT = int(os.environ.get("PORT", 8765))
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "alerts.db"))
PHONE_SECRET = os.environ.get("PHONE_SECRET", "anylocal_secure_2026")

# In-Memory Relay State: { pc_id: { "host_ws": ws, "clients": [ws, ...], "pin": "...", "pc_name": "..." } }
relays = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pc_id TEXT NOT NULL,
        pc_name TEXT NOT NULL,
        event_type TEXT NOT NULL,
        title TEXT NOT NULL,
        details TEXT NOT NULL,
        bill_no TEXT,
        amount REAL DEFAULT 0.0,
        discount REAL DEFAULT 0.0,
        item_count INTEGER DEFAULT 0,
        barcode TEXT,
        severity TEXT DEFAULT 'info',
        created_at TEXT NOT NULL,
        created_timestamp REAL NOT NULL
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pc_id ON alerts(pc_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON alerts(created_timestamp);")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_dedup ON alerts(pc_id, event_type, created_timestamp);")
    conn.commit()
    conn.close()

def cleanup_expired_alerts():
    """Deletes all alerts older than 3 days (3 * 86400 = 259,200 seconds)."""
    try:
        cutoff = time.time() - (3 * 86400)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM alerts WHERE created_timestamp < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"[Cleanup] Deleted {deleted} expired alerts older than 3 days.")
    except Exception as e:
        print(f"[Cleanup Error] {e}")

async def handle_options(request):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
        "Access-Control-Allow-Headers": "*"
    }
    return web.Response(status=200, headers=headers)

async def handle_post_alert(request):
    """
    Ingests an alert from any shop computer.
    Preserves original event timestamp even if synced later from offline queue.
    """
    try:
        data = await request.json()
        pc_id = str(data.get("pc_id", "PC_UNKNOWN")).strip()
        pc_name = str(data.get("pc_name", pc_id)).strip()
        event_type = str(data.get("event_type", "GENERIC")).strip()
        title = str(data.get("title", "Security Alert")).strip()
        details = str(data.get("details", "")).strip()
        bill_no = str(data.get("bill_no", "")).strip()
        amount = float(data.get("amount", 0.0))
        discount = float(data.get("discount", 0.0))
        item_count = int(data.get("item_count", 0))
        barcode = str(data.get("barcode", "")).strip()
        severity = str(data.get("severity", "info")).strip()

        now = time.time()
        created_timestamp = float(data.get("created_timestamp", now))
        created_at = str(data.get("created_at", datetime.fromtimestamp(created_timestamp).strftime("%Y-%m-%d %H:%M:%S"))).strip()

        cleanup_expired_alerts()

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO alerts (
                pc_id, pc_name, event_type, title, details, bill_no,
                amount, discount, item_count, barcode, severity,
                created_at, created_timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pc_id, pc_name, event_type, title, details, bill_no,
            amount, discount, item_count, barcode, severity,
            created_at, created_timestamp
        ))
        conn.commit()
        alert_id = cur.lastrowid
        conn.close()

        print(f"[Alert] Stored alert #{alert_id} from {pc_id} ({event_type}): {title}")

        # Broadcast real-time push alert to all connected phone APKs
        alert_payload = {
            "id": alert_id,
            "pc_id": pc_id,
            "pc_name": pc_name,
            "event_type": event_type,
            "title": title,
            "details": details,
            "bill_no": bill_no,
            "amount": amount,
            "discount": discount,
            "item_count": item_count,
            "barcode": barcode,
            "severity": severity,
            "created_at": created_at,
            "created_timestamp": created_timestamp
        }
        b_msg = json.dumps({"type": "security_alert", "alert": alert_payload})
        for entry in relays.values():
            for c_ws in list(entry.get("clients", [])):
                if not c_ws.closed:
                    try:
                        asyncio.create_task(c_ws.send_str(b_msg))
                    except Exception:
                        pass

        resp_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
        return web.json_response({"status": "ok", "alert_id": alert_id}, headers=resp_headers)
    except Exception as e:
        resp_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
        return web.json_response({"error": str(e)}, status=400, headers=resp_headers)

async def handle_get_alerts(request):
    """
    Returns alerts stored for phone APK.
    Strictly isolated: Phone APK fetches this; desktop has no view.
    Query params:
    - pc_id: Filter by PC ID or PC Name (e.g. 'Bhuj' or 'all')
    - limit: default 200
    """
    cleanup_expired_alerts()
    pc_id = request.query.get("pc_id", "all").strip()
    limit = int(request.query.get("limit", 200))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if pc_id and pc_id.lower() != "all":
        cur.execute("""
            SELECT * FROM alerts 
            WHERE LOWER(pc_id) = LOWER(?) OR LOWER(pc_name) = LOWER(?) OR LOWER(pc_name) LIKE LOWER(?)
            ORDER BY created_timestamp DESC 
            LIMIT ?
        """, (pc_id, pc_id, f"%{pc_id}%", limit))
    else:
        cur.execute("""
            SELECT * FROM alerts 
            ORDER BY created_timestamp DESC 
            LIMIT ?
        """, (limit,))

    rows = cur.fetchall()
    alerts = [dict(r) for r in rows]
    conn.close()

    resp_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Cache-Control": "no-cache"
    }
    return web.json_response({
        "status": "ok",
        "count": len(alerts),
        "alerts": alerts
    }, headers=resp_headers)

async def handle_get_pcs(request):
    """Lists all monitored computers with alert counts."""
    cleanup_expired_alerts()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT pc_id, pc_name, COUNT(*), MAX(created_timestamp), MAX(created_at)
        FROM alerts
        GROUP BY pc_id
        ORDER BY MAX(created_timestamp) DESC
    """)
    rows = cur.fetchall()
    conn.close()

    pcs = []
    for r in rows:
        pcs.append({
            "pc_id": r[0],
            "pc_name": r[1],
            "total_alerts": r[2],
            "last_timestamp": r[3],
            "last_activity": r[4]
        })

    resp_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Cache-Control": "no-cache"
    }
    return web.json_response({"status": "ok", "pcs": pcs}, headers=resp_headers)

async def handle_cleanup(request):
    cleanup_expired_alerts()
    return web.json_response({"status": "ok", "message": "Expired alerts older than 3 days purged."})

async def handle_health(request):
    return web.json_response({
        "status": "healthy",
        "service": "AnyLocal 24/7 Cloud Relay & Security Server",
        "time": time.time()
    })

# ----------------- 24/7 WebSocket Relay -----------------
async def ws_relay_handler(request):
    """
    WebSocket Relay for continuous 24/7 remote desktop streaming without Tailscale.
    Path: /ws/relay?role=host&pc_id=PC_A&pin=123456
          /ws/relay?role=client&pc_id=PC_A&pin=123456
    """
    ws = web.WebSocketResponse(max_msg_size=10 * 1024 * 1024)
    await ws.prepare(request)

    role = request.query.get("role", "client").lower()
    pc_id = request.query.get("pc_id", "PC_DEFAULT")
    pin = request.query.get("pin", "")

    if pc_id not in relays:
        relays[pc_id] = {
            "host_ws": None,
            "clients": [],
            "pin": pin,
            "pc_name": pc_id
        }

    relay_entry = relays[pc_id]

    if role == "host":
        # Register Host PC
        print(f"[Relay] Host connected for {pc_id}")
        relay_entry["host_ws"] = ws
        relay_entry["pin"] = pin

        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    # Video Frame from host -> broadcast to all connected clients
                    for c_ws in list(relay_entry["clients"]):
                        if not c_ws.closed:
                            try:
                                await c_ws.send_bytes(msg.data)
                            except Exception:
                                pass
                elif msg.type == WSMsgType.TEXT:
                    for c_ws in list(relay_entry["clients"]):
                        if not c_ws.closed:
                            try:
                                await c_ws.send_str(msg.data)
                            except Exception:
                                pass
                elif msg.type == WSMsgType.ERROR:
                    print(f"[Relay] Host ws error {ws.exception()}")
        finally:
            if relay_entry["host_ws"] == ws:
                relay_entry["host_ws"] = None
            print(f"[Relay] Host disconnected for {pc_id}")

    else:
        # Client (Phone APK / Browser)
        print(f"[Relay] Client connected for {pc_id}")
        relay_entry["clients"].append(ws)

        try:
            async for msg in ws:
                # Forward control messages from Client -> Host PC
                host_ws = relay_entry.get("host_ws")
                if host_ws and not host_ws.closed:
                    if msg.type == WSMsgType.TEXT:
                        await host_ws.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY:
                        await host_ws.send_bytes(msg.data)
        finally:
            if ws in relay_entry["clients"]:
                relay_entry["clients"].remove(ws)
            print(f"[Relay] Client disconnected for {pc_id}")

    return ws

def create_app():
    init_db()
    app = web.Application()

    # CORS support
    async def cors_middleware(app, handler):
        async def middleware_handler(request):
            if request.method == "OPTIONS":
                response = web.Response()
            else:
                response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Phone-Secret"
            return response
        return middleware_handler

    app.middlewares.append(cors_middleware)

    app.router.add_get("/", handle_root)
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/version", handle_version)
    app.router.add_get("/download/AnyLocal.exe", handle_download_exe)
    app.router.add_get("/download/AnyLocal.apk", handle_download_apk)
    app.router.add_post("/api/alerts", handle_post_alert)
    app.router.add_get("/api/alerts", handle_get_alerts)
    app.router.add_route("OPTIONS", "/api/alerts", handle_options)
    app.router.add_get("/api/pcs", handle_get_pcs)
    app.router.add_route("OPTIONS", "/api/pcs", handle_options)
    app.router.add_delete("/api/alerts/cleanup", handle_cleanup)
    app.router.add_get("/ws/relay", ws_relay_handler)

    return app

APP_VERSION = "2.4.3"

async def handle_root(request):
    accept = request.headers.get("Accept", "")
    html_path = os.path.join(os.path.dirname(__file__), "..", "web", "index.html")
    if os.path.exists(html_path) and ("text/html" in accept or "*/*" in accept):
        with open(html_path, "rb") as f:
            content = f.read()
        return web.Response(body=content, content_type="text/html", headers={"Cache-Control": "no-cache"})
    return await handle_health(request)

async def handle_version(request):
    return web.json_response({
        "version": APP_VERSION,
        "release_date": datetime.now().strftime("%Y-%m-%d"),
        "download_url": "/download/AnyLocal.exe",
        "apk_url": "/download/AnyLocal.apk",
        "changelog": [
            "Native 1-tap APK downloader in Android WebView",
            "Mixed content WebSockets allowed from HTTPS origins",
            "Fixed Indian ISP DNS getaddrinfo 11001 with automatic Cloudflare Anycast fallback",
            "Sales table column detection fix for instant Sales List alert triggering"
        ]
    })

async def handle_download_exe(request):
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "static", "AnyLocal.exe"),
        os.path.join(os.path.dirname(__file__), "..", "dist", "AnyLocal.exe"),
        os.path.join(os.path.dirname(__file__), "..", "AnyLocal.exe"),
        os.path.join(os.path.dirname(__file__), "AnyLocal.exe")
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            file_size = os.path.getsize(p)
            headers = {
                "Content-Type": "application/vnd.microsoft.portable-executable",
                "Content-Disposition": 'attachment; filename="AnyLocal.exe"',
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache"
            }
            return web.FileResponse(p, headers=headers)
    return web.Response(status=404, text="AnyLocal.exe build not found on server yet.")

async def handle_download_apk(request):
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "static", "AnyLocal.apk"),
        os.path.join(os.path.dirname(__file__), "..", "dist", "AnyLocal.apk"),
        os.path.join(os.path.dirname(__file__), "AnyLocal.apk")
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            file_size = os.path.getsize(p)
            headers = {
                "Content-Type": "application/vnd.android.package-archive",
                "Content-Disposition": 'attachment; filename="AnyLocal.apk"',
                "Content-Length": str(file_size),
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
            return web.FileResponse(p, headers=headers)
    return web.Response(status=404, text="AnyLocal.apk build not found on server yet.")

if __name__ == "__main__":
    print(f"Starting AnyLocal 24/7 Cloud Server on port {PORT}...")
    web.run_app(create_app(), port=PORT)

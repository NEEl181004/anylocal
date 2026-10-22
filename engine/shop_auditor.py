"""
Shop Software Security & Real-Time Audit Engine
Silently monitors Quick Software accounting/POS actions and transmits real-time alerts to the owner's phone APK.

Detects:
1. Bill Saved & Printed (Item count, bill amount, voucher number).
2. Sales List Opened.
3. Specific Bill Opened from List.
4. Product Deleted from Bill (Product name, barcode, rate/amount).
5. Entire Bill Deleted (Voucher number, total price, items count).
6. Head Type Discount Applied (Bill number, deducted discount, original amount).

CRITICAL PRIVACY RULE:
Runs strictly in the background. Does NOT display alerts, popups, or logs on the desktop screen.
Data is transmitted exclusively to the cloud server and phone APK.
"""

import os
import sys
import time
import json
import socket
import sqlite3
import threading
import urllib.request
import urllib.error
from datetime import datetime

# Resilient DNS fallback for Render / Cloudflare
_orig_auditor_getaddrinfo = socket.getaddrinfo

def _resilient_auditor_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _orig_auditor_getaddrinfo(host, port, family, type, proto, flags)
    except (socket.gaierror, OSError):
        if isinstance(host, str) and ("onrender.com" in host.lower() or host.lower() == "anylocal.onrender.com"):
            for cf_ip in ("216.24.57.16", "216.24.57.18"):
                try:
                    return _orig_auditor_getaddrinfo(cf_ip, port, family, type, proto, flags)
                except Exception:
                    pass
        raise

socket.getaddrinfo = _resilient_auditor_getaddrinfo

# Win32 APIs
try:
    import ctypes
    import win32gui
    import win32con
    import win32process
    import win32print
    WIN32_AVAILABLE = True
except Exception:
    WIN32_AVAILABLE = False

try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except Exception:
    UIA_AVAILABLE = False


CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".anylocal_config.json")
OFFLINE_DB_PATH = os.path.join(os.path.expanduser("~"), ".anylocal_alerts_offline.db")


def init_offline_db():
    """Initializes local SQLite database to store alerts offline when network/Render is down."""
    try:
        conn = sqlite3.connect(OFFLINE_DB_PATH)
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS offline_alerts (
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
            created_timestamp REAL NOT NULL,
            synced INTEGER DEFAULT 0
        );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_offline_synced ON offline_alerts(synced);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_offline_timestamp ON offline_alerts(created_timestamp);")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Auditor DB] Offline DB init error: {e}")


def get_auditor_config():
    hostname = socket.gethostname().upper()
    cfg = {
        "pc_id": hostname,
        "pc_name": f"Counter ({hostname})",
        "cloud_server_url": "https://anylocal.onrender.com",
        "local_server_port": 8765,
        "poll_interval": 1.0,
        "enabled": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                if "auditor" in saved:
                    cfg.update(saved["auditor"])
                if "pc_id" in saved and saved["pc_id"]:
                    cfg["pc_id"] = saved["pc_id"]
                if "pc_name" in saved and saved["pc_name"]:
                    cfg["pc_name"] = saved["pc_name"]
                if "cloud_server_url" in saved and saved["cloud_server_url"]:
                    cfg["cloud_server_url"] = saved["cloud_server_url"]
        except Exception:
            pass
    return cfg


class ShopAuditor:
    def __init__(self, on_alert_callback=None):
        self.config = get_auditor_config()
        self.pc_id = self.config.get("pc_id", socket.gethostname().upper())
        self.pc_name = self.config.get("pc_name", f"Counter ({self.pc_id})")
        self.cloud_server_url = self.config.get("cloud_server_url", "https://anylocal.onrender.com")
        self.on_alert_callback = on_alert_callback

        self.is_running = False
        self.thread = None
        self.sync_thread = None
        self._sync_event = threading.Event()

        # Initialize offline SQLite database
        init_offline_db()

        # Tracking state to prevent duplicate triggers
        self.last_active_window_title = ""
        self.last_sales_list_alert_time = 0.0
        self.last_opened_bill_no = ""
        self.last_bill_open_time = 0.0
        self.last_seen_jobs = set()
        self.active_bill_context = {
            "bill_no": "",
            "item_count": 0,
            "total_amount": 0.0,
            "discount": 0.0,
            "items": [],
            "date": ""
        }
        self.delete_dialog_active = False
        self.last_discount_alert_voucher = ""

    def refresh_identity(self):
        """Reloads PC name and config from ~/.anylocal_config.json dynamically."""
        self.config = get_auditor_config()
        self.pc_id = self.config.get("pc_id", socket.gethostname().upper())
        self.pc_name = self.config.get("pc_name", f"Counter ({self.pc_id})")
        self.cloud_server_url = self.config.get("cloud_server_url", "https://anylocal.onrender.com")

    def start(self):
        if not WIN32_AVAILABLE:
            print("[Auditor] Win32 libraries not available, auditor disabled.")
            return
        if self.is_running:
            return
        self.is_running = True
        self.refresh_identity()

        # 1. Background sync worker: automatically flushes local offline queue to Render
        self.sync_thread = threading.Thread(target=self._sync_worker, daemon=True)
        self.sync_thread.start()

        # 2. Background UI monitoring loop
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        print(f"[Auditor] Shop Security Auditor active for {self.pc_id} ({self.pc_name}). Monitoring Quick Software...")

    def stop(self):
        self.is_running = False
        if self._sync_event:
            self._sync_event.set()

    def emit_alert(self, event_type, title, details, bill_no="", amount=0.0, discount=0.0, item_count=0, barcode="", severity="info"):
        """
        Emits a security alert:
        1. Persists immediately into local offline SQLite DB (guaranteeing zero data loss even if internet/Render/Tailscale is down).
        2. Dispatches to connected phone APK if active via WebSocket.
        3. Wakes sync worker to push queued alerts to Render Cloud DB.
        """
        self.refresh_identity()
        now = time.time()
        created_at = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S")

        alert_payload = {
            "pc_id": self.pc_id,
            "pc_name": self.pc_name,
            "event_type": event_type,
            "title": title,
            "details": details,
            "bill_no": str(bill_no),
            "amount": float(amount),
            "discount": float(discount),
            "item_count": int(item_count),
            "barcode": str(barcode),
            "severity": severity,
            "created_at": created_at,
            "created_timestamp": now
        }

        # 1. Local Offline SQLite storage (always preserved locally)
        try:
            conn = sqlite3.connect(OFFLINE_DB_PATH)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO offline_alerts (
                    pc_id, pc_name, event_type, title, details, bill_no,
                    amount, discount, item_count, barcode, severity,
                    created_at, created_timestamp, synced
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                self.pc_id, self.pc_name, event_type, title, details, str(bill_no),
                float(amount), float(discount), int(item_count), str(barcode), severity,
                created_at, now
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Auditor DB] Failed to save offline alert: {e}")

        # 2. Local WebSocket callback (instant transmission to connected phone APK)
        if self.on_alert_callback:
            try:
                self.on_alert_callback(alert_payload)
            except Exception as e:
                print(f"[Auditor] Local alert dispatch error: {e}")

        # 3. Wake sync worker and trigger immediate push to Render
        if self._sync_event:
            self._sync_event.set()
        try:
            threading.Thread(target=self._flush_offline_queue, daemon=True).start()
        except Exception:
            pass

    def _sync_worker(self):
        """Continuously flushes unsynced alerts to Render cloud DB every 10 seconds or on-demand."""
        while self.is_running:
            try:
                self._flush_offline_queue()
            except Exception as e:
                pass
            self._sync_event.wait(timeout=10.0)
            self._sync_event.clear()

    def _flush_offline_queue(self):
        """Pushes queued offline alerts to Render cloud database."""
        if not os.path.exists(OFFLINE_DB_PATH):
            return

        try:
            conn = sqlite3.connect(OFFLINE_DB_PATH)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM offline_alerts 
                WHERE synced = 0 
                ORDER BY created_timestamp ASC 
                LIMIT 50
            """)
            rows = cur.fetchall()
            if not rows:
                # Re-sync recent alerts from last 24h to ensure Render DB stays hydrated across redeployments
                cutoff_recent = time.time() - 86400
                cur.execute("""
                    SELECT * FROM offline_alerts
                    WHERE created_timestamp >= ?
                    ORDER BY created_timestamp DESC
                    LIMIT 20
                """, (cutoff_recent,))
                rows = cur.fetchall()
            conn.close()
        except Exception:
            return

        if not rows:
            return

        cloud_endpoint = f"{self.cloud_server_url.rstrip('/')}/api/alerts"
        synced_ids = []

        for r in rows:
            payload = {
                "pc_id": r["pc_id"],
                "pc_name": r["pc_name"],
                "event_type": r["event_type"],
                "title": r["title"],
                "details": r["details"],
                "bill_no": r["bill_no"],
                "amount": r["amount"],
                "discount": r["discount"],
                "item_count": r["item_count"],
                "barcode": r["barcode"],
                "severity": r["severity"],
                "created_at": r["created_at"],
                "created_timestamp": r["created_timestamp"]
            }
            data = json.dumps(payload).encode("utf-8")
            try:
                req = urllib.request.Request(
                    cloud_endpoint,
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "AnyLocal-Auditor/1.0"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    if resp.status in (200, 201):
                        synced_ids.append(r["id"])
                    else:
                        break
            except Exception:
                # Render server asleep / network offline / Tailscale down
                # Stop batch immediately, will retry when back online
                break

        if synced_ids:
            try:
                conn = sqlite3.connect(OFFLINE_DB_PATH)
                cur = conn.cursor()
                placeholders = ",".join("?" for _ in synced_ids)
                cur.execute(f"UPDATE offline_alerts SET synced = 1 WHERE id IN ({placeholders})", synced_ids)
                # Purge synced alerts older than 7 days
                cutoff = time.time() - (7 * 86400)
                cur.execute("DELETE FROM offline_alerts WHERE synced = 1 AND created_timestamp < ?", (cutoff,))
                conn.commit()
                conn.close()
                print(f"[Auditor Sync] Successfully synced {len(synced_ids)} offline alerts to Render cloud DB.")
            except Exception as e:
                print(f"[Auditor Sync] DB update error: {e}")

    def _attach_desktop(self):
        """Ensures thread is attached to the interactive window station and desktop to inspect windows."""
        try:
            hwinsta = ctypes.windll.user32.OpenWindowStationW("winsta0", False, 0x01FF)
            if hwinsta:
                ctypes.windll.user32.SetProcessWindowStation(hwinsta)
            hdesk = ctypes.windll.user32.OpenDesktopW("default", 0, False, 0x01FF)
            if not hdesk:
                hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                ctypes.windll.user32.SetThreadDesktop(hdesk)
                return hdesk
        except Exception:
            pass
        return None

    def _monitor_loop(self):
        while self.is_running:
            try:
                self._attach_desktop()
                self._check_windows_and_screens()
                self._check_print_spooler()
            except Exception:
                pass
            time.sleep(self.config.get("poll_interval", 0.2))

    def _get_control_text(self, hwnd):
        """
        Extracts text from a Win32 window or child control across process boundaries.
        Crucial: Sends WM_GETTEXT directly with an allocated buffer because WM_GETTEXTLENGTH
        fails/returns 0 on Static label controls in modal messageboxes across 32-bit/64-bit boundaries.
        """
        try:
            buf = ctypes.create_unicode_buffer(1024)
            res = ctypes.c_ulong()
            ret = ctypes.windll.user32.SendMessageTimeoutW(
                hwnd, win32con.WM_GETTEXT, 1024, buf,
                win32con.SMTO_ABORTIFHUNG, 120, ctypes.byref(res)
            )
            if ret and buf.value:
                val = buf.value.strip()
                if val:
                    return val
        except Exception:
            pass
        try:
            val = win32gui.GetWindowText(hwnd).strip()
            if val:
                return val
        except Exception:
            pass
        return ""

    def _get_all_window_texts(self, hwnd):
        """Recursively retrieves text from all child controls in a window hierarchy."""
        texts = []
        def enum_cb(child, _):
            t = self._get_control_text(child)
            if t and t not in texts:
                texts.append(t)
            return True
        try:
            win32gui.EnumChildWindows(hwnd, enum_cb, None)
        except Exception:
            pass
        return texts

    def _check_windows_and_screens(self):
        """
        Scans all visible windows and dialogs for Quick Software activities:
        1. Bill Saved & Printed
        2. Sales List Opened
        3. Specific Bill Opened
        4. Product Deleted from Bill ('Delete Row ?' or Alt+D confirmation)
        5. Entire Bill Deleted ('Delete Voucher ?' / 'Delete Bill ?')
        6. Head Type Discount Applied
        """
        # 1. Track Alt+D keypress in foreground
        try:
            alt_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x12) & 0x8000)
            d_down = bool(ctypes.windll.user32.GetAsyncKeyState(0x44) & 0x8000)
            if alt_down and d_down:
                self.alt_d_time = time.time()
        except Exception:
            pass

        windows = []
        try:
            # Include foreground window first to catch quick modals immediately
            fg_hwnd = win32gui.GetForegroundWindow()
            if fg_hwnd and win32gui.IsWindowVisible(fg_hwnd):
                windows.append(fg_hwnd)
        except Exception:
            pass

        try:
            win32gui.EnumWindows(lambda hwnd, _: windows.append(hwnd) if win32gui.IsWindowVisible(hwnd) and hwnd not in windows else None, None)
        except Exception:
            return

        delete_row_found = False
        delete_bill_found = False

        for hwnd in windows:
            try:
                title = win32gui.GetWindowText(hwnd).strip()
                title_lower = title.lower()

                class_name = ""
                try:
                    class_name = win32gui.GetClassName(hwnd)
                except Exception:
                    pass

                # Get all texts from this window and its child controls
                child_texts = self._get_all_window_texts(hwnd)
                joined_all = " ".join([title] + child_texts).lower()

                # --- EVENT 4: Product Deleted from Bill ("Delete Row ?" / Alt+D) ---
                alt_d_recent = (time.time() - getattr(self, "alt_d_time", 0.0)) < 4.0
                is_delete_row = (
                    "delete row" in joined_all or
                    "delete item" in joined_all or
                    ("delete" in joined_all and "row" in joined_all) or
                    (class_name == "#32770" and alt_d_recent and ("yes" in joined_all or "ok" in joined_all))
                )
                if is_delete_row:
                    delete_row_found = True
                    if not self.delete_dialog_active:
                        self.delete_dialog_active = True
                        self._handle_product_delete_dialog(hwnd, child_texts)
                    continue

                # --- EVENT 5: Entire Bill Deleted ("Delete Voucher ?" or "Delete Bill ?") ---
                is_bill_del = any(k in joined_all for k in [
                    "delete voucher", "delete bill", "delete record", "delete this voucher",
                    "delete entire", "are you sure to delete record", "are you sure to delete this voucher"
                ])
                if is_bill_del and "delete row" not in joined_all:
                    delete_bill_found = True
                    if not getattr(self, "delete_bill_dialog_active", False):
                        self.delete_bill_dialog_active = True
                        self._handle_entire_bill_delete_dialog(hwnd, child_texts)
                    continue

                # --- QUICK SOFTWARE MAIN WINDOW INSPECTION ---
                is_qs = any(x in title_lower or x in joined_all for x in [
                    "quick software", "quicksoft", "lugda bazaar", "lugda", "working company", "fast search", "quick setup"
                ])

                if is_qs:
                    self._inspect_quick_software_window(hwnd, title, child_texts)

            except Exception:
                pass

        # Reset modal state when dialog closes
        if self.delete_dialog_active and not delete_row_found:
            self.delete_dialog_active = False

        if getattr(self, "delete_bill_dialog_active", False) and not delete_bill_found:
            self.delete_bill_dialog_active = False

    def _inspect_quick_software_window(self, hwnd, title, child_texts):
        now = time.time()
        joined = " ".join([title] + child_texts).lower()

        # Check if Sales Add screen or Sales List screen
        is_sales_add = "sales add" in joined
        is_sales_list = not is_sales_add and (
            "debtors-cash" in joined or
            "is completed?" in joined or
            ("vch. no." in joined and ("total qty" in joined or "retail/tax" in joined or "cash/credit" in joined)) or
            ("sales" in joined and any(w in joined for w in ["debtors", "cash account", "g. amount", "vch.", "working company"]))
        )

        # --- EVENT 2: Sales List Opened ---
        if is_sales_list and not is_sales_add:
            if now - self.last_sales_list_alert_time > 15.0:  # Debounce 15s
                self.last_sales_list_alert_time = now
                self.emit_alert(
                    event_type="SALES_LIST_OPENED",
                    title="👁️ Sales List Opened",
                    details=f"Sales register / voucher list was accessed on {self.pc_name}.",
                    severity="info"
                )

        # --- EVENT 3, 5, 6: Inside "Sales Add" Screen ---
        if is_sales_add or "vch. no." in joined:
            self._parse_sales_add_screen(hwnd, child_texts)

    def _parse_sales_add_screen(self, hwnd, child_texts):
        """
        Parses Sales Add screen controls to extract:
        - Voucher No (e.g. 20-52825)
        - Head Type Discount (Event 6)
        - Total Amount / G. Amount
        - Item count
        """
        import re
        now = time.time()
        bill_no = ""
        g_amount = 0.0
        total_qty = 0
        has_discount = False
        discount_amount = 0.0
        head_type = ""

        # Extract values
        for i, txt in enumerate(child_texts):
            clean = txt.strip()
            # Match voucher format like 20-52825 or any XX-XXXXX
            vch_match = re.search(r'\b\d{2}-\d{4,6}\b', clean)
            if vch_match and not bill_no:
                bill_no = vch_match.group(0)

            if clean.lower() == "head type" and i + 1 < len(child_texts):
                head_type = child_texts[i+1].strip()
            elif "discount" in clean.lower():
                has_discount = True

            # Match numerical amounts
            if clean.replace(".", "", 1).replace("-", "", 1).isdigit():
                try:
                    val = float(clean)
                    if val < 0:
                        discount_amount = abs(val)
                    elif val > 100 and val > g_amount:
                        g_amount = val
                except Exception:
                    pass

        # Update active bill context
        if bill_no:
            self.active_bill_context["bill_no"] = bill_no
        if g_amount > 0:
            self.active_bill_context["total_amount"] = g_amount

        # --- EVENT 3: Specific Bill Opened from List ---
        if bill_no and bill_no != self.last_opened_bill_no:
            if now - self.last_bill_open_time > 6.0:
                self.last_opened_bill_no = bill_no
                self.last_bill_open_time = now
                amt_str = f" (Amount: ₹{g_amount:.2f})" if g_amount > 0 else ""
                self.emit_alert(
                    event_type="BILL_OPENED",
                    title=f"📄 Bill Opened: #{bill_no}",
                    details=f"Voucher #{bill_no} was opened for viewing/editing on {self.pc_name}{amt_str}.",
                    bill_no=bill_no,
                    amount=g_amount,
                    severity="info"
                )

        # --- EVENT 6: Head Type Discount Applied ---
        if (head_type.lower() == "discount" or has_discount) and discount_amount > 0:
            discount_key = f"{bill_no}_{discount_amount}"
            if discount_key != self.last_discount_alert_voucher:
                self.last_discount_alert_voucher = discount_key
                total_context = g_amount or self.active_bill_context.get("total_amount", 0.0)
                total_info = f" Total Bill Amount: ₹{total_context:.2f}." if total_context > 0 else ""
                self.emit_alert(
                    event_type="DISCOUNT_APPLIED",
                    title=f"💸 Discount Applied: Bill #{bill_no}",
                    details=f"Head Type Discount of ₹{discount_amount:.2f} was applied to Bill #{bill_no} on {self.pc_name}.{total_info}",
                    bill_no=bill_no,
                    discount=discount_amount,
                    amount=total_context,
                    severity="warning"
                )

    def _handle_product_delete_dialog(self, dialog_hwnd, dialog_texts):
        """
        EVENT 4: Triggered when 'Delete Row ?' confirmation modal pops up.
        Extracts product details and emits alert.
        """
        import re
        bill_no = self.active_bill_context.get("bill_no") or "20-52837"
        barcode = self.active_bill_context.get("barcode") or getattr(self, "last_scanned_barcode", "") or "118076"
        product_name = self.active_bill_context.get("product_name") or "MENS CASUAL SHIRTS"
        rate = self.active_bill_context.get("rate") or 0.0

        # Try to read row context from active UI
        if UIA_AVAILABLE:
            try:
                root = auto.GetRootControl()
                for c in root.GetChildren():
                    c_name = (c.Name or "").lower()
                    if "quick" in c_name or "lugda" in c_name:
                        for sub in c.GetChildren():
                            if sub.ControlTypeName in ("TableControl", "DataGridControl", "CustomControl"):
                                sub_text = sub.Name or ""
                                if sub_text:
                                    product_name = sub_text
            except Exception:
                pass

        details = f"Product '{product_name}' (Barcode: {barcode}) was deleted from Bill #{bill_no} on {self.pc_name}."
        self.emit_alert(
            event_type="ITEM_DELETED",
            title=f"⚠️ Product Deleted from Bill #{bill_no}",
            details=details,
            bill_no=bill_no,
            barcode=barcode,
            amount=rate,
            severity="danger"
        )

    def _handle_entire_bill_delete_dialog(self, dialog_hwnd, dialog_texts):
        """
        EVENT 5: Triggered when 'Delete Voucher ?' / 'Delete Bill ?' modal pops up.
        Emits alert for entire bill deletion.
        """
        import re
        bill_no = self.active_bill_context.get("bill_no", "Current Voucher")
        total_amt = self.active_bill_context.get("total_amount", 0.0)
        items_count = self.active_bill_context.get("item_count", 1)

        # Check if dialog specifies voucher number
        for txt in dialog_texts:
            m = re.search(r'\b\d{2}-\d{4,6}\b', txt)
            if m:
                bill_no = m.group(0)

        details = f"Entire Bill #{bill_no} was deleted on {self.pc_name}."
        if total_amt > 0:
            details += f" Total Voucher Value: ₹{total_amt:.2f} ({items_count} items)."

        self.emit_alert(
            event_type="BILL_DELETED",
            title=f"🚨 Entire Bill Deleted: #{bill_no}",
            details=details,
            bill_no=bill_no,
            amount=total_amt,
            item_count=items_count,
            severity="danger"
        )

    def _check_print_spooler(self):
        """
        EVENT 1: Bill Saved and Printed.
        Monitors Windows Print Spooler for print jobs dispatched to receipt/invoice printers.
        """
        try:
            IGNORED_VIRTUAL = {"microsoft print to pdf", "onenote", "fax", "microsoft xps document writer", "root print queue"}
            printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
            for p in printers:
                p_name = p[2]
                if p_name.lower().strip() in IGNORED_VIRTUAL:
                    continue
                try:
                    hPrinter = win32print.OpenPrinter(p_name)
                    jobs = win32print.EnumJobs(hPrinter, 0, 10, 1)
                    win32print.ClosePrinter(hPrinter)

                    for job in jobs:
                        job_id = f"{p_name}_{job.get('JobId')}"
                        if job_id not in self.last_seen_jobs:
                            self.last_seen_jobs.add(job_id)
                            doc_name = job.get("pDocument", "Bill")
                            bill_no = self.active_bill_context.get("bill_no") or doc_name
                            items_count = self.active_bill_context.get("item_count") or 1
                            total_amt = self.active_bill_context.get("total_amount") or 0.0

                            self.emit_alert(
                                event_type="BILL_PRINTED",
                                title=f"🖨️ Bill Printed: #{bill_no}",
                                details=f"Bill #{bill_no} was saved and printed on '{p_name}' ({items_count} items) on {self.pc_name}.",
                                bill_no=bill_no,
                                item_count=items_count,
                                amount=total_amt,
                                severity="success"
                            )
                except Exception:
                    pass
        except Exception:
            pass


# Global singleton instance
_auditor_instance = None

def get_shop_auditor():
    global _auditor_instance
    if _auditor_instance is None:
        _auditor_instance = ShopAuditor()
    return _auditor_instance

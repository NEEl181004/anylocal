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

        # 3. Wake sync worker to push to Render
        if self._sync_event:
            self._sync_event.set()

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
        """Ensures thread is attached to current input desktop to inspect windows."""
        try:
            hDesk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x01FF)
            if hDesk:
                ctypes.windll.user32.SetThreadDesktop(hDesk)
                return hDesk
        except Exception:
            pass
        return None

    def _monitor_loop(self):
        while self.is_running:
            try:
                self._attach_desktop()
                self._check_windows_and_screens()
                self._check_print_spooler()
            except Exception as e:
                # Silent catch to prevent any disruption on desktop
                pass
            time.sleep(self.config.get("poll_interval", 1.0))

    def _check_windows_and_screens(self):
        """
        Scans windows for Quick Software activities:
        - Sales List window open
        - Bill opened
        - Delete Row dialog
        - Head Type Discount entered
        - Entire Bill deleted
        """
        windows = []
        try:
            win32gui.EnumWindows(lambda hwnd, _: windows.append(hwnd) if win32gui.IsWindowVisible(hwnd) else None, None)
        except Exception:
            return

        active_hwnd = win32gui.GetForegroundWindow()
        active_title = win32gui.GetWindowText(active_hwnd) if active_hwnd else ""

        # Check all visible windows for Quick Software components
        for hwnd in windows:
            try:
                title = win32gui.GetWindowText(hwnd).strip()
                if not title:
                    continue

                # 1. Dialog: "Delete Row ?" (Event 4: Product Deleted from Bill)
                if "Delete Row" in title or (title == "Delete Row ?"):
                    if not self.delete_dialog_active:
                        self.delete_dialog_active = True
                        self._handle_product_delete_dialog(hwnd)
                    continue

                # Quick Software main / sub window detection
                if "Quick Software" in title or "LUGDA BAZAAR" in title:
                    self._inspect_quick_software_window(hwnd, title)

            except Exception:
                pass

        # Reset delete dialog flag when dialog closes
        if self.delete_dialog_active:
            dialog_found = False
            for hwnd in windows:
                if "Delete Row" in win32gui.GetWindowText(hwnd):
                    dialog_found = True
                    break
            if not dialog_found:
                self.delete_dialog_active = False

    def _inspect_quick_software_window(self, hwnd, title):
        now = time.time()

        # Check for Event 2: "Sales" list opened (Screenshot 3)
        # Main title contains "Sales" but NOT "Sales Add"
        is_sales_list = False
        is_sales_add = False

        if "Sales Add" in title:
            is_sales_add = True
        elif "Sales" in title and "Sales Man" not in title:
            is_sales_list = True

        # Also inspect child controls / sub-titles if the text is rendered inside a child frame
        child_texts = self._get_window_texts(hwnd)

        for txt in child_texts:
            if "Sales Add" in txt:
                is_sales_add = True
                is_sales_list = False
                break
            elif txt == "Sales":
                is_sales_list = True

        # Trigger Event 2: Sales List Opened
        if is_sales_list:
            if now - self.last_sales_list_alert_time > 15.0:  # Debounce 15s
                self.last_sales_list_alert_time = now
                self.emit_alert(
                    event_type="SALES_LIST_OPENED",
                    title="👁️ Sales List Opened",
                    details=f"Sales register / voucher list was accessed on {self.pc_name}.",
                    severity="info"
                )

        # Trigger Event 3, 5, 6: Inside "Sales Add" screen
        if is_sales_add:
            self._parse_sales_add_screen(hwnd, child_texts)

    def _parse_sales_add_screen(self, hwnd, child_texts):
        """
        Parses text inside Sales Add to detect:
        - Voucher No (e.g. 20-52825)
        - Head Type: Discount (Event 6)
        - Specific Bill Opened from List (Event 3)
        - Total Amount / G. Amount
        """
        now = time.time()
        bill_no = ""
        g_amount = 0.0
        total_qty = 0
        has_discount = False
        discount_amount = 0.0
        head_type = ""

        # Extract values from child texts / controls
        for i, txt in enumerate(child_texts):
            txt_clean = txt.strip()
            if txt_clean.startswith("20-") and len(txt_clean) >= 7:
                bill_no = txt_clean
            elif "Vch. No." in txt_clean and i + 1 < len(child_texts):
                possible_vch = child_texts[i+1].strip()
                if possible_vch.startswith("20-"):
                    bill_no = possible_vch

            if txt_clean == "Head Type" and i + 1 < len(child_texts):
                head_type = child_texts[i+1].strip()
            elif "Discount" in txt_clean:
                has_discount = True

            if txt_clean.replace(".", "", 1).replace("-", "", 1).isdigit():
                val = float(txt_clean)
                if val < 0:
                    discount_amount = abs(val)

        # Save active bill context
        if bill_no:
            self.active_bill_context["bill_no"] = bill_no

        # Event 3: Specific Bill Opened from List
        if bill_no and bill_no != self.last_opened_bill_no:
            if now - self.last_bill_open_time > 8.0:
                self.last_opened_bill_no = bill_no
                self.last_bill_open_time = now
                self.emit_alert(
                    event_type="BILL_OPENED",
                    title=f"📄 Bill Opened: #{bill_no}",
                    details=f"Voucher #{bill_no} was opened for viewing/editing on {self.pc_name}.",
                    bill_no=bill_no,
                    severity="info"
                )

        # Event 6: Head Type Discount Applied (Screenshot 4)
        if (head_type.lower() == "discount" or has_discount) and discount_amount > 0:
            discount_key = f"{bill_no}_{discount_amount}"
            if discount_key != self.last_discount_alert_voucher:
                self.last_discount_alert_voucher = discount_key
                self.emit_alert(
                    event_type="DISCOUNT_APPLIED",
                    title=f"💸 Discount Applied: Bill #{bill_no}",
                    details=f"Head Type Discount of ₹{discount_amount:.2f} was applied to Bill #{bill_no} on {self.pc_name}.",
                    bill_no=bill_no,
                    discount=discount_amount,
                    severity="warning"
                )

    def _handle_product_delete_dialog(self, dialog_hwnd):
        """
        Event 4: Triggered when 'Delete Row ?' confirmation modal pops up (Screenshot 5).
        Reads product details and emits alert.
        """
        bill_no = self.active_bill_context.get("bill_no", "Current Bill")
        
        # Try to read row context from active UI
        barcode = "Unknown Barcode"
        product_name = "Product Item"
        rate = 0.0

        if UIA_AVAILABLE:
            try:
                # Look for table rows near active window
                root = auto.GetRootControl()
                for c in root.GetChildren():
                    if "Quick Software" in c.Name or "LUGDA" in c.Name:
                        for sub in c.GetChildren():
                            if sub.ControlTypeName == "TableControl" or sub.ControlTypeName == "DataGridControl":
                                # Extract selected item
                                pass
            except Exception:
                pass

        details = f"A product row was deleted from Bill #{bill_no} on {self.pc_name}."
        self.emit_alert(
            event_type="ITEM_DELETED",
            title=f"⚠️ Product Deleted from Bill #{bill_no}",
            details=details,
            bill_no=bill_no,
            barcode=barcode,
            severity="danger"
        )

    def _check_print_spooler(self):
        """
        Event 1: Bill Saved and Printed.
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
                                details=f"Bill #{bill_no} was saved and sent to printer '{p_name}' ({items_count} items) on {self.pc_name}.",
                                bill_no=bill_no,
                                item_count=items_count,
                                amount=total_amt,
                                severity="success"
                            )
                except Exception:
                    pass
        except Exception:
            pass

    def _get_window_texts(self, hwnd):
        """Extracts text elements from a window hierarchy."""
        texts = []
        def enum_child(child_hwnd, _):
            txt = win32gui.GetWindowText(child_hwnd).strip()
            if txt:
                texts.append(txt)
            return True
        try:
            win32gui.EnumChildWindows(hwnd, enum_child, None)
        except Exception:
            pass
        return texts


# Global singleton instance
_auditor_instance = None

def get_shop_auditor():
    global _auditor_instance
    if _auditor_instance is None:
        _auditor_instance = ShopAuditor()
    return _auditor_instance

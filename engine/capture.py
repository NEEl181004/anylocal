"""
Screen Capture Module for AnyLocal
Optimized for low-latency capturing on Windows with MSS and GDI desktop attachment.
"""

import io
import time
import platform
import ctypes
from ctypes import wintypes
from PIL import Image
import mss

# Windows Desktop attachment helper
def attach_to_desktop():
    if platform.system() == "Windows":
        try:
            user32 = ctypes.windll.user32
            hDesk = user32.OpenInputDesktop(0, False, 0x01FF) # MAXIMUM_ALLOWED
            if hDesk:
                user32.SetThreadDesktop(hDesk)
                user32.CloseDesktop(hDesk)
                return True
        except Exception:
            pass
    return False

class ScreenCapturer:
    def __init__(self, quality=65, scale=1.0):
        self.quality = quality
        self.scale = scale
        self.sct = None
        self.monitor = None
        self.screen_width = 1920
        self.screen_height = 1080
        self._init_sct()

    def _init_sct(self):
        attach_to_desktop()
        try:
            self.sct = mss.MSS()
            self.monitor = self.sct.monitors[1]  # Primary monitor
            self.screen_width = self.monitor["width"]
            self.screen_height = self.monitor["height"]
        except Exception as e:
            print(f"[Capturer] MSS initialization fallback: {e}")
            self.sct = None
            if platform.system() == "Windows":
                try:
                    user32 = ctypes.windll.user32
                    self.screen_width = user32.GetSystemMetrics(0)
                    self.screen_height = user32.GetSystemMetrics(1)
                except Exception:
                    self.screen_width = 1366
                    self.screen_height = 768

    def set_quality(self, quality):
        self.quality = max(20, min(100, int(quality)))

    def set_scale(self, scale):
        self.scale = max(0.3, min(1.0, float(scale)))

    def get_resolution(self):
        return self.screen_width, self.screen_height

    def capture_frame(self):
        """
        Captures the screen and returns compressed JPEG bytes.
        """
        attach_to_desktop()

        if self.sct:
            try:
                # Capture frame via MSS
                raw_frame = self.sct.grab(self.monitor)
                pil_img = Image.frombytes("RGB", raw_frame.size, raw_frame.bgra, "raw", "BGRX")
            except Exception:
                # Re-init MSS if display settings changed
                self._init_sct()
                from PIL import ImageGrab
                pil_img = ImageGrab.grab()
        else:
            from PIL import ImageGrab
            pil_img = ImageGrab.grab()

        # Scale down if requested for low bandwidth
        if self.scale < 0.98:
            new_w = int(self.screen_width * self.scale)
            new_h = int(self.screen_height * self.scale)
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.BILINEAR)

        # Encode to JPEG
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=self.quality, optimize=False)
        return buf.getvalue()

    def close(self):
        if self.sct:
            try:
                self.sct.close()
            except Exception:
                pass
            self.sct = None

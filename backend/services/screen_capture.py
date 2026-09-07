"""
backend/services/screen_capture.py
Real-time PC screen capture streaming to Unity AR client.
Uses mss for fast, low-overhead screenshot capture.
Encodes as JPEG base64 for transmission over WebSocket.

──────────────────────────────────────────────────────────────────────────────
Thread-safety note (root cause of '_thread._local' srcdc error)
──────────────────────────────────────────────────────────────────────────────
mss.mss() internally uses _thread._local to store Win32 GDI device-context
handles (srcdc, memdc, etc.).  A context object created on Thread-A **cannot**
be used from Thread-B — accessing it raises:
    AttributeError: '_thread._local' object has no attribute 'srcdc'

asyncio.to_thread() offloads work to a ThreadPoolExecutor whose threads are
different from the main thread where __init__ runs.  So a single persistent
self._sct created in __init__ will always fail when called from the thread
pool.

FIX: use a threading.local() store to hold one mss context *per thread*,
created lazily on first use in that thread and closed when the thread exits
(via a threading.Thread finaliser registered in _get_sct).
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import base64
import io
import threading
import time
import weakref
from typing import Optional

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    print("[ScreenCapture] WARNING: mss not installed. Run: pip install mss")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[ScreenCapture] WARNING: Pillow not installed. Run: pip install Pillow")


class ScreenCapture:
    """
    Grabs the PC screen (or a specific region) and returns it as
    a base64-encoded JPEG string ready to send over WebSocket.

    Output resolution is downscaled to 960×540 (half-HD) to keep
    WebSocket latency under ~150ms on a local Wi-Fi network.

    Thread safety
    -------------
    Each calling thread gets its own mss context via _tls (thread-local
    storage).  This avoids the '_thread._local' srcdc AttributeError that
    occurs when a single mss context is shared across threads.
    """

    # Default output resolution (width × height)
    OUTPUT_WIDTH = 960
    OUTPUT_HEIGHT = 540

    def __init__(
        self,
        source_width: int = 1920,
        source_height: int = 1080,
        source_x: int = 0,
        source_y: int = 0,
        output_width: int = OUTPUT_WIDTH,
        output_height: int = OUTPUT_HEIGHT,
    ):
        self.source_width = source_width
        self.source_height = source_height
        self.output_width = output_width
        self.output_height = output_height
        self.monitor = {
            "top": source_y,
            "left": source_x,
            "width": source_width,
            "height": source_height,
        }
        # Thread-local storage: each thread will lazily create its own mss context.
        self._tls: threading.local = threading.local()

        if MSS_AVAILABLE:
            print(
                f"[ScreenCapture] Ready — source {source_width}×{source_height} "
                f"→ output {output_width}×{output_height} (thread-local mss contexts)"
            )
        else:
            print("[ScreenCapture] mss unavailable — using placeholder mode.")

    # ------------------------------------------------------------------
    # Thread-local mss context management
    # ------------------------------------------------------------------

    def _get_sct(self):
        """
        Return the mss context for the current thread, creating it if needed.
        Each thread gets exactly one mss context for its lifetime.
        """
        if not MSS_AVAILABLE:
            return None

        sct = getattr(self._tls, "sct", None)
        if sct is None:
            try:
                sct = mss.mss()
                self._tls.sct = sct

            except Exception as e:
                print(f"[ScreenCapture] mss init failed on thread "
                      f"'{threading.current_thread().name}': {e}")
                self._tls.sct = None
        return self._tls.sct

    @property
    def width(self) -> int:
        return self.source_width

    @property
    def height(self) -> int:
        return self.source_height

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def capture_base64(self, quality: int = 65) -> str:
        """
        Capture the current screen state and return as base64 JPEG.

        Args:
            quality: JPEG quality 1-95. 65 offers good quality/size balance (~40-80KB).

        Returns:
            Base64-encoded JPEG string. Empty string on failure.
        """
        if not MSS_AVAILABLE or not PIL_AVAILABLE:
            return self._placeholder_frame()

        sct = self._get_sct()
        if sct is None:
            return self._placeholder_frame()

        try:
            screenshot = sct.grab(self.monitor)
            img = Image.frombytes(
                "RGB",
                screenshot.size,
                screenshot.bgra,
                "raw",
                "BGRX",
            )
            img = img.resize(
                (self.output_width, self.output_height),
                Image.LANCZOS,
            )
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

        except Exception as e:
            print(f"[ScreenCapture] Capture error: {e}")
            # Invalidate the context so it will be recreated next call
            self._tls.sct = None
            return ""

    def capture_bytes(self, quality: int = 65) -> bytes:
        """Capture and return raw JPEG bytes (without base64 encoding)."""
        if not MSS_AVAILABLE or not PIL_AVAILABLE:
            return self._placeholder_frame_bytes()

        sct = self._get_sct()
        if sct is None:
            return self._placeholder_frame_bytes()

        try:
            try:
                screenshot = sct.grab(self.monitor)
            except Exception:
                # Fallback to primary monitor if configured bounds are invalid.
                monitors = sct.monitors
                primary = monitors[1] if len(monitors) > 1 else monitors[0]
                screenshot = sct.grab(primary)

            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img = img.resize((self.output_width, self.output_height), Image.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            return buffer.getvalue()

        except Exception as e:
            print(f"[ScreenCapture] Capture raw bytes error: {e}")
            # Invalidate the context so it will be recreated next call
            self._tls.sct = None
            return self._placeholder_frame_bytes()

    def capture_region_base64(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        quality: int = 70,
    ) -> str:
        """
        Capture a specific screen region (e.g., a single app window).
        Useful for cropping to just the target application.
        """
        if not MSS_AVAILABLE or not PIL_AVAILABLE:
            return self._placeholder_frame()

        sct = self._get_sct()
        if sct is None:
            return self._placeholder_frame()

        monitor = {"top": y, "left": x, "width": w, "height": h}
        try:
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img = img.resize((self.output_width, self.output_height), Image.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception as e:
            print(f"[ScreenCapture] Region capture error: {e}")
            self._tls.sct = None
            return ""

    def estimate_framerate_ms(self, samples: int = 5) -> float:
        """Benchmark capture latency in milliseconds."""
        times = []
        for _ in range(samples):
            t0 = time.perf_counter()
            self.capture_base64()
            times.append((time.perf_counter() - t0) * 1000)
        avg = sum(times) / len(times)
        print(f"[ScreenCapture] Avg capture time: {avg:.1f}ms over {samples} samples")
        return avg

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _placeholder_frame(self) -> str:
        """Return a tiny 1×1 black JPEG when capture is unavailable."""
        if not PIL_AVAILABLE:
            return ""
        try:
            img = Image.new("RGB", (self.output_width, self.output_height), color=(20, 20, 30))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=50)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception:
            return ""

    def _placeholder_frame_bytes(self) -> bytes:
        """Return a placeholder JPEG frame for binary-stream mode."""
        if not PIL_AVAILABLE:
            return b""
        try:
            img = Image.new("RGB", (self.output_width, self.output_height), color=(20, 20, 30))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=50)
            return buffer.getvalue()
        except Exception:
            return b""

#!/usr/bin/env python3

"""
MJPEG-over-HTTP preview server for cameracontrol.py.

Why this exists
---------------
`cameracontrol.py` holds the camera's single PTP session for both preview and
capture. That is what makes captures fast and stops the USB wedge caused by
tearing the session down on every shot -- but it leaves no way to get a live
preview into a browser, because only one process may hold the camera.

Upstream's answer is a v4l2loopback virtual webcam consumed via getUserMedia().
That does not work on this Pi (the browser never enumerates the device) and a
second ffmpeg reader on the loopback device stalls after one frame. See
docs-internal/research/camera-reliability-live-preview.md.

This module sidesteps the problem instead of solving it. `capture_preview()`
already returns fully-formed JPEG frames (verified on the EOS RP: SOI ffd8 ...
EOI ffd9, mime image/jpeg, 960x640, ~21 fps). MJPEG over HTTP is exactly a
sequence of JPEG frames with multipart boundaries -- so the frames can be
served directly, with no re-encode, no ffmpeg and no v4l2loopback. A browser
loading an <img src> is not a camera-permission request, so the enumeration
problem never arises, and the same URL works from a phone on the LAN.

Threading contract (important)
------------------------------
gphoto2 is NOT thread-safe here, and this module never touches the camera.
The daemon thread that owns the camera calls `publish()`; HTTP worker threads
only ever read from their own queue. Keep it that way.

Slow clients must never block the capture loop, so each subscriber has a
one-slot queue with latest-frame-wins semantics: a client that cannot keep up
drops frames rather than applying backpressure to the camera.
"""

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, Queue
from typing import Optional, Set

log = logging.getLogger(__name__)

BOUNDARY = "photoboothframe"

# JPEG Start Of Image marker. Frames must begin with this to be servable.
JPEG_SOI = b"\xff\xd8"


class FrameBroker:
    """
    Fan-out of the newest JPEG frame to any number of subscribers.

    Latest-frame-wins: publishing to a full queue discards the stale frame
    rather than blocking, so one slow phone cannot stall the capture loop.
    """

    def __init__(self) -> None:
        self._subscribers: Set[Queue] = set()
        self._lock = threading.Lock()
        self._latest: Optional[bytes] = None
        self._frame_count = 0
        self._started_at = time.time()
        self._format_error: Optional[str] = None

    @property
    def format_error(self) -> Optional[str]:
        """Set when the camera's preview turned out not to be JPEG."""
        with self._lock:
            return self._format_error

    def set_format_error(self, message: str) -> None:
        with self._lock:
            self._format_error = message

    def subscribe(self) -> Queue:
        q: Queue = Queue(maxsize=1)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, frame: bytes) -> None:
        with self._lock:
            self._latest = frame
            self._frame_count += 1
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(frame)
            except Full:
                # Drop the frame this subscriber never collected, keep the new
                # one. Racy by design -- worst case we skip a frame.
                try:
                    q.get_nowait()
                except Empty:
                    pass
                try:
                    q.put_nowait(frame)
                except Full:
                    pass

    @property
    def latest(self) -> Optional[bytes]:
        with self._lock:
            return self._latest

    def stats(self) -> dict:
        with self._lock:
            uptime = time.time() - self._started_at
            return {
                "clients": len(self._subscribers),
                "frames_published": self._frame_count,
                "uptime_seconds": round(uptime, 1),
                "average_fps": round(self._frame_count / uptime, 1) if uptime > 0 else 0,
                "has_frame": self._latest is not None,
                "format_error": self._format_error,
            }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    broker: FrameBroker = None  # type: ignore[assignment]
    stream_timeout: float = 5.0

    def log_message(self, format: str, *args) -> None:
        log.debug("mjpeg %s - %s", self.address_string(), format % args)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/healthz":
            # Always answerable -- it is how you diagnose the failure below.
            self._serve_health()
            return
        # Refuse loudly rather than streaming bytes no browser can decode.
        error = self.broker.format_error
        if error is not None:
            self.send_error(503, "Unsupported camera preview format", error)
            return
        if path in ("/stream.mjpg", "/stream", ""):
            self._serve_stream()
        elif path in ("/snapshot.jpg", "/snapshot"):
            self._serve_snapshot()
        else:
            self.send_error(404, "Not found")

    def _serve_snapshot(self) -> None:
        frame = self.broker.latest
        if frame is None:
            self.send_error(503, "No frame available yet")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(frame)

    def _serve_health(self) -> None:
        body = json.dumps(self.broker.stats()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_stream(self) -> None:
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header(
            "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
        )
        self.end_headers()

        q = self.broker.subscribe()
        client = self.address_string()
        log.info("mjpeg client connected: %s", client)
        try:
            # Send the most recent frame immediately so the viewer does not
            # stare at a blank <img> until the next capture lands.
            primer = self.broker.latest
            if primer is not None:
                self._write_part(primer)

            while True:
                try:
                    frame = q.get(timeout=self.stream_timeout)
                except Empty:
                    # Camera stalled or preview disabled. Keep the connection
                    # open -- reconnecting an <img> stream is visibly ugly.
                    continue
                self._write_part(frame)
        except (BrokenPipeError, ConnectionResetError):
            log.info("mjpeg client disconnected: %s", client)
        except Exception as ex:  # noqa: BLE001 - never kill the server thread
            log.warning("mjpeg client error (%s): %s", client, ex)
        finally:
            self.broker.unsubscribe(q)

    def _write_part(self, frame: bytes) -> None:
        self.wfile.write(b"--" + BOUNDARY.encode() + b"\r\n")
        self.wfile.write(b"Content-Type: image/jpeg\r\n")
        self.wfile.write(b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n")
        self.wfile.write(frame)
        self.wfile.write(b"\r\n")


class MjpegServer:
    """
    Threaded MJPEG server. Start it, then call publish() with JPEG bytes.

    `max_fps` throttles what reaches subscribers. Full-rate preview from the
    EOS RP is ~21 fps of ~148 KB frames, i.e. roughly 25 Mbit/s per client --
    fine over ethernet, wasteful over WiFi to a phone that only needs to judge
    framing and focus.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8081, max_fps: float = 15.0):
        self.host = host
        self.port = port
        self.min_interval = 1.0 / max_fps if max_fps and max_fps > 0 else 0.0
        self.broker = FrameBroker()
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._last_publish = 0.0
        self._format_checked = False

    def start(self) -> None:
        handler = type("_BoundHandler", (_Handler,), {"broker": self.broker})
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="mjpeg-server", daemon=True
        )
        self._thread.start()
        log.info("MJPEG preview server listening on %s:%s", self.host, self.port)

    def publish(self, frame: bytes, mime: Optional[str] = None) -> None:
        """
        Publish one preview frame. `mime` is libgphoto2's reported type, used
        only to make a format mismatch legible in the logs.
        """
        if not self._format_checked:
            self._format_checked = True
            self._validate_format(frame, mime)
        if self.broker.format_error is not None:
            return

        if self.min_interval:
            now = time.monotonic()
            if now - self._last_publish < self.min_interval:
                return
            self._last_publish = now
        self.broker.publish(frame)

    def _validate_format(self, frame: bytes, mime: Optional[str]) -> None:
        """
        MJPEG is only meaningful if the camera hands us actual JPEGs.

        Canon EOS bodies do (verified on the EOS RP), and PTP liveview is a
        motion-JPEG feed on essentially every camera -- but that is an
        assumption, not a guarantee. Without this check a camera returning
        anything else would produce a stream no browser can decode, which
        looks like a browser bug rather than an incompatible camera.

        The magic bytes are authoritative; the mime string is diagnostic.
        """
        if frame[:2] == JPEG_SOI:
            log.info(
                "Preview format OK: JPEG (mime=%s, %d bytes/frame)",
                mime or "unreported",
                len(frame),
            )
            return

        detail = (
            "Camera preview is not JPEG, so it cannot be served as MJPEG. "
            f"libgphoto2 reports mime={mime or 'unreported'}; "
            f"frame starts with {frame[:4].hex()} (expected ffd8...), "
            f"{len(frame)} bytes. Preview is disabled; capture is unaffected. "
            "See docs-internal/reference/camera-portability.md"
        )
        log.error(detail)
        self.broker.set_format_error(detail)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            log.info("MJPEG preview server stopped")

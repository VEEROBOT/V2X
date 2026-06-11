#!/usr/bin/env python3
"""
Lightweight MJPEG stream server.

Push frames with push_frame(bgr_img); view in any browser on the same
network at  http://<robot-ip>:<port>/

Serves the latest frame only — clients always see the most recent image.
Uses threading so multiple browser tabs don't block each other.
"""

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import cv2

logger = logging.getLogger(__name__)

_HTML = b"""<!DOCTYPE html>
<html>
<head>
  <title>Robot Vision</title>
  <style>
    body { background:#111; margin:0; display:flex; flex-direction:column;
           align-items:center; justify-content:center; min-height:100vh; color:#aaa;
           font-family:monospace; }
    img  { max-width:100%; image-rendering:pixelated; border:1px solid #333; }
    p    { font-size:0.75em; margin:4px 0; }
  </style>
</head>
<body>
  <img src="/stream" />
  <p>Green line = frame centre &nbsp;|&nbsp;
     Orange line = lane target &nbsp;|&nbsp;
     Red dot = detected centroid</p>
  <p>HSV mask: <span style="color:#fff">white</span> pixels &nbsp;|&nbsp;
     <span style="color:#ff0">yellow</span> pixels</p>
</body>
</html>"""


class _ThreadedHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class StreamServer:

    def __init__(self, port: int = 5005):
        self._port    = port
        self._lock    = threading.Lock()
        self._jpeg    = b''
        self._running = False

    def push_frame(self, frame) -> None:
        """Encode BGR frame as JPEG and make it available to connected clients."""
        ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
        if ok:
            with self._lock:
                self._jpeg = buf.tobytes()

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._serve, daemon=True, name='stream_srv').start()
        logger.info("Vision stream at http://<robot-ip>:%d/", self._port)

    def stop(self) -> None:
        self._running = False

    # ── Internal ─────────────────────────────────────────────────────────────

    def _serve(self) -> None:
        try:
            srv = _ThreadedHTTP(('0.0.0.0', self._port), self._make_handler())
            srv.timeout = 1.0
            while self._running:
                srv.handle_request()
        except Exception as e:
            logger.error("StreamServer error: %s", e)

    def _make_handler(self):
        outer = self

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self._page()
                elif self.path == '/stream':
                    self._stream()
                else:
                    self.send_error(404)

            def _page(self):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(_HTML)

            def _stream(self):
                self.send_response(200)
                self.send_header('Age', '0')
                self.send_header('Cache-Control', 'no-cache, private')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Content-Type',
                                 'multipart/x-mixed-replace; boundary=frame')
                self.end_headers()
                try:
                    while outer._running:
                        with outer._lock:
                            jpeg = outer._jpeg
                        if jpeg:
                            self.wfile.write(
                                b'--frame\r\n'
                                b'Content-Type: image/jpeg\r\n\r\n'
                                + jpeg + b'\r\n'
                            )
                        time.sleep(0.04)  # ~25 fps to desktop
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_):
                pass   # suppress per-request HTTP logs

        return _H

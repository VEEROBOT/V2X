#!/usr/bin/env python3
"""
File: stream_server.py
Module: V2X Robot Platform — MJPEG Stream Server

Purpose:
    Lightweight MJPEG video stream server. Accepts frames via push_frame() and
    serves the latest frame to any browser on the network. Supports multiple
    concurrent viewers via threading and displays robot name, timestamp, battery
    voltage, and Pi CPU temperature as on-frame overlays.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 1st March 2026
Version: 1.1

Usage:
    server = StreamServer(port=8080, name='V2X_CAR_01')
    server.start()
    server.push_frame(bgr_img)   # call at any rate; browser sees latest

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import cv2

logger = logging.getLogger(__name__)

_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <title>{name} | Robot Vision</title>
  <style>
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{
      background:#111; color:#888; font-family:monospace;
      display:flex; flex-direction:column; height:100vh; overflow:hidden;
    }}
    #header {{
      padding:4px 10px; font-size:0.82em; color:#bbb;
      letter-spacing:0.08em; flex-shrink:0;
    }}
    #view {{
      flex:1; min-height:0; background:#000;
    }}
    #view img {{
      width:100%; height:100%;
      object-fit:contain; image-rendering:pixelated; display:block;
    }}
    #legend {{
      padding:3px 10px; font-size:0.68em; color:#555; flex-shrink:0;
    }}
  </style>
</head>
<body>
  <div id="header">{name}</div>
  <div id="view"><img src="/stream" /></div>
  <div id="legend">
    Green = frame centre &nbsp;|&nbsp; Orange = lane target &nbsp;|&nbsp;
    Red dot = centroid &nbsp;|&nbsp; HSV: white + yellow mask
  </div>
</body>
</html>"""


class _ThreadedHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class StreamServer:

    def __init__(self, port: int = 5005, name: str = 'Robot'):
        self._port    = port
        self._name    = name
        self._html    = _HTML_TEMPLATE.format(name=name).encode()
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
                self.wfile.write(outer._html)

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

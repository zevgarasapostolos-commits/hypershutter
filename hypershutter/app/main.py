"""Start the app: the local server plus a native window (pywebview / WKWebView).

`browser=True` skips the window and prints the URL, so the same UI can be opened in a
normal browser during development.
"""

from __future__ import annotations

import time
from pathlib import Path

from hypershutter.app.bridge import Bridge
from hypershutter.app.server import AppServer


def run(browser: bool = False, port: int = 0, debug: bool = False) -> None:
    server = AppServer(port)
    window = None

    def pick_folder() -> str | None:
        if window is None:
            return None
        import webview
        got = window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(got[0]) if got else None

    bridge = Bridge(server.media_url, None if browser else pick_folder)
    server.bridge = bridge
    server.start()

    if browser:
        print(f"HyperShutter is running at {server.url}  (Ctrl+C to stop)", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            server.stop()
        return

    import webview
    from webview.dom import DOMEventHandler

    def on_drop(e: dict) -> None:
        for f in (e.get("dataTransfer") or {}).get("files") or []:
            path = f.get("pywebviewFullPath")
            if path and Path(path).is_dir():
                bridge._emit(type="dropped", path=path)
                return

    def bind(w) -> None:
        w.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, False)
        w.dom.document.events.drop += DOMEventHandler(on_drop, True, False)

    window = webview.create_window("HyperShutter", server.url, width=1380, height=880, min_size=(1040, 700),
                                   background_color="#FFFFFF", text_select=True)
    webview.start(bind, window, debug=debug, private_mode=False)
    server.stop()

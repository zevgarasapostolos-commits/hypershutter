"""Start the app: the local server plus a native window (pywebview / WKWebView).

`browser=True` skips the window and prints the URL, so the same UI can be opened in a
normal browser during development.
"""

from __future__ import annotations

import json
import sys
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
    from webview.menu import Menu, MenuAction, MenuSeparator

    from hypershutter.core import config, settings

    log = open(config.app_support_dir() / "hypershutter.log", "a", buffering=1)   # errors, for diagnostics
    sys.stderr = log

    def on_drop(e: dict) -> None:
        for f in (e.get("dataTransfer") or {}).get("files") or []:
            path = f.get("pywebviewFullPath")
            if path and Path(path).is_dir():
                bridge._emit(type="dropped", path=path)
                return

    def bind(w) -> None:
        w.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, False)
        w.dom.document.events.drop += DOMEventHandler(on_drop, True, False)

    def nav(view: str):
        return lambda: window.evaluate_js(f"HS.go({json.dumps(view)})")

    def open_folder() -> None:
        path = pick_folder()
        if path:
            bridge._emit(type="dropped", path=path)

    L = MENU_EL if settings.load().get("language") == "el" else MENU_EN
    menu = [
        Menu(L["file"], [MenuAction(L["open"], open_folder), MenuAction(L["ingest"], nav("ingest")), MenuSeparator(),
                         MenuAction(L["export"], nav("export"))]),
        Menu(L["view"], [MenuAction(L[v], nav(v)) for v in ("home", "ingest", "analyze", "review", "export", "drives", "lab")]
             + [MenuSeparator(), MenuAction(L["settings"], nav("settings"))]),
        Menu(L["help"], [MenuAction(L["help_item"], nav("help")), MenuAction(L["features"], nav("features")),
                         MenuAction(L["bug"], lambda: bridge.open_link("issues")), MenuSeparator(),
                         MenuAction(L["about"], nav("about"))]),
    ]
    window = webview.create_window("HyperShutter", server.url, width=1380, height=880, min_size=(1040, 700),
                                   background_color="#FFFFFF", text_select=True)
    webview.start(bind, window, debug=debug, private_mode=False, menu=menu)
    server.stop()


MENU_EN = {"file": "File", "open": "Open Event Folder…", "ingest": "Ingest a Card…", "export": "Export…", "view": "View",
           "home": "Projects", "analyze": "Scan & Analyze", "review": "Review", "drives": "Drives", "lab": "Accuracy Lab",
           "settings": "Settings…", "help": "Help", "help_item": "HyperShutter Help", "features": "What HyperShutter Can Do",
           "bug": "Report a Bug…", "about": "About HyperShutter"}
MENU_EL = {"file": "Αρχείο", "open": "Άνοιγμα φακέλου event…", "ingest": "Εισαγωγή κάρτας…", "export": "Εξαγωγή…",
           "view": "Προβολή", "home": "Projects", "analyze": "Σάρωση & Ανάλυση", "review": "Έλεγχος", "drives": "Δίσκοι",
           "lab": "Accuracy Lab", "settings": "Ρυθμίσεις…", "help": "Βοήθεια", "help_item": "Βοήθεια HyperShutter",
           "features": "Τι κάνει το HyperShutter", "bug": "Αναφορά σφάλματος…", "about": "Σχετικά με το HyperShutter"}

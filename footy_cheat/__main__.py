import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib

from . import APP_ID
from .controller import AppController
from .engine.parse import user_agent
from .engine.store import Store
from .engine.sync import HttpFetcher
from .ui.window import FootyWindow


class FootyApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name("Footy Cheat")
        self.connect("activate", self._activate)

    def _activate(self, _app) -> None:
        window = self.get_active_window()
        if window is not None:
            window.present()
            return
        data = Path(GLib.get_user_data_dir()) / "footy-cheat"
        data.mkdir(parents=True, exist_ok=True)
        store = Store.open_file(data / "footy.db")
        fetcher = HttpFetcher(lambda: user_agent(store.load_settings().contact_email))
        controller = AppController(store, fetcher)
        root = Path(__file__).resolve().parent
        window = FootyWindow(
            self,
            controller,
            root / "assets" / "logos",
            root / "assets" / "icons",
            root / "style.css",
        )
        window.present()
        GLib.idle_add(self._start, controller)

    def _start(self, controller: AppController) -> bool:
        controller.start()
        return False


def main() -> None:
    app = FootyApplication()
    raise SystemExit(app.run(sys.argv))


if __name__ == "__main__":
    main()

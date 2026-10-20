"""Background lobby scout.

Playwright's sync API is bound to the thread that created it, so the lobby list
is refreshed by one dedicated worker thread that owns its own headless browser.
The HTTP layer only ever reads the cached snapshot — instantly.
"""
from __future__ import annotations

import threading
import time

from bot.site import PokerPatioSite

REFRESH_SECONDS = 45


class LobbyService:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.tables: list[dict] = []
        self.fetched_at: float = 0.0
        self.error: str | None = None
        self.loading = False

    # ------------------------------------------------------------------ public
    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="lobby-scout")
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def snapshot(self, force: bool = False, wait: float = 0.0) -> dict:
        self.start()
        if force:
            deadline = time.time() + max(wait, 0.1)
            self._wake.set()
            while time.time() < deadline:
                if self.fetched_at and not self.loading:
                    break
                time.sleep(0.1)
        with self._lock:
            age = time.time() - self.fetched_at if self.fetched_at else None
            return {
                "tables": list(self.tables),
                "count": len(self.tables),
                "fetched_at": self.fetched_at or None,
                "age_s": round(age, 1) if age is not None else None,
                "stale": (age is None or age > REFRESH_SECONDS * 2),
                "loading": self.loading,
                "error": self.error,
            }

    # -------------------------------------------------------------------- loop
    def _loop(self):
        site = None
        while not self._stop.is_set():
            try:
                if site is None:
                    site = PokerPatioSite(headless=True)
                    site.open()
                with self._lock:
                    self.loading = True
                tables = site.lobby_tables()
                with self._lock:
                    self.tables = tables
                    self.fetched_at = time.time()
                    self.error = None
            except Exception as e:
                with self._lock:
                    self.error = f"{type(e).__name__}: {e}"
                try:
                    if site:
                        site.close()
                except Exception:
                    pass
                site = None
            finally:
                with self._lock:
                    self.loading = False
            self._wake.wait(REFRESH_SECONDS)
            self._wake.clear()
        try:
            if site:
                site.close()
        except Exception:
            pass


SCOUT = LobbyService()

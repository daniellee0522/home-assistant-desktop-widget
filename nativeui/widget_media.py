"""What a desktop widget shows besides its tiles' states (weather, a camera, a chart, a player), fetched again now and\nthen, and a player's controls (widget.py)."""
import datetime
import threading
import time
import traceback

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMenu


from . import kinds, render
from .widget_common import EXTRAS_EVERY

class SurfaceMedia:
    """What a desktop widget shows besides its tiles' states (weather, a camera, a chart, a player), fetched again now and\nthen, and a player's controls (widget.py)"""

    # ---- what another kind shows besides states -----------------------------------------
    def refresh_extras(self):
        """Fetch, off the GUI thread, what is due: the weather's coming days, the camera's picture (not while
        dimmed: the desktop is out of sight), the sensors' last day."""
        kind = self.wkind
        if kind == "custom":
            if self.isVisible():
                self.kit.refresh()
            return
        if kind not in EXTRAS_EVERY or not self.tiles or not self.isVisible() or kind in self._fetching:
            return
        if kind == "camera" and self.dim_target:     # the desktop is out of sight (a song's cover, fetched only
            return                                    # when the song changes, still follows it)
        art_url = None
        now = time.monotonic()
        if kind == "media":
            # its cover, as soon as the song changed (no waiting out an interval: a skip shows the new
            # cover at once), and the old one gone meanwhile, never beside the new song's title
            art_url = ((self.states.get(self.tiles[0]["entity"]) or {}).get("attributes") or {}).get("entity_picture")
            if art_url == self.extras.get("art_url"):
                return
            if self.extras.get("art") is not None:
                self.extras.update(art=None, art_url=None)
                self._redraw_tiles()
        elif now - self._extras_at.get(kind, -1e9) < EXTRAS_EVERY[kind]:
            return
        self._extras_at[kind] = now
        self._fetching.add(kind)
        tiles, states, api = list(self.tiles), dict(self.states), self.api

        def go():
            got = {}
            try:
                if kind == "weather":
                    got["forecast"] = api.get_forecast(tiles[0]["entity"])
                elif kind == "camera":
                    e = tiles[0]["entity"]
                    url = ((states.get(e) or {}).get("attributes") or {}).get("entity_picture") or "/api/camera_proxy/" + e
                    data = api.get_picture(url)
                    img = QImage.fromData(data) if data else None
                    if img is not None and not img.isNull():
                        got["picture"], got["picture_at"] = img, time.time()
                elif kind == "chart":
                    got["history"] = {t["entity"]: (api.get_history(t["entity"], 24) or {}).get("points") or []
                                      for t in tiles}
                elif kind == "media":
                    data = api.get_picture(art_url) if art_url else None
                    img = QImage.fromData(data) if data else None
                    got["art"] = img if img is not None and not img.isNull() else None
                    got["art_url"] = art_url
            except Exception:
                traceback.print_exc()

            def done():
                self._fetching.discard(kind)
                if got and kind == self.wkind:
                    self.extras.update(got)
                    self._redraw_tiles()
                if kind == "media":               # the song changed again while its cover came: that one's
                    QTimer.singleShot(0, self.refresh_extras)
            self.facade.run_on_ui_thread(done)
        threading.Thread(target=go, daemon=True).start()

    def _seek(self, at):
        entity = self.tiles[0]["entity"]
        st = self.states.get(entity) or {}
        self.optimistic(entity, {"attributes": dict(st.get("attributes") or {}, media_position=at,
                                                    media_position_updated_at=datetime.datetime.now(
                                                        datetime.timezone.utc).isoformat())})
        api = self.api

        def go():
            try:
                api.call_service("media_player", "media_seek", entity, {"seek_position": round(at, 1)})
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

    def _choose_source(self):
        """Where it plays: this computer or one of Home Assistant's players, from a menu under its name."""
        api = self.api

        def go():
            try:
                sources = api.get_media_sources()
            except Exception:
                sources = []
            self.facade.run_on_ui_thread(lambda: self._source_menu(sources))
        threading.Thread(target=go, daemon=True).start()

    def _source_menu(self, sources):
        if not sources:
            return
        dark = self.theme == "dark"
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        # as the screens' floating panes (style.popup_pane): a solid pane, a hairline rim, rounded rows
        menu.setStyleSheet(
            "QMenu { background: %s; border: 1px solid %s; border-radius: 14px; padding: 6px;"
            " font-family: 'Segoe UI Variable Text', 'Microsoft JhengHei UI'; font-size: 14px; }"
            "QMenu::item { color: %s; padding: 8px 18px 8px 12px; border-radius: 9px; }"
            "QMenu::item:selected { background: %s; }"
            "QMenu::item:checked { color: #409cff; font-weight: 600; }"
            "QMenu::indicator { width: 0px; }" % (
                "#1c1f25" if dark else "#f4f6f9", "rgba(255,255,255,0.14)" if dark else "rgba(0,0,0,0.12)",
                "#f5f5f7" if dark else "#1d1d1f", "rgba(255,255,255,0.12)" if dark else "rgba(0,0,0,0.07)"))
        current = self.tiles[0]["entity"] if self.tiles else None
        for s in sources:
            act = menu.addAction(("✓  " if s["entity_id"] == current else "     ") + render.tr(s["name"]))
            act.setCheckable(True)
            act.setChecked(s["entity_id"] == current)
            act.setData(s["entity_id"])
        rect = next((r for r, a in self.kind_buttons if a == "source"), None)
        k = self.scale / (self.devicePixelRatioF() or 1.0)
        at = self.mapToGlobal(QPoint(round(rect.x() * k), round(rect.bottom() * k))) if rect else None
        chosen = menu.exec(at) if at is not None else menu.exec()
        if chosen is not None and chosen.data() and chosen.data() != current:
            api, wid, entity = self.api, self.widget_id, chosen.data()
            threading.Thread(target=lambda: api.set_widget_source(wid, entity), daemon=True).start()

    def _play(self, action):
        """A player's button: previous, play or pause, next (shown at once, then asked of Home Assistant)."""
        if action == "source":
            self._choose_source()
            return
        entity = self.tiles[0]["entity"]
        st = self.states.get(entity) or {}
        if action == "play_pause" and st:
            self.optimistic(entity, kinds.play_pause_patch(st))
        service = {"previous": "media_previous_track", "play_pause": "media_play_pause",
                   "next": "media_next_track"}[action]
        api = self.api

        def go():
            try:
                api.call_service("media_player", service, entity, {})
            except Exception:
                traceback.print_exc()
        threading.Thread(target=go, daemon=True).start()

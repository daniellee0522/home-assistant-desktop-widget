"""Native settings pages, scrolling, page reversal and source-tile handoff over real glass."""
import json
from pathlib import Path
import sys
import time
from PySide6.QtCore import QEvent, QObject

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from nativeui import detail
from tools import glass_review as R
import test_native_panel as T
import test_native_widget as W


class PaintClock(QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.times=[]

    def eventFilter(self,watched,event):
        if event.type()==QEvent.Paint and any(t["view"] is watched.page_frame for t in watched.tweens.running):
            self.times.append(time.perf_counter())
        return False


def main(out=None):
    out = Path(out) if out else ROOT / "visual/settings-review"
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for material in ("classic", "liquid"):
        for theme in ("light", "dark"):
            for domain in ("light", "switch", "lock", "sensor"):
                state = {"state": "off", "attributes": {}}
                if domain == "lock": state["state"] = "locked"
                if domain == "sensor": state = {"state": "26.3", "attributes": {"unit_of_measurement": "°C"}}
                tile = W.tile(0, domain, room="客廳")
                api, win, source = W.make([tile], size="1x1", states={tile["entity"]:state},
                                          theme=theme, glass_style=material)
                card_win = None
                try:
                    capture = R.CaptureApi(material, theme, "busy")
                    api.get_desktop_backdrop = capture.get_desktop_backdrop
                    source.invalidate_glass()
                    R.pump_until(lambda: source.glass is not None)
                    popapi = T.FakeApi("grid", [tile])
                    popapi._prefs = api._prefs
                    popapi.get_desktop_backdrop = capture.get_desktop_backdrop
                    popapi.get_popover_source_image = source.transition_image
                    popapi._popover_origin = lambda w,h: (100,100)
                    card_win = detail.create_popover(popapi)
                    card = card_win.native
                    card.push_states([(tile["entity"], state)])
                    def resize(pw, ph, seq, origin=None):
                        q = card.devicePixelRatioF()
                        card.resize(round(pw/q), round(ph/q))
                        if origin: card.move(round(origin[0]/q), round(origin[1]/q))
                    popapi.resize_popover_window = resize
                    x,y,w,h = source.rects[0]
                    anchor = (100,100,round(w*source.scale),round(h*source.scale))
                    image = source.transition_image(tile["id"])
                    source.prepare_transition(tile["id"])
                    card.source_surface = source
                    card.set_transition_source(anchor, image, tile["id"], source_dpi=source.dpi)
                    card.open_tile(tile["id"])
                    card.sync_source_cover()
                    source.set_transition_tile(tile["id"])
                    card.show()
                    R.pump_until(lambda: card.glass is not None)
                    name = f"{material}-{theme}-{domain}"
                    R.shot(card,"busy").save(str(out/f"{name}-first.png"))
                    card.enter(); T.pump(600)
                    R.shot(card,"busy").save(str(out/f"{name}-control.png"))
                    width = card.transition_frame().width()
                    canvas = card.pw, card.ph
                    original = card.content_image
                    paints = []
                    def measured():
                        dirty = card._content_dirty or card._content is None
                        start = time.perf_counter()
                        image = original()
                        if dirty: paints.append((time.perf_counter()-start)*1000)
                        return image
                    card.content_image = measured
                    card.set_edit(True)
                    paths, times = [], []
                    start = time.perf_counter()
                    for index in range(18):
                        T.pump(20)
                        path = out/f"{name}-morph-{index:02}.png"
                        R.shot(card,"busy").save(str(path))
                        paths.append(str(path)); times.append(round((time.perf_counter()-start)*1000,2))
                        assert card.transition_frame().width() == width
                        assert (card.pw,card.ph) == canvas
                    morph_paints=list(paints)
                    T.pump(400)
                    R.shot(card,"busy").save(str(out/f"{name}-settings-top.png"))
                    card.body_scroll.scroll_to(card.body_scroll.max_offset())
                    T.pump(40)
                    R.shot(card,"busy").save(str(out/f"{name}-settings-bottom.png"))
                    for mode in (False,True,False):
                        before = card.transition_frame()
                        card.set_edit(mode)
                        assert card.transition_frame() == before
                        T.pump(65)
                    T.pump(600)
                    R.shot(card,"busy").save(str(out/f"{name}-returned.png"))
                    clock=PaintClock(card)
                    card.installEventFilter(clock)
                    card.set_edit(True)
                    until=time.perf_counter()+.65
                    while time.perf_counter()<until:
                        R.app.processEvents()
                        time.sleep(.001)
                    card.removeEventFilter(clock)
                    gaps=[(b-a)*1000 for a,b in zip(clock.times,clock.times[1:])]
                    records.append(dict(name=name, width=width, settings_height=card.page_targets[True].height(),
                                        canvas=canvas, paint_ms=paints, morph_paint_ms=morph_paints,
                                        frame_gaps_ms=gaps, paths=paths, times_ms=times))
                    card.content_image = original
                    card.close_card(); T.pump(500)
                    source.set_transition_tile(None)
                finally:
                    if card_win:
                        card_win.native.stop()
                        if card_win.native._glass_thread: card_win.native._glass_thread.join(1)
                        card_win.dispose()
                    source.stop()
                    if source._glass_thread: source._glass_thread.join(1)
                    W.done(win)
    (out/"frames.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
    print(json.dumps([dict(name=r["name"], max_paint_ms=round(max(r["paint_ms"],default=0),2))
                      for r in records],indent=2))


if __name__ == "__main__":
    main()

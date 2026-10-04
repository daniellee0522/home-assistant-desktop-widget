"""Measure and capture native menu entrance with real glass and a state arriving mid-motion."""
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from tools import glass_review as review
import test_native_panel as T


def find(view):
    return ([view] if view.__class__.__name__ == "ModeCard" else []) + [x for child in view.children for x in find(child)]


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "visual/interaction-review"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for style in ("classic", "liquid"):
        for theme in ("light", "dark"):
            api = T.FakeApi("grid", [dict(id="ac", entity="climate.ac", domain="climate", room="客廳冷氣", label="")])
            prefs = api._prefs()
            api._prefs = lambda: dict(prefs, theme=theme, glass_style=style)
            capture = review.CaptureApi(style, theme, "busy")
            api.get_desktop_backdrop = capture.get_desktop_backdrop
            win, sc = T.make_panel(api)
            try:
                st = {"state": "cool", "attributes": {"temperature": 24, "hvac_modes": ["off", "cool"],
                                                       "fan_modes": ["auto", "low"], "fan_mode": "auto"}}
                sc.push_states([("climate.ac", st)])
                sc.open_detail("ac")
                T.pump(400)
                review.pump_until(lambda: sc.glass is not None)
                paint_ms = []
                content_image = sc.content_image
                def measured():
                    start = time.perf_counter()
                    image = content_image()
                    paint_ms.append((time.perf_counter() - start) * 1000)
                    return image
                sc.content_image = measured
                card = find(sc.detail_view)[1]
                x, y, k = card.in_scene()
                ratio = sc.scale / sc.devicePixelRatioF()
                pos = QPoint(round((x + card.w * k / 2) * ratio), round((y + card.h * k / 2) * ratio))
                QTest.mouseMove(sc, pos)
                QTest.mouseClick(sc, Qt.LeftButton, pos=pos)
                assert sc.popup is not None, "Pointer click did not open the menu"
                start, changed = time.monotonic(), False
                samples, saved = [], set()
                while time.monotonic() - start < 0.4:
                    review.app.processEvents()
                    elapsed = (time.monotonic() - start) * 1000
                    if elapsed >= 45 and not changed:
                        before = (sc.popup.alpha, sc.popup.dy)
                        sc.push_states([("climate.ac", dict(st, attributes=dict(st["attributes"], fan_mode="low")))])
                        assert before == (sc.popup.alpha, sc.popup.dy), "Menu jumped during state update"
                        changed = True
                    samples.append(dict(ms=round(elapsed, 2), alpha=round(sc.popup.alpha, 5), dy=round(sc.popup.dy, 5)))
                    for at in (0, 40, 80, 160):
                        if elapsed >= at and at not in saved:
                            review.shot(sc, "busy").save(str(out / f"{style}-{theme}-{at}ms.png"))
                            saved.add(at)
                    time.sleep(0.004)
                assert (sc.popup.alpha, sc.popup.dy) == (1, 0)
                sc.close_popup()
                results.append(dict(style=style, theme=theme, captures=capture.captures, frames=len(paint_ms),
                                    median_content_ms=round(statistics.median(paint_ms), 3),
                                    max_content_ms=round(max(paint_ms), 3), samples=samples,
                                    timer_after_close=sc.tweens.timer.isActive()))
            finally:
                sc.stop()
                if sc._glass_thread:
                    sc._glass_thread.join(1)
                win.dispose()
    (out / "measurements.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps([{k: v for k, v in r.items() if k != "samples"} for r in results], indent=2))


if __name__ == "__main__":
    main()

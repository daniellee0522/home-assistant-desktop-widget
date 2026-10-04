"""Native capsule transitions, cancellation and device detail with captured desktop fixtures."""
import json
from pathlib import Path
import statistics
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from tools import glass_review as R
import test_native_panel as T
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from nativeui import render

out = ROOT / 'visual/capsule-interaction'
out.mkdir(parents=True, exist_ok=True)
results = []
for material in ('classic', 'liquid'):
    for theme in ('light', 'dark'):
        api = T.FakeApi()
        original = api._prefs
        api._prefs = lambda: dict(original(), theme=theme, glass_style=material)
        capture = R.CaptureApi(material, theme, 'busy')
        api.get_desktop_backdrop = capture.get_desktop_backdrop
        win, sc = T.make_panel(api)
        render.set_language('zh-TW')
        timings = []
        original_image = sc.content_image
        def measured():
            repaint = sc._content_dirty or sc._content is None
            start = time.perf_counter()
            image = original_image()
            if repaint:
                timings.append((time.perf_counter() - start) * 1000)
            return image
        sc.content_image = measured
        try:
            R.pump_until(lambda: sc.glass is not None)
            h = sc.home
            def click(view):
                x, y, k = view.in_scene()
                ratio = sc.scale / sc.devicePixelRatioF()
                pos = QPoint(round((x + view.w * k / 2) * ratio), round((y + view.h * k / 2) * ratio))
                QTest.mouseClick(sc, Qt.LeftButton, pos=pos)
            click(h.pills['light'])
            assert h.m.category == 'light'
            for at in (0, 80):
                if at: T.pump(at)
                R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-open-{at}.png'))
            before = (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom)
            sc.push_states([('light.a', {'state': 'off', 'attributes': {}})])
            assert before == (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom)
            click(h.pills['light'])
            assert before == (h.main.alpha, h.cat_view.alpha, h.cat_view.zoom)
            R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-cancel-0.png'))
            T.pump(450)
            assert (h.main.alpha, h.cat_view.alpha) == (1, 0)
            R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-cancel-end.png'))
            for category in ('env', 'light', 'security'):
                h.toggle_category(category)
                T.pump(450)
                R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-{category}.png'))
                h.toggle_editing()
                T.pump(450)
                R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-{category}-edit.png'))
            h.toggle_category('security')
            T.pump(450)
            click(h.chips[1])
            assert h.m.room == h.chips[1].key
            T.pump(450)
            R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-room.png'))
            sc.open_detail('home:climate.ac')
            T.pump(450)
            R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-detail.png'))
            sc.close_detail()
            T.pump(450)
            assert not sc.tweens.timer.isActive()
            h.m.room = ""
            h.m.category = None
            h.loaded(dict(rooms=["入口"], entities=[
                T.ent("lock.front", "lock", "大門", "入口", "locked"),
                T.ent("lock.entry", "lock", "玄關門", "入口", "locked")], sensors=[]))
            h.chip_click("入口")
            T.pump(450)
            h.toggle_category("security")
            T.pump(450)
            R.shot(sc, 'busy').save(str(out / f'{material}-{theme}-entry-locks.png'))
            frames = []
            h.toggle_category('security')
            T.pump(450)
            for action in ('open', 'cancel'):
                h.toggle_category('security')
                for index in range(18):
                    T.pump(20)
                    path = out / f'{material}-{theme}-motion-{action}-{index}.png'
                    R.shot(sc, 'busy').save(str(path))
                    frames.append(str(path))
            (out / f'{material}-{theme}-frames.json').write_text(json.dumps(frames), encoding='utf-8')
            results.append(dict(material=material, theme=theme, frames=len(timings),
                                median_ms=round(statistics.median(timings), 3), max_ms=round(max(timings), 3),
                                captures=capture.captures, timer_active=sc.tweens.timer.isActive()))
        finally:
            sc.stop()
            if sc._glass_thread: sc._glass_thread.join(1)
            win.dispose()
(out / 'measurements.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps(results, indent=2))

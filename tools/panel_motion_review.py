"""Native panel header and flyout motion review, with measured paint costs."""
import json
from pathlib import Path
import sys
import time
from PySide6.QtCore import QEventLoop, QTimer

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import test_native_panel as T
from tools import glass_review as R


def main():
    out = ROOT / "visual/panel-motion"
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for theme in ("light", "dark"):
        api = T.FakeApi("home")
        prefs = dict(api._prefs(), theme=theme)
        api._prefs = lambda: prefs
        capture = R.CaptureApi(theme=theme, pattern="bright" if theme == "light" else "dark")
        api.get_desktop_backdrop = capture.get_desktop_backdrop
        win, scene = T.make_panel(api)
        try:
            scene.start_glass()
            R.pump_until(lambda: scene.glass is not None)
            for entity in ("light.a", "climate.ac", "lock.d"):
                scene.open_detail("home:" + entity)
                T.pump(600)
                scene.grab().save(str(out / (theme + "-" + entity + ".png")))
                scene.close_detail(animate=False)
            scene.close_detail(animate=False)
            frames = []
            scene.anim_alpha, scene.anim_dy = 0, scene.css_h
            scene.flyout_enter()
            for _ in range(20):
                T.pump(20)
                frames.append(scene.grab().toImage())
            scene.flyout_leave()
            for _ in range(12):
                T.pump(20)
                frames.append(scene.grab().toImage())
            images = []
            for index, frame in enumerate(frames):
                filename = out / (theme + "-motion-%02d.png" % index)
                frame.save(str(filename))
                images.append(R.Image.open(filename).convert("RGBA"))
            images[0].save(out / (theme + "-motion.gif"), save_all=True, append_images=images[1:],
                           duration=20, loop=0, disposal=2)
            costs = []
            times = []
            ticks = []
            scene.tweens.timer.timeout.connect(lambda: ticks.append((phase, time.perf_counter())))
            phase = "enter"
            original = scene.paintEvent
            def paint(event):
                started = time.perf_counter()
                moving = getattr(scene, "moving", False)
                original(event)
                if moving:
                    costs.append((time.perf_counter() - started) * 1000)
                    times.append((phase, started))
            scene.paintEvent = paint
            scene.raise_()
            scene.activateWindow()
            T.app.setActiveWindow(scene)
            scene.anim_alpha, scene.anim_dy = 0, scene.css_h
            scene.flyout_enter()
            loop = QEventLoop()
            QTimer.singleShot(430, loop.quit)
            loop.exec()
            phase = "leave"
            scene.flyout_leave()
            QTimer.singleShot(230, loop.quit)
            loop.exec()
            ranked = sorted(costs)
            gaps = sorted((b[1]-a[1])*1000 for a,b in zip(times,times[1:]) if a[0]==b[0])
            tick_gaps = sorted((b[1]-a[1])*1000 for a,b in zip(ticks,ticks[1:]) if a[0]==b[0])
            results.append(dict(theme=theme, samples=len(costs),
                                screen_hz=scene.screen().refreshRate(),
                                timer_ms=scene.tweens.timer.interval(),
                                tick_gap_median_ms=round(tick_gaps[len(tick_gaps)//2],2),
                                median_ms=round(ranked[len(ranked)//2], 2),
                                p95_ms=round(ranked[min(len(ranked)-1, int(len(ranked)*.95))], 2),
                                max_ms=round(max(costs), 2),
                                frame_gap_median_ms=round(gaps[len(gaps)//2], 2),
                                frame_gap_p95_ms=round(gaps[min(len(gaps)-1,int(len(gaps)*.95))], 2)))
        finally:
            win.dispose()
    (out / "performance.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

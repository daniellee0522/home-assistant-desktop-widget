"""Measure the real main.py panel, including live capture and cold/warm opening."""
import json
from pathlib import Path
import time


def run(api, folder):
    scene = None
    paints, steps = [], []
    phase = ["idle"]
    opened = [0.0]
    enters = []

    def instrument():
        original = scene.paintEvent
        def paint(event):
            start = time.perf_counter()
            moving = getattr(scene, "moving", False)
            original(event)
            if moving:
                paints.append((phase[0], start, (time.perf_counter()-start)*1000))
        scene.paintEvent = paint
        enter = scene.flyout_enter
        def entering():
            enters.append((phase[0], (time.perf_counter()-opened[0])*1000))
            return enter()
        scene.flyout_enter = entering
    ensure = api._ensure_overlay
    def ensure_instrumented(kind):
        nonlocal scene
        window = ensure(kind)
        if kind == 'flyout' and scene is None:
            scene = window.native
            window.run_on_ui_thread(instrument)
        return window
    api._ensure_overlay = ensure_instrumented

    def timed(name, original):
        def invoke(*args, **kwargs):
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                steps.append(dict(phase=phase[0], method=name, ms=round((time.perf_counter()-start)*1000, 2)))
        return invoke
    for name in ("_ensure_overlay", "_sync_client_entities", "_place_flyout", "_arm_backdrop",
                 "_apply_capture_exclusion", "_apply_system_glass"):
        setattr(api, name, timed(name, getattr(api,name)))
    results = []
    for cycle in range(3):
        label = "cold" if cycle == 0 else "warm-%d" % cycle
        phase[0] = label
        opened[0] = time.perf_counter()
        api.show_flyout(from_key=True)
        call_ms = (time.perf_counter()-opened[0])*1000
        time.sleep(.8)
        samples = [(stamp,cost) for name,stamp,cost in paints if name==label]
        gaps = sorted((b[0]-a[0])*1000 for a,b in zip(samples,samples[1:]))
        costs = sorted(cost for _,cost in samples)
        results.append(dict(cycle=label, open_call_ms=round(call_ms,2),
                            enter_after_ms=next((round(ms,2) for name,ms in enters if name==label),None),
                            frames=len(samples), timer_ms=scene.tweens.timer.interval(),
                            screen_hz=scene.screen().refreshRate(),
                            paint_p95_ms=round(costs[min(len(costs)-1,int(len(costs)*.95))],2) if costs else None,
                            gap_median_ms=round(gaps[len(gaps)//2],2) if gaps else None,
                            gap_p95_ms=round(gaps[min(len(gaps)-1,int(len(gaps)*.95))],2) if gaps else None))
        phase[0] = label + "-close"
        api.hide_flyout()
        time.sleep(.35)
    Path(folder, "live-motion.json").write_text(json.dumps(dict(results=results, steps=steps),indent=2), encoding="utf-8")
    api._quit()

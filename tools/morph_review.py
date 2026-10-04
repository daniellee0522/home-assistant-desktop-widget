"""Render shared tile/detail geometry and entrance-only tile motion on native windows."""
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from nativeui import detail, render
from tools import glass_review as R
import test_native_panel as T
import test_native_widget as W

out = ROOT/'visual/morph-review'
out.mkdir(parents=True, exist_ok=True)
measurements=[]
def frames(sc, name, count=22):
    paths=[]; times=[]; paints=[]
    original=sc.content_image
    def measured():
        dirty=sc._content_dirty or sc._content is None
        start=time.perf_counter(); image=original()
        if dirty: paints.append((time.perf_counter()-start)*1000)
        return image
    sc.content_image=measured
    start=time.monotonic()
    try:
        for index in range(count):
            R.app.processEvents()
            path=out/f'{name}-{index:02}.png'
            R.shot(sc,'busy').save(str(path))
            paths.append(str(path)); times.append(round((time.monotonic()-start)*1000,2))
            T.pump(20)
    finally: sc.content_image=original
    measurements.append(dict(name=name, times_ms=times, paint_ms=paints, paths=paths))

for material in ('classic','liquid'):
    api=T.FakeApi()
    prefs=api._prefs()
    api._prefs=lambda: dict(prefs, glass_style=material, theme='dark')
    api.get_desktop_backdrop=R.CaptureApi(material,'dark','busy').get_desktop_backdrop
    win,sc=T.make_panel(api)
    try:
        render.set_language('zh-TW')
        R.pump_until(lambda: sc.glass is not None)
        tile=sc.home.tile_views()[0]
        sc.popover(tile,tile.tile)
        frames(sc,material+'-panel-open')
        sc.close_detail(); frames(sc,material+'-panel-close')
        sc.home.toggle_category('light'); frames(sc,material+'-capsule-open',28)
        sc.home.toggle_category('light'); frames(sc,material+'-capsule-fade')
        sc.home.chip_click('臥室'); frames(sc,material+'-room-enter',28)
        assert (sc.css_w,sc.css_h)==sc.base_css
    finally:
        sc.stop()
        if sc._glass_thread: sc._glass_thread.join(1)
        win.dispose()

api,win,surf=W.make([W.tile(i,'light') for i in range(4)], size='2x4',
                      states={'light.e0':{'state':'off','attributes':{}}}, glass_style='classic')
try:
    pending=[]
    api.open_popover=lambda *args: pending.append(args)
    x,y,w,h=surf.rects[0]; ratio=surf.scale/surf.devicePixelRatioF()
    QTest.mouseClick(surf,Qt.LeftButton,pos=QPoint(round((x+180)*ratio),round((y+h/2)*ratio)))
    R.pump_until(lambda: bool(pending))
    tile_id,ax,ay,aw,ah,owner,image=pending[0]
    popapi=T.FakeApi('grid',api.tiles)
    prefs=api._prefs()
    popapi._prefs=lambda: prefs
    popapi._popover_origin=lambda w,h:(ax,ay)
    popapi.get_desktop_backdrop=R.CaptureApi('classic','light','busy').get_desktop_backdrop
    pop=detail.create_popover(popapi); card=pop.native
    def resize(pw,ph,seq,origin=None):
        q=card.devicePixelRatioF()
        card.resize(round(pw/q),round(ph/q))
        if origin: card.move(round(origin[0]/q),round(origin[1]/q))
    popapi.resize_popover_window=resize
    try:
        surf.prepare_transition(tile_id)
        card.source_surface=surf
        card.set_transition_source((ax,ay,aw,ah),image,tile_id)
        card.open_tile(tile_id)
        card.sync_source_cover()
        surf.set_transition_tile(tile_id)
        card.show()
        R.pump_until(lambda:card.glass is not None)
        card.enter(); frames(card,'desktop-bar-open',28)
        card.close_card(); frames(card,'desktop-bar-close',28)
    finally:
        surf.set_transition_tile(None)
        card.stop()
        if card._glass_thread: card._glass_thread.join(1)
        pop.dispose()
finally: W.done(win)
(out/'frames.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')
print(json.dumps([dict(name=x['name'], paints=len(x['paint_ms']), max_ms=round(max(x['paint_ms'],default=0),2)) for x in measurements],indent=2))

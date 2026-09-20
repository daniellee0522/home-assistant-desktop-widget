"""Render README theme screenshots with demo devices; no HA credentials needed."""
import json
from pathlib import Path
import sys

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'

TILES = [
    {'id': 'light', 'entity': 'light.desk', 'domain': 'light', 'room': 'Desk lamp', 'label': ''},
    {'id': 'climate', 'entity': 'climate.living', 'domain': 'climate', 'room': 'Living room', 'label': 'Cooling'},
    {'id': 'fan', 'entity': 'fan.office', 'domain': 'fan', 'room': 'Office fan', 'label': ''},
    {'id': 'cover', 'entity': 'cover.bedroom', 'domain': 'cover', 'room': 'Blinds', 'label': ''},
    {'id': 'lock', 'entity': 'lock.front', 'domain': 'lock', 'room': 'Front door', 'label': ''},
    {'id': 'vacuum', 'entity': 'vacuum.home', 'domain': 'vacuum', 'room': 'Vacuum', 'label': 'Cleaning'},
    {'id': 'sensor', 'entity': 'sensor.temperature', 'domain': 'sensor', 'room': 'Temperature', 'label': ''},
    {'id': 'humidity', 'entity': 'sensor.humidity', 'domain': 'sensor', 'room': 'Humidity', 'label': ''},
]
STATES = {
    'light.desk': {'state': 'on', 'attributes': {'brightness': 180, 'rgb_color': [255, 190, 108]}},
    'climate.living': {'state': 'cool', 'attributes': {'temperature': 24, 'current_temperature': 27}},
    'fan.office': {'state': 'on', 'attributes': {'percentage': 65}},
    'cover.bedroom': {'state': 'closed', 'attributes': {}},
    'lock.front': {'state': 'locked', 'attributes': {}},
    'vacuum.home': {'state': 'cleaning', 'attributes': {}},
    'sensor.temperature': {'state': '27.5', 'attributes': {'device_class': 'temperature', 'unit_of_measurement': '°C'}},
    'sensor.humidity': {'state': '75', 'attributes': {'device_class': 'humidity', 'unit_of_measurement': '%'}},
}

app = QApplication(sys.argv)
view = QWebEngineView()
view.setAttribute(Qt.WA_DontShowOnScreen, True)
view.resize(720, 360)
view.page().setBackgroundColor(QColor('#b8c8d9'))

variants = [
    ('classic', 'light'), ('classic', 'dark'),
    ('liquid', 'light'), ('liquid', 'dark'),
    ('windows', 'light'), ('windows', 'dark'),
]
index = 0


def next_variant():
    global index
    if index >= len(variants):
        app.quit()
        return
    glass, theme = variants[index]
    index += 1
    script = f"""
      CONFIG = Object.assign(CONFIG, {{tiles: {json.dumps(TILES)}, columns: 4,
        glass_style: {json.dumps(glass)}, theme: {json.dumps(theme)}, language: 'en', zoom: 100}});
      STATES = {json.dumps(STATES)};
      window.pywebview.api = new Proxy({{}}, {{get: () => () => Promise.resolve(null)}});
      setInterfaceLanguage('en'); applyTheme(); renderGrid();
      document.body.style.background = {json.dumps('linear-gradient(125deg, #a6bed2, #e4edf2 58%, #8cabc5)' if theme == 'light' else 'linear-gradient(125deg, #293344, #52697c 58%, #1d2838)')};
      document.querySelector('#view-grid').style.position = 'relative';
      document.querySelector('#view-grid').style.zIndex = '1';
    """
    view.page().runJavaScript(script)

    def save():
        image = view.grab().toImage()
        # The document's stage sits in the upper-left of the view.
        target = DOCS / f'theme-{glass}-{theme}.png'
        image.save(str(target))
        print(target.relative_to(ROOT), image.width(), image.height())
        QTimer.singleShot(120, next_variant)

    QTimer.singleShot(500, save)


def loaded(ok):
    if not ok:
        raise RuntimeError('Could not load widget page')
    QTimer.singleShot(800, next_variant)


view.loadFinished.connect(loaded)
view.load(QUrl.fromLocalFile(str(ROOT / 'web' / 'index.html')))
view.show()
QTimer.singleShot(20000, app.quit)
sys.exit(app.exec())

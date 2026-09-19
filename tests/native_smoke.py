"""Windows/Qt smoke checks; no HA connection and no visible app windows."""
import ctypes
import multiprocessing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    import main
    import qtshell
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication

    capture = main._DesktopCapture()
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    process = kernel.GetCurrentProcess()
    main._user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    before = main._user32.GetGuiResources(process, 0)
    try:
        for size in range(8, 80):
            assert capture._ensure('_out_dc', '_out_bmp', '_out_size', size, size)
            assert main._gdi32.PatBlt(capture._out_dc, 0, 0, size, size, 0x42)
            frame = capture._read_out(size, size)
            assert frame is not None and len(frame) == size * size * 4
            assert frame[:3] == b'\0\0\0'
    finally:
        capture.reset()
    after = main._user32.GetGuiResources(process, 0)
    assert after <= before, (before, after)
    print('Native GDI resize/read/reset passed with no GDI handle growth')

    worker = main._compat_capture
    try:
        frame = worker.grab(0, 0, 16, 16)
        assert worker._process is not None and worker._process.is_alive()
        assert frame is None or len(frame) == 16 * 16 * 4
        print('Native compatibility worker round-trip passed')
    finally:
        worker.close()

    app = QApplication.instance() or QApplication([])
    qtshell._marshal = qtshell._Marshal()
    window = qtshell.Window('Load test', hidden=True, transparent=True)
    window.native.setAttribute(Qt.WA_DontShowOnScreen, True)
    window.native.show()
    received = []
    pixels = []
    last_pixels = []

    def check_pixels():
        image = window.native.grab().toImage()
        center = image.pixelColor(image.width() // 2, image.height() // 2)
        corner = image.pixelColor(0, 0)
        last_pixels[:] = [center.getRgb(), corner.getRgb()]
        if center.getRgb() == (18, 52, 86, 255) and corner.alpha() == 0:
            pixels.append(True)
            app.quit()
        else:
            QTimer.singleShot(100, check_pixels)

    def loaded():
        def result(value):
            received.append(value)
            QTimer.singleShot(100, check_pixels)
        window.native.view.page().runJavaScript('JSON.stringify(window.received)', result)

    window.events.loaded += loaded
    window.native.view.setHtml(
        '<style>html,body{margin:0;background:transparent}'
        '#card{height:100vh;background:#123456;border-radius:24px}</style>'
        '<div id="card"></div>'
        '<script>window.received=[];'
        'window.__haPushBatch = items => window.received.push(...items);</script>')
    window.evaluate_js('window.__haPushBatch(["queued"])')
    QTimer.singleShot(10000, app.quit)
    app.exec()
    assert received == ['["queued"]'], received
    assert pixels, ('Qt must render the card color and preserve transparent corners', last_pixels)
    window.native.close()
    print('Hidden Qt page delivered queued push and rendered transparent corners correctly')


if __name__ == '__main__':
    multiprocessing.freeze_support()
    run()

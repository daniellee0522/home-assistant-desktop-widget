"""Windows/Qt smoke checks; no HA connection and no visible app windows."""
import ctypes
import multiprocessing
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run():
    import main
    import qtshell
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from PIL import Image
    import pystray
    from tray import restore_tray_icon

    # Exercise pystray's real Windows message loop without adding a test icon
    # to the user's taskbar. Record only the final Shell_NotifyIcon boundary.
    icon = pystray.Icon('resume-test', Image.new('RGBA', (16, 16)))
    ready = threading.Event()
    restored = threading.Event()
    calls = []

    def record_notification(code, flags, **kwargs):
        calls.append((code, threading.get_ident()))
        if code == 0:  # NIM_ADD
            restored.set()

    def setup(tray_icon):
        tray_icon.visible = True
        ready.set()

    icon._message = record_notification
    icon.run_detached(setup)
    try:
        assert ready.wait(5), 'Tray message loop did not start'
        calls.clear()
        restored.clear()
        assert restore_tray_icon(icon), 'Failed to queue tray recovery'
        assert restored.wait(5), 'Tray recovery was not processed'
        assert [code for code, _ in calls] == [2, 0], calls  # DELETE, ADD
        assert all(tid != threading.get_ident() for _, tid in calls), calls
        assert icon.visible
        print('Native tray recovery deleted/re-added the icon on its own message thread')
    finally:
        icon.stop()

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
    power_filter = qtshell._PowerFilter()
    app.installNativeEventFilter(power_filter)
    # WA_DontShowOnScreen is a render-only window; use a hidden native
    # top-level receiver for the Windows broadcast test.
    receiver = QWidget()
    post = ctypes.windll.user32.PostMessageW
    post.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    post.restype = ctypes.c_int
    qtshell._resume_pending.clear()
    assert post(int(receiver.winId()), 0x0218, 0x0012, 0)
    resume_loop = QEventLoop()
    QTimer.singleShot(200, resume_loop.quit)
    resume_loop.exec()
    assert qtshell._resume_pending.is_set(), 'Qt did not receive the native resume notification'
    qtshell._resume_pending.clear()
    app.removeNativeEventFilter(power_filter)
    receiver.close()
    print('Native Windows resume notification reached the Qt power filter')
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

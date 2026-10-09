"""The program's life: the desktop widgets and the tray, what the tray's menu does, and what to rebuild when Windows
changes the display or wakes from sleep."""

import multiprocessing
import os
import sys

from PySide6.QtCore import QTimer

from app.api import Api
from app.capture import compat_capture, desktop_capture, screen_duplication
from app.widget_windows import create_widget_window, restore_widget_place
from winsys import qtshell
from winsys.tray import build_tray_icon, restore_tray_icon
from winsys.windows import apply_window_shape, hide_own_console, run_on_ui_thread, send_to_bottom, set_noactivate

# The executable's own folder when frozen (the log is written there); else the project's.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Shell:
    """What the tray's menu, the widgets' close button and the system's notices do to the desktop."""

    def __init__(self, api):
        self.api = api
        api._closing_handler = self.on_closing

    # -- the desktop's visibility -------------------------------------------------------------------
    def hide_desktop(self):
        api = self.api
        for widget_window in list(api._widgets.values()):
            widget_window.hide()
        if api._popover_window:
            api._popover_window.hide()
        if api._settings_window:
            api._settings_window.hide()
        api._desktop_visible = False

    def show_desktop(self):
        api = self.api
        for widget_window in list(api._widgets.values()):
            widget_window.show()
        api._apply_system_glass()
        api._desktop_visible = True

    def on_closing(self):
        self.api.hide_flyout()
        self.hide_desktop()
        return False                      # keep running in the tray

    # -- the tray's menu ------------------------------------------------------------------------------
    def toggle_visibility(self, icon=None, item=None):
        self.api.hide_flyout()
        if self.api._desktop_visible:
            self.hide_desktop()
        else:
            self.show_desktop()

    def activate(self, icon=None, item=None):
        self.api.toggle_flyout()

    def open_settings(self, icon=None, item=None):
        if not self.api._desktop_visible:
            self.show_desktop()
        self.api.open_settings_window()

    def toggle_theme(self, icon=None, item=None):
        order = ["light", "dark", "auto"]
        current = self.api._cfg.get("theme", "auto")
        following = order[(order.index(current) + 1) % len(order)] if current in order else "light"
        self.api.save_prefs({"theme": following})

    def refresh_now(self, icon=None, item=None):
        self.api._refresh_now()

    def quit_action(self, icon=None, item=None):
        self.api._quit()

    # -- the display changes and sleep ------------------------------------------------------------------
    def restore_window(self):
        """Screen arrival and DPI changes can happen after the resume retries: refresh every surface (hidden
        panels defer repainting until shown)."""
        api = self.api
        if api._desktop_visible:
            for widget_window in list(api._widgets.values()):
                widget_window.native._cache_hwnd()
                set_noactivate(widget_window, True)
                widget_window.native.showNormal()
                restore_widget_place(api, widget_window)
                send_to_bottom(widget_window)
        for win in api._all_windows():
            win.refresh_display()
            apply_window_shape(win)
        api._apply_capture_exclusion()
        api._apply_system_glass()
        qtshell.log("Display surfaces refreshed")

    def restore_tray(self):
        """The entry point to the panel even when the desktop widget was manually hidden: independent of the
        desktop's visibility."""
        try:
            posted = restore_tray_icon(self.api._tray_icon)
            qtshell.log("Resume tray re-registration requested: %s" % posted)
        except Exception as exc:
            qtshell.log("Resume tray re-registration failed: %s" % exc)

    def on_resume(self):
        """Rebuild what a suspend invalidates: GDI objects made for the old display, DWM attributes, capture
        exclusion, and the websocket."""
        api = self.api
        window = api._window

        def schedule_restore():
            for delay in (0, 2000, 5000):
                QTimer.singleShot(delay, self.restore_tray)
                QTimer.singleShot(delay, self.restore_window)

        run_on_ui_thread(window, schedule_restore)
        desktop_capture.reset()
        screen_duplication.reset()
        compat_capture.close()
        for win in api._all_windows():
            try:
                apply_window_shape(win)
            except Exception:
                pass
        try:
            api._apply_capture_exclusion()
        except Exception:
            pass
        # A connection open across a suspend is usually half-open, and recv() on it can block for minutes.
        # Reconnect now.
        try:
            api._client._kick()
        except Exception:
            pass
        # Every window's backdrop and frame hash describe the old screen.
        api._broadcast("invalidate_glass")


def main():
    hide_own_console()

    api = Api()
    qtshell.prepare(log_dir=BASE_DIR)

    for widget in api._cfg["widgets"]:
        create_widget_window(api, widget)
    shell = Shell(api)
    qtshell.on_display_change(shell.restore_window)
    qtshell.on_resume(shell.on_resume)
    api._watch_for_idle()
    if os.environ.get("HA_WIDGET_OPEN_PANEL"):
        from app.probe import start_probe
        start_probe(api)
    if os.environ.get("HA_WIDGET_SAMPLE"):
        from app.probe import start_sampler
        start_sampler(os.environ["HA_WIDGET_SAMPLE"])

    tray_icon = build_tray_icon(shell.activate, shell.toggle_visibility, shell.open_settings,
                                shell.toggle_theme, shell.refresh_now, shell.quit_action)
    api._tray_icon = tray_icon
    tray_icon.run_detached()
    api._apply_hotkey()

    qtshell.start()
    # The event loop ends without Quit when Windows asks the program to close (an installer updating it,
    # signing out, shutting down). The tray's thread would then hold the process open until it was
    # killed: leave the way Quit does.
    api._quit()


def run():
    multiprocessing.freeze_support()
    main()

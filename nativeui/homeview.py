"""The Home view of the tray panel (filled in next)."""
from .ui import View


class HomeView(View):
    def __init__(self, panel):
        super().__init__(0, 0, 678, 600)
        self.panel = panel

    def load(self):
        pass

    def states_changed(self, entities):
        pass

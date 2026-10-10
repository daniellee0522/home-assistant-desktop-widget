"""widgetkit: building blocks for widgets that are not the program's own kinds.

A separate area. It reads the program's look (`nativeui.render`, `nativeui.style`) and changes nothing in it; the
program does not import it. `tools/widgetkit_gallery.py` draws every block and a few widgets made from them.

    charts   ring, rings, gauge, bar, segments, columns, line, sparkline, donut
    controls button, icon_button, toggle, segmented, slider, field, stepper, checkbox, icon, icon_badge, HitMap
    rows     quote_row, news_item
    sources  JsonSource, RssSource, StaticSource, Store (what a widget's data comes from)
    form      Form (the user's settings window, made from a widget's Fields; clicks, typing, menus)
    definition Field, WidgetDef, Context (what a developer writes: settings, sources, drawing)
    media    picture, caption_card, collage, shade
    motion   Spring (interruptible), project, rubber_band, set_reduced_motion
    theme    Theme (the colours), text (a line of a text role), paragraph (wrapped, cut at N lines)
"""
from . import charts, controls, media, motion, rows, sources
from .definition import Action, Context, Field, WidgetDef, copy, launch, media as media_action, open_app, open_url
from .form import Form
from .theme import Theme, paragraph, smooth, text

__all__ = ["Action", "Context", "Field", "Form", "copy", "launch", "media_action", "open_app", "open_url", "WidgetDef", "sources", "charts", "controls", "media", "motion", "rows", "Theme", "paragraph", "smooth", "text"]

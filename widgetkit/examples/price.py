"""A symbol's price and its recent run (a coin, a stock, a rate), from Yahoo. Everything a developer writes is
in this one file."""
from PySide6.QtCore import QRectF

from widgetkit import charts
from widgetkit.definition import Field, WidgetDef
from widgetkit.sources import JsonSource
from widgetkit.theme import text

PAD = 24

# 1. WHERE THE DATA COMES FROM: an address (its {braces} are the user's settings) and which values to take.
PRICES = JsonSource(
    "prices",
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval=1h",
    {"series": "chart.result.0.indicators.quote.0.close",       # a list of prices (some may be missing)
     "currency": "chart.result.0.meta.currency"},
    every=120)


# 2. HOW IT LOOKS: given the data (ctx.data), the settings (ctx.config) and a painter.
def draw(p, th, W, H, ctx):
    answer = ctx.data.get("prices")
    points = [v for v in (answer or {}).get("series") or [] if v is not None]
    symbol, cur = ctx.config["symbol"].upper(), (answer or {}).get("currency") or ""
    text(p, th, "eyebrow", "%s · %s" % (symbol, cur) if cur else symbol, PAD, PAD)
    if len(points) < 2:
        text(p, th, "body", "No data" if ctx.errors else "Loading…", PAD, PAD + 30)
        return
    now, first = points[-1], points[0]
    change = (now - first) / first * 100
    color = th.accent("green" if change >= 0 else "red")
    text(p, th, "display", "{:,.2f}".format(now), PAD, PAD + 14)
    text(p, th, "headline", "%+.2f%% · %s" % (change, ctx.config["range"]), W - PAD - 220, PAD + 8, 220, "r", color)
    charts.line(p, th, QRectF(PAD, 112, W - 2 * PAD, H - 112 - PAD), [points], [color], grid=0)


# 3. WHAT THE USER MAY CHANGE: each becomes a field in the settings window and a key in the shared file.
WIDGET = WidgetDef(
    id="example.price", name="Price and trend", size="2x4",
    config=[Field("symbol", "text", "BTC-USD", "Symbol"),
            Field("range", "choice", "5d", "Range", options=("1d", "5d", "1mo", "6mo"))],
    sources=[PRICES],
    draw=draw)

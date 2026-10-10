"""A stocks watchlist written as a developer would write it: the symbols, how they are shown, and the news feeds are
settings; the numbers and headlines come from sources; this file only says how to draw them."""
import math

from PySide6.QtCore import QRectF

from widgetkit import rows
from widgetkit.definition import Field, WidgetDef
from widgetkit.sources import JsonSource, RssSource

PAD = 24
QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{item}"
QUOTE_FIELDS = {"price": "chart.result.0.meta.regularMarketPrice",
                "prev": "chart.result.0.meta.chartPreviousClose",
                "name": "chart.result.0.meta.shortName"}
NEWS = [{"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex"}]


def _value(q, show):
    price, prev = q.get("price"), q.get("prev")
    if price is None:
        return "--", True
    up = prev is None or price >= prev
    if show == "change" and prev:
        return "%+.2f%%" % ((price - prev) / prev * 100), up
    return ("{:,.0f}" if price >= 1000 else "{:,.2f}").format(price), up


def draw(p, th, W, H, ctx):
    quotes = ctx.data.get("quotes") or []
    show = ctx.config["show"]
    per_col = max(1, math.ceil(len(quotes) / 2))
    col_w = (W - 2 * PAD - 40) / 2
    for i, q in enumerate(quotes):
        value, up = _value(q, show)
        name = q.get("label") or q.get("item")
        rect = QRectF(PAD + (i // per_col) * (col_w + 40), PAD + (i % per_col) * 40, col_w, 40)
        rows.quote_row(p, th, rect, name, value, up)
    y = PAD + per_col * 40 + 26
    for item in (ctx.data.get("news") or []):
        h = rows.news_height(W - 2 * PAD, item["title"])
        if y + h > H - PAD:                       # no room for another: stop, never draw over the edge
            break
        y += rows.news_item(p, th, QRectF(PAD, y, W - 2 * PAD, h), item["source"], item["title"]) + 22


WIDGET = WidgetDef(
    id="example.watchlist", name="Watchlist", size="4x4",
    config=[Field("symbols", "list", ["^DJI=Dow Jones", "^GSPC=S&P 500", "AAPL", "BA", "BRK-B", "DIS"], "Stocks",
                  help="Type a symbol, or SYMBOL=Name to choose the name shown."),
            Field("show", "choice", "price", "Show", options=("price", "change"),
                  choices={"price": "Price", "change": "Change %"}),
            Field("feeds", "feeds", NEWS, "News sources", help="Any RSS or Atom address."),
            Field("max_news", "number", 4, "Headlines", minimum=0, maximum=8)],
    sources=[JsonSource("quotes", QUOTE_URL, QUOTE_FIELDS, each="symbols", every=60),
             RssSource("news", feeds="feeds", limit="max_news", every=300)],
    draw=draw)

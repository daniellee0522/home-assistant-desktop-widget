"""Recipe: a number from the web. A JsonSource fetches it (the address's {braces} are the user's settings), the widget says it
needs `network:` for that host, and draws something sensible before the first answer and when there is none."""
from widgetkit.definition import Field, WidgetDef
from widgetkit.sources import JsonSource
from widgetkit.theme import text

PAD = 24

NOW = JsonSource("now", "https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current=temperature_2m",
                 {"temperature": "current.temperature_2m"}, every=900)


def draw(p, th, W, H, ctx):
    answer = ctx.data.get("now") or {}
    value = answer.get("temperature")
    text(p, th, "eyebrow", ctx.config["place"], PAD, PAD, W - 2 * PAD)
    if value is None:                                                       # not here yet, or it could not be fetched
        text(p, th, "body", "No data" if ctx.errors else "Loading…", PAD, PAD + 34, W - 2 * PAD)
        return
    text(p, th, "hero", "%d°" % round(value), PAD, PAD + 18, W - 2 * PAD)


WIDGET = WidgetDef(
    id="example.temperature", name={"en": "Temperature", "zh": "氣溫"}, size="2x2",
    config=[Field("place", "text", "Taipei", {"en": "Place", "zh": "地點"}),
            Field("latitude", "number", 25.04, {"en": "Latitude", "zh": "緯度"}, minimum=-90, maximum=90, step=0.01),
            Field("longitude", "number", 121.56, {"en": "Longitude", "zh": "經度"}, minimum=-180, maximum=180, step=0.01)],
    sources=[NOW], draw=draw, permissions=("network:api.open-meteo.com",))

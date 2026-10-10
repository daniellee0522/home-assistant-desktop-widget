"""Ask a service something and show its answer: a text input, Enter to send, the reply in the widget."""
from PySide6.QtCore import QRectF

from widgetkit import controls
from widgetkit.definition import Field, WidgetDef, request
from widgetkit.theme import paragraph, text

PAD = 22
HOST = "api.example.com"


def draw(p, th, W, H, ctx):
    controls.search_bar(p, th, QRectF(PAD, PAD, W - 2 * PAD, 84), ctx.config["prompt"], "mdi:star-four-points",
                        "mdi:send", hits=ctx.hits, id="ask", trailing_id="send", **ctx.text_input("ask"))
    y = PAD + 84 + 18
    reply = ctx.state.get("reply")
    if ctx.state.get("reply_busy"):
        text(p, th, "secondary", "Thinking…", PAD, y)
    elif reply:
        question = ctx.state.get("question")
        if question:
            text(p, th, "caption", question, PAD, y, W - 2 * PAD)
            y += 22
        body = reply["data"].get("answer") if reply["ok"] and isinstance(reply["data"], dict) else \
            reply.get("error") or "The service answered %s" % reply["status"]
        paragraph(p, th, "body", str(body), QRectF(PAD, y, W - 2 * PAD, H - y - PAD), max_lines=7)


def on_submit(id, value, ctx):
    ctx.set_state(question=value, reply=None)
    return request(ctx.config["endpoint"], "POST", json={"q": value},
                   headers={"Authorization": "Bearer " + ctx.config["api_key"]}, into="reply")


def on_tap(id, ctx):
    if id == "send":
        text_typed = ctx.inputs.get("ask", "").strip()
        if text_typed:
            ctx.set_input("ask", "")
            return on_submit("ask", text_typed, ctx)


WIDGET = WidgetDef(
    id="example.ask", name="Ask", size="2x4",
    config=[Field("prompt", "text", "Ask anything", "Words in the bar"),
            Field("endpoint", "text", "https://%s/ask" % HOST, "Service address"),
            Field("api_key", "secret", "", "Key", help="Kept on this computer; never in a shared settings file.")],
    sources=[], draw=draw, on_tap=on_tap, on_submit=on_submit, permissions=("network:" + HOST,))

"""Which state changes of the devices on the tiles are worth a notification: locks and safety sensors.

Only a change is reported, from a state already known (the first state seen of a device is its
baseline, so starting the program or reconnecting says nothing about how things already were), and
the same news about a device at most once a minute.
"""
import time

# Binary sensors whose "on" is news, and what it is (Home Assistant's device classes).
SENSOR_NEWS = {
    "door": ("已打開", "opened"),
    "window": ("已打開", "opened"),
    "garage_door": ("已打開", "opened"),
    "opening": ("已打開", "opened"),
    "smoke": ("偵測到煙霧", "smoke detected"),
    "gas": ("偵測到瓦斯", "gas detected"),
    "carbon_monoxide": ("偵測到一氧化碳", "carbon monoxide detected"),
    "moisture": ("偵測到漏水", "water leak detected"),
    "safety": ("安全警報", "safety alert"),
    "tamper": ("遭到拆動", "tampering detected"),
    "problem": ("發生問題", "problem detected"),
    "heat": ("溫度過高", "too hot"),
    "lock": ("已解鎖", "unlocked"),             # a binary lock sensor is on when unlocked
}
LOCK_NEWS = {
    "unlocked": ("已解鎖", "unlocked"),
    "open": ("已開啟", "opened"),
    "jammed": ("卡住了", "jammed"),
}
QUIET_S = 60.0
_UNKNOWN = (None, "", "unavailable", "unknown")


def _state(st):
    return (st or {}).get("state")


def news(entity_id, old, new, sensors=True, locks=True):
    """(zh, en) of what happened to the device, or None when it is not worth a notification."""
    before, now = _state(old), _state(new)
    if before in _UNKNOWN or now in _UNKNOWN or before == now:
        return None
    domain = entity_id.split(".", 1)[0]
    if domain == "lock" and locks:
        return LOCK_NEWS.get(now)
    if domain == "binary_sensor" and sensors and now == "on" and before == "off":
        kind = ((new or {}).get("attributes") or {}).get("device_class")
        return SENSOR_NEWS.get(kind)
    return None


class Alerts:
    """Turns state changes into notifications through `notify(title, message)`."""

    def __init__(self, notify, clock=time.monotonic):
        self.notify, self.clock = notify, clock
        self._last = {}                    # (entity, state) -> when it was last told

    def check(self, entity_id, old, new, sensors, locks, language="zh-TW"):
        """Notify about this change if it is news. True when a notification was sent."""
        what = news(entity_id, old, new, sensors, locks)
        if what is None:
            return False
        key = (entity_id, _state(new))
        now = self.clock()
        if now - self._last.get(key, -QUIET_S) < QUIET_S:
            return False
        self._last[key] = now
        name = ((new or {}).get("attributes") or {}).get("friendly_name") or entity_id
        text = what[1] if language == "en" else what[0]
        self.notify("HA Widgets", "%s %s" % (name, text))
        return True

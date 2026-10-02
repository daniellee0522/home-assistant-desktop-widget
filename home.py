"""The Home-style panel's data: the accessories that can be controlled, by the
room (Home Assistant area) they are in unless the user has moved them, and
the temperature and humidity readings, which are shown as status, not tiles."""

# What the panel shows as a tile. Everything else (diagnostic sensors,
# helpers, scenes, scripts, automations) is not an accessory.
ACCESSORY_DOMAINS = (
    "light", "switch", "climate", "cover", "fan", "lock", "media_player", "vacuum",
)


def domain_of(entity_id):
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def sensor_kind(state):
    """'temperature', 'humidity' or None for a sensor state."""
    attrs = state.get("attributes") or {}
    device_class = attrs.get("device_class")
    unit = attrs.get("unit_of_measurement") or ""
    entity_id = state.get("entity_id", "")
    if device_class in ("temperature", "humidity"):
        return device_class
    if device_class is None:
        if unit in ("°C", "°F"):
            return "temperature"
        if unit == "%" and "humid" in entity_id:
            return "humidity"
    return None


def build_home(states, areas, devices, registry, overrides):
    """(accessories, sensors, rooms).

    A device's area applies to its entities unless an entity has its own;
    `overrides` ({entity_id: room name}) wins over both. Hidden, disabled and
    configuration/diagnostic entities are left out, as Home Assistant's own
    dashboards do, and so is an accessory that does not answer and has no
    room (a camera's settings, say)."""
    area_names = {a.get("area_id"): a.get("name") or "" for a in areas}
    device_area = {d.get("id"): d.get("area_id") for d in devices}
    by_entity = {e.get("entity_id"): e for e in registry}
    overrides = overrides or {}
    accessories, sensors = [], []
    for state in states:
        entity_id = state.get("entity_id", "")
        domain = domain_of(entity_id)
        if domain not in ACCESSORY_DOMAINS and domain != "sensor":
            continue
        reg = by_entity.get(entity_id) or {}
        if reg.get("hidden_by") or reg.get("disabled_by") or reg.get("entity_category"):
            continue
        area_id = reg.get("area_id") or device_area.get(reg.get("device_id"))
        room = overrides.get(entity_id) or area_names.get(area_id) or ""
        name = (state.get("attributes") or {}).get("friendly_name") or entity_id
        if domain == "sensor":
            kind = sensor_kind(state)
            if not kind:
                continue
            sensors.append({"entity_id": entity_id, "kind": kind, "name": name,
                            "area": room, "state": state})
            continue
        if state.get("state") == "unavailable" and not room:
            continue
        accessories.append({"entity_id": entity_id, "domain": domain, "name": name,
                            "area": room, "state": state})
    order = {d: i for i, d in enumerate(ACCESSORY_DOMAINS)}
    accessories.sort(key=lambda e: (order[e["domain"]], e["name"].lower()))
    sensors.sort(key=lambda s: s["name"].lower())
    rooms = sorted({e["area"] for e in (*accessories, *sensors) if e["area"]},
                   key=lambda n: n.lower())
    return accessories, sensors, rooms

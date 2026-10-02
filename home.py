"""The Home-style panel's data: every device, grouped by the room (Home
Assistant area) it is in, unless the user has moved it."""

# Devices people think of as accessories. Scenes, scripts and automations are
# not shown by room.
HOME_DOMAINS = (
    "light", "switch", "climate", "cover", "fan", "lock", "media_player",
    "vacuum", "sensor", "binary_sensor", "input_boolean",
)


def domain_of(entity_id):
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def build_home(states, areas, devices, registry, overrides):
    """[{entity_id, domain, name, area, state}], rooms first by name, and a
    sorted list of room names.

    A device's area applies to its entities unless an entity has its own;
    `overrides` ({entity_id: room name}) wins over both. Hidden, disabled and
    configuration/diagnostic entities are left out, as Home Assistant's own
    dashboards do."""
    area_names = {a.get("area_id"): a.get("name") or "" for a in areas}
    device_area = {d.get("id"): d.get("area_id") for d in devices}
    by_entity = {e.get("entity_id"): e for e in registry}
    overrides = overrides or {}
    entities = []
    for state in states:
        entity_id = state.get("entity_id", "")
        domain = domain_of(entity_id)
        if domain not in HOME_DOMAINS:
            continue
        reg = by_entity.get(entity_id) or {}
        if reg.get("hidden_by") or reg.get("disabled_by") or reg.get("entity_category"):
            continue
        area_id = reg.get("area_id") or device_area.get(reg.get("device_id"))
        room = overrides.get(entity_id) or area_names.get(area_id) or ""
        entities.append({
            "entity_id": entity_id,
            "domain": domain,
            "name": (state.get("attributes") or {}).get("friendly_name") or entity_id,
            "area": room,
            "state": state,
        })
    order = {d: i for i, d in enumerate(HOME_DOMAINS)}
    entities.sort(key=lambda e: (order[e["domain"]], e["name"].lower()))
    rooms = sorted({e["area"] for e in entities if e["area"]},
                   key=lambda n: n.lower())
    return entities, rooms

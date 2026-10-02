TILES = [
    {"id": "light", "entity": "light.desk", "domain": "light", "room": "Desk lamp", "label": ""},
    {"id": "climate", "entity": "climate.living", "domain": "climate", "room": "Living room", "label": "Cooling"},
    {"id": "fan", "entity": "fan.office", "domain": "fan", "room": "Office fan", "label": ""},
    {"id": "cover", "entity": "cover.bedroom", "domain": "cover", "room": "Blinds", "label": ""},
    {"id": "lock", "entity": "lock.front", "domain": "lock", "room": "Front door", "label": ""},
    {"id": "vacuum", "entity": "vacuum.home", "domain": "vacuum", "room": "Vacuum", "label": "Cleaning"},
    {"id": "sensor", "entity": "sensor.temperature", "domain": "sensor", "room": "Temperature", "label": ""},
    {"id": "media", "entity": "media_player.speaker", "domain": "media_player", "room": "書房", "label": ""},
]
STATES = {
    "light.desk": {"state": "on", "attributes": {"brightness": 180}},
    "climate.living": {"state": "cool", "attributes": {"temperature": 24, "current_temperature": 27}},
    "fan.office": {"state": "on", "attributes": {"percentage": 65}},
    "cover.bedroom": {"state": "closed", "attributes": {}},
    "lock.front": {"state": "unlocked", "attributes": {}},
    "vacuum.home": {"state": "cleaning", "attributes": {}},
    "sensor.temperature": {"state": "27.5", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C"}},
    "media_player.speaker": {"state": "paused", "attributes": {"media_title": "Tiny Giant", "media_artist": "Sãn"}},
}



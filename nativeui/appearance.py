"""What a tile looks like, decided in one place: its icon says what kind of thing it is (its family), and
the family gives the colour of the icon when on, the words for its state, and the look of its detail.

Every device has a family of its own (a light's is "light"). A device that is only switched on and off (a
switch, an input boolean) can take the family of any on/off thing (a lamp, a fan, a lock, an air
conditioner...): the icon chosen for it says which. Other devices take, among the icons, only other shapes
of their own family (a ceiling light, a floor lamp; a door, a gate). Any other icon is only an icon: the
tile keeps its own family's colours, words and detail. Icons beyond these lists are typed as MDI names in
the edit panel, and are only icons too.
"""

# family: (label, icons). The first icon is the family's own (a tile with no icon of its own shows it);
# "mdi:" names are Material Design Icons, the others are the app's own drawings (icon_paths.json).
FAMILIES = {
    "switch": ("開關", ["mdi:toggle-switch-variant", "mdi:light-switch", "mdi:power"]),
    "outlet": ("插座", ["switch", "mdi:power-socket-us", "mdi:power-socket-eu"]),
    "light": ("燈具", ["light", "mdi:ceiling-light", "mdi:floor-lamp", "mdi:desk-lamp", "mdi:lamp",
                      "mdi:wall-sconce-round", "mdi:chandelier", "mdi:light-recessed", "mdi:led-strip-variant",
                      "mdi:string-lights"]),
    "fan": ("風扇", ["fan", "mdi:ceiling-fan", "mdi:air-purifier"]),
    "lock": ("門鎖", ["lock", "mdi:lock-smart", "mdi:door-closed-lock", "door", "mdi:gate", "mdi:garage-variant"]),
    "climate": ("空調", ["mdi:air-conditioner", "mdi:thermostat", "mdi:radiator", "mdi:heat-pump"]),
    "media": ("影音", ["media", "mdi:television", "monitor", "mdi:cast", "mdi:music"]),
    "appliance": ("家電", ["mdi:coffee-maker", "mdi:kettle", "mdi:washing-machine", "mdi:dishwasher",
                          "mdi:water-boiler"]),
    "cover": ("窗簾", ["mdi:blinds", "mdi:curtains", "mdi:roller-shade", "mdi:window-shutter", "mdi:garage"]),
    "vacuum": ("掃地機", ["mdi:robot-vacuum", "mdi:robot-mower"]),
    "sensor": ("感測器", ["sensor", "thermometer", "humidity", "mdi:gauge", "mdi:flash", "mdi:molecule-co2",
                         "mdi:weather-windy"]),
    "detector": ("偵測器", ["mdi:door-open", "mdi:window-open-variant", "mdi:motion-sensor",
                           "mdi:smoke-detector", "mdi:water-alert"]),
    "scene": ("場景", ["mdi:palette", "script", "mdi:robot", "mdi:home", "mdi:play-circle", "mdi:movie-open",
                      "mdi:weather-night"]),
    "camera": ("攝影機", ["mdi:cctv", "mdi:webcam", "mdi:doorbell-video"]),
    "weather": ("天氣", ["mdi:weather-partly-cloudy"]),
}
# the families a thing switched on and off can take
ON_OFF = ("switch", "outlet", "light", "fan", "lock", "climate", "media", "appliance")
# each kind of device: its own family, and the families it can take
DOMAINS = {
    "switch": ("switch", ON_OFF), "input_boolean": ("switch", ON_OFF),
    "light": ("light", ("light",)), "fan": ("fan", ("fan",)), "lock": ("lock", ("lock",)),
    "climate": ("climate", ("climate",)), "media_player": ("media", ("media",)), "cover": ("cover", ("cover",)),
    "vacuum": ("vacuum", ("vacuum",)), "sensor": ("sensor", ("sensor",)), "binary_sensor": ("detector", ("detector",)),
    "scene": ("scene", ("scene",)), "script": ("scene", ("scene",)), "automation": ("scene", ("scene",)),
    "camera": ("camera", ("camera",)), "weather": ("weather", ("weather",)),
}
# the colour of an icon that is on, by family: an ACCENT name of render (a light's own colour is its bulb's)
COLORS = {"switch": "blue", "outlet": "blue", "light": "yellow", "fan": "blue", "lock": "teal", "climate": "cyan",
          "media": "green", "appliance": "blue", "cover": "blue", "vacuum": "blue", "detector": "green",
          "scene": "blue"}
# what an on/off thing of a family says it is
WORDS = {"lock": ("已解鎖", "已上鎖")}
DEFAULT_WORDS = ("開啟", "關閉")
# an icon's other shape for a thing that is open (or unlocked)
OPEN_SHAPE = {"lock": "lock-open", "mdi:lock-smart": "mdi:lock-open-variant", "mdi:door-closed-lock": "mdi:door-open",
              "door": "mdi:door-open", "mdi:garage-variant": "mdi:garage-open-variant", "mdi:blinds": "mdi:blinds-open",
              "mdi:garage": "mdi:garage-open"}

_FAMILY_OF = {icon: fam for fam, (_, icons) in FAMILIES.items() for icon in icons}


def domain_families(domain):
    return DOMAINS.get(domain, ("sensor", ()))


def family_of_icon(icon):
    """The family an icon belongs to ("" for an icon of none: one typed by its MDI name)."""
    return _FAMILY_OF.get(icon or "", "")


def family(tile):
    """What the tile is shown as: its icon's family when its kind of device can take it, else its own."""
    own, can = domain_families(tile.get("domain", ""))
    fam = family_of_icon(tile.get("icon"))
    return fam if fam in can else own


def supports(tile, icon):
    """Whether choosing this icon also changes what the tile is shown as (or only its picture)."""
    return family_of_icon(icon) in domain_families(tile.get("domain", ""))[1]


def own_icon(tile):
    """The icon of the tile's family (what it shows with no icon of its own)."""
    return FAMILIES[family(tile)][1][0]


def words(tile):
    """(on, off): what an on/off tile of this family says it is."""
    return WORDS.get(family(tile), DEFAULT_WORDS)


def open_shape(icon):
    return OPEN_SHAPE.get(icon, icon)

"""Map tile arithmetic (Web Mercator, 256 px tiles, as OpenStreetMap and most map services use): which tiles cover a
widget centred on a place, and where they go; and where a drag moves the centre to."""
import math

TILE = 256
MAX_LAT = 85.0511


def to_world(lat, lon, zoom):
    """Pixels from the top-left of the whole world map at `zoom`."""
    n = TILE * 2 ** zoom
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def from_world(x, y, zoom):
    n = TILE * 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, (lon + 180.0) % 360.0 - 180.0


def tile_grid(lat, lon, zoom, w, h):
    """The tiles that cover a w x h picture centred on (lat, lon): [(tx, ty, px, py)], where (px, py) is the tile's
    top-left in the picture. Rows off the map are left out; columns wrap round the world."""
    cx, cy = to_world(lat, lon, zoom)
    left, top = cx - w / 2, cy - h / 2
    n = 2 ** zoom
    out = []
    for ty in range(math.floor(top / TILE), math.floor((top + h) / TILE) + 1):
        if not 0 <= ty < n:
            continue
        for tx in range(math.floor(left / TILE), math.floor((left + w) / TILE) + 1):
            out.append((tx % n, ty, tx * TILE - left, ty * TILE - top))
    return out


def pan(lat, lon, zoom, dx, dy):
    """The centre after the map is dragged by (dx, dy) px: the map follows the pointer, so the centre goes the other way."""
    cx, cy = to_world(lat, lon, zoom)
    return from_world(cx - dx, cy - dy, zoom)

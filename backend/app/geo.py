from geoalchemy2.elements import WKTElement


def point(lat: float, lon: float) -> WKTElement:
    """PostGIS expects POINT(lon lat)."""
    return WKTElement(f"POINT({lon} {lat})", srid=4326)

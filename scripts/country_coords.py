# Static centroid lookup: no external geocoding needed.
# Coordinates are rough representative points, not precise geocodes
# ("anywhere works" — user confirmed precision isn't required).

COUNTRY_COORDS = {
    "USA": (39.8, -98.6),
    "Japan": (36.2, 138.3),
    "China": (35.9, 104.2),
    "Turkey": (38.9, 35.2),
    "India": (22.4, 79.0),
    "Cambodia": (12.6, 104.9),
    "Nigeria": (9.1, 8.7),
    "Indonesia": (-2.5, 118.0),
    "South Korea": (36.5, 127.9),
    "Pakistan": (30.4, 69.3),
    "UK": (54.0, -2.9),
    "Mexico": (23.6, -102.5),
    "Haiti": (18.9, -72.3),
    "Lebanon": (33.9, 35.9),
    "Sweden": (60.1, 18.6),
    "Australia": (-25.3, 133.8),
    "Spain": (40.3, -3.7),
    "Tibet": (31.7, 88.1),
    "Austria": (47.5, 14.6),
    "France": (46.6, 2.2),
    "Poland": (51.9, 19.1),
    "Israel": (31.0, 34.8),
    "Ireland": (53.1, -7.7),
    "Czech Republic": (49.8, 15.5),
    "Guyana": (4.9, -58.9),
    "New Zealand": (-41.0, 174.9),
    "Zimbabwe": (-19.0, 29.2),
    "Italy": (42.8, 12.6),
    "Argentina": (-38.4, -63.6),
    "Vietnam": (14.1, 108.3),
    "Algeria": (28.0, 1.7),
    "Canada": (56.1, -106.3),
    "Iran": (32.4, 53.7),
    "Ukraine": (48.4, 31.2),
    "Russia": (61.5, 105.3),
    "Germany": (51.2, 10.5),
    "Thailand": (15.9, 100.9),
    "Chile": (-35.7, -71.5),
    "Afghanistan": (33.9, 67.7),
    "Brazil": (-14.2, -51.9),
    "Sri Lanka": (7.9, 80.8),
    "Antigua": (17.06, -61.80),
    "Taiwan": (23.7, 121.0),
}

# India state/UT regions — looked up first when the CSV's `region` column
# is filled in, giving finer placement than the national centroid.
INDIA_REGION_COORDS = {
    "West Bengal": (22.9, 87.9),
    "Kashmir": (34.1, 74.8),
    "Gujarat": (22.6, 71.6),
    "Karnataka": (15.3, 75.7),
    "Goa/Mumbai": (17.6, 72.9),
    "Goa": (15.4, 74.0),
    "Nagaland": (26.2, 94.6),
    "Rajasthan": (27.0, 74.2),
    "Delhi": (28.7, 77.1),
    "Tamil Nadu": (11.1, 78.7),
    "Andhra Pradesh/Telangana": (16.5, 79.0),
    "Punjab": (31.1, 75.3),
    "Kerala": (10.5, 76.3),
    "Jharkhand": (23.6, 85.3),
    "Odisha": (20.9, 85.1),
    "Andaman Islands": (11.7, 92.7),
    "Bihar": (25.6, 85.1),
    "Ladakh": (34.2, 77.6),
}


def resolve_coords(country: str, region: str):
    """Region takes precedence over country when present (India states)."""
    region = (region or "").strip()
    country = (country or "").strip()
    if region and region in INDIA_REGION_COORDS:
        return INDIA_REGION_COORDS[region]
    if country in COUNTRY_COORDS:
        return COUNTRY_COORDS[country]
    return None

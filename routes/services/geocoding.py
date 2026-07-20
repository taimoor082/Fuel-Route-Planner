import requests
from django.conf import settings
from django.core.cache import cache

GEOCODE_CACHE_TIMEOUT = 60 * 60 * 24


class GeocodingError(Exception):
    pass


def resolve_location(query):
    """Resolve a free-text location or a "lat,lon" pair to coordinates."""
    coords = _parse_coordinates(query)
    if coords:
        return {'query': query, 'name': query, 'latitude': coords[0], 'longitude': coords[1]}
    return _geocode(query)


def _parse_coordinates(query):
    parts = query.split(',')
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise GeocodingError(f'Coordinates out of range: "{query}"')
    return lat, lon


def _geocode(query):
    cache_key = 'geocode:' + query.strip().lower()
    result = cache.get(cache_key)
    if result:
        return result

    try:
        response = requests.get(
            f'{settings.NOMINATIM_BASE_URL}/search',
            params={'q': query, 'format': 'json', 'limit': 1, 'countrycodes': 'us'},
            headers={'User-Agent': 'fuel-route-planner'},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GeocodingError(f'Geocoding service unavailable: {exc}') from exc

    matches = response.json()
    if not matches:
        raise GeocodingError(f'Could not find a location in the USA for "{query}"')

    match = matches[0]
    result = {
        'query': query,
        'name': match['display_name'],
        'latitude': float(match['lat']),
        'longitude': float(match['lon']),
    }
    cache.set(cache_key, result, GEOCODE_CACHE_TIMEOUT)
    return result

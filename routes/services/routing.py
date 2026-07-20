import requests
from django.conf import settings
from django.core.cache import cache

METERS_PER_MILE = 1609.344
ROUTE_CACHE_TIMEOUT = 60 * 60


class RoutingError(Exception):
    pass


def fetch_route(start, finish):
    """Fetch a driving route from OSRM between two resolved locations.

    Returns the route geometry as a list of (longitude, latitude) pairs
    together with the total distance in miles and duration in hours.
    """
    cache_key = 'route:{:.4f},{:.4f}:{:.4f},{:.4f}'.format(
        start['latitude'], start['longitude'], finish['latitude'], finish['longitude']
    )
    route = cache.get(cache_key)
    if route:
        return route

    url = '{}/route/v1/driving/{},{};{},{}'.format(
        settings.OSRM_BASE_URL,
        start['longitude'], start['latitude'],
        finish['longitude'], finish['latitude'],
    )
    try:
        response = requests.get(
            url,
            params={'overview': 'full', 'geometries': 'geojson'},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RoutingError(f'Routing service unavailable: {exc}') from exc

    payload = response.json()
    if payload.get('code') != 'Ok' or not payload.get('routes'):
        raise RoutingError('No drivable route found between the given locations')

    best = payload['routes'][0]
    route = {
        'geometry': best['geometry']['coordinates'],
        'distance_miles': best['distance'] / METERS_PER_MILE,
        'duration_hours': best['duration'] / 3600,
    }
    cache.set(cache_key, route, ROUTE_CACHE_TIMEOUT)
    return route

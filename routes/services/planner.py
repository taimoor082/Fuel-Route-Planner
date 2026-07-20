import math
from collections import defaultdict

from django.conf import settings

from routes.models import FuelStation
from routes.services.geocoding import resolve_location
from routes.services.routing import fetch_route

EARTH_RADIUS_MILES = 3958.8
SAMPLE_SPACING_MILES = 2
GRID_CELL_DEGREES = 0.15
PRICE_TOLERANCE_PER_GALLON = 0.05


class PlanningError(Exception):
    pass


def plan_trip(start_query, finish_query):
    start = resolve_location(start_query)
    finish = resolve_location(finish_query)
    route = fetch_route(start, finish)

    samples = _sample_route(route['geometry'])
    candidates = _stations_along_route(samples)
    stops, total_cost, total_gallons = _plan_fuel_stops(route['distance_miles'], candidates)

    return {
        'start': start,
        'finish': finish,
        'route': {
            'distance_miles': round(route['distance_miles'], 1),
            'duration_hours': round(route['duration_hours'], 1),
            'geometry': {'type': 'LineString', 'coordinates': route['geometry']},
        },
        'fuel_stops': stops,
        'summary': {
            'total_fuel_cost_usd': round(total_cost, 2),
            'total_gallons_purchased': round(total_gallons, 1),
            'number_of_stops': len(stops),
            'assumptions': {
                'vehicle_range_miles': settings.VEHICLE_RANGE_MILES,
                'miles_per_gallon': settings.VEHICLE_MPG,
                'tank_full_at_start': True,
            },
        },
    }


def _haversine_miles(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def _sample_route(coordinates):
    """Downsample the route geometry to points roughly SAMPLE_SPACING_MILES
    apart, each annotated with its distance from the start."""
    samples = []
    travelled = 0.0
    last_sampled = None
    prev = None
    for lon, lat in coordinates:
        if prev is not None:
            travelled += _haversine_miles(prev[0], prev[1], lat, lon)
        if last_sampled is None or travelled - last_sampled >= SAMPLE_SPACING_MILES:
            samples.append((lat, lon, travelled))
            last_sampled = travelled
        prev = (lat, lon)
    if prev is not None and samples[-1][2] < travelled:
        samples.append((prev[0], prev[1], travelled))
    return samples


def _grid_cell(lat, lon):
    return math.floor(lat / GRID_CELL_DEGREES), math.floor(lon / GRID_CELL_DEGREES)


def _stations_along_route(samples):
    """Find fuel stations within the search radius of the route, keyed by how
    far along the route they sit.

    A coarse spatial grid over the sampled route points keeps this fast: each
    station only gets compared against nearby samples instead of the whole
    route.
    """
    radius = settings.STATION_SEARCH_RADIUS_MILES
    grid = defaultdict(list)
    for lat, lon, position in samples:
        grid[_grid_cell(lat, lon)].append((lat, lon, position))

    lats = [s[0] for s in samples]
    lons = [s[1] for s in samples]
    margin = GRID_CELL_DEGREES
    stations = FuelStation.objects.filter(
        latitude__gte=min(lats) - margin,
        latitude__lte=max(lats) + margin,
        longitude__gte=min(lons) - margin,
        longitude__lte=max(lons) + margin,
    )

    candidates = []
    for station in stations:
        row, col = _grid_cell(station.latitude, station.longitude)
        nearest = None
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                for lat, lon, position in grid.get((row + dr, col + dc), ()):
                    distance = _haversine_miles(station.latitude, station.longitude, lat, lon)
                    if distance <= radius and (nearest is None or distance < nearest[0]):
                        nearest = (distance, position)
        if nearest:
            candidates.append({'station': station, 'position': nearest[1]})

    candidates.sort(key=lambda c: c['position'])
    return candidates


def _plan_fuel_stops(route_miles, candidates):
    """Pick cost-effective fuel stops using the classic gas station greedy:
    at each station, if a meaningfully cheaper station is reachable on a full
    tank, buy just enough fuel to get there; otherwise fill up completely and
    drive to the farthest of the cheapest reachable stations. A small price
    tolerance avoids extra stops that would only save a few cents, and the
    destination acts as a free "station" so the tank is never overfilled on
    the last leg."""
    range_miles = settings.VEHICLE_RANGE_MILES
    mpg = settings.VEHICLE_MPG

    points = [
        {'station': c['station'], 'position': c['position'], 'price': float(c['station'].retail_price)}
        for c in candidates
    ]
    points.append({'station': None, 'position': route_miles, 'price': 0.0})

    current = {'station': None, 'position': 0.0, 'price': math.inf}
    fuel_miles = float(range_miles)
    purchases = []

    while current['position'] < route_miles:
        reachable = [
            p for p in points
            if current['position'] < p['position'] <= current['position'] + range_miles
        ]
        if not reachable:
            raise PlanningError(
                'No fuel station found within vehicle range at mile '
                f"{current['position']:.0f} of the route"
            )
        cheaper = [
            p for p in reachable
            if p['price'] < current['price'] - PRICE_TOLERANCE_PER_GALLON
        ]
        if cheaper:
            target = min(cheaper, key=lambda p: p['position'])
            needed = (target['position'] - current['position']) - fuel_miles
            bought = max(needed, 0.0)
        else:
            best_price = min(p['price'] for p in reachable)
            target = max(
                (p for p in reachable if p['price'] <= best_price + PRICE_TOLERANCE_PER_GALLON),
                key=lambda p: p['position'],
            )
            bought = range_miles - fuel_miles
        if bought > 0:
            purchases.append({'stop': current, 'miles_of_fuel': bought})
        fuel_miles = fuel_miles + bought - (target['position'] - current['position'])
        current = target

    stops = []
    total_cost = 0.0
    total_gallons = 0.0
    for purchase in purchases:
        station = purchase['stop']['station']
        gallons = purchase['miles_of_fuel'] / mpg
        cost = gallons * purchase['stop']['price']
        total_cost += cost
        total_gallons += gallons
        stops.append({
            'name': station.name,
            'address': station.address,
            'city': station.city,
            'state': station.state,
            'latitude': station.latitude,
            'longitude': station.longitude,
            'price_per_gallon': purchase['stop']['price'],
            'miles_from_start': round(purchase['stop']['position'], 1),
            'gallons_purchased': round(gallons, 1),
            'fuel_cost_usd': round(cost, 2),
        })
    return stops, total_cost, total_gallons

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from routes.models import FuelStation
from routes.services import planner
from routes.services.planner import PlanningError, _plan_fuel_stops, _sample_route


def make_candidate(position, price, name='Station'):
    station = FuelStation(
        opis_id=int(position),
        name=name,
        address='',
        city='Testville',
        state='TX',
        retail_price=Decimal(str(price)),
        latitude=0.0,
        longitude=0.0,
    )
    return {'station': station, 'position': position}


class PlanFuelStopsTests(TestCase):
    def test_no_stops_needed_when_route_within_range(self):
        stops, cost, gallons = _plan_fuel_stops(400, [make_candidate(200, 3.0)])
        self.assertEqual(stops, [])
        self.assertEqual(cost, 0)
        self.assertEqual(gallons, 0)

    def test_single_stop_buys_only_fuel_needed_to_finish(self):
        stops, cost, gallons = _plan_fuel_stops(600, [make_candidate(300, 3.0)])
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]['miles_from_start'], 300)
        self.assertAlmostEqual(gallons, 10.0)
        self.assertAlmostEqual(cost, 30.0)

    def test_prefers_meaningfully_cheaper_station(self):
        candidates = [
            make_candidate(100, 4.0, 'Expensive'),
            make_candidate(400, 3.0, 'Cheap'),
        ]
        stops, cost, gallons = _plan_fuel_stops(700, candidates)
        self.assertEqual([s['name'] for s in stops], ['Cheap'])
        self.assertAlmostEqual(cost, gallons * 3.0)

    def test_fills_tank_at_cheap_station_before_expensive_stretch(self):
        candidates = [
            make_candidate(300, 2.5, 'Cheap'),
            make_candidate(700, 4.0, 'Expensive'),
        ]
        stops, cost, gallons = _plan_fuel_stops(1100, candidates)
        self.assertEqual([s['name'] for s in stops], ['Cheap', 'Expensive'])
        self.assertEqual(stops[0]['gallons_purchased'], 30.0)
        self.assertEqual(stops[1]['gallons_purchased'], 30.0)

    def test_raises_when_no_station_within_range(self):
        with self.assertRaises(PlanningError):
            _plan_fuel_stops(1200, [make_candidate(100, 3.0)])

    def test_total_gallons_match_distance_beyond_initial_tank(self):
        candidates = [make_candidate(pos, 3.0) for pos in range(100, 1500, 100)]
        stops, cost, gallons = _plan_fuel_stops(1500, candidates)
        self.assertAlmostEqual(gallons, 100.0)
        self.assertAlmostEqual(cost, 300.0)


class SampleRouteTests(TestCase):
    def test_cumulative_distance_is_monotonic(self):
        coordinates = [[-118.0, 34.0], [-117.5, 34.2], [-117.0, 34.4], [-116.5, 34.6]]
        samples = _sample_route(coordinates)
        positions = [position for _, _, position in samples]
        self.assertEqual(positions, sorted(positions))
        self.assertGreater(positions[-1], 0)

    def test_last_point_carries_total_distance(self):
        coordinates = [[-118.0, 34.0], [-117.0, 34.0]]
        samples = _sample_route(coordinates)
        self.assertAlmostEqual(samples[-1][2], 57.3, places=1)


class RouteApiTests(TestCase):
    def setUp(self):
        FuelStation.objects.create(
            opis_id=1, name='Midway Fuel', address='I-10', city='Midway', state='TX',
            retail_price=Decimal('3.000'), latitude=34.0, longitude=-114.0,
        )

    def fake_route(self, start, finish):
        coordinates = [
            [-118.0 + step * 0.1, 34.0] for step in range(81)
        ]
        return {'geometry': coordinates, 'distance_miles': 600.0, 'duration_hours': 9.0}

    def fake_location(self, query):
        return {'query': query, 'name': query, 'latitude': 34.0, 'longitude': -118.0}

    def test_route_endpoint_returns_plan(self):
        with patch.object(planner, 'resolve_location', side_effect=self.fake_location), \
                patch.object(planner, 'fetch_route', side_effect=self.fake_route):
            response = self.client.get('/api/route/', {'start': 'A', 'finish': 'B'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['route']['distance_miles'], 600.0)
        self.assertEqual(data['summary']['number_of_stops'], 1)
        self.assertEqual(data['fuel_stops'][0]['name'], 'Midway Fuel')

    def test_missing_params_rejected(self):
        response = self.client.get('/api/route/', {'start': 'A'})
        self.assertEqual(response.status_code, 400)

# Fuel Route Planner

Django API that plans a driving route between two locations in the USA and
picks the most cost-effective fuel stops along the way, based on real fuel
prices from the OPIS truckstop dataset.

The vehicle is assumed to have a 500 mile range on a full tank and to achieve
10 miles per gallon.

## How it works

- **Station geocoding (one-time, offline):** the assessment CSV only has city
  and state for each truckstop, so a management command geocodes all ~6,700
  stations against the free US Census Gazetteer files (city centroids). No
  paid or rate-limited geocoding API is involved, and nothing is geocoded at
  request time.
- **Routing (1 call per request):** the route is fetched from the free OSRM
  demo server in a single request that returns both the geometry and the
  distance. Results are cached in memory, so repeating a request makes no
  external calls at all.
- **Start/finish geocoding (up to 2 calls per request):** free-text inputs are
  resolved through Nominatim (also cached). You can pass raw `lat,lon`
  coordinates instead to skip these calls entirely.
- **Fuel stop selection:** the route geometry is downsampled to points ~2
  miles apart and indexed in a coarse spatial grid. Every station within 5
  miles of the route is located along it, then a greedy pass picks stops:
  whenever the destination is out of range, stop at the cheapest reachable
  station and buy exactly the fuel needed to reach the next stop (or the
  destination). The tank is assumed full at the start.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py import_stations
python manage.py runserver
```

`import_stations` downloads the two Census Gazetteer files (~4 MB total) into
`data/` on first run, then loads the stations into SQLite.

## API

```
GET /api/route/?start=<location>&finish=<location>
```

`start` and `finish` accept free text (`Los Angeles, CA`) or coordinates
(`34.05,-118.24`).

Example:

```bash
curl "http://127.0.0.1:8000/api/route/?start=Los Angeles, CA&finish=New York, NY"
```

Response:

```json
{
  "start": {"query": "...", "name": "...", "latitude": 34.05, "longitude": -118.24},
  "finish": {"query": "...", "name": "...", "latitude": 40.71, "longitude": -74.0},
  "route": {
    "distance_miles": 2789.6,
    "duration_hours": 41.4,
    "geometry": {"type": "LineString", "coordinates": [[-118.24, 34.05], ...]}
  },
  "fuel_stops": [
    {
      "name": "PILOT TRAVEL CENTER",
      "city": "...", "state": "...",
      "latitude": 35.1, "longitude": -111.6,
      "price_per_gallon": 3.15,
      "miles_from_start": 466.2,
      "gallons_purchased": 48.9,
      "fuel_cost_usd": 154.04
    }
  ],
  "summary": {
    "total_fuel_cost_usd": 731.5,
    "total_gallons_purchased": 229.0,
    "number_of_stops": 5,
    "assumptions": {"vehicle_range_miles": 500, "miles_per_gallon": 10, "tank_full_at_start": true}
  }
}
```

A small map UI is served at `http://127.0.0.1:8000/` — it calls the same API
and renders the route and fuel stops with Leaflet.

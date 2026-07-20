import csv
import io
import re
import unicodedata
import zipfile
from decimal import Decimal
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from routes.models import FuelStation

DATA_DIR = Path(settings.BASE_DIR) / 'data'
FUEL_PRICES_CSV = DATA_DIR / 'fuel-prices-for-be-assessment.csv'

GAZETTEER_URL = 'https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/{}.zip'
GAZETTEER_FILES = ['2023_Gaz_place_national', '2023_Gaz_cousubs_national']

PLACE_SUFFIX = re.compile(
    r' (city|town|village|cdp|borough|municipality|township|charter township'
    r'|plantation|gore|grant|location|purchase|reservation|comunidad'
    r'|zona urbana|city and borough|consolidated government|metro government'
    r'|metropolitan government|unified government|urban county)( \(balance\))?$'
)


class Command(BaseCommand):
    help = (
        'Load fuel stations from the assessment CSV into the database, '
        'geocoding each one by city/state using the free US Census Gazetteer.'
    )

    def handle(self, *args, **options):
        if not FUEL_PRICES_CSV.exists():
            raise CommandError(f'Fuel prices file not found: {FUEL_PRICES_CSV}')

        lookup = self.build_city_lookup()
        stations, skipped = self.read_stations(lookup)

        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(stations, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f'Imported {len(stations)} fuel stations ({skipped} rows skipped: '
            'non-US or city not found in the gazetteer)'
        ))

    def build_city_lookup(self):
        """Map normalized (city, state) pairs to coordinates using the Census
        Gazetteer places and county subdivisions files."""
        lookup = {}
        for name in GAZETTEER_FILES:
            path = DATA_DIR / f'{name}.txt'
            if not path.exists():
                self.download_gazetteer(name, path)
            with open(path, encoding='latin-1') as f:
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    row = {k.strip(): v.strip() for k, v in row.items() if k}
                    state = row['USPS']
                    coords = (float(row['INTPTLAT']), float(row['INTPTLONG']))
                    place = PLACE_SUFFIX.sub('', normalize_name(row['NAME']))
                    for key in city_keys(place, state):
                        lookup.setdefault(key, coords)
                    base = place.split('-')[0]
                    if base != place:
                        for key in city_keys(base, state):
                            lookup.setdefault(key, coords)
        return lookup

    def download_gazetteer(self, name, destination):
        self.stdout.write(f'Downloading {name} from census.gov ...')
        try:
            response = requests.get(GAZETTEER_URL.format(name), timeout=120)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f'Could not download gazetteer file: {exc}') from exc
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            destination.write_bytes(archive.read(f'{name}.txt'))

    def read_stations(self, lookup):
        """Build station records, keeping the cheapest price when the same
        OPIS truckstop appears more than once in the CSV."""
        by_id = {}
        skipped = 0
        with open(FUEL_PRICES_CSV, newline='') as f:
            for row in csv.DictReader(f):
                opis_id = int(row['OPIS Truckstop ID'])
                price = Decimal(row['Retail Price']).quantize(Decimal('0.001'))
                existing = by_id.get(opis_id)
                if existing is not None:
                    existing.retail_price = min(existing.retail_price, price)
                    continue
                coords = self.locate(row['City'], row['State'], lookup)
                if coords is None:
                    skipped += 1
                    continue
                by_id[opis_id] = FuelStation(
                    opis_id=opis_id,
                    name=row['Truckstop Name'].strip(),
                    address=row['Address'].strip(),
                    city=row['City'].strip(),
                    state=row['State'].strip(),
                    retail_price=price,
                    latitude=coords[0],
                    longitude=coords[1],
                )
        return list(by_id.values()), skipped

    def locate(self, city, state, lookup):
        for key in city_keys(normalize_name(city), state.strip()):
            if key in lookup:
                return lookup[key]
        return None


def normalize_name(name):
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode()
    name = re.sub(r'\s+', ' ', name.lower().strip())
    name = name.replace('saint ', 'st. ')
    name = re.sub(r'^mc ', 'mc', name)
    return name


def city_keys(name, state):
    """Yield lookup keys for a city name: the name itself, a squashed
    letters-only form (handles Winston Salem vs Winston-Salem), and the name
    without a trailing "city" (handles Boise vs Boise City)."""
    yield name, state
    yield re.sub(r'[^a-z]', '', name), state
    if name.endswith(' city'):
        yield name[:-5], state

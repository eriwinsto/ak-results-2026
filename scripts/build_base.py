"""Build site/data/base.json: the reference layers drawn under and over the results map.

Sources (all public domain):
  * U.S. Census Bureau TIGER/Line 2024: Alaska places (tl_2024_02_place) and
    primary/secondary roads (tl_2024_02_prisecroads)
  * U.S. Census Bureau 2020 redistricting file (PL 94-171), Alaska geo header: place populations
  * Natural Earth 1:10m: countries (Canada, Russia), lakes, rivers

Usage:
  python3 scripts/build_base.py            # downloads into build/base/ the first time
Needs: pip install pyshp ; npm i -g mapshaper ; site/data/geo.json built first
(Anchorage neighborhood labels are placed on the Division's precincts of the same name.)
"""
import json, os, re, subprocess, sys, urllib.request, zipfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, 'build', 'base')
OUT = os.path.join(ROOT, 'site', 'data', 'base.json')
P = '+proj=aea +lat_1=55 +lat_2=65 +lat_0=50 +lon_0=-154 +x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs'
NE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/'
SRC = {
    'place.zip': 'https://www2.census.gov/geo/tiger/TIGER2024/PLACE/tl_2024_02_place.zip',
    'roads.zip': 'https://www2.census.gov/geo/tiger/TIGER2024/PRISECROADS/tl_2024_02_prisecroads.zip',
    'pl.zip': 'https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Alaska/ak2020.pl.zip',
    'countries.geojson': NE + 'ne_10m_admin_0_countries.geojson',
    'lakes.geojson': NE + 'ne_10m_lakes.geojson',
    'rivers.geojson': NE + 'ne_10m_rivers_lake_centerlines.geojson',
    'towns.geojson': NE + 'ne_10m_populated_places_simple.geojson',
}
# clip box in projected metres: the map's extent plus a margin
CLIP = '-2700000,50000,2050000,2850000'

# Regional hubs labeled before larger suburbs, so the statewide view reads as a map of Alaska.
HUBS = ['Anchorage', 'Fairbanks', 'Juneau', 'Utqiaġvik', 'Nome', 'Kotzebue', 'Bethel', 'Dillingham',
        'Kodiak', 'Unalaska', 'Ketchikan', 'Sitka', 'Valdez', 'Tok', 'Galena', 'McGrath', 'Wasilla',
        'Palmer', 'Homer', 'Kenai', 'Soldotna', 'Seward', 'Cordova', 'Petersburg', 'Wrangell', 'Haines',
        'Skagway', 'Craig', 'Delta Junction', 'Glennallen', 'Prudhoe Bay', 'Fort Yukon', 'Aniak',
        'King Salmon', 'Sand Point', 'St. Paul', 'Unalakleet', 'Hooper Bay', 'Metlakatla', 'Healy']
# Anchorage neighborhoods, placed on the precincts that carry the name (Division precinct names)
NEIGHBORHOODS = {
    'Downtown': ['Downtown Anchorage'], 'Midtown': ['North Midtown', 'South Midtown'],
    'Eagle River': ['Eagle River'], 'Peters Creek': ['Peters Creek'], 'Hillside': ['Hillside'],
    'JBER': ['JBER'], 'Muldoon': ['North Muldoon'], 'Mountain View': ['Mountainview', 'South Mountainview'],
    'Government Hill': ['Government Hill'], 'Airport Heights': ['Airport Heights'], 'Oceanview': ['Oceanview'],
}
SEAS = [('Bering Sea', -176.0, 58.5), ('Gulf of Alaska', -145.0, 57.0), ('Chukchi Sea', -169.0, 69.5),
        ('Beaufort Sea', -146.0, 71.6), ('Bristol Bay', -160.0, 57.9), ('Cook Inlet', -152.3, 60.25)]
COUNTRIES = [('CANADA', -133.0, 63.5), ('RUSSIA', -176.5, 65.6)]

def fetch():
    os.makedirs(WORK, exist_ok=True)
    for f, u in SRC.items():
        p = os.path.join(WORK, f)
        if not os.path.exists(p):
            print('downloading', u)
            urllib.request.urlretrieve(u, p)
        if f.endswith('.zip'):
            d = os.path.join(WORK, f[:-4])
            if not os.path.isdir(d):
                zipfile.ZipFile(p).extractall(d)

def ms(*args):
    subprocess.run(['mapshaper', *args], check=True, stderr=subprocess.DEVNULL)

def main():
    fetch()
    import shapefile
    from pyproj import Transformer
    tf = Transformer.from_crs('EPSG:4326', P, always_xy=True)
    W = lambda *a: os.path.join(WORK, *a)

    # --- layers via mapshaper -> one TopoJSON
    ms('-i', W('countries.geojson'), '-filter', "['CAN','RUS'].indexOf(ADM0_A3) > -1",
       '-filter-fields', 'ADM0_A3', '-proj', P, '-clip', f'bbox={CLIP}',
       '-simplify', '8%', 'planar', 'keep-shapes', '-o', W('neighbors.json'), 'format=geojson')
    ms('-i', W('lakes.geojson'), '-clip', 'bbox=-180,50,-128,72', '-filter-fields', 'name',
       '-proj', P, '-simplify', '30%', 'planar', '-o', W('lakes_p.json'), 'format=geojson')
    ms('-i', W('rivers.geojson'), '-clip', 'bbox=-170,55,-129,71', '-filter', 'scalerank <= 8',
       '-filter-fields', 'name,scalerank', '-proj', P, '-simplify', '30%', 'planar', '-o', W('rivers_p.json'), 'format=geojson')
    ms('-i', W('roads', 'tl_2024_02_prisecroads.shp'), '-each', "cls = MTFCC == 'S1100' ? 1 : 2",
       '-filter-fields', 'cls', '-proj', P, '-dissolve', 'cls', '-simplify', '12%', 'planar',
       '-o', W('roads_p.json'), 'format=geojson')
    tmp = W('base_topo.json')
    ms('-i', W('neighbors.json'), W('lakes_p.json'), W('rivers_p.json'), W('roads_p.json'), 'combine-files',
       '-rename-layers', 'neighbors,lakes,rivers,roads',
       '-o', 'format=topojson', 'quantization=40000', tmp)
    topo = json.load(open(tmp))

    # --- place labels: TIGER internal points + 2020 population
    pop = {}
    for line in open(W('pl', 'akgeo2020.pl'), encoding='latin-1'):
        r = line.split('|')
        if r[2] == '160' and r[4] == '00':
            pop[r[9]] = int(r[90])
    # TIGER's internal point for a large borough or municipality (Anchorage, Juneau) can sit far
    # from town, so use Natural Earth's town point where it has one.
    town = {f['properties']['name']: f['geometry']['coordinates'] for f in json.load(open(W('towns.geojson')))['features']
            if f['properties'].get('adm1name') == 'Alaska'}
    places = []
    for rec in shapefile.Reader(W('place', 'tl_2024_02_place')).records():
        lon, lat = town.get(rec['NAME'], (float(rec['INTPTLON']), float(rec['INTPTLAT'])))
        x, y = tf.transform(lon, lat)
        n = rec['NAME']
        p = pop.get(rec['GEOID'], 0)
        tier = 1 if n in HUBS[:3] else 2 if n in HUBS else 3 if rec['LSAD'] in ('25', '53', '37') else 4
        places.append([n, round(x), round(y), p, tier])

    # --- Anchorage neighborhoods, placed on the Division precincts that carry the name
    from shapely.geometry import shape
    from shapely.ops import unary_union
    gj = W('precincts_p.json')
    ms('-i', os.path.join(ROOT, 'site', 'data', 'geo.json'), '-o', gj, 'format=geojson', 'target=precincts')
    feats = json.load(open(gj))['features']
    groups = defaultdict(list)
    for f in feats:
        pr = f['properties']
        if not 9 <= pr['hd'] <= 24:
            continue
        base = re.sub(r'\s*(No\.?\s*\d+|#\s*\d+|\d+)$', '', pr['name']).strip()
        for label, names in NEIGHBORHOODS.items():
            if base in names:
                groups[label].append(shape(f['geometry']))
    hoods = []
    for label, geoms in groups.items():
        u = unary_union(geoms)
        pt = u.representative_point() if not u.contains(u.centroid) else u.centroid
        hoods.append([label, round(pt.x), round(pt.y), 0, 5])
    seas = [[n, *map(round, tf.transform(lon, lat)), 0, 6] for n, lon, lat in SEAS]
    countries = [[n, *map(round, tf.transform(lon, lat)), 0, 7] for n, lon, lat in COUNTRIES]

    topo['labels'] = places + hoods + seas + countries
    topo['source'] = 'U.S. Census Bureau TIGER/Line 2024 and 2020 census; Natural Earth'
    json.dump(topo, open(OUT, 'w'), separators=(',', ':'), ensure_ascii=False)
    print(f'wrote {OUT} ({os.path.getsize(OUT):,} bytes): {len(places)} places, {len(hoods)} neighborhoods; '
          f"layers {[(k, len(v['geometries'])) for k, v in topo['objects'].items()]}")

if __name__ == '__main__':
    main()

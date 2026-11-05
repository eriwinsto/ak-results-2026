"""Build site/data/geo.json (TopoJSON) from the Division of Elections precinct shapefile.

Usage: python3 scripts/build_geo.py /path/to/Precincts.shp
Needs: pip install pyshp shapely ; npm i -g mapshaper
Eight precincts in the 2023 file have counter-clockwise outer rings, which
mapshaper reads as holes and drops; they are re-oriented here first.

Division precincts extend across open water (Cook Inlet, Knik Arm, the Inside Passage), so the
shapes are clipped to the shoreline with the Census Bureau's cartographic boundary file for
Alaska (cb_2024_us_state_500k, public domain), downloaded into build/base/ the first time.
"""
import json, subprocess, sys, os, tempfile, urllib.request, zipfile
import shapefile
from shapely.geometry import shape, mapping
from shapely.geometry.polygon import orient
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import make_valid

src = sys.argv[1]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(root, 'site', 'data', 'geo.json')
r = shapefile.Reader(os.path.splitext(src)[0])
feats = []
for s, rec in zip(r.shapes(), r.records()):
    g = make_valid(shape(s.__geo_interface__))
    polys = [p for p in getattr(g, 'geoms', [g]) if isinstance(p, Polygon)] or \
            [q for p in getattr(g, 'geoms', [g]) if hasattr(p, 'geoms') for q in p.geoms if isinstance(q, Polygon)]
    g = MultiPolygon([orient(p, 1.0) for p in polys])
    n = rec['Precinct_N']
    feats.append({'type': 'Feature', 'geometry': mapping(g),
                  'properties': {'id': n[:6], 'name': n[7:].strip(), 'hd': int(rec['HouseDistr']), 'sd': rec['SenateDist']}})
tmp = tempfile.mkdtemp()
fp = os.path.join(tmp, 'precincts.json')
json.dump({'type': 'FeatureCollection', 'features': feats}, open(fp, 'w'))
P = '+proj=aea +lat_1=55 +lat_2=65 +lat_0=50 +lon_0=-154 +x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs'
M = '+proj=merc +a=6378137 +b=6378137 +lat_ts=0 +lon_0=0 +x_0=0 +y_0=0 +k=1 +units=m +no_defs'
CB = 'https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip'
base = os.path.join(root, 'build', 'base')
os.makedirs(base, exist_ok=True)
cbz = os.path.join(base, 'cb_state.zip')
if not os.path.exists(cbz):
    print('downloading', CB)
    urllib.request.urlretrieve(CB, cbz)
cbd = os.path.join(base, 'cb_state')
if not os.path.isdir(cbd):
    zipfile.ZipFile(cbz).extractall(cbd)
land = os.path.join(tmp, 'land.json')
subprocess.run(['mapshaper', '-i', os.path.join(cbd, 'cb_2024_us_state_500k.shp'), '-filter', "STUSPS=='AK'",
                '-proj', P, '-o', land, 'format=geojson'], check=True)
subprocess.run(['mapshaper', '-i', fp, 'snap', 'name=precincts', '-proj', f'from={M}', P,
                '-clip', land, 'remove-slivers',
                '-simplify', '4%', 'weighted', 'keep-shapes', 'planar',
                '-dissolve', 'hd', '+', 'name=districts', 'copy-fields=sd',
                '-dissolve', 'sd', 'target=districts', '+', 'name=senate',
                '-o', 'format=topojson', 'quantization=20000', 'target=precincts,districts,senate', out], check=True)
print('wrote', out, os.path.getsize(out), 'bytes')

# Region boxes (lon/lat) for the map's quick-zoom buttons, projected to the same
# Alaska Albers metres as the geometry and stored in geo.json as "regions".
from pyproj import Transformer
REGIONS = {
    'Anchorage': (-150.00, 61.10, -149.66, 61.25),
    'Mat-Su': (-150.25, 61.48, -148.95, 61.72),
    'Fairbanks': (-148.15, 64.74, -147.30, 64.98),
    'Kenai Peninsula': (-151.95, 59.45, -149.30, 60.85),
    'Juneau': (-134.75, 58.26, -134.33, 58.45),
    'Southeast': (-137.6, 54.6, -130.0, 59.6),
}
tf = Transformer.from_crs('EPSG:4326', P, always_xy=True)
reg = {}
for k, (x0, y0, x1, y1) in REGIONS.items():
    pts = [tf.transform(x, y) for x in (x0, x1) for y in (y0, y1)]
    reg[k] = [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]
topo = json.load(open(out))
topo['regions'] = reg
json.dump(topo, open(out, 'w'), separators=(',', ':'))
print('regions:', list(reg))

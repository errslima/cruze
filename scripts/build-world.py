"""Build compact Equal Earth country paths from Natural Earth's public-domain GeoJSON.
Usage: python scripts/build-world.py /path/to/ne_110m_admin_0_countries.geojson
Source: https://github.com/nvkelso/natural-earth-vector/tree/master/geojson
"""
import json
import math
from pathlib import Path
import sys


def project(lon, lat):
    theta = math.asin(math.sqrt(3) / 2 * math.sin(math.radians(lat)))
    t2, t6 = theta**2, theta**6
    a, b, c, d = 1.340264, -.081106, .000893, .003796
    x = 2 * math.sqrt(3) * math.radians(lon) * math.cos(theta) / (3 * (a + 3*b*t2 + t6*(7*c+9*d*t2)))
    y = theta * (a + b*t2 + t6*(c+d*t2))
    return f'{500+x*180:.1f},{260-y*180:.1f}'

result = []
for feature in json.loads(Path(sys.argv[1]).read_text())['features']:
    props, geometry = feature['properties'], feature['geometry']
    if props['ADMIN'] == 'Antarctica':
        continue
    code = props.get('ISO_A2_EH', props['ISO_A2'])
    polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
    path = ''.join('M'+'L'.join(project(*point[:2]) for point in ring)+'Z' for polygon in polygons for ring in polygon)
    result.append({'code': code, 'path': path})
Path('static/world.json').write_text(json.dumps(result, separators=(',', ':'))+'\n')

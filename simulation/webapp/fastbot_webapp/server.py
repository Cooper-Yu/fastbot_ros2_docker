#!/usr/bin/env python3
"""FastBot static site and atomic project waypoint storage (no robot commands)."""

import argparse
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit


class WaypointStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {'version': 1, 'revision': 0, 'waypoints': []}
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or type(data.get('revision')) is not int:
                raise ValueError('Invalid stored waypoint document; restore the project backup')
            self.validate(data['waypoints'])
            return data

    @staticmethod
    def validate(points):
        if not isinstance(points, list) or len(points) > 100:
            raise ValueError('At most 100 waypoints are supported')
        ids, names = set(), set()
        for p in points:
            if not isinstance(p, dict):
                raise ValueError('Invalid waypoint')
            for field, limit in [('id', 128), ('name', 48), ('frame', 256), ('mapId', 4096)]:
                if not isinstance(p.get(field), str) or not 1 <= len(p[field].strip()) <= limit:
                    raise ValueError(f'Invalid waypoint {field}')
            if p['id'] in ids or p['name'] in names:
                raise ValueError('Choose a unique waypoint name')
            if not all(
                type(p.get(k)) in (int, float) and math.isfinite(p[k]) for k in ('x', 'y', 'yaw')
            ):
                raise ValueError('Coordinates and yaw must be finite numbers')
            ids.add(p['id'])
            names.add(p['name'])

    def replace(self, revision, points):
        self.validate(points)
        with self.lock:
            current = self.read()
            if type(revision) is not int or revision != current['revision']:
                raise Conflict(current)
            result = {
                'version': 1,
                'revision': revision + 1,
                'waypoints': [
                    {k: p[k] for k in ('id', 'name', 'x', 'y', 'yaw', 'frame', 'mapId')}
                    for p in points
                ],
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.waypoints-', suffix='.tmp', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, allow_nan=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp, self.path)
                directory = os.open(self.path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return result


def project_store(root, data_dir=None, legacy=None):
    """Initialize only a missing store; an intentionally empty saved list stays empty."""
    root = Path(root)
    store = WaypointStore(Path(data_dir or root / 'data') / 'waypoints.json')
    if not store.path.exists():
        legacy = (
            Path(legacy)
            if legacy is not None
            else Path.home() / '.local/share/fastbot_slam/waypoints.json'
        )
        seed = root / 'config/waypoints.default.json'
        source = legacy if legacy.is_file() else seed
        if source.is_file():
            document = json.loads(source.read_text(encoding='utf-8'))
            store.replace(0, document['waypoints'])
    store.read()  # Corrupt files must fail loudly, never silently become an empty list.
    return store


class Conflict(Exception):
    def __init__(self, current):
        self.current = current


def handler(root, store):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            super().end_headers()

        def json_response(self, status, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == '/api/waypoints':
                try:
                    self.json_response(200, store.read())
                except (OSError, ValueError, KeyError):
                    self.json_response(
                        500, {'error': 'Cannot read project waypoints; check or restore the backup'}
                    )
            elif (
                Path(self.translate_path(self.path))
                .resolve()
                .is_relative_to(store.path.parent.resolve())
                or path == '/data'
                or path.startswith('/data/')
                or any(part.startswith('.') for part in path.split('/') if part)
            ):
                self.send_error(404)
            elif path.startswith('/api/'):
                self.send_error(404)
            else:
                super().do_GET()

        def do_PUT(self):
            if urlsplit(self.path).path != '/api/waypoints':
                return self.send_error(404)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.send_error(403)
            if self.headers.get_content_type() != 'application/json':
                return self.send_error(415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 512 * 1024:
                    return self.send_error(413)
                data = json.loads(self.rfile.read(size))
                self.json_response(200, store.replace(data.get('revision'), data.get('waypoints')))
            except Conflict as error:
                self.json_response(
                    409,
                    {
                        'error': 'Waypoints changed in another window; reopen the editor',
                        'current': error.current,
                    },
                )
            except (ValueError, TypeError, AttributeError) as error:
                self.json_response(400, {'error': str(error)})
            except OSError:
                self.json_response(
                    500, {'error': 'Project waypoint save failed; disk write is unconfirmed'}
                )

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', nargs='?', type=int, default=7000)
    parser.add_argument(
        '--data-dir',
        type=Path,
        default=None,
        help='Persistent project directory (default: ./data beside server.py)',
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    store = project_store(root, args.data_dir)
    server = ThreadingHTTPServer(('0.0.0.0', args.port), handler(root, store))
    print(f'FastBot webpage port {args.port}; project waypoints: {store.path}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

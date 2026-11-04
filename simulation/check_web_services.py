#!/usr/bin/env python3
"""Coach support: check the two container-local Web services at startup."""
import argparse
import base64
import hashlib
import json
import os
import socket
import time
import urllib.request


def check_services():
    with urllib.request.urlopen('http://127.0.0.1:8000/index.html', timeout=0.4) as reply:
        if reply.status != 200 or b'<html' not in reply.read(1024):
            raise RuntimeError('HTTP index is not ready')
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        'GET / HTTP/1.1\r\nHost: 127.0.0.1:9090\r\nUpgrade: websocket\r\n'
        'Connection: Upgrade\r\nSec-WebSocket-Key: ' + key
        + '\r\nSec-WebSocket-Version: 13\r\n\r\n'
    ).encode()
    with socket.create_connection(('127.0.0.1', 9090), timeout=0.4) as connection:
        connection.sendall(request)
        response = b''
        while b'\r\n\r\n' not in response:
            part = connection.recv(4096)
            if not part or len(response) > 16384:
                raise RuntimeError('Incomplete WebSocket handshake')
            response += part
    lines = response.split(b'\r\n')
    if b' 101 ' not in lines[0]:
        raise RuntimeError('WebSocket upgrade was rejected')
    headers = {
        key.strip().lower(): value.strip()
        for row in lines[1:] if b':' in row
        for key, value in [row.split(b':', 1)]
    }
    expected = base64.b64encode(
        hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()
    )
    if headers.get(b'sec-websocket-accept') != expected:
        raise RuntimeError('Invalid WebSocket accept header')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=15)
    args = parser.parse_args()
    if not 0 < args.timeout <= 120:
        parser.error('timeout must be between 0 and 120 seconds')
    deadline = time.monotonic() + args.timeout
    last_error = 'Services have not responded'
    while time.monotonic() < deadline:
        try:
            check_services()
            print(json.dumps({'http_ready': True, 'rosbridge_handshake_ready': True}))
            return
        except (OSError, ValueError, RuntimeError) as error:
            last_error = str(error)
            time.sleep(0.2)
    raise SystemExit('CP23 Web startup readiness failed: ' + last_error)


if __name__ == '__main__':
    main()
import ipaddress
import socket
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from urllib.parse import quote, unquote, urlsplit


def browser_host(host):
    if host != '0.0.0.0':
        return host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.connect(('192.0.2.1', 1))
            address = connection.getsockname()[0]
            if not ipaddress.ip_address(address).is_loopback:
                return address
    except OSError:
        pass
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = entry[4][0]
            if not ipaddress.ip_address(address).is_loopback:
                return address
    except OSError:
        pass
    return '127.0.0.1'


class ReportServer(ThreadingHTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class ReportHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, report, **kwargs):
        self.report = report
        super().__init__(*args, directory=str(report.parent), **kwargs)

    def send_head(self):
        if unquote(urlsplit(self.path).path) != '/' + self.report.name:
            self.send_error(404)
            return None
        return super().send_head()

    def log_message(self, format, *args):
        pass


def serve_report(report, host='0.0.0.0', port=8000):
    handler = partial(ReportHandler, report=report.resolve())
    with ReportServer((host, port), handler) as server:
        address = browser_host(host)
        url = f'http://{address}:{server.server_port}/{quote(report.name)}'
        print(f'[progress] Serving report on {host}:{server.server_port}; press Ctrl+C to stop',
              file=sys.stderr, flush=True)
        print(f'[open in browser] {url}', file=sys.stderr, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

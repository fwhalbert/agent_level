import contextlib
import io
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, build_opener

import assess
from assessment import server
from tests.test_assessment_core import TempCase


class TestReportServer(TempCase):
    def test_browser_host_uses_route_address(self):
        with patch.object(server.socket, 'socket') as connection:
            connection.return_value.__enter__.return_value.getsockname.return_value = ('192.168.1.12', 1234)
            self.assertEqual(server.browser_host('0.0.0.0'), '192.168.1.12')
            self.assertEqual(server.browser_host('127.0.0.1'), '127.0.0.1')
            self.assertEqual(server.browser_host('192.168.1.20'), '192.168.1.20')

    def test_browser_host_falls_back_without_a_default_route(self):
        with patch.object(server.socket, 'socket', side_effect=OSError), \
                patch.object(server.socket, 'getaddrinfo', return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 0)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.1.2.3', 0)),
                ]):
            self.assertEqual(server.browser_host('0.0.0.0'), '10.1.2.3')
        with patch.object(server.socket, 'socket', side_effect=OSError), \
                patch.object(server.socket, 'getaddrinfo', side_effect=OSError):
            self.assertEqual(server.browser_host('0.0.0.0'), '127.0.0.1')

    def test_serve_rejects_stdout_non_html_and_invalid_ports(self):
        cases = [(['--serve', '-o', '-'], 'requires an HTML report'),
                 (['--serve', '--format', 'json'], 'requires an HTML report'),
                 (['--serve', '--port', '-1'], '--port must be'),
                 (['--serve', '--port', '65536'], '--port must be')]
        for args, message in cases:
            with self.subTest(args=args):
                status, output, error = self.cli(args, stdout=False)
                self.assertEqual((status, output), (2, ''))
                self.assertIn(message, error)

    def test_cli_defaults_to_all_interfaces_and_reports_bind_errors(self):
        report = self.root / 'report.html'
        args = ['--source', 'claude', '--claude-dir', str(self.root / 'missing'),
                '--serve', '-o', str(report)]
        with patch.object(server, 'serve_report', side_effect=OSError('Address already in use')) as serve:
            status, output, error = self.cli(args, stdout=False)
        self.assertEqual((status, output), (2, ''))
        serve.assert_called_once_with(report, '0.0.0.0', 8000)
        self.assertTrue(report.is_file())
        self.assertIn('cannot serve report: Address already in use', error)
        self.assertNotIn('[open in browser]', error)

    def test_serve_dual_format_uses_html_path(self):
        output = self.root / 'report.json'
        with patch.object(server, 'serve_report') as serve:
            status, _, _ = self.cli(['--source', 'claude', '--claude-dir', str(self.root / 'missing'),
                                    '--serve', '--format', 'txt+html', '-o', str(output)], stdout=False)
        self.assertEqual(status, 0)
        serve.assert_called_once_with(output.with_suffix('.html'), '0.0.0.0', 8000)
        self.assertTrue(output.with_suffix('.txt').is_file())

    def test_http_cli_serves_only_the_report_and_stops_on_interrupt(self):
        report = self.root / 'report 空格 #.html'
        private = self.root / 'private.txt'
        private.write_text('private data', encoding='utf-8')
        process = subprocess.Popen(
            [sys.executable, str(Path(assess.__file__).with_name('agent-level')),
             '--source', 'claude', '--claude-dir', str(self.root / 'missing'),
             '--no-auto-evals', '--serve', '--host', '127.0.0.1', '--port', '0', '-o', str(report)],
            cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop_process, process)
        prefix = b'[open in browser] '
        captured = b''
        deadline = time.monotonic() + 10
        with selectors.DefaultSelector() as selector:
            selector.register(process.stderr, selectors.EVENT_READ)
            while prefix not in captured or not captured.endswith(b'\n'):
                remaining = deadline - time.monotonic()
                self.assertGreater(remaining, 0, captured.decode())
                self.assertTrue(selector.select(remaining), captured.decode())
                chunk = os.read(process.stderr.fileno(), 4096)
                self.assertTrue(chunk, captured.decode())
                captured += chunk
        url = next(line[len(prefix):].decode() for line in captured.splitlines() if line.startswith(prefix))
        self.assertNotIn(b'file://', captured)
        self.assertEqual(urlsplit(url).path, '/' + quote(report.name))
        opener = build_opener(ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            self.assertEqual(response.headers.get_content_type(), 'text/html')
            self.assertEqual(response.read(), report.read_bytes())
        with opener.open(url + '?download=1', timeout=5) as response:
            self.assertEqual(response.read(), report.read_bytes())
        base = url.rsplit('/', 1)[0]
        for path in ('/', '/private.txt', '/%70rivate.txt', '/../private.txt', '/%2e%2e/private.txt'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                opener.open(base + path, timeout=5)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        process.send_signal(signal.SIGINT)
        output, error = process.communicate(timeout=5)
        self.assertEqual((process.returncode, output, error), (0, '', ''))

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.kill()
        process.communicate()

    def test_server_announces_intranet_address_and_actual_port(self):
        report = self.root / 'report.html'
        with patch.object(server, 'ThreadingHTTPServer') as factory, \
                patch.object(server, 'browser_host', return_value='192.168.1.12'), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            instance = factory.return_value.__enter__.return_value
            instance.server_port = 8123
            instance.serve_forever.side_effect = KeyboardInterrupt
            server.serve_report(report, port=0)
        self.assertIn('[open in browser] http://192.168.1.12:8123/report.html', error.getvalue())
        factory.return_value.__exit__.assert_called_once()

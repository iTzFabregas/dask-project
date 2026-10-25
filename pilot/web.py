"""Static results server without reverse-DNS lookups during bind."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer


class ResultsServer(ThreadingHTTPServer):
    def server_bind(self):
        TCPServer.server_bind(self)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


def serve(directory, bind, port):
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    with ResultsServer((bind, port), handler) as server:
        print(f'Static results: http://{bind}:{port}; directory={directory}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass

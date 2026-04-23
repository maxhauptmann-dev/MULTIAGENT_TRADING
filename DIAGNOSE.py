from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os

class MockHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        b = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _normalized_path(self):
        p = self.path
        # accept both /v1/api/iserver/... and /iserver/...
        if p.startswith("/v1/api"):
            p = p[len("/v1/api"):]
        return p

    def do_GET(self):
        p = self._normalized_path()
        if p.startswith("/iserver/accounts"):
            self._send_json(["DU1234567"])
        elif p.startswith("/iserver/account/") and p.endswith("/summary"):
            self._send_json({"accountSummary":[{"tag":"BuyingPower","value":"100000"}]})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        p = self._normalized_path()
        if p.startswith("/iserver/secdef/search"):
            self._send_json([{"conid":123456,"symbol":"AAPL"}])
            return
        if p.startswith("/iserver/account/") and p.endswith("/orders"):
            self._send_json({"orderId":99999,"status":"placed"})
            return
        self.send_response(404); self.end_headers()

def run(host: str = "127.0.0.1", port: int = 5003):
    # allow quick restart on same port
    class ReuseHTTPServer(HTTPServer):
        allow_reuse_address = True

    server = ReuseHTTPServer((host, port), MockHandler)
    print(f"Mock IBKR server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Mock stopped by user")
    finally:
        server.server_close()

if __name__ == "__main__":
    HOST = os.getenv("DIAGNOSE_HOST", "127.0.0.1")
    PORT = int(os.getenv("DIAGNOSE_PORT", "5003"))
    run(HOST, PORT)
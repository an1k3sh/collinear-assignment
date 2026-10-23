import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from server.codec import SyncError
from server.store import Store


class Handler(BaseHTTPRequestHandler):
    def dispatch(self):
        try:
            route = urlsplit(self.path)
            args = {key: values[0] for key, values in parse_qs(route.query).items()}
            store = Store(self.server.database)
            if self.command == "GET" and route.path == "/health":
                result = {"ok": True}
            elif self.command == "POST" and route.path in ("/mutate", "/batch"):
                try:
                    request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                except (ValueError, TypeError) as exc:
                    raise SyncError(400, "invalid") from exc
                result = store.mutate_batch(request) if route.path == "/batch" else store.mutate(request)
            elif self.command == "GET" and route.path in ("/snapshot", "/pull"):
                try:
                    tenant, limit = args["tenant"], int(args["limit"])
                    if route.path == "/snapshot":
                        result = store.snapshot(tenant, limit, args.get("cursor"))
                    else:
                        result = store.pull(tenant, args["checkpoint"], limit, args.get("cursor"))
                except (KeyError, ValueError) as exc:
                    raise SyncError(400, "invalid") from exc
            else:
                raise SyncError(404, "not_found")
            status = 200
        except SyncError as exc:
            status, result = exc.status, {"ok": False, "code": exc.code, "detail": exc.detail}
        except Exception:
            logging.exception("Unhandled synchronization request failure")
            status, result = 500, {"ok": False, "code": "internal"}
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = dispatch
    do_POST = dispatch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.database = args.db
    server.serve_forever()


if __name__ == "__main__":
    main()

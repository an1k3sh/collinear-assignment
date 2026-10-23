import argparse
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from server.codec import SyncError
from server.store import Store


def _reject_constant(name):
    raise ValueError(f"nonfinite constant {name}")


class Handler(BaseHTTPRequestHandler):
    def read_json(self):
        try:
            length = int(self.headers["Content-Length"])
            if length < 0:
                raise ValueError("negative length")
            return json.loads(self.rfile.read(length).decode("utf-8"),
                              parse_constant=_reject_constant)
        except (ValueError, TypeError, RecursionError) as exc:
            raise SyncError(400, "invalid") from exc

    def dispatch(self):
        try:
            route = urlsplit(self.path)
            args = {key: values[0] for key, values in
                    parse_qs(route.query, keep_blank_values=True).items()}
            store = self.server.store
            if self.command == "GET" and route.path == "/health":
                result = {"ok": True}
            elif self.command == "POST" and route.path in ("/mutate", "/batch"):
                request = self.read_json()
                result = (store.mutate_batch(request) if route.path == "/batch"
                          else store.mutate(request))
            elif self.command == "GET" and route.path in ("/snapshot", "/pull"):
                if "tenant" not in args or not re.fullmatch(r"[0-9]{1,4}", args.get("limit", "")):
                    raise SyncError(400, "invalid")
                tenant, limit = args["tenant"], int(args["limit"])
                if route.path == "/snapshot":
                    result = store.snapshot(tenant, limit, args.get("cursor"))
                else:
                    if "checkpoint" not in args:
                        raise SyncError(400, "invalid")
                    result = store.pull(tenant, args["checkpoint"], limit, args.get("cursor"))
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
    server.store = Store(args.db)
    server.serve_forever()


if __name__ == "__main__":
    main()

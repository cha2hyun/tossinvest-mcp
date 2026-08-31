from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

HOST = "127.0.0.1"
PORT = 18080

TENANTS = {
    "e2e-client-alpha": {
        "secret": "e2e-secret-alpha-not-real",
        "token": "e2e-access-token-alpha",
        "last_price": "71000",
    },
    "e2e-client-beta": {
        "secret": "e2e-secret-beta-not-real",
        "token": "e2e-access-token-beta",
        "last_price": "72000",
    },
}


class FakeTossHandler(BaseHTTPRequestHandler):
    """Strict fake for the two upstream operations exercised by the E2E test."""

    server_version = "TossInvestE2E/1"
    sys_version = ""
    token_issues: ClassVar[dict[str, int]] = {}
    token_lock: ClassVar[threading.Lock] = threading.Lock()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        if parsed.path != "/api/v1/prices":
            self._error(404, "unexpected-path")
            return

        tenant = self._tenant_for_bearer()
        if tenant is None:
            self._error(401, "invalid-token")
            return
        if not self.headers.get("User-Agent", "").startswith("tossinvest-mcp/"):
            self._error(400, "missing-user-agent")
            return

        symbols = parse_qs(parsed.query).get("symbols")
        if symbols == ["E2EERROR"]:
            self._send(
                502,
                {
                    "error": {
                        "code": "upstream-e2e-error",
                        "message": f"upstream echoed {tenant['secret']}",
                    }
                },
            )
            return
        if symbols != ["005930"]:
            self._error(400, "unexpected-symbols")
            return

        self._send(
            200,
            {
                "result": [
                    {
                        "symbol": "005930",
                        "lastPrice": tenant["last_price"],
                        "currency": "KRW",
                    }
                ]
            },
            headers={
                "X-Request-Id": f"e2e-price-{tenant['last_price']}",
                "X-RateLimit-Limit": "20",
                "X-RateLimit-Remaining": "19",
            },
        )

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/oauth2/token":
            self._error(404, "unexpected-path")
            return
        if not self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            self._error(400, "unexpected-content-type")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 4096:
            self._error(400, "invalid-content-length")
            return
        fields = parse_qs(self.rfile.read(content_length).decode("utf-8"))
        client_id = fields.get("client_id", [""])[0]
        supplied_secret = fields.get("client_secret", [""])[0]
        tenant = TENANTS.get(client_id)
        if (
            tenant is None
            or fields.get("grant_type") != ["client_credentials"]
            or not secrets.compare_digest(supplied_secret, tenant["secret"])
        ):
            self._error(401, "invalid-client")
            return

        with self.token_lock:
            issue_count = self.token_issues.get(client_id, 0) + 1
            self.token_issues[client_id] = issue_count
        if issue_count > 1:
            self._error(500, "oauth-token-was-not-cached")
            return

        self._send(
            200,
            {
                "access_token": tenant["token"],
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            headers={"X-Request-Id": f"e2e-oauth-{client_id}"},
        )

    def _tenant_for_bearer(self) -> dict[str, str] | None:
        authorization = self.headers.get("Authorization", "")
        for tenant in TENANTS.values():
            if secrets.compare_digest(authorization, f"Bearer {tenant['token']}"):
                return tenant
        return None

    def _error(self, status_code: int, code: str) -> None:
        self._send(
            status_code,
            {"error": {"code": code, "message": f"E2E fake rejected request: {code}"}},
        )

    def _send(
        self,
        status_code: int,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), FakeTossHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Minimal WSGI exchange service for official Kite Connect mobile login.

The API secret belongs only in this server's environment. Do not put it in the
Flutter application or commit it to source control.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from wsgiref.simple_server import make_server

KITE_SESSION_URL = "https://api.kite.trade/session/token"
MAX_BODY_BYTES = 8 * 1024
_REQUEST_TOKEN = re.compile(r"^[!-~]{1,2048}$")


def _response(start_response, status, payload):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store, max-age=0"),
            ("Pragma", "no-cache"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
        ],
    )
    return [body]


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path == "/health":
        configured = bool(os.environ.get("KITE_API_KEY") and os.environ.get("KITE_API_SECRET"))
        return _response(
            start_response,
            "200 OK",
            {"status": "ok", "kite_connect_configured": configured},
        )

    if method != "POST" or path != "/api/kite/session":
        return _response(start_response, "404 Not Found", {"status": "error", "message": "Not found."})

    api_key = os.environ.get("KITE_API_KEY", "").strip()
    api_secret = os.environ.get("KITE_API_SECRET", "")
    if not api_key or not api_secret:
        return _response(
            start_response,
            "503 Service Unavailable",
            {"status": "error", "message": "Kite Connect is not configured on this server."},
        )

    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        length = -1
    if length <= 0 or length > MAX_BODY_BYTES:
        return _response(start_response, "400 Bad Request", {"status": "error", "message": "Invalid request."})

    try:
        raw_body = environ["wsgi.input"].read(length)
        body = json.loads(raw_body.decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return _response(start_response, "400 Bad Request", {"status": "error", "message": "Invalid request."})
    if not isinstance(body, dict):
        return _response(start_response, "400 Bad Request", {"status": "error", "message": "Invalid request."})

    submitted_key = body.get("api_key")
    request_token = body.get("request_token")
    if (
        not isinstance(submitted_key, str)
        or not hmac.compare_digest(submitted_key.strip(), api_key)
        or not isinstance(request_token, str)
        or not _REQUEST_TOKEN.fullmatch(request_token)
    ):
        return _response(
            start_response,
            "400 Bad Request",
            {"status": "error", "message": "Invalid Kite login response. Start the login again."},
        )

    checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode("utf-8")).hexdigest()
    form = urlencode(
        {"api_key": api_key, "request_token": request_token, "checksum": checksum}
    ).encode("ascii")
    request = Request(
        KITE_SESSION_URL,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Kite-Version": "3",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                return _response(
                    start_response,
                    "401 Unauthorized",
                    {"status": "error", "message": "Kite rejected the login. The request token may have expired."},
                )
            result = json.loads(response.read(64 * 1024).decode("utf-8"))
    except HTTPError:
        return _response(
            start_response,
            "401 Unauthorized",
            {"status": "error", "message": "Kite rejected the login. The request token may have expired."},
        )
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _response(
            start_response,
            "502 Bad Gateway",
            {"status": "error", "message": "Could not complete the secure Kite token exchange."},
        )

    data = result.get("data") if isinstance(result, dict) and result.get("status") == "success" else None
    if not isinstance(data, dict):
        return _response(
            start_response,
            "401 Unauthorized",
            {"status": "error", "message": "Kite rejected the login. Check the API key and retry."},
        )

    returned_key = data.get("api_key")
    user_id = data.get("user_id")
    access_token = data.get("access_token")
    if (
        not isinstance(returned_key, str)
        or not hmac.compare_digest(returned_key, api_key)
        or not isinstance(user_id, str)
        or not user_id.strip()
        or not isinstance(access_token, str)
        or not access_token.strip()
    ):
        return _response(
            start_response,
            "502 Bad Gateway",
            {"status": "error", "message": "Kite returned an incomplete authentication response."},
        )

    # The one-time request token, checksum, and API secret are never logged or echoed.
    return _response(
        start_response,
        "200 OK",
        {
            "status": "success",
            "data": {
                "api_key": api_key,
                "user_id": user_id.strip(),
                "user_name": str(data.get("user_name") or "").strip(),
                "access_token": access_token.strip(),
            },
        },
    )


def main():
    port = int(os.environ.get("PORT", "8080"))
    print("Development server only; deploy behind HTTPS for real Kite credentials.")
    with make_server("127.0.0.1", port, application) as server:
        print(f"Kite auth service listening on 127.0.0.1:{port}")
        server.serve_forever()


if __name__ == "__main__":
    main()

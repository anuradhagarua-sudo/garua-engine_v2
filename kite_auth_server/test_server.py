import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from kite_auth_server.server import application


class KiteAuthServerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {"KITE_API_KEY": "public-key", "KITE_API_SECRET": "server-secret"},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def call(self, payload, method="POST", path="/api/kite/session"):
        raw_body = json.dumps(payload).encode("utf-8")
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(raw_body)),
            "wsgi.input": io.BytesIO(raw_body),
        }
        output = b"".join(application(environ, start_response))
        return captured, json.loads(output.decode("utf-8"))

    def test_wrong_api_key_is_rejected_without_exchange(self):
        with patch("kite_auth_server.server.urlopen") as urlopen:
            response, payload = self.call(
                {"api_key": "other-key", "request_token": "single-use-token"}
            )
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(payload["status"], "error")
        urlopen.assert_not_called()

    def test_successful_exchange_uses_official_checksum_and_returns_profile(self):
        api_response = {
            "status": "success",
            "data": {
                "api_key": "public-key",
                "user_id": "AB1234",
                "user_name": "Test User",
                "access_token": "returned-access-token",
            },
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, _size):
                return json.dumps(api_response).encode("utf-8")

        with patch("kite_auth_server.server.urlopen", return_value=FakeResponse()) as urlopen:
            response, payload = self.call(
                {"api_key": "public-key", "request_token": "one-time-token"}
            )

        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(response["headers"]["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(payload["data"]["user_id"], "AB1234")
        self.assertEqual(payload["data"]["access_token"], "returned-access-token")
        self.assertNotIn("server-secret", json.dumps(payload))

        request = urlopen.call_args.args[0]
        form = parse_qs(request.data.decode("ascii"))
        expected = hashlib.sha256(
            b"public-keyone-time-tokenserver-secret"
        ).hexdigest()
        self.assertEqual(form["checksum"], [expected])
        self.assertEqual(form["api_key"], ["public-key"])
        self.assertEqual(form["request_token"], ["one-time-token"])
        self.assertEqual(request.full_url, "https://api.kite.trade/session/token")

    def test_health_does_not_expose_secret(self):
        response, payload = self.call({}, method="GET", path="/health")
        self.assertEqual(response["status"], "200 OK")
        self.assertTrue(payload["kite_connect_configured"])
        self.assertNotIn("server-secret", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()

# Garua Engine V2

Android trading dashboard with a legacy Kivy/Python implementation and an in-progress Flutter/Dart migration.

## Flutter migration

The Flutter project is in `flutter_app/`. It includes the dashboard, draft legs, risk/trigger controls, and two authentication options:

1. **Kite Connect (recommended):** signs in through Kite's official hosted login, then exchanges the one-time request token through the companion HTTPS service in `kite_auth_server/`.
2. **Legacy enctoken:** retained for compatibility only; it uses an unofficial Zerodha web-session endpoint.

Live market streaming, portfolio synchronization, and order execution are intentionally disabled. Successful authentication is not proof that the Flutter app is ready for live trading.

### Kite Connect setup

1. Create a Kite Connect app in the Zerodha developer console. Configure an HTTPS redirect URL that can be intercepted by the app's embedded web view.
2. Deploy `kite_auth_server/` on a private, trusted server behind HTTPS. Set `KITE_API_KEY` and `KITE_API_SECRET` as server environment variables. The API key must match the app's API key; **never put the API secret in Flutter, an APK, source control, chat, or client-side build flags**.
3. Install the server dependency from `kite_auth_server/requirements.txt` and run it with a WSGI server, for example:

   ```sh
   pip install -r kite_auth_server/requirements.txt
   gunicorn --bind 0.0.0.0:8080 kite_auth_server.server:application
   ```

   Run the backend unit tests with `python3 -m unittest kite_auth_server.test_server -v`. Terminate TLS at a trusted HTTPS reverse proxy/load balancer and expose `/api/kite/session`. The built-in `python -m kite_auth_server.server` server is for local development only. Do not expose it directly to the internet.
4. In the Flutter app, enter the generated API key, the exact registered redirect URL, and the HTTPS backend URL ending in `/api/kite/session`.
5. Enter your Kite user ID, password, PIN, and TOTP only on the official Kite login page inside the app. Garua Engine does not request or receive those credentials. The app intercepts the registered redirect, sends the short-lived request token to your backend, and saves the returned access token in Android secure storage. Kite access tokens normally expire by the next day's session boundary; authenticate again when required.

The backend computes the official SHA-256 checksum and calls Kite's `/session/token` endpoint. Its API secret stays server-side. The app's Logout action attempts official token revocation, then clears local broker tokens even if remote logout cannot be confirmed. The legacy enctoken option cannot revoke the broker's web session.

The **Flutter Android APK** workflow runs on Arena-branch pushes, pull requests to `main`/`master`, or manual dispatch. It formats, analyzes, tests, builds a release APK, and uploads `Garua-Engine-Flutter-APK`.

## Legacy Python build

`main.py` and `buildozer.spec` retain the original Kivy/Flask implementation. The **Build Android APK** workflow still builds that legacy app. Do not confuse its artifact with the Flutter APK.

## Credentials and trading safety

- Never commit or send broker credentials in chat. Enter broker passwords and TOTP only on Kite's official login page.
- The Flutter app stores verified tokens using Android secure storage. The legacy Python app keeps its enctoken session in process memory.
- The enctoken flow is unofficial and may change or reject non-browser clients. Prefer the official Kite Connect flow.
- Live trading can lose money. Verify authentication, market data, order status, portfolio reconciliation, and exit behavior in a non-live environment before enabling live orders. The Flutter port currently sends no orders.

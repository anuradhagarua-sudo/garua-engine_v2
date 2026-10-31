# Garua Engine V2

Android trading dashboard with a legacy Kivy/Python implementation and an in-progress Flutter/Dart migration.

## Flutter migration

The Flutter project is in `flutter_app/`. The initial Flutter build includes the dashboard, draft legs, risk/trigger controls, and a broker-session connectivity check. **It is not yet a complete trading replacement:** live market streaming, portfolio synchronization, and order execution are intentionally disabled. The enctoken endpoint is unofficial and must not be treated as production authentication.

The **Flutter Android APK** workflow runs on Arena-branch pushes, pull requests to `main`/`master`, or manual dispatch. It formats, analyzes, tests, builds a release APK, and uploads `Garua-Engine-Flutter-APK`.

## Legacy Python build

`main.py` and `buildozer.spec` retain the original Kivy/Flask implementation. The **Build Android APK** workflow still builds that legacy app. Do not confuse its artifact with the Flutter APK.

## Credentials and safety

- Never commit or send broker credentials in chat. Enter them only on the device.
- The Flutter migration stores a verified session in Android secure storage. The legacy Python app keeps the session in process memory.
- The existing enctoken-based implementation uses unofficial Zerodha web-session endpoints that can change or reject non-browser clients. For dependable trading integration, migrate to the official Kite Connect API.
- Live trading can lose money. Verify authentication, market data, order status, portfolio reconciliation, and exit behavior in a non-live environment before enabling live orders. The Flutter port currently sends no orders.

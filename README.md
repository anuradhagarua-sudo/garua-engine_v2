# Garua Engine V2

Android/Kivy trading dashboard and strategy runner.

## Build the Android APK

The repository's GitHub Actions workflow builds a debug APK on pull requests to `main`/`master`, matching pushes, or a manual workflow dispatch. The APK is uploaded as a workflow artifact. A local build requires Buildozer, the Android SDK/NDK, Java, and the dependencies listed in `buildozer.spec`.

## Credentials and safety

- Enter the broker user ID and session token only in the app on the device. Never commit credentials or send them in chat.
- Credentials are kept in process memory and are not written to the repository or a local credential file. The app verifies the session against the broker before enabling streaming.
- The dashboard binds to the device loopback interface and rejects remote and cross-origin requests.
- This version uses Zerodha web-session (`enctoken`) endpoints, which are not the supported Kite Connect API and can change without notice. Authentication, market data, order execution, and fills have not been validated against a live account in this environment.
- Trading can lose money. Verify data, order status, position reconciliation, and exit behavior in a non-live environment before considering any live use. The app is not a substitute for broker-side risk controls.

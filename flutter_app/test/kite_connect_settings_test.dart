import 'package:flutter_test/flutter_test.dart';
import 'package:garua_engine/services/broker_session_service.dart';

void main() {
  const settings = KiteConnectSettings(
    apiKey: 'kite-app-key',
    redirectUrl: 'https://login.example.com/kite/callback',
    backendUrl: 'https://api.example.com/api/kite/session',
  );

  test('builds the official Kite Connect login URL', () {
    expect(settings.loginUri.scheme, 'https');
    expect(settings.loginUri.host, 'kite.zerodha.com');
    expect(settings.loginUri.path, '/connect/login');
    expect(settings.loginUri.queryParameters, {
      'v': '3',
      'api_key': 'kite-app-key',
    });
  });

  test('accepts only the configured HTTPS callback origin and path', () {
    expect(
      settings.matchesRedirect(
        Uri.parse(
          'https://login.example.com/kite/callback?status=success&request_token=abc123',
        ),
      ),
      isTrue,
    );
    expect(
      settings.matchesRedirect(
        Uri.parse(
          'https://attacker.example/kite/callback?request_token=abc123',
        ),
      ),
      isFalse,
    );
    expect(
      settings.matchesRedirect(
        Uri.parse('https://login.example.com/other?request_token=abc123'),
      ),
      isFalse,
    );
  });

  test('rejects an insecure token exchange backend', () {
    const insecure = KiteConnectSettings(
      apiKey: 'kite-app-key',
      redirectUrl: 'https://login.example.com/kite/callback',
      backendUrl: 'http://api.example.com/api/kite/session',
    );
    expect(insecure.validationError, contains('HTTPS'));
  });
}

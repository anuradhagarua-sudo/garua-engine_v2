import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class BrokerSessionService {
  BrokerSessionService({http.Client? client, FlutterSecureStorage? storage})
    : _client = client ?? http.Client(),
      _storage = storage ?? const FlutterSecureStorage();

  static final Uri _profileUri = Uri.https(
    'kite.zerodha.com',
    '/oms/user/profile/full',
  );
  static final Uri _kiteTokenExchangeUri = Uri.https(
    'api.kite.trade',
    '/session/token',
  );

  final http.Client _client;
  final FlutterSecureStorage _storage;

  /// Completes the official Kite Connect request-token exchange through the
  /// user's HTTPS backend. The API secret is never sent to or stored by this app.
  Future<KiteBrokerProfile> connectWithKiteConnect({
    required KiteConnectSettings settings,
    required String requestToken,
  }) async {
    final validationError = settings.validationError;
    if (validationError != null) {
      throw BrokerSessionException(validationError);
    }
    final token = requestToken.trim();
    if (token.isEmpty || token.length > 2048) {
      throw const BrokerSessionException(
        'Kite returned an invalid request token. Start the login again.',
      );
    }

    final endpoint = Uri.parse(settings.backendUrl.trim());
    late final http.Response response;
    try {
      response = await _client
          .post(
            endpoint,
            headers: {HttpHeaders.contentTypeHeader: 'application/json'},
            body: jsonEncode({
              'api_key': settings.apiKey.trim(),
              'request_token': token,
            }),
          )
          .timeout(const Duration(seconds: 25));
    } on HandshakeException {
      throw const BrokerSessionException(
        'Secure connection to the Kite authentication service failed.',
      );
    } on SocketException {
      throw const BrokerSessionException(
        'Could not reach the Kite authentication service. Check its HTTPS URL and network.',
      );
    } on TimeoutException {
      throw const BrokerSessionException(
        'The Kite authentication service did not respond in time.',
      );
    } on http.ClientException {
      throw const BrokerSessionException(
        'Could not connect to the Kite authentication service.',
      );
    }

    final payload = _decodeResponse(response);
    if (response.statusCode != 200 || payload['status'] != 'success') {
      final message = payload['message'];
      throw BrokerSessionException(
        message is String && message.trim().isNotEmpty
            ? message.trim()
            : 'Kite Connect login failed. Check the server configuration and try again.',
      );
    }

    final rawData = payload['data'];
    if (rawData is! Map) {
      throw const BrokerSessionException(
        'The authentication service returned an invalid response.',
      );
    }
    final data = Map<String, dynamic>.from(rawData);
    final returnedApiKey = '${data['api_key'] ?? ''}'.trim();
    final userId = '${data['user_id'] ?? ''}'.trim();
    final accessToken = '${data['access_token'] ?? ''}'.trim();
    final userName = '${data['user_name'] ?? ''}'.trim();
    if (returnedApiKey != settings.apiKey.trim() ||
        userId.isEmpty ||
        accessToken.isEmpty) {
      throw const BrokerSessionException(
        'The authentication service did not confirm the Kite account. Check the API key and retry.',
      );
    }

    // Persist only after the official token exchange has succeeded. Never store
    // the API secret, Kite password, PIN, or TOTP in this app.
    await _storage.write(key: 'broker_user_id', value: userId);
    await _storage.write(key: 'broker_auth_type', value: 'kite_connect');
    await _storage.write(key: 'broker_api_key', value: settings.apiKey.trim());
    await _storage.write(key: 'broker_access_token', value: accessToken);
    await _storage.delete(key: 'broker_enctoken');
    await saveKiteSettings(settings);

    return KiteBrokerProfile(userId: userId, userName: userName);
  }

  /// Legacy compatibility only. Prefer the official Kite Connect flow above.
  Future<void> connectWithEnctoken({
    required String userId,
    required String enctoken,
  }) async {
    final id = userId.trim();
    final token = enctoken.trim();
    if (id.isEmpty || token.isEmpty) {
      throw const BrokerSessionException(
        'Enter both your broker user ID and session token.',
      );
    }

    late final http.Response response;
    try {
      response = await _client
          .get(
            _profileUri,
            headers: {
              HttpHeaders.authorizationHeader: 'enctoken $token',
              HttpHeaders.userAgentHeader:
                  'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36',
              HttpHeaders.acceptHeader: 'application/json, text/plain, */*',
              'Referer': 'https://kite.zerodha.com/',
              'X-Kite-Version': '3',
            },
          )
          .timeout(const Duration(seconds: 20));
    } on HandshakeException {
      throw const BrokerSessionException(
        'Secure connection to Zerodha failed. Check phone date/time and network.',
      );
    } on SocketException catch (error) {
      final detail = _safeTransportDetail(error.message);
      throw BrokerSessionException(
        'Network/DNS error reaching Zerodha: $detail',
      );
    } on TimeoutException {
      throw const BrokerSessionException(
        'Zerodha did not respond in time. Check internet access and retry.',
      );
    } on http.ClientException catch (error) {
      throw BrokerSessionException(
        'HTTP connection failed: ${_safeTransportDetail(error.message)}',
      );
    }

    final payload = _decodeResponse(response);
    if (response.statusCode != 200 || payload['status'] != 'success') {
      throw BrokerSessionException(
        'Zerodha rejected the session (HTTP ${response.statusCode}). Check that the token is current.',
      );
    }

    final data = payload['data'];
    final brokerUserId = data is Map ? '${data['user_id'] ?? ''}'.trim() : '';
    if (brokerUserId.isEmpty ||
        brokerUserId.toLowerCase() != id.toLowerCase()) {
      throw const BrokerSessionException(
        'The broker response did not confirm the entered user ID.',
      );
    }

    await _storage.write(key: 'broker_user_id', value: id);
    await _storage.write(key: 'broker_auth_type', value: 'legacy_enctoken');
    await _storage.write(key: 'broker_enctoken', value: token);
    await _storage.delete(key: 'broker_access_token');
    await _storage.delete(key: 'broker_api_key');
  }

  Future<KiteConnectSettings?> readKiteSettings() async {
    final apiKey = await _storage.read(key: 'kite_api_key');
    final redirectUrl = await _storage.read(key: 'kite_redirect_url');
    final backendUrl = await _storage.read(key: 'kite_auth_backend_url');
    if (apiKey == null || redirectUrl == null || backendUrl == null) {
      return null;
    }
    final settings = KiteConnectSettings(
      apiKey: apiKey,
      redirectUrl: redirectUrl,
      backendUrl: backendUrl,
    );
    return settings.validationError == null ? settings : null;
  }

  Future<void> saveKiteSettings(KiteConnectSettings settings) async {
    await _storage.write(key: 'kite_api_key', value: settings.apiKey.trim());
    await _storage.write(
      key: 'kite_redirect_url',
      value: settings.redirectUrl.trim(),
    );
    await _storage.write(
      key: 'kite_auth_backend_url',
      value: settings.backendUrl.trim(),
    );
  }

  Future<String?> readUserId() => _storage.read(key: 'broker_user_id');

  Future<bool> disconnect() async {
    var remoteLogoutConfirmed = true;
    final authType = await _storage.read(key: 'broker_auth_type');
    if (authType == 'kite_connect') {
      final apiKey = await _storage.read(key: 'broker_api_key');
      final accessToken = await _storage.read(key: 'broker_access_token');
      if (apiKey == null || accessToken == null) {
        remoteLogoutConfirmed = false;
      } else {
        try {
          final response = await _client
              .delete(
                _kiteTokenExchangeUri,
                headers: {
                  HttpHeaders.authorizationHeader:
                      'token ${apiKey.trim()}:$accessToken',
                  'X-Kite-Version': '3',
                },
              )
              .timeout(const Duration(seconds: 15));
          remoteLogoutConfirmed = response.statusCode == 200;
        } on Exception {
          remoteLogoutConfirmed = false;
        }
      }
    } else if (authType == 'legacy_enctoken') {
      remoteLogoutConfirmed = false;
    }

    await _storage.delete(key: 'broker_user_id');
    await _storage.delete(key: 'broker_auth_type');
    await _storage.delete(key: 'broker_api_key');
    await _storage.delete(key: 'broker_access_token');
    await _storage.delete(key: 'broker_enctoken');
    return remoteLogoutConfirmed;
  }

  Map<String, dynamic> _decodeResponse(http.Response response) {
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map<String, dynamic>) return decoded;
    } on FormatException {
      // Return a safe generic error below; never echo an untrusted response body.
    }
    throw BrokerSessionException(
      'Authentication returned an invalid response (HTTP ${response.statusCode}).',
    );
  }

  String _safeTransportDetail(String value) {
    final sanitized = value.replaceAll(RegExp(r'[\r\n\t]+'), ' ').trim();
    return sanitized.length > 150
        ? '${sanitized.substring(0, 150)}…'
        : sanitized;
  }
}

class KiteConnectSettings {
  const KiteConnectSettings({
    required this.apiKey,
    required this.redirectUrl,
    required this.backendUrl,
  });

  final String apiKey;
  final String redirectUrl;
  final String backendUrl;

  Uri get loginUri => Uri.https('kite.zerodha.com', '/connect/login', {
    'v': '3',
    'api_key': apiKey.trim(),
  });

  Uri get parsedRedirectUri => Uri.parse(redirectUrl.trim());

  String? get validationError {
    final key = apiKey.trim();
    if (key.isEmpty || key.length > 128 || key.contains(RegExp(r'\s'))) {
      return 'Enter the API key generated for your Kite Connect app.';
    }

    final redirect = Uri.tryParse(redirectUrl.trim());
    if (redirect == null ||
        redirect.scheme != 'https' ||
        redirect.host.isEmpty ||
        redirect.userInfo.isNotEmpty ||
        redirect.hasFragment) {
      return 'Enter the HTTPS redirect URL registered in your Kite Connect app.';
    }

    final backend = Uri.tryParse(backendUrl.trim());
    final isLocalDevelopment =
        backend != null &&
        (backend.host == 'localhost' ||
            backend.host == '127.0.0.1' ||
            backend.host == '::1');
    if (backend == null ||
        backend.host.isEmpty ||
        backend.userInfo.isNotEmpty ||
        (backend.scheme != 'https' &&
            !(isLocalDevelopment && backend.scheme == 'http'))) {
      return 'The token-exchange backend must use HTTPS (HTTP is allowed only for localhost development).';
    }
    return null;
  }

  bool matchesRedirect(Uri candidate) {
    final expected = parsedRedirectUri;
    return candidate.scheme.toLowerCase() == expected.scheme.toLowerCase() &&
        candidate.host.toLowerCase() == expected.host.toLowerCase() &&
        candidate.port == expected.port &&
        _normalizedPath(candidate.path) == _normalizedPath(expected.path);
  }

  static String _normalizedPath(String path) =>
      path.isEmpty ? '/' : path.replaceFirst(RegExp(r'/+$'), '');
}

class KiteBrokerProfile {
  const KiteBrokerProfile({required this.userId, required this.userName});

  final String userId;
  final String userName;
}

class BrokerSessionException implements Exception {
  const BrokerSessionException(this.message);
  final String message;

  @override
  String toString() => message;
}

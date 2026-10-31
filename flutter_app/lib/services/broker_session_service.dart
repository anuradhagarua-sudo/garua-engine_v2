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
  final http.Client _client;
  final FlutterSecureStorage _storage;

  Future<void> connect({
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

    Map<String, dynamic> payload;
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('Unexpected response format');
      }
      payload = decoded;
    } on FormatException {
      if (response.statusCode == 401 || response.statusCode == 403) {
        throw const BrokerSessionException(
          'Zerodha rejected this session token. Sign in again and use a fresh token.',
        );
      }
      throw BrokerSessionException(
        'Zerodha returned an unexpected response (HTTP ${response.statusCode}).',
      );
    }

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

    // Store only after the broker verifies the session. No credential values are logged.
    await _storage.write(key: 'broker_user_id', value: id);
    await _storage.write(key: 'broker_enctoken', value: token);
  }

  Future<String?> readUserId() => _storage.read(key: 'broker_user_id');

  Future<void> disconnect() async {
    await _storage.delete(key: 'broker_user_id');
    await _storage.delete(key: 'broker_enctoken');
  }

  String _safeTransportDetail(String value) {
    final sanitized = value.replaceAll(RegExp(r'[\r\n\t]+'), ' ').trim();
    return sanitized.length > 150
        ? '${sanitized.substring(0, 150)}…'
        : sanitized;
  }
}

class BrokerSessionException implements Exception {
  const BrokerSessionException(this.message);
  final String message;

  @override
  String toString() => message;
}

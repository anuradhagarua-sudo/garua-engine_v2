import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import '../services/broker_session_service.dart';

class KiteLoginPage extends StatefulWidget {
  const KiteLoginPage({required this.settings, super.key});

  final KiteConnectSettings settings;

  @override
  State<KiteLoginPage> createState() => _KiteLoginPageState();
}

class _KiteLoginPageState extends State<KiteLoginPage> {
  late final WebViewController _controller;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onNavigationRequest: _handleNavigation,
          onPageStarted: (_) {
            if (mounted) setState(() => _loading = true);
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _loading = false);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame == true && mounted) {
              setState(() {
                _loading = false;
                _error =
                    'Kite login page failed to load. Check your connection.';
              });
            }
          },
        ),
      );
    _prepareWebView();
  }

  Future<void> _prepareWebView() async {
    try {
      final platformController = _controller.platform;
      final cookieManager = WebViewCookieManager().platform;
      if (platformController is AndroidWebViewController &&
          cookieManager is AndroidWebViewCookieManager) {
        await cookieManager.setAcceptThirdPartyCookies(
          platformController,
          true,
        );
      }
      await _controller.loadRequest(widget.settings.loginUri);
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Could not open the official Kite login page.';
        });
      }
    }
  }

  NavigationDecision _handleNavigation(NavigationRequest request) {
    final uri = Uri.tryParse(request.url);
    if (uri == null) return NavigationDecision.prevent;

    if (widget.settings.matchesRedirect(uri)) {
      final status = uri.queryParameters['status'];
      final requestToken = uri.queryParameters['request_token'];
      if (status == 'success' &&
          requestToken != null &&
          requestToken.isNotEmpty) {
        Navigator.of(context).pop(requestToken);
      } else if (mounted) {
        setState(() {
          _error = 'Kite did not complete login. Check your account and retry.';
          _loading = false;
        });
      }
      // Do not load the registered redirect URL with the one-time token attached.
      return NavigationDecision.prevent;
    }

    if (uri.scheme != 'https') {
      return NavigationDecision.prevent;
    }
    return NavigationDecision.navigate;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Sign in with Kite'),
      leading: IconButton(
        tooltip: 'Close login',
        onPressed: () => Navigator.of(context).pop(),
        icon: const Icon(Icons.close),
      ),
    ),
    body: Column(
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 12, 16, 8),
          child: Text(
            'Sign in only on the official Kite page below. Your Kite password, PIN, and TOTP are not collected by Garua Engine.',
          ),
        ),
        if (_loading) const LinearProgressIndicator(minHeight: 2),
        if (_error != null)
          MaterialBanner(
            content: Text(_error!),
            leading: const Icon(Icons.error_outline),
            actions: [
              TextButton(
                onPressed: () {
                  setState(() {
                    _error = null;
                    _loading = true;
                  });
                  _controller.loadRequest(widget.settings.loginUri);
                },
                child: const Text('Retry'),
              ),
            ],
          ),
        Expanded(child: WebViewWidget(controller: _controller)),
      ],
    ),
  );
}

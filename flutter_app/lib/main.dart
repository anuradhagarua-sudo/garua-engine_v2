import 'package:flutter/material.dart';

import 'services/broker_session_service.dart';

void main() => runApp(const GaruaEngineApp());

const _accent = Color(0xFF66FCF1);
const _background = Color(0xFF0B0C10);
const _surface = Color(0xFF1F2833);

class GaruaEngineApp extends StatelessWidget {
  const GaruaEngineApp({super.key});

  @override
  Widget build(BuildContext context) {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: _accent,
      brightness: Brightness.dark,
      surface: _surface,
    );
    return MaterialApp(
      title: 'Garua Engine',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: colorScheme,
        scaffoldBackgroundColor: _background,
        appBarTheme: const AppBarTheme(
          backgroundColor: _surface,
          foregroundColor: _accent,
          centerTitle: false,
        ),
        cardTheme: CardThemeData(
          color: _surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: BorderSide(color: colorScheme.outline),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: _background,
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
        ),
      ),
      home: const EngineHomePage(),
    );
  }
}

class EngineHomePage extends StatefulWidget {
  const EngineHomePage({super.key});

  @override
  State<EngineHomePage> createState() => _EngineHomePageState();
}

class _EngineHomePageState extends State<EngineHomePage> {
  final BrokerSessionService _broker = BrokerSessionService();
  final TextEditingController _symbolController = TextEditingController();
  final TextEditingController _quantityController = TextEditingController(
    text: '75',
  );
  final List<StrategyLeg> _legs = [];
  final List<String> _events = [
    'Flutter interface started. Live trading is disabled.',
  ];
  int _tab = 0;
  bool _connected = false;
  bool _autoSquareoff = true;
  bool _trailingStop = false;
  bool _usePremium = false;
  bool _useTime = false;
  bool _useVwap = false;
  double _target = 2000;
  double _stoploss = -1000;
  double _trailingGap = 300;
  double _premiumTarget = 150;
  String _timeTarget = '09:20';
  String _combineMode = 'AND';
  String _draftSide = 'SELL';
  bool _showMigrationBanner = true;

  @override
  void initState() {
    super.initState();
    _loadSavedSessionHint();
  }

  Future<void> _loadSavedSessionHint() async {
    try {
      final userId = await _broker.readUserId();
      if (mounted && userId != null) {
        _appendEvent('A saved broker ID is available; reconnect manually.');
      }
    } catch (_) {
      // The dashboard remains usable if secure storage is unavailable in a test/device.
    }
  }

  @override
  void dispose() {
    _symbolController.dispose();
    _quantityController.dispose();
    super.dispose();
  }

  void _appendEvent(String value) {
    if (!mounted) return;
    setState(() {
      _events.insert(0, '${TimeOfDay.now().format(context)}  $value');
      if (_events.length > 30) _events.removeLast();
    });
  }

  Future<void> _showLogin() async {
    final userIdController = TextEditingController();
    final tokenController = TextEditingController();
    final formKey = GlobalKey<FormState>();
    var busy = false;
    String? error;

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) {
        final navigator = Navigator.of(dialogContext);
        return StatefulBuilder(
          builder: (context, setDialogState) => AlertDialog(
            title: const Text('Zerodha session'),
            content: SizedBox(
              width: 460,
              child: Form(
                key: formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text(
                      'Enter credentials on this device only. The session token is stored in Android secure storage only after verification.',
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: userIdController,
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(labelText: 'User ID'),
                      validator: (value) =>
                          value == null || value.trim().isEmpty
                          ? 'User ID is required'
                          : null,
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: tokenController,
                      obscureText: true,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: const InputDecoration(labelText: 'ENCTOKEN'),
                      validator: (value) =>
                          value == null || value.trim().isEmpty
                          ? 'Session token is required'
                          : null,
                    ),
                    if (error != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: busy ? null : () => navigator.pop(),
                child: const Text('Cancel'),
              ),
              FilledButton.icon(
                onPressed: busy
                    ? null
                    : () async {
                        if (!formKey.currentState!.validate()) return;
                        setDialogState(() {
                          busy = true;
                          error = null;
                        });
                        try {
                          await _broker.connect(
                            userId: userIdController.text,
                            enctoken: tokenController.text,
                          );
                          if (!mounted) return;
                          setState(() => _connected = true);
                          _appendEvent('Broker session verified.');
                          navigator.pop();
                        } on BrokerSessionException catch (exception) {
                          setDialogState(() {
                            busy = false;
                            error = exception.message;
                          });
                          _appendEvent(
                            'Broker sign-in failed: ${exception.message}',
                          );
                        } catch (_) {
                          setDialogState(() {
                            busy = false;
                            error =
                                'Unexpected sign-in error. Check the network and try again.';
                          });
                          _appendEvent(
                            'Broker sign-in failed with an unexpected error.',
                          );
                        } finally {
                          tokenController.clear();
                        }
                      },
                icon: busy
                    ? const SizedBox.square(
                        dimension: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.lock_open),
                label: Text(busy ? 'Checking…' : 'Connect'),
              ),
            ],
          ),
        );
      },
    );
    userIdController.dispose();
    tokenController.dispose();
  }

  Future<void> _disconnect() async {
    await _broker.disconnect();
    if (!mounted) return;
    setState(() => _connected = false);
    _appendEvent('Broker session cleared from secure storage.');
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      _dashboardPage(),
      _builderPage(),
      _riskPage(),
      _activityPage(),
    ];
    return Scaffold(
      appBar: AppBar(
        title: const Text('Garua Engine'),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: Chip(
              avatar: Icon(
                _connected ? Icons.check_circle : Icons.cloud_off,
                size: 16,
                color: _connected ? Colors.greenAccent : Colors.redAccent,
              ),
              label: Text(_connected ? 'SESSION OK' : 'DISCONNECTED'),
            ),
          ),
          IconButton(
            tooltip: _connected ? 'Disconnect' : 'Connect broker',
            onPressed: _connected ? _disconnect : _showLogin,
            icon: Icon(_connected ? Icons.logout : Icons.login),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          if (_showMigrationBanner)
            MaterialBanner(
              leading: const Icon(Icons.info_outline),
              content: const Text(
                'Flutter migration in progress: live market streaming and order execution are not enabled. No orders will be sent.',
              ),
              actions: [
                TextButton(
                  onPressed: () => setState(() => _showMigrationBanner = false),
                  child: const Text('Dismiss'),
                ),
              ],
            ),
          Expanded(child: pages[_tab]),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (index) => setState(() => _tab = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.dashboard_outlined),
            label: 'Dashboard',
          ),
          NavigationDestination(icon: Icon(Icons.tune), label: 'Leg Builder'),
          NavigationDestination(
            icon: Icon(Icons.shield_outlined),
            label: 'Risk & Gates',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long),
            label: 'Activity',
          ),
        ],
      ),
    );
  }

  Widget _dashboardPage() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Wrap(
        spacing: 12,
        runSpacing: 12,
        children: const [
          _MetricCard(title: 'NET P&L', value: '—', icon: Icons.currency_rupee),
          _MetricCard(
            title: 'COMBO PREMIUM',
            value: '—',
            icon: Icons.show_chart,
          ),
          _MetricCard(title: 'MASTER LTP', value: '—', icon: Icons.insights),
          _MetricCard(title: 'COMBO IV', value: '—', icon: Icons.percent),
        ],
      ),
      const SizedBox(height: 16),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Active Positions',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 12),
              const Text(
                'No positions loaded. Live portfolio sync is not enabled in the Flutter port.',
              ),
            ],
          ),
        ),
      ),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Strategy Legs',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              if (_legs.isEmpty)
                const Text('No strategy legs added.')
              else
                ..._legs.map(
                  (leg) => ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(leg.symbol),
                    subtitle: Text('${leg.side} · ${leg.quantity}'),
                    trailing: Icon(
                      leg.enabled ? Icons.circle : Icons.circle_outlined,
                      color: leg.enabled ? Colors.greenAccent : Colors.grey,
                      size: 14,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
      Card(
        color: _surface,
        child: ListTile(
          leading: const Icon(Icons.warning_amber, color: Colors.amber),
          title: const Text('Live execution is intentionally locked'),
          subtitle: const Text(
            'The current enctoken endpoint is unofficial and has not been validated from this Flutter client.',
          ),
        ),
      ),
    ],
  );

  Widget _builderPage() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Add Strategy Leg',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _symbolController,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(labelText: 'Trading symbol'),
              ),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(
                initialValue: _draftSide,
                decoration: const InputDecoration(labelText: 'Side'),
                items: const [
                  DropdownMenuItem(value: 'SELL', child: Text('SELL')),
                  DropdownMenuItem(value: 'BUY', child: Text('BUY')),
                ],
                onChanged: (value) =>
                    setState(() => _draftSide = value ?? 'SELL'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _quantityController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Quantity'),
              ),
              const SizedBox(height: 12),
              FilledButton.icon(
                onPressed: () {
                  final symbol = _symbolController.text.trim().toUpperCase();
                  final quantity = int.tryParse(
                    _quantityController.text.trim(),
                  );
                  if (symbol.isEmpty || quantity == null || quantity <= 0) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Enter a symbol and positive quantity.'),
                      ),
                    );
                    return;
                  }
                  setState(
                    () => _legs.add(
                      StrategyLeg(
                        symbol: symbol,
                        side: _draftSide,
                        quantity: quantity,
                      ),
                    ),
                  );
                  _symbolController.clear();
                  _appendEvent('Draft leg added: $symbol. No order was sent.');
                },
                icon: const Icon(Icons.add),
                label: const Text('Add Draft Leg'),
              ),
            ],
          ),
        ),
      ),
      const SizedBox(height: 8),
      ..._legs.asMap().entries.map((entry) {
        final index = entry.key;
        final leg = entry.value;
        return Card(
          child: ListTile(
            title: Text(leg.symbol),
            subtitle: Text('${leg.side} · ${leg.quantity}'),
            trailing: IconButton(
              tooltip: 'Remove draft leg',
              onPressed: () => setState(() => _legs.removeAt(index)),
              icon: const Icon(Icons.delete_outline),
            ),
          ),
        );
      }),
    ],
  );

  Widget _riskPage() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Portfolio risk draft',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              _numberRow(
                'Target profit (₹)',
                _target,
                (value) => setState(() => _target = value),
              ),
              _numberRow(
                'Stop loss (₹)',
                _stoploss,
                (value) => setState(() => _stoploss = value),
              ),
              SwitchListTile(
                title: const Text('Trailing stop'),
                value: _trailingStop,
                onChanged: (value) => setState(() => _trailingStop = value),
              ),
              if (_trailingStop)
                _numberRow(
                  'Trailing gap (₹)',
                  _trailingGap,
                  (value) => setState(() => _trailingGap = value),
                ),
              SwitchListTile(
                title: const Text('Auto square-off'),
                value: _autoSquareoff,
                onChanged: (value) => setState(() => _autoSquareoff = value),
              ),
            ],
          ),
        ),
      ),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Trigger conditions (draft only)',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              DropdownButtonFormField<String>(
                initialValue: _combineMode,
                decoration: const InputDecoration(
                  labelText: 'Combine enabled conditions',
                ),
                items: const [
                  DropdownMenuItem(
                    value: 'AND',
                    child: Text('All enabled gates (AND)'),
                  ),
                  DropdownMenuItem(
                    value: 'OR',
                    child: Text('Any enabled gate (OR)'),
                  ),
                ],
                onChanged: (value) =>
                    setState(() => _combineMode = value ?? 'AND'),
              ),
              SwitchListTile(
                title: const Text('Combo premium threshold'),
                value: _usePremium,
                onChanged: (value) => setState(() => _usePremium = value),
              ),
              if (_usePremium)
                _numberRow(
                  'Premium target',
                  _premiumTarget,
                  (value) => setState(() => _premiumTarget = value),
                ),
              SwitchListTile(
                title: const Text('Time gate'),
                value: _useTime,
                onChanged: (value) => setState(() => _useTime = value),
              ),
              if (_useTime)
                ListTile(
                  title: Text('Target time: $_timeTarget'),
                  trailing: const Icon(Icons.schedule),
                  onTap: () async {
                    final picked = await showTimePicker(
                      context: context,
                      initialTime: const TimeOfDay(hour: 9, minute: 20),
                    );
                    if (picked != null)
                      setState(
                        () => _timeTarget =
                            '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}',
                      );
                  },
                ),
              SwitchListTile(
                title: const Text('Premium vs VWAP gate'),
                value: _useVwap,
                onChanged: (value) => setState(() => _useVwap = value),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: null,
                icon: const Icon(Icons.lock_outline),
                label: const Text(
                  'Live arming unavailable in Flutter migration',
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Mode: $_combineMode · P&L controls are not connected to live positions.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    ],
  );

  Widget _numberRow(
    String label,
    double value,
    ValueChanged<double> onChanged,
  ) {
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: TextFormField(
        initialValue: value.toStringAsFixed(value % 1 == 0 ? 0 : 2),
        keyboardType: const TextInputType.numberWithOptions(
          decimal: true,
          signed: true,
        ),
        decoration: InputDecoration(labelText: label),
        onFieldSubmitted: (text) {
          final parsed = double.tryParse(text);
          if (parsed != null && parsed.isFinite) onChanged(parsed);
        },
      ),
    );
  }

  Widget _activityPage() => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      Text('Local activity', style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 8),
      ..._events.map(
        (event) => Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Text(event, style: const TextStyle(fontFamily: 'monospace')),
          ),
        ),
      ),
    ],
  );
}

class StrategyLeg {
  StrategyLeg({
    required this.symbol,
    required this.side,
    required this.quantity,
    this.enabled = true,
  });
  final String symbol;
  final String side;
  final int quantity;
  final bool enabled;
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({
    required this.title,
    required this.value,
    required this.icon,
  });
  final String title;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 165,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: _accent),
            const SizedBox(height: 8),
            Text(title, style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 4),
            Text(
              value,
              style: Theme.of(
                context,
              ).textTheme.headlineSmall?.copyWith(color: _accent),
            ),
          ],
        ),
      ),
    ),
  );
}

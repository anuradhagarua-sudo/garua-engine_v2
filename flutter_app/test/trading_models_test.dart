import 'package:flutter_test/flutter_test.dart';
import 'package:garua_engine/models/trading_models.dart';

void main() {
  group('Position P&L', () {
    test('calculates long and short unrealized P&L', () {
      const long = Position(
        symbol: 'NIFTYCE',
        side: PositionSide.long,
        quantity: 50,
        entryPrice: 100,
      );
      const short = Position(
        symbol: 'NIFTYCE',
        side: PositionSide.short,
        quantity: 50,
        entryPrice: 100,
      );
      expect(long.unrealizedPnl(110), 500);
      expect(short.unrealizedPnl(110), -500);
    });
  });

  group('StrategyConfig', () {
    test('AND fails closed when a selected input is missing', () {
      const config = StrategyConfig(
        premiumEnabled: true,
        premiumThreshold: 100,
        underlyingEnabled: true,
        underlyingThreshold: 20000,
      );
      expect(
        config.matches(const StrategySnapshot(comboPremium: 120)),
        isFalse,
      );
    });

    test('OR matches when one active gate is true', () {
      const config = StrategyConfig(
        mode: GateMode.any,
        premiumEnabled: true,
        premiumThreshold: 100,
        ivEnabled: true,
        ivThreshold: 20,
      );
      expect(
        config.matches(const StrategySnapshot(comboPremium: 120, comboIv: 10)),
        isTrue,
      );
    });

    test('no enabled gates never triggers', () {
      expect(
        const StrategyConfig().matches(
          const StrategySnapshot(comboPremium: 500),
        ),
        isFalse,
      );
    });
  });

  group('RiskSettings', () {
    test('trailing stop only moves upward', () {
      const settings = RiskSettings(trailingEnabled: true, trailingGap: 100);
      final first = settings.nextTrailingStop(previousStop: null, pnl: 300);
      final next = settings.nextTrailingStop(previousStop: first, pnl: 250);
      expect(first, 200);
      expect(next, 200);
    });

    test('auto square-off respects disabled flag and panic override', () {
      const settings = RiskSettings(autoSquareoff: false);
      expect(settings.shouldSquareoff(pnl: 5000), isFalse);
      expect(settings.shouldSquareoff(pnl: 0, panic: true), isTrue);
    });
  });
}

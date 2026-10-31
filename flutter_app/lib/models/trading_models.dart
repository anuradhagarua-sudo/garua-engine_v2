enum PositionSide { long, short }

enum Comparison { greater, greaterOrEqual, less, lessOrEqual }

enum GateMode { all, any }

class Position {
  const Position({
    required this.symbol,
    required this.side,
    required this.quantity,
    required this.entryPrice,
    this.multiplier = 1,
  });

  final String symbol;
  final PositionSide side;
  final int quantity;
  final double entryPrice;
  final double multiplier;

  double unrealizedPnl(double marketPrice) {
    final direction = side == PositionSide.long ? 1.0 : -1.0;
    return (marketPrice - entryPrice) * quantity * multiplier * direction;
  }
}

class StrategySnapshot {
  const StrategySnapshot({
    this.comboPremium,
    this.comboVwap,
    this.premiumDifference,
    this.underlyingPrice,
    this.underlyingVwap,
    this.comboIv,
    this.localTime,
  });

  final double? comboPremium;
  final double? comboVwap;
  final double? premiumDifference;
  final double? underlyingPrice;
  final double? underlyingVwap;
  final double? comboIv;
  final DateTime? localTime;
}

class StrategyConfig {
  const StrategyConfig({
    this.mode = GateMode.all,
    this.premiumEnabled = false,
    this.premiumComparison = Comparison.greaterOrEqual,
    this.premiumThreshold = 150,
    this.premiumDifferenceEnabled = false,
    this.premiumDifferenceMaximum = 5,
    this.premiumVwapEnabled = false,
    this.premiumAboveVwap = false,
    this.timeEnabled = false,
    this.timeTargetMinutes = 9 * 60 + 20,
    this.underlyingEnabled = false,
    this.underlyingComparison = Comparison.greaterOrEqual,
    this.underlyingThreshold = 22000,
    this.underlyingVwapEnabled = false,
    this.underlyingAboveVwap = true,
    this.ivEnabled = false,
    this.ivComparison = Comparison.greaterOrEqual,
    this.ivThreshold = 15,
  });

  final GateMode mode;
  final bool premiumEnabled;
  final Comparison premiumComparison;
  final double premiumThreshold;
  final bool premiumDifferenceEnabled;
  final double premiumDifferenceMaximum;
  final bool premiumVwapEnabled;
  final bool premiumAboveVwap;
  final bool timeEnabled;
  final int timeTargetMinutes;
  final bool underlyingEnabled;
  final Comparison underlyingComparison;
  final double underlyingThreshold;
  final bool underlyingVwapEnabled;
  final bool underlyingAboveVwap;
  final bool ivEnabled;
  final Comparison ivComparison;
  final double ivThreshold;

  bool matches(StrategySnapshot snapshot) {
    final evaluations = <bool>[];
    if (premiumEnabled) {
      evaluations.add(
        _compare(snapshot.comboPremium, premiumThreshold, premiumComparison),
      );
    }
    if (premiumDifferenceEnabled) {
      final difference = snapshot.premiumDifference;
      evaluations.add(
        difference != null && difference <= premiumDifferenceMaximum,
      );
    }
    if (premiumVwapEnabled) {
      final premium = snapshot.comboPremium;
      final vwap = snapshot.comboVwap;
      evaluations.add(
        premium != null &&
            vwap != null &&
            (premiumAboveVwap ? premium > vwap : premium < vwap),
      );
    }
    if (timeEnabled) {
      final time = snapshot.localTime;
      final currentMinutes = time == null ? null : time.hour * 60 + time.minute;
      evaluations.add(
        currentMinutes != null && currentMinutes >= timeTargetMinutes,
      );
    }
    if (underlyingEnabled) {
      evaluations.add(
        _compare(
          snapshot.underlyingPrice,
          underlyingThreshold,
          underlyingComparison,
        ),
      );
    }
    if (underlyingVwapEnabled) {
      final price = snapshot.underlyingPrice;
      final vwap = snapshot.underlyingVwap;
      evaluations.add(
        price != null &&
            vwap != null &&
            (underlyingAboveVwap ? price > vwap : price < vwap),
      );
    }
    if (ivEnabled) {
      evaluations.add(_compare(snapshot.comboIv, ivThreshold, ivComparison));
    }

    if (evaluations.isEmpty) return false;
    return mode == GateMode.all
        ? evaluations.every((value) => value)
        : evaluations.any((value) => value);
  }

  static bool _compare(double? actual, double target, Comparison comparison) {
    if (actual == null) return false;
    return switch (comparison) {
      Comparison.greater => actual > target,
      Comparison.greaterOrEqual => actual >= target,
      Comparison.less => actual < target,
      Comparison.lessOrEqual => actual <= target,
    };
  }
}

class RiskSettings {
  const RiskSettings({
    this.targetProfit = 2000,
    this.maximumLoss = -1000,
    this.autoSquareoff = true,
    this.trailingEnabled = false,
    this.trailingGap = 300,
  });

  final double targetProfit;
  final double maximumLoss;
  final bool autoSquareoff;
  final bool trailingEnabled;
  final double trailingGap;

  double nextTrailingStop({
    required double? previousStop,
    required double pnl,
  }) {
    if (!trailingEnabled) return maximumLoss;
    final candidate = pnl > 0 ? pnl - trailingGap : maximumLoss;
    final floor = previousStop ?? maximumLoss;
    return candidate > floor ? candidate : floor;
  }

  bool shouldSquareoff({
    required double pnl,
    double? trailingStop,
    bool panic = false,
  }) {
    if (panic) return true;
    if (!autoSquareoff) return false;
    final activeStop = trailingEnabled
        ? (trailingStop ?? maximumLoss)
        : maximumLoss;
    return pnl >= targetProfit || pnl <= activeStop;
  }
}

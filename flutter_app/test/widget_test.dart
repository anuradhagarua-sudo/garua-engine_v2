import 'package:flutter_test/flutter_test.dart';
import 'package:garua_engine/main.dart';

void main() {
  testWidgets('renders the Flutter migration dashboard safely', (tester) async {
    await tester.pumpWidget(const GaruaEngineApp());
    await tester.pump();

    expect(find.text('Garua Engine'), findsOneWidget);
    expect(find.textContaining('live market streaming and order execution are not enabled'), findsOneWidget);
    expect(find.text('DISCONNECTED'), findsOneWidget);
  });
}

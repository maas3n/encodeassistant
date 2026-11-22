import 'package:encode_assistant/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('starts with the worker connection form', (tester) async {
    await tester.pumpWidget(const EncodeAssistant());
    expect(find.text('Encode Assistant'), findsOneWidget);
    expect(find.text('Worker URL'), findsOneWidget);
    expect(find.text('Connect'), findsOneWidget);
    expect(find.text('New encode'), findsNothing);
  });
}

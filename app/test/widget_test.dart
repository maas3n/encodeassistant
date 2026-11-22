import 'package:encode_assistant/main.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

class _TestWorker extends WorkerClient {
  _TestWorker(super.address, super.token);

  @override
  Future<Map<String, dynamic>> request(String path, {
    String method = 'GET', Map<String, dynamic>? body,
  }) async => switch (path) {
    '/health' => {'api_configured': true},
    '/sources' => {'sources': ['test.mkv']},
    '/jobs' => {
      'jobs': <Map<String, dynamic>>[
        {
          'id': 'abc123',
          'source': 'test.mkv',
          'status': 'completed',
          'progress': 1,
          'message': 'Encoding recommendation ready',
          'report': <String, dynamic>{
            'crf': 17.0,
            'sample_kbps': 19255,
            'crf_reviews': <String, dynamic>{
              '17.0': <String, dynamic>{
                'summary': 'Fine grain and shadow detail matched the source.',
                'findings': <Map<String, dynamic>>[],
              },
            },
          },
        },
      ],
    },
    _ => throw StateError('Unexpected worker request'),
  };
}

void main() {
  testWidgets('starts with the worker connection form', (tester) async {
    await tester.pumpWidget(const EncodeAssistant());
    expect(find.text('Encode Assistant'), findsOneWidget);
    expect(find.text('Worker URL'), findsOneWidget);
    expect(find.text('Connect'), findsOneWidget);
    expect(find.text('New encode'), findsNothing);
  });

  testWidgets('shows the visual report and rearranges it when resized', (tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(1280, 900);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(EncodeAssistant(createWorker: _TestWorker.new));
    await tester.tap(find.text('Connect'));
    await tester.pumpAndSettle();

    final controls = find.text('Encoding worker');
    final result = find.text('Job result');
    expect(find.text('Fine grain and shadow detail matched the source.'), findsOneWidget);
    expect(tester.getTopLeft(result).dx, greaterThan(tester.getTopLeft(controls).dx));

    tester.view.physicalSize = const Size(390, 844);
    await tester.pumpAndSettle();
    expect(tester.getTopLeft(result).dx, closeTo(tester.getTopLeft(controls).dx, 1));
    expect(tester.getTopLeft(result).dy, greaterThan(tester.getTopLeft(controls).dy));
    expect(tester.takeException(), isNull);
  });
}

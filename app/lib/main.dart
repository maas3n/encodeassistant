import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';

void main() => runApp(const EncodeAssistant());

class EncodeAssistant extends StatelessWidget {
  const EncodeAssistant({super.key, this.createWorker = WorkerClient.new});

  final WorkerClient Function(String, String) createWorker;

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Encode Assistant',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        brightness: Brightness.dark,
        seedColor: const Color(0xffa9e2b6),
      ),
      scaffoldBackgroundColor: const Color(0xff101513),
      inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
    ),
    home: EncodePage(createWorker: createWorker),
  );
}

class WorkerClient {
  WorkerClient(String address, this.token) : base = Uri.parse(address.trim());

  final Uri base;
  final String token;
  final _http = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  Map<String, String> get headers => token.isEmpty ? {} : {'Authorization': 'Bearer $token'};

  Uri uri(String path) {
    if (!base.hasAuthority || !['http', 'https'].contains(base.scheme)) {
      throw const FormatException('Enter a worker URL starting with http:// or https://.');
    }
    final prefix = base.path.replaceFirst(RegExp(r'/$'), '');
    return base.replace(path: '$prefix$path', query: '', fragment: '');
  }

  Future<Map<String, dynamic>> request(String path, {
    String method = 'GET', Map<String, dynamic>? body,
  }) async {
    final request = await _http.openUrl(method, uri(path));
    headers.forEach((key, value) => request.headers.set(key, value));
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.write(jsonEncode(body));
    }
    final response = await request.close().timeout(const Duration(seconds: 30));
    final text = await response.transform(utf8.decoder).join();
    final payload = jsonDecode(text) as Map<String, dynamic>;
    if (response.statusCode >= 400) {
      final detail = payload['detail'];
      if (detail is List) {
        throw FormatException(detail.map((item) => (item as Map)['msg']).join('. '));
      }
      throw HttpException(detail?.toString() ?? 'HTTP ${response.statusCode}');
    }
    return payload;
  }

  void close() => _http.close(force: true);
}

class EncodePage extends StatefulWidget {
  const EncodePage({super.key, required this.createWorker});

  final WorkerClient Function(String, String) createWorker;

  @override
  State<EncodePage> createState() => _EncodePageState();
}

class _EncodePageState extends State<EncodePage> {
  final _address = TextEditingController(text: 'http://127.0.0.1:8765');
  final _token = TextEditingController();
  final _target = TextEditingController();
  final _tuning = TextEditingController();
  final _crop = TextEditingController();
  WorkerClient? _worker;
  Timer? _timer;
  String? _source;
  String? _error;
  String _scan = 'auto';
  bool _busy = false;
  bool _polling = false;
  bool _full = false;
  List<String> _sources = [];
  List<Map<String, dynamic>> _jobs = [];
  Map<String, dynamic>? _job;

  bool get _active => const ['queued', 'running', 'cancelling'].contains(_job?['status']);

  @override
  void dispose() {
    _timer?.cancel();
    _worker?.close();
    for (final c in [_address, _token, _target, _tuning, _crop]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _action(Future<void> Function() work) async {
    setState(() { _busy = true; _error = null; });
    try {
      await work();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _connect() => _action(() async {
    final client = widget.createWorker(_address.text, _token.text.trim());
    try {
      final health = await client.request('/health');
      final sources = await client.request('/sources');
      final jobs = await client.request('/jobs');
      if (!mounted) { client.close(); return; }
      _timer?.cancel();
      _worker?.close();
      setState(() {
        _worker = client;
        _sources = List<String>.from(sources['sources'] as List);
        _jobs = List<Map<String, dynamic>>.from(jobs['jobs'] as List);
        _source = null;
        _job = _jobs.isEmpty ? null : _jobs.first;
        if (health['api_configured'] != true) {
          _error = 'Set OPENAI_API_KEY on the worker before starting a job.';
        }
      });
      _watch();
    } catch (_) {
      client.close();
      rethrow;
    }
  });

  Future<void> _start() => _action(() async {
    final target = int.tryParse(_target.text.trim());
    final tuning = int.tryParse(_tuning.text.trim());
    if (target == null || tuning == null || tuning <= 0 || tuning >= target) {
      throw const FormatException('Enter a positive tuning bitrate below the expected final bitrate.');
    }
    List<int>? crop;
    final text = _crop.text.trim();
    if (text.isNotEmpty) {
      final values = text.split(',').map((v) => int.tryParse(v.trim())).toList();
      if (values.length != 4 || values.any((n) => n == null || n < 0 || n.isOdd)) {
        throw const FormatException('Use four nonnegative even numbers for left, top, right, bottom.');
      }
      crop = values.cast<int>();
    }
    final job = await _worker!.request('/jobs', method: 'POST', body: {
      'source': _source, 'tuning_kbps': tuning, 'expected_kbps': target,
      'crop': crop, 'scan': _scan, 'full_encode': _full,
    });
    if (!mounted) return;
    setState(() { _job = job; _jobs = [job, ..._jobs]; });
    _watch();
  });

  void _watch() {
    _timer?.cancel();
    if (_active) {
      _timer = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
    }
  }

  Future<void> _refresh() async {
    final id = _job?['id'];
    final worker = _worker;
    if (_polling || id == null || worker == null) return;
    _polling = true;
    try {
      final state = await worker.request('/jobs/$id');
      if (!mounted || _job?['id'] != id || _worker != worker) return;
      setState(() {
        _job = state;
        _jobs = _jobs.map((job) => job['id'] == id ? state : job).toList();
      });
      if (!_active) _timer?.cancel();
    } catch (error) {
      if (mounted && _worker == worker) setState(() => _error = error.toString());
    } finally {
      _polling = false;
    }
  }

  Future<void> _cancel() => _action(() async {
    final id = _job!['id'];
    final state = await _worker!.request('/jobs/$id/cancel', method: 'POST');
    if (!mounted) return;
    setState(() => _job = state);
    _watch();
  });

  Widget _panel(String title, List<Widget> children) => Card(
    margin: const EdgeInsets.only(bottom: 18),
    child: Padding(
      padding: const EdgeInsets.all(22),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(title, style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 16),
        ...children,
      ]),
    ),
  );

  Widget _field(TextEditingController controller, String label, {bool number = false, bool secret = false}) =>
    Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller, obscureText: secret,
        keyboardType: number ? TextInputType.number : TextInputType.text,
        decoration: InputDecoration(labelText: label),
      ),
    );

  Widget _connection() => _panel('Encoding worker', [
    _field(_address, 'Worker URL'),
    _field(_token, 'Worker access token', secret: true),
    Align(
      alignment: Alignment.centerLeft,
      child: FilledButton.tonal(
        onPressed: _busy ? null : _connect,
        child: Text(_worker == null ? 'Connect' : 'Reconnect'),
      ),
    ),
  ]);

  Widget _jobForm() => _panel('New encode', [
    if (_sources.isEmpty) const Text('Add a video to the worker’s source folder.'),
    if (_sources.isNotEmpty) DropdownButtonFormField<String>(
      key: ValueKey(_worker),
      initialValue: _source,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'Source video'),
      onChanged: _busy || _active ? null : (value) => setState(() => _source = value),
      items: _sources.map((source) => DropdownMenuItem(
        value: source, child: Text(source, overflow: TextOverflow.ellipsis),
      )).toList(),
    ),
    const SizedBox(height: 12),
    _field(_target, 'Expected final bitrate (kb/s)', number: true),
    _field(_tuning, 'Slightly lower two-pass bitrate (kb/s)', number: true),
    _field(_crop, 'Crop left, top, right, bottom (blank for auto)'),
    DropdownButtonFormField<String>(
      initialValue: _scan,
      isExpanded: true,
      decoration: const InputDecoration(labelText: 'Scan type'),
      items: const [
        DropdownMenuItem(
          value: 'auto',
          child: Text('Inspect automatically', overflow: TextOverflow.ellipsis),
        ),
        DropdownMenuItem(
          value: 'progressive',
          child: Text('Progressive', overflow: TextOverflow.ellipsis),
        ),
        DropdownMenuItem(
          value: 'tff',
          child: Text('Interlaced, top field first', overflow: TextOverflow.ellipsis),
        ),
        DropdownMenuItem(
          value: 'bff',
          child: Text('Interlaced, bottom field first', overflow: TextOverflow.ellipsis),
        ),
      ],
      onChanged: (value) => setState(() => _scan = value ?? 'auto'),
    ),
    SwitchListTile(
      contentPadding: EdgeInsets.zero,
      title: const Text('Encode the full source after a transparent result'),
      value: _full,
      onChanged: (value) => setState(() => _full = value),
    ),
    Align(
      alignment: Alignment.centerLeft,
      child: FilledButton.icon(
        onPressed: _busy || _active || _source == null ? null : _start,
        icon: const Icon(Icons.play_arrow),
        label: const Text('Run visual tuning'),
      ),
    ),
  ]);

  Widget _result() {
    final job = _job!;
    final report = job['report'] as Map<String, dynamic>?;
    final commands = report?['command'] as Map<String, dynamic>?;
    final status = job['status'] as String;
    final progress = (job['progress'] as num).toDouble();
    final files = (report?['comparison_files'] as List?)?.cast<String>() ?? [];
    final settings = report?['settings'] as Map<String, dynamic>?;
    final reviews = report?['crf_reviews'] as Map<String, dynamic>?;
    final review = (reviews?[report?['crf']?.toString()] ??
        report?['verification']) as Map<String, dynamic>?;
    return _panel('Job result', [
      Text(job['source'] as String, style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 8),
      Text('${status.toUpperCase()} · ${job['message']}'),
      if (_active) ...[
        const SizedBox(height: 12),
        LinearProgressIndicator(value: progress > 0 ? progress : null),
        TextButton(
          onPressed: _busy || status == 'cancelling' ? null : _cancel,
          child: const Text('Cancel job'),
        ),
      ],
      if (report != null) ...[
        const SizedBox(height: 16),
        if (report['crf'] != null)
          Text('CRF ${report['crf']} · ${report['sample_kbps']} kb/s on excerpts',
            style: Theme.of(context).textTheme.headlineSmall),
        if (settings != null)
          Text('Deblock ${settings['deblock']} · Psy-RDO ${settings['psy']} · AQ ${settings['mode']} / ${settings['strength']}'),
        if (report['crf_inspected_b_frames'] != null)
          Text('${report['crf_inspected_b_frames']} inspected of '
               '${report['crf_shared_b_frames']} shared B-frame timestamps'),
        if (report['crop'] != null) Text('Crop (L/T/R/B) ${report['crop']}'),
        if (review != null) _visualReview(review),
        if (commands != null)
          for (final entry in commands.entries)
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              title: Text(entry.key == 'bash' ? 'Bash command' : 'Windows CMD command'),
              children: [
                SelectableText(entry.value as String),
                TextButton(
                  onPressed: () => Clipboard.setData(ClipboardData(text: entry.value as String)),
                  child: const Text('Copy command'),
                ),
              ],
            ),
        TextButton(
          onPressed: () => Clipboard.setData(
            ClipboardData(text: const JsonEncoder.withIndent('  ').convert(report)),
          ),
          child: const Text('Copy complete report'),
        ),
        if (report['output_file'] != null)
          SelectableText('Full encode saved to ${job['id']}/${report['output_file']} in the worker job folder.'),
        for (final file in files)
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Comparison ${file.replaceFirst('comparison-', '').replaceFirst('.png', '')}'),
            subtitle: const Text('Source on left · candidate on right'),
            children: [
              Image.network(
                _worker!.uri('/jobs/${job['id']}/files/$file').toString(),
                headers: _worker!.headers,
                fit: BoxFit.contain,
                errorBuilder: (_, error, stack) => const Text('Could not load comparison image.'),
              ),
            ],
          ),
      ],
    ]);
  }

  Widget _visualReview(Map<String, dynamic> review) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    initiallyExpanded: true,
    title: const Text('Visual review'),
    expandedCrossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(review['summary'] as String),
      for (final finding in (review['findings'] as List).cast<Map<String, dynamic>>())
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(finding['observation'] as String),
          subtitle: Text('Frame ${finding['frame']} · ${finding['category']}'),
        ),
    ],
  );

  Widget _recentJobs() => _panel('Recent jobs', [
    for (final job in _jobs.take(8))
      ListTile(
        contentPadding: EdgeInsets.zero,
        title: Text(job['source'] as String),
        subtitle: Text(job['status'] as String),
        onTap: () {
          setState(() => _job = job);
          _watch();
        },
      ),
  ]);

  Widget _workspace(BoxConstraints viewport) {
    final controls = [
      _connection(),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ),
      if (_worker != null) _jobForm(),
      if (_jobs.length > 1) _recentJobs(),
    ];
    final showColumns = viewport.maxWidth >= 1040 && _job != null;
    return SingleChildScrollView(
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: showColumns ? 1240 : 800),
          child: showColumns
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 400,
                      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: controls),
                    ),
                    const SizedBox(width: 20),
                    Expanded(child: _result()),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [...controls, if (_job != null) _result()],
                ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Encode Assistant')),
    body: SafeArea(child: LayoutBuilder(builder: (_, viewport) => _workspace(viewport))),
  );
}

import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';
import 'dart:io';

void main() => runApp(ChatApp());

class ChatApp extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(home: ChatScreen(), debugShowCheckedModeBanner: false);
  }
}

class ChatScreen extends StatefulWidget {
  @override
  _ChatScreenState createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with TickerProviderStateMixin {
  final TextEditingController _queryController = TextEditingController();
  String _selectedSessionId = 'default';
  String _previousSummary = '';
  bool _isLoading = false;
  late final AnimationController _rotationController;

  Map<String, List<Map<String, String>>> _allSessions = {};
  final _uuid = Uuid();
  final String _apiBaseUrl = 'http://127.0.0.1:8000';

  @override
  void initState() {
    super.initState();
    _loadSessions();

    // 애니메이션 컨트롤러 초기화
    _rotationController = AnimationController(
      vsync: this,
      duration: Duration(seconds: 1),
    );
  }

  @override
  void dispose() {
    _rotationController.dispose();
    super.dispose();
  }

  // 서버에서 세션 데이터를 받아서 _allSessions라는 변수에 저장
  Future<void> _loadSessions() async {
    final response = await http.get(Uri.parse("$_apiBaseUrl/load_sessions"));

    if (response.statusCode == 200) {
      final Map<String, dynamic> decoded = jsonDecode(
        utf8.decode(response.bodyBytes),
      );

      final Map<String, List<Map<String, String>>> sessions = {};

      decoded.forEach((sessionId, sessionData) {
        final List<Map<String, String>> typedHistory = [];

        if (sessionData is Map && sessionData['history'] is List) {
          for (var item in sessionData['history']) {
            if (item is Map) {
              final q = item['q']?.toString() ?? '';
              final a = item['a']?.toString() ?? '';
              typedHistory.add({'q': q, 'a': a});
            }
          }
        }

        sessions[sessionId] = typedHistory;
      });

      setState(() {
        _allSessions = sessions;
        if (!_allSessions.containsKey(_selectedSessionId) &&
            _allSessions.isNotEmpty) {
          _selectedSessionId = _allSessions.keys.first;
        }
      });
    } else {
      print("세션 불러오기 실패: ${response.body}");
    }
  }

  Future<void> _sendQuery() async {
    String query = _queryController.text.trim();
    if (query.isEmpty) return;

    setState(() => _isLoading = true);
    _rotationController.repeat(); // 회전 시작

    try {
      // default 세션이면 새로 만들기
      if (_selectedSessionId == 'default') {
        String newSessionId = _uuid.v4();
        setState(() {
          _selectedSessionId = newSessionId;
          _allSessions[newSessionId] = [];
        });
      }

      final response = await http.post(
        Uri.parse("$_apiBaseUrl/chat"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "session_id": _selectedSessionId,
          "previous_summary": _previousSummary,
          "query": query,
        }),
      );

      if (response.statusCode == 200) {
        final responseData = jsonDecode(utf8.decode(response.bodyBytes));

        setState(() {
          _queryController.clear();
          _previousSummary = responseData["new_summary"];
          final history = List<Map<String, String>>.from(
            (responseData["chat_history"] as List).map(
              (e) => {"q": e["q"] as String, "a": e["a"] as String},
            ),
          );
          _allSessions[_selectedSessionId] = history;
        });
      } else {
        print("Error: ${response.body}");
      }
    } finally {
      _rotationController.stop(); // 회전 중단
      _rotationController.reset();
      setState(() => _isLoading = false);
    }
  }

  Future<void> _deleteSession() async {
    if (_selectedSessionId == 'default') return;

    final response = await http.delete(
      Uri.parse("$_apiBaseUrl/delete_session"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"session_id": _selectedSessionId}),
    );

    if (response.statusCode == 200) {
      setState(() {
        _allSessions.remove(_selectedSessionId);
        _selectedSessionId = 'default';
        _previousSummary = '';
      });
    } else {
      print("Delete failed: ${response.body}");
    }
  }

  List<DropdownMenuItem<String>> _buildSessionDropdownItems() {
    List<DropdownMenuItem<String>> items = [
      DropdownMenuItem(value: 'default', child: Text('➕ 새 세션')),
    ];
    _allSessions.forEach((id, history) {
      // id 길이가 8보다 작으면 id 전체, 크면 앞 8글자만 표시
      final display = id.length > 8 ? id.substring(0, 8) : id;
      items.add(DropdownMenuItem(value: id, child: Text(display)));
    });
    return items;
  }

  List<Widget> _buildChatHistory() {
    if (_selectedSessionId == 'default' ||
        !_allSessions.containsKey(_selectedSessionId)) {
      return [Text("새 세션을 입력해보세요.")];
    }

    return _allSessions[_selectedSessionId]!.map((item) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 질문은 오른쪽
          Align(
            alignment: Alignment.centerRight,
            child: _buildBubble(item['q']!, isUser: true),
          ),
          SizedBox(height: 8),
          // 답변은 왼쪽
          Align(
            alignment: Alignment.centerLeft,
            child: _buildBubble(item['a']!, isUser: false),
          ),
          SizedBox(height: 16),
        ],
      );
    }).toList();
  }

  Widget _buildBubble(String text, {required bool isUser}) {
    return Container(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width * 0.75, // 화면 너비의 75%까지
      ),
      padding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: isUser ? Colors.blue.shade100 : Colors.grey.shade200,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 16,
          fontWeight: isUser ? FontWeight.bold : FontWeight.normal,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('생활 꿀팁 검색 요약 서비스 ✨'),
        actions: [
          DropdownButton<String>(
            value: _selectedSessionId,
            items: _buildSessionDropdownItems(),
            onChanged: (value) {
              setState(() {
                _selectedSessionId = value!;
                _previousSummary = '';
              });
            },
          ),
          IconButton(
            icon: Icon(Icons.delete),
            onPressed: _deleteSession,
            tooltip: '세션 삭제',
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(12.0),
        child: Column(
          children: [
            Expanded(child: ListView(children: _buildChatHistory())),
            TextField(
              controller: _queryController,
              decoration: InputDecoration(
                labelText: '질문을 입력하세요',
                suffixIcon:
                    _isLoading
                        ? RotationTransition(
                          turns: _rotationController,
                          child: Padding(
                            padding: const EdgeInsets.all(12.0),
                            child: SizedBox(
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                          ),
                        )
                        : IconButton(
                          icon: Icon(Icons.send),
                          onPressed: _sendQuery,
                        ),
              ),
              onSubmitted: (_) => _sendQuery(),
            ),
          ],
        ),
      ),
    );
  }
}

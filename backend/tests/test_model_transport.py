import json
import os
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from app import llm_service


def test_windows_https_keeps_credentials_out_of_command_line(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'openai')
    monkeypatch.setenv('LLM_API_KEY', 'test-private-key')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setenv('LLM_BASE_URL', 'https://model.example/v1')
    monkeypatch.setenv('LLM_TRANSPORT', 'windows')
    monkeypatch.setattr(llm_service.shutil, 'which', lambda name: 'powershell.exe')
    captured = []
    def run(argv, **kwargs):
        captured.append((argv, kwargs))
        return SimpleNamespace(stdout=json.dumps({'status': 200, 'body': json.dumps({'choices': [{'message': {'content': '{"reply":"具体观察到了什么？"}'}}]})}))
    monkeypatch.setattr(llm_service.subprocess, 'run', run)
    result = llm_service.invoke_messages([('user', '今天检查了数据')])
    assert json.loads(result)['reply'] == '具体观察到了什么？'
    argv, kwargs = captured[0]
    assert 'test-private-key' not in str(argv) and '今天检查了数据' not in str(argv)
    assert json.loads(kwargs['input'])['url'] == 'https://model.example/v1/chat/completions'


def test_connection_check_returns_actionable_auth_failure_without_secret(monkeypatch):
    monkeypatch.setattr(llm_service, 'enabled', lambda: True)
    def fail(_): raise llm_service.ModelConnectionError(401)
    monkeypatch.setattr(llm_service, 'invoke_messages', fail)
    result = llm_service.connection_check()
    assert not result['connected'] and '鉴权失败' in result['message']


def test_malformed_model_json_does_not_become_an_assistant_response(monkeypatch):
    monkeypatch.setattr(llm_service, 'enabled', lambda: True)
    monkeypatch.setattr(llm_service, 'invoke_messages', lambda _: 'invalid structured response')
    assert llm_service.invoke_json('daily_dialogue', {}) is None


@pytest.mark.skipif(os.name != 'nt', reason='Windows HTTPS transport')
@pytest.mark.parametrize('shell_name', ['powershell.exe', 'pwsh.exe'])
@pytest.mark.parametrize('content_type,escaped,prefix,suffix,status', [
    ('application/json', False, b'', b'', 200),
    ('application/json; charset=utf-8', False, b'', b'', 200),
    ('application/json', True, b'', b'', 200),
    ('application/json', False, b'\xef\xbb\xbf', b'', 200),
    ('application/json', False, b'', b'\xff', 0),
])
def test_windows_transport_decodes_utf8_json(shell_name, content_type, escaped, prefix, suffix, status):
    executable = shutil.which(shell_name)
    if not executable:
        pytest.skip(f'{shell_name} is not installed')
    reply = '今天阅读了联邦学习文献。具体研究了哪种方法？📚 café'
    response_bytes = prefix + json.dumps({
        'choices': [{'message': {'content': json.dumps({'reply': reply}, ensure_ascii=escaped)}}],
    }, ensure_ascii=escaped).encode('utf-8') + suffix
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)

        def log_message(self, *args):
            pass

    request_body = {'messages': [{'role': 'user', 'content': '今天阅读了一篇文献'}]}
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = subprocess.run([
                executable, '-NoProfile', '-NonInteractive', '-File',
                str(Path(llm_service.__file__).with_name('windows_model_http.ps1')),
            ], input=json.dumps({
                'url': f'http://127.0.0.1:{server.server_port}/chat/completions',
                'key': 'test-only-key', 'body': json.dumps(request_body, ensure_ascii=True),
            }, ensure_ascii=True), capture_output=True, encoding='utf-8', timeout=42,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        finally:
            server.shutdown()
            worker.join(timeout=5)
    assert result.returncode == 0
    envelope = json.loads(result.stdout.lstrip('\ufeff'))
    assert received == [request_body]
    assert envelope['status'] == status
    if status != 200:
        assert envelope['body'] == ''
        return
    content = json.loads(envelope['body'])['choices'][0]['message']['content']
    assert json.loads(content)['reply'] == reply

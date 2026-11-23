"""Optional OpenAI-compatible LLM adapter for GPT and DeepSeek.

The daily conversation reports failures explicitly and persists the user's
message before calling the provider. Reports fall back to verbatim evidence.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PROMPT_DIR=Path(__file__).resolve().parents[1]/"prompts"


class ModelConnectionError(Exception):
    def __init__(self, status_code=0):
        super().__init__('Model request failed')
        self.status_code = status_code


def invoke_messages(messages):
    """Keep TLS verification on. Windows uses its native HTTPS implementation."""
    if os.name != 'nt' or os.getenv('LLM_TRANSPORT', 'windows') == 'python':
        return _client().invoke(messages).content
    provider = os.getenv('LLM_PROVIDER', 'deepseek' if os.getenv('DEEPSEEK_API_KEY') and not os.getenv('LLM_API_KEY') else 'openai').lower()
    key = os.getenv('DEEPSEEK_API_KEY') if provider == 'deepseek' else os.getenv('OPENAI_API_KEY') or os.getenv('LLM_API_KEY')
    default_url = 'https://api.deepseek.com' if provider == 'deepseek' else 'https://api.openai.com/v1'
    default_model = 'deepseek-chat' if provider == 'deepseek' else 'gpt-4o-mini'
    payload = {'url': os.getenv('LLM_BASE_URL', default_url).rstrip('/') + '/chat/completions', 'key': key,
               'body': json.dumps({'model': os.getenv('LLM_MODEL', default_model), 'temperature': 0,
                    'messages': [{'role': role, 'content': content} for role, content in messages]}, ensure_ascii=True)}
    executable = shutil.which('pwsh.exe') or shutil.which('powershell.exe')
    if not executable: raise ModelConnectionError()
    result = subprocess.run([executable, '-NoProfile', '-NonInteractive', '-File', str(Path(__file__).with_name('windows_model_http.ps1'))],
                            input=json.dumps(payload, ensure_ascii=True), capture_output=True, encoding='utf-8', timeout=42,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        envelope = json.loads(result.stdout.lstrip('\ufeff'))
        if envelope.get('status') != 200: raise ModelConnectionError(envelope.get('status', 0))
        return json.loads(envelope['body'])['choices'][0]['message']['content']
    except (ValueError, KeyError, IndexError) as exc:
        raise ModelConnectionError() from exc

def enabled():
    provider=os.getenv("LLM_PROVIDER", "openai" if os.getenv('LLM_API_KEY') or os.getenv('OPENAI_API_KEY') else 'deepseek' if os.getenv('DEEPSEEK_API_KEY') else "mock").lower()
    key=os.getenv("DEEPSEEK_API_KEY") if provider=="deepseek" else os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    return provider in {"openai","deepseek"} and bool(key)

def _client():
    from langchain_openai import ChatOpenAI
    provider=os.getenv("LLM_PROVIDER", "deepseek" if os.getenv('DEEPSEEK_API_KEY') and not os.getenv('LLM_API_KEY') else "openai").lower()
    if provider=="deepseek":
        return ChatOpenAI(api_key=os.getenv("DEEPSEEK_API_KEY"),base_url=os.getenv("LLM_BASE_URL","https://api.deepseek.com"),model=os.getenv("LLM_MODEL","deepseek-chat"),temperature=0,timeout=35,max_retries=0)
    return ChatOpenAI(api_key=os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY"),base_url=os.getenv("LLM_BASE_URL","https://api.openai.com/v1"),model=os.getenv("LLM_MODEL","gpt-4o-mini"),temperature=0,timeout=35,max_retries=0)

def invoke_json(prompt_name:str,payload:dict):
    if not enabled(): return None
    system=(PROMPT_DIR/f"{prompt_name}.txt").read_text(encoding="utf-8")
    try:
        content=invoke_messages([("system",system),("user",json.dumps(payload,ensure_ascii=False)+"\n只输出JSON，不要Markdown代码块。")])
        match=re.search(r"\{.*\}",content,re.S)
        return json.loads(match.group(0) if match else content)
    except Exception:
        # Each caller decides whether to expose a retry or use verbatim evidence.
        return None


def connection_check():
    if not enabled(): return {'connected': False, 'message': '尚未配置模型密钥。当前可使用基础追问，记录会保存。'}
    try:
        response = invoke_messages([('user', 'Connection test. Reply OK only.')])
        if response: return {'connected': True, 'message': 'AI 连接成功，可以开始科研对话。'}
    except Exception as exc:
        code = getattr(exc, 'status_code', None)
        if code in (401, 403): message = '模型鉴权失败，请检查后端配置的密钥及访问权限。'
        elif code == 402: message = '模型账户余额不足，请检查模型账户。'
        elif code in (400, 404): message = '模型地址或名称不可用，请检查后端配置。'
        elif code == 429: message = '模型服务请求过于频繁，请稍后重试。'
        else: message = '暂时无法连接模型服务，请检查电脑网络及后端配置。你的科研记录不受影响。'
        return {'connected': False, 'message': message}
    return {'connected': False, 'message': '模型没有返回内容，请稍后重试。'}


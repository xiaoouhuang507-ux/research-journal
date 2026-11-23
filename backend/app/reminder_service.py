"""WeChat subscription delivery plus once-daily foreground reminders (China time)."""
import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
import httpx
from fastapi import HTTPException
from .database import connect, row

CHINA = timezone(timedelta(hours=8))
_access_token = {'value': '', 'expires': 0}


def now(): return datetime.now(CHINA)


def configuration():
    required = ('WECHAT_APP_ID', 'WECHAT_APP_SECRET', 'WECHAT_REMINDER_TEMPLATE_ID', 'WECHAT_TEMPLATE_DATA')
    missing = [key for key in required if not os.getenv(key)]
    try:
        data = json.loads(os.getenv('WECHAT_TEMPLATE_DATA', '{}'))
        if not isinstance(data, dict) or not data or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            if 'WECHAT_TEMPLATE_DATA' not in missing: missing.append('WECHAT_TEMPLATE_DATA')
    except (ValueError, TypeError):
        if 'WECHAT_TEMPLATE_DATA' not in missing: missing.append('WECHAT_TEMPLATE_DATA')
    return {'configured': not missing, 'missing': missing, 'template_id': os.getenv('WECHAT_REMINDER_TEMPLATE_ID', ''),
            'subscription_kind': 'longterm' if os.getenv('WECHAT_SUBSCRIPTION_KIND') == 'longterm' else 'once'}


def has_record(day):
    return bool(row('SELECT t.id FROM journal_turns t JOIN projects p ON p.id=t.project_id WHERE p.user_id=1 AND t.occurred_on=? LIMIT 1', (day,)))


def preferences():
    setting = row('SELECT * FROM reminder_settings WHERE user_id=1')
    current = now()
    config = configuration()
    active = row("SELECT id FROM projects WHERE status='active' AND user_id=1")
    delivered = row("SELECT id FROM reminder_deliveries WHERE user_id=1 AND local_date=? AND status IN ('shown','sent','sending')", (str(current.date()),))
    due = bool(setting['enabled'] and active and current.strftime('%H:%M') >= setting['reminder_time'] and not has_record(str(current.date())) and not delivered)
    return {'enabled': bool(setting['enabled']), 'reminder_time': setting['reminder_time'], 'timezone': 'Asia/Shanghai',
            'wechat': {**config, 'linked': bool(setting['openid']), 'remaining': setting['credits'], 'last_error': setting['last_error'],
                       'ready': bool(config['configured'] and setting['openid'] and setting['credits'] > 0 and setting['enabled'])},
            'due': due}


def update(body):
    with connect() as con:
        con.execute('UPDATE reminder_settings SET enabled=?,reminder_time=? WHERE user_id=1', (int(body.enabled), body.reminder_time))
    return preferences()


def claim_foreground():
    if not preferences()['due']: return {'show': False}
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute("SELECT 1 FROM reminder_deliveries WHERE user_id=1 AND local_date=? AND status IN ('shown','sent','sending')", (str(now().date()),)).fetchone(): return {'show': False}
        cur = con.execute("INSERT OR IGNORE INTO reminder_deliveries(user_id,local_date,channel,status) VALUES(1,?,'foreground','shown')", (str(now().date()),))
        return {'show': cur.rowcount == 1}


def link_wechat(code):
    if not configuration()['configured']: raise HTTPException(409, '微信提醒尚未配置，请先在后端填写小程序与订阅模板配置')
    try:
        data = httpx.get('https://api.weixin.qq.com/sns/jscode2session', params={'appid': os.environ['WECHAT_APP_ID'], 'secret': os.environ['WECHAT_APP_SECRET'], 'js_code': code, 'grant_type': 'authorization_code'}, timeout=12).json()
        if not data.get('openid'): raise ValueError('login failed')
    except Exception as exc:
        raise HTTPException(502, '微信身份连接失败，请在真机重试并检查小程序 AppID') from exc
    token = secrets.token_urlsafe(32)
    with connect() as con:
        con.execute("UPDATE reminder_settings SET openid=?,device_token=?,credits=CASE WHEN openid=? THEN credits ELSE 0 END,last_error='' WHERE user_id=1", (data['openid'], token, data['openid']))
    return {'device_token': token}


def subscribe(body):
    config = configuration()
    if not config['configured'] or body.template_id != config['template_id']: raise HTTPException(409, '订阅模板配置已变化，请重新授权')
    with connect() as con:
        setting = con.execute('SELECT device_token,openid FROM reminder_settings WHERE user_id=1').fetchone()
        if not setting['openid'] or not secrets.compare_digest(setting['device_token'], body.device_token): raise HTTPException(401, '请先连接微信身份')
        # Keep one pending daily reminder. Each successful authorization replenishes one.
        con.execute("UPDATE reminder_settings SET credits=1,last_error='' WHERE user_id=1")
    return preferences()


def access_token():
    if _access_token['expires'] > time.monotonic(): return _access_token['value']
    data = httpx.get('https://api.weixin.qq.com/cgi-bin/token', params={'grant_type': 'client_credential', 'appid': os.environ['WECHAT_APP_ID'], 'secret': os.environ['WECHAT_APP_SECRET']}, timeout=12).json()
    if not data.get('access_token'): raise ValueError('wechat token unavailable')
    _access_token.update(value=data['access_token'], expires=time.monotonic() + max(0, int(data.get('expires_in', 7200)) - 120))
    return data['access_token']


def dispatch():
    if not configuration()['configured']: return
    setting = row('SELECT * FROM reminder_settings WHERE user_id=1')
    current = now()
    day = str(current.date())
    if not setting['enabled'] or not setting['openid'] or setting['credits'] < 1 or current.strftime('%H:%M') < setting['reminder_time'] or has_record(day): return
    project = row("SELECT id FROM projects WHERE status='active' AND user_id=1")
    if not project: return
    if row("SELECT id FROM reminder_deliveries WHERE user_id=1 AND local_date=? AND status IN ('shown','sent','sending')", (day,)): return
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        latest = con.execute('SELECT enabled,credits FROM reminder_settings WHERE user_id=1').fetchone()
        if not latest['enabled'] or latest['credits'] < 1: return
        if con.execute("SELECT 1 FROM reminder_deliveries WHERE user_id=1 AND local_date=? AND status IN ('shown','sent','sending')", (day,)).fetchone(): return
        claimed = con.execute("INSERT OR IGNORE INTO reminder_deliveries(user_id,local_date,channel,status) VALUES(1,?,'wechat','sending')", (day,))
        if not claimed.rowcount: return
    status, error, consumed = 'failed', '', False
    try:
        values = json.loads(os.environ['WECHAT_TEMPLATE_DATA'])
        data = {key: {'value': value.replace('{date}', day).replace('{datetime}', current.strftime('%Y-%m-%d %H:%M'))} for key, value in values.items()}
        result = httpx.post('https://api.weixin.qq.com/cgi-bin/message/subscribe/send', params={'access_token': access_token()},
                            json={'touser': setting['openid'], 'template_id': os.environ['WECHAT_REMINDER_TEMPLATE_ID'],
                                  'page': 'pages/chat/index?id=' + str(project['id']), 'data': data,
                                  'miniprogram_state': os.getenv('WECHAT_MINIPROGRAM_STATE', 'developer'), 'lang': 'zh_CN'}, timeout=12).json()
        if result.get('errcode') == 0:
            status, consumed = 'sent', configuration()['subscription_kind'] == 'once'
        else:
            code = result.get('errcode')
            consumed = code == 43101
            error = '订阅授权已用完，请在小程序重新授权' if consumed else f'微信提醒发送失败（{code}），请检查模板及配置'
    except Exception:
        error = '微信提醒发送未确认，请检查后端网络。为避免重复打扰，当天不自动重发。'
    with connect() as con:
        con.execute("UPDATE reminder_deliveries SET status=? WHERE user_id=1 AND local_date=? AND channel='wechat'", (status, day))
        con.execute('UPDATE reminder_settings SET credits=MAX(0,credits-?),last_error=? WHERE user_id=1', (int(consumed), error))


async def scheduler():
    while True:
        try: await asyncio.to_thread(dispatch)
        except Exception: pass  # A reminder must never stop the dialogue API.
        await asyncio.sleep(30)

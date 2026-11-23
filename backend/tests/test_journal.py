import json
from datetime import timedelta, datetime
from app import journal_service as service, reminder_service as reminders
from app.database import row, rows, connect, init_db
from app.schemas import local_today


def project(client, name='特征选择'):
    response = client.post('/api/v2/projects', json={'name': name, 'topic': '多标签特征选择', 'direction': '比较两种方法的性能与计算开销',
        'references': [{'title': '参考论文甲', 'authors': '研究者', 'notes': '使用标签相关性进行特征排序'}]})
    assert response.status_code == 200, response.text
    return response.json()['project_id']


def message(client, pid, text='今天跑通了基线，但还没有结果', day=None, token='journal-token-1'):
    return client.post(f'/api/v2/projects/{pid}/conversation', json={'message': text, 'occurred_on': day or str(local_today()), 'client_token': token})


def test_project_profile_edit_preserves_dialogue_and_isolated_references(client):
    pid = project(client)
    message(client, pid)
    body = {'name': '修改名称', 'topic': '新主题', 'direction': '新研究方向', 'references': [{'title': '参考论文乙'}]}
    result = client.put(f'/api/v2/projects/{pid}', json=body)
    assert result.status_code == 200
    assert result.json()['project']['references'][0]['title'] == '参考论文乙'
    assert len(client.get(f'/api/v2/projects/{pid}/conversation').json()['turns']) == 1
    second = project(client, '课题二')
    assert client.get(f'/api/v2/projects/{second}/conversation').json()['turns'] == []
    assert message(client, pid, token='journal-token-old').status_code == 409


def test_input_validation_and_future_dates(client):
    assert client.post('/api/v2/projects', json={'name': ' ', 'topic': '主题', 'direction': '方向'}).status_code == 422
    pid = project(client)
    assert message(client, pid, ' ', token='blank-message').status_code == 422
    assert message(client, pid, day=str(local_today() + timedelta(days=1))).status_code == 422
    assert client.put('/api/v2/reminder', json={'reminder_time': '25:80'}).status_code == 422


def test_model_receives_topic_references_and_actual_followup_history(client, monkeypatch):
    pid = project(client)
    inputs = []
    def invoke(name, payload):
        inputs.append(payload)
        return {'reply': '小样本使用了什么数据集，观察到什么现象？'}
    monkeypatch.setattr(service.llm_service, 'enabled', lambda: True)
    monkeypatch.setattr(service.llm_service, 'invoke_json', invoke)
    first = message(client, pid).json()
    assert first['ai_mode'] == 'model'
    assert inputs[0]['project']['references'][0]['notes'] == '使用标签相关性进行特征排序'
    assert inputs[0]['project']['direction'] == '比较两种方法的性能与计算开销'
    assert message(client, pid, '还没开始训练，只完成环境检查', token='journal-token-2').status_code == 200
    assert inputs[1]['history'][0]['user_content'] == '今天跑通了基线，但还没有结果'
    assert inputs[1]['history'][0]['assistant_content'] == first['assistant_content']


def test_message_retry_is_idempotent_and_model_failure_retains_user_evidence(client, monkeypatch):
    pid = project(client)
    monkeypatch.setattr(service.llm_service, 'enabled', lambda: True)
    monkeypatch.setattr(service.llm_service, 'invoke_json', lambda *args: None)
    assert message(client, pid).status_code == 503
    stored = client.get(f'/api/v2/projects/{pid}/conversation').json()['turns']
    assert len(stored) == 1 and stored[0]['status'] == 'failed'
    monkeypatch.setattr(service.llm_service, 'invoke_json', lambda *args: {'reply': '具体卡在哪一步？'})
    retry = message(client, pid)
    assert retry.status_code == 200
    assert message(client, pid).json()['id'] == retry.json()['id']
    assert len(client.get(f'/api/v2/projects/{pid}/conversation').json()['turns']) == 1
    assert message(client, pid, '改变相同请求的内容').status_code == 409


def test_date_report_uses_only_inclusive_user_evidence_not_ai_questions_or_other_project(client):
    pid = project(client)
    old_day = str(local_today() - timedelta(days=1))
    message(client, pid, '昨天只安装了环境', day=old_day)
    current = message(client, pid, '明天才做对照实验，今天只检查数据', token='journal-token-now').json()
    second = project(client, '另外一个课题')
    message(client, second, '其他课题的秘密实验', token='other-project-token')
    body = {'time_scope': '自定义', 'start_date': str(local_today()), 'end_date': str(local_today())}
    result = client.post(f'/api/v2/projects/{pid}/report', json=body).json()
    assert result['evidence_count'] == 1
    assert result['sources'][0]['id'] == current['id']
    assert '明天才做对照实验' in result['markdown']
    assert '昨天只安装了环境' not in result['markdown'] and '秘密实验' not in result['markdown']
    assert current['assistant_content'] not in result['markdown']
    saved = client.post(f'/api/v2/projects/{pid}/report', json={'save': True, 'draft_id': result['draft_id'], 'markdown': '# 手动编辑后的汇报'}).json()
    assert saved['markdown'] == '# 手动编辑后的汇报'
    assert client.post(f'/api/v2/projects/{pid}/report', json={'save': True, 'draft_id': result['draft_id'], 'markdown': '# 手动编辑后的汇报'}).json()['report_id'] == saved['report_id']
    revision = client.post(f"/api/v2/projects/{pid}/reports/{saved['report_id']}/revision").json()
    assert revision['markdown'] == '# 手动编辑后的汇报'
    assert client.post(f"/api/v2/projects/{second}/reports/{saved['report_id']}/revision").status_code == 404


def test_empty_date_range_and_invented_model_citations(client, monkeypatch):
    pid = project(client)
    yesterday = str(local_today() - timedelta(days=1))
    empty = client.post(f'/api/v2/projects/{pid}/report', json={'time_scope': '自定义', 'start_date': yesterday, 'end_date': yesterday}).json()
    assert empty['sources'] == []
    assert '没有科研对话' in empty['markdown']
    message(client, pid)
    monkeypatch.setattr(service.llm_service, 'invoke_json', lambda *args: {'sections': {'研究进展': [{'text': '编造的结果', 'source_ids': [999999]}]}})
    result = client.post(f'/api/v2/projects/{pid}/report', json={'time_scope': '本周'}).json()
    assert result['ai_mode'] == 'source' and '编造的结果' not in result['markdown']


def test_report_model_has_no_assistant_text_and_valid_citations(client, monkeypatch):
    pid = project(client)
    turn = message(client, pid, '完成了数据检查').json()
    def invoke(name, payload):
        assert name == 'dialogue_report'
        assert payload['evidence'] == [{'id': turn['id'], 'date': str(local_today()), 'content': '完成了数据检查'}]
        return {'sections': {'研究进展': [{'text': '已完成数据检查', 'source_ids': [turn['id']]}]}}
    monkeypatch.setattr(service.llm_service, 'invoke_json', invoke)
    result = client.post(f'/api/v2/projects/{pid}/report', json={'time_scope': '本周'}).json()
    assert result['ai_mode'] == 'model' and '已完成数据检查' in result['markdown']


def test_reminder_before_time_once_per_day_and_skip_recorded_day(client, monkeypatch):
    pid = project(client)
    fixed = datetime.combine(local_today(), datetime.min.time(), reminders.CHINA)
    monkeypatch.setattr(reminders, 'now', lambda: fixed.replace(hour=19, minute=59))
    assert not client.post('/api/v2/reminder/claim').json()['show']
    monkeypatch.setattr(reminders, 'now', lambda: fixed.replace(hour=20))
    assert client.post('/api/v2/reminder/claim').json()['show']
    assert not client.post('/api/v2/reminder/claim').json()['show']
    with connect() as con: con.execute('DELETE FROM reminder_deliveries')
    message(client, pid)
    assert not client.post('/api/v2/reminder/claim').json()['show']
    assert client.get('/api/v2/reminder').json()['reminder_time'] == '20:00'


def configure_wechat(monkeypatch):
    for key, value in {'WECHAT_APP_ID': 'test-id', 'WECHAT_APP_SECRET': 'test-secret', 'WECHAT_REMINDER_TEMPLATE_ID': 'test-template', 'WECHAT_TEMPLATE_DATA': '{"thing1":"科研记录","time2":"{datetime}"}'}.items(): monkeypatch.setenv(key, value)


def test_actual_push_requires_authorization_and_does_not_duplicate(client, monkeypatch):
    project(client)
    configure_wechat(monkeypatch)
    monkeypatch.setattr(reminders, 'now', lambda: datetime.combine(local_today(), datetime.min.time(), reminders.CHINA).replace(hour=20))
    calls = []
    class Response:
        def json(self): return {'errcode': 0}
    monkeypatch.setattr(reminders, 'access_token', lambda: 'test-token')
    monkeypatch.setattr(reminders.httpx, 'post', lambda *a, **kw: calls.append(kw) or Response())
    reminders.dispatch()
    assert not calls
    with connect() as con: con.execute("UPDATE reminder_settings SET openid='test-openid',credits=1 WHERE user_id=1")
    reminders.dispatch(); reminders.dispatch()
    assert len(calls) == 1
    assert row('SELECT credits FROM reminder_settings')['credits'] == 0
    assert not client.post('/api/v2/reminder/claim').json()['show']


def test_reminder_disabled_or_foreground_shown_prevents_push(client, monkeypatch):
    project(client)
    configure_wechat(monkeypatch)
    monkeypatch.setattr(reminders, 'now', lambda: datetime.combine(local_today(), datetime.min.time(), reminders.CHINA).replace(hour=20))
    with connect() as con: con.execute("UPDATE reminder_settings SET openid='test-openid',credits=1,enabled=0")
    reminders.dispatch()
    assert not rows('SELECT * FROM reminder_deliveries')
    client.put('/api/v2/reminder', json={'enabled': True, 'reminder_time': '20:00'})
    assert client.post('/api/v2/reminder/claim').json()['show']
    reminders.dispatch()
    assert len(rows('SELECT * FROM reminder_deliveries')) == 1


def test_incremental_migration_keeps_existing_projects_and_reports(client):
    pid = project(client)
    with connect() as con:
        con.execute("INSERT INTO reports(project_id,time_scope,content) VALUES(?,'旧版','之前的汇报')", (pid,))
    init_db(); init_db()
    assert row('SELECT * FROM reports')['content'] == '之前的汇报'
    assert row('SELECT * FROM project_references')['title'] == '参考论文甲'


def test_longterm_subscription_keeps_permission_for_next_day(client, monkeypatch):
    project(client)
    configure_wechat(monkeypatch)
    monkeypatch.setenv('WECHAT_SUBSCRIPTION_KIND', 'longterm')
    fixed = datetime.combine(local_today(), datetime.min.time(), reminders.CHINA).replace(hour=20)
    monkeypatch.setattr(reminders, 'now', lambda: fixed)
    class Response:
        def json(self): return {'errcode': 0}
    calls = []
    monkeypatch.setattr(reminders, 'access_token', lambda: 'token')
    monkeypatch.setattr(reminders.httpx, 'post', lambda *a, **kw: calls.append(kw) or Response())
    with connect() as con: con.execute("UPDATE reminder_settings SET openid='test-openid',credits=1")
    reminders.dispatch(); reminders.dispatch()
    monkeypatch.setattr(reminders, 'now', lambda: fixed + timedelta(days=1))
    reminders.dispatch()
    assert len(calls) == 2
    assert row('SELECT credits FROM reminder_settings')['credits'] == 1


def test_push_failure_is_visible_and_does_not_loop(client, monkeypatch):
    project(client)
    configure_wechat(monkeypatch)
    monkeypatch.setattr(reminders, 'now', lambda: datetime.combine(local_today(), datetime.min.time(), reminders.CHINA).replace(hour=20))
    class Response:
        def json(self): return {'errcode': 43101}
    monkeypatch.setattr(reminders, 'access_token', lambda: 'token')
    monkeypatch.setattr(reminders.httpx, 'post', lambda *a, **kw: Response())
    with connect() as con: con.execute("UPDATE reminder_settings SET openid='test-openid',credits=1")
    reminders.dispatch()
    state = client.get('/api/v2/reminder').json()
    assert not state['wechat']['ready'] and state['wechat']['remaining'] == 0
    assert '授权' in state['wechat']['last_error']

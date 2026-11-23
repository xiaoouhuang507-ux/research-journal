from datetime import timedelta
from uuid import uuid4

from app import database, main
from app.product_service import today


def project(client, stage='文献调研'):
    response = client.post('/api/v1/projects', json={'name':'测试课题', 'goal':'验证工具调用可靠性', 'stage':stage, 'deadline':str(today()+timedelta(days=28))})
    assert response.status_code == 200, response.text
    return response.json()['project_id']


def plan(client, pid):
    preview = client.post(f'/api/v1/projects/{pid}/plan', json={}).json()
    response = client.post(f'/api/v1/projects/{pid}/plan', json={'confirm':True,'draft_id':preview['draft_id']})
    assert response.status_code == 200, response.text
    return response.json()['task_ids']


def progress(client, tid, **overrides):
    payload = {'client_token':str(uuid4()), 'occurred_on':str(today()), 'accomplishment':'完成小样本验证', 'result':'观察到参数格式不一致', 'blocker':'', 'next_step':'检查输出校验', 'status':'进行中', 'progress':40}
    payload.update(overrides)
    return client.post(f'/api/v1/tasks/{tid}/progress', json=payload)


def test_first_run_empty_and_preferences_available(client):
    assert client.get('/health').status_code == 200
    assert client.get('/api/v1/dashboard').json()['active_project'] is None
    assert client.get('/api/v1/projects').json() == []
    assert client.get('/api/v1/preferences').json()['warn_days'] == 3
    assert client.post('/api/v1/projects', json={'name':'', 'goal':'x','deadline':str(today())}).status_code == 422


def test_stage_aware_plan_and_short_deadline(client):
    pid = project(client, '实验验证')
    preview = client.post(f'/api/v1/projects/{pid}/plan', json={}).json()
    assert [item['stage'] for item in preview['project_plan']] == ['实验验证','结果总结']
    with database.connect() as con:
        con.execute('UPDATE projects SET deadline=? WHERE id=?',(str(today()),pid))
    preview = client.post(f'/api/v1/projects/{pid}/plan', json={}).json()
    assert len(preview['project_plan']) == 1
    assert preview['project_plan'][0]['deadline'] == str(today())


def test_edit_selection_exact_save_and_retry_without_generation(client, monkeypatch):
    pid = project(client)
    preview = client.post(f'/api/v1/projects/{pid}/plan', json={}).json()
    assert client.get('/api/v1/tasks').json() == []
    chosen = preview['project_plan'][:1]
    chosen[0].update(name='用户编辑的任务名称', deliverable='用户定义的结果表',priority='高')
    monkeypatch.setattr(main,'run_plan',lambda *_: (_ for _ in ()).throw(AssertionError('确认时不得重新生成')))
    body = {'confirm':True,'draft_id':preview['draft_id'],'items':chosen}
    first = client.post(f'/api/v1/projects/{pid}/plan', json=body).json()
    second = client.post(f'/api/v1/projects/{pid}/plan', json=body).json()
    tasks = client.get('/api/v1/tasks').json()
    assert first == second and len(tasks) == 1
    assert tasks[0]['name'] == chosen[0]['name'] and tasks[0]['deliverable'] == chosen[0]['deliverable']
    chosen[0]['name']='已保存后的新修改'
    assert client.post(f'/api/v1/projects/{pid}/plan',json=body).status_code==409


def test_draft_survives_reload_and_requires_correct_project(client):
    pid = project(client)
    preview = client.post(f'/api/v1/projects/{pid}/plan',json={}).json()
    assert client.get(f'/api/v1/projects/{pid}/plan-draft').json()['draft_id'] == preview['draft_id']
    other = project(client)
    assert client.post(f'/api/v1/projects/{other}/plan',json={'confirm':True,'draft_id':preview['draft_id']}).status_code == 409
    assert client.post(f'/api/v1/projects/{other}/plan',json={'confirm':True}).status_code == 409


def test_invalid_plan_dates_and_empty_selection_rejected(client):
    pid = project(client)
    preview = client.post(f'/api/v1/projects/{pid}/plan',json={}).json()
    item = preview['project_plan'][0]
    item['deadline'] = str(today()-timedelta(days=1))
    assert client.post(f'/api/v1/projects/{pid}/plan',json={'confirm':True,'draft_id':preview['draft_id'],'items':[item]}).status_code == 422
    assert client.post(f'/api/v1/projects/{pid}/plan',json={'confirm':True,'draft_id':preview['draft_id'],'items':[]}).status_code == 422
    assert client.get('/api/v1/tasks').json() == []


def test_progress_persists_updates_task_and_is_idempotent(client):
    tid = plan(client,project(client))[0]
    key = str(uuid4())
    first = progress(client,tid,client_token=key,status='已完成',progress=80)
    second = progress(client,tid,client_token=key,status='已完成',progress=80)
    assert first.status_code == 200 and second.json()['duplicate']
    task = client.get(f'/api/v1/tasks/{tid}').json()
    assert task['progress'] == 100 and task['completed_at'] == str(today()) and len(task['logs']) == 1
    assert progress(client,tid,client_token=key,result='内容改变').status_code == 409


def test_progress_validation_and_historical_backfill(client):
    tid = plan(client,project(client))[0]
    assert progress(client,tid,occurred_on=str(today()+timedelta(days=1))).status_code == 422
    assert progress(client,tid,status='遇到阻碍',blocker='').status_code == 422
    assert progress(client,tid,status='已完成',progress=100).status_code == 200
    assert progress(client,tid,occurred_on=str(today()-timedelta(days=3)),status='进行中',progress=20).status_code == 200
    task=client.get(f'/api/v1/tasks/{tid}').json()
    assert task['status'] == '已完成' and task['progress'] == 100 and len(task['logs']) == 2


def test_task_state_changes_are_report_evidence(client):
    pid=project(client)
    tid=plan(client,pid)[0]
    updated=client.put(f'/api/v1/tasks/{tid}',json={'status':'done'}).json()
    assert updated['status']=='已完成' and updated['progress']==100
    report=client.post(f'/api/v1/projects/{pid}/report',json={}).json()
    assert updated['name'] in report['report']['已完成工作'][0] and report['sources']


def test_blocked_risk_preview_confirmation_and_conflicts(client):
    pid=project(client)
    tid=plan(client,pid)[0]
    progress(client,tid,status='遇到阻碍',blocker='完整数据尚未拿到')
    warning=client.post(f'/api/v1/projects/{pid}/risk').json()['warnings'][0]
    assert warning['task_id']==tid and warning['actions']
    before=client.get(f'/api/v1/tasks/{tid}').json()
    preview=client.post(f'/api/v1/tasks/{tid}/risk-action',json={}).json()
    assert client.get(f'/api/v1/tasks/{tid}').json()['deadline']==before['deadline']
    body={'confirm':True,'draft_id':preview['draft_id']}
    assert client.post(f'/api/v1/tasks/{tid}/risk-action',json=body).json()['saved']
    assert client.post(f'/api/v1/tasks/{tid}/risk-action',json=body).status_code==200
    assert client.get(f'/api/v1/tasks/{tid}').json()['priority']=='高'


def test_stale_risk_suggestion_rejected(client):
    tid=plan(client,project(client))[0]
    preview=client.post(f'/api/v1/tasks/{tid}/risk-action',json={}).json()
    progress(client,tid,progress=75)
    assert client.post(f'/api/v1/tasks/{tid}/risk-action',json={'confirm':True,'draft_id':preview['draft_id']}).status_code==409


def test_overdue_tasks_remain_on_dashboard(client):
    tid=plan(client,project(client))[0]
    with database.connect() as con:
        con.execute('UPDATE tasks SET start_date=?,deadline=? WHERE id=?',(str(today()-timedelta(days=5)),str(today()-timedelta(days=1)),tid))
    dashboard=client.get('/api/v1/dashboard').json()
    assert tid in [task['id'] for task in dashboard['today_tasks']]
    assert '已逾期' in dashboard['risk']['warnings'][0]['reason']


def test_report_date_filter_custom_range_and_provenance(client):
    pid=project(client)
    tid=plan(client,pid)[0]
    old=today()-timedelta(days=20)
    progress(client,tid,occurred_on=str(old),result='旧日期专属实验结果',accomplishment='旧日期完成的检查')
    progress(client,tid,result='今日专属实验结果',accomplishment='今日完成的检查')
    report=client.post(f'/api/v1/projects/{pid}/report',json={'time_scope':'本周'}).json()
    assert '今日专属实验结果' in report['markdown'] and '旧日期专属实验结果' not in report['markdown']
    assert len(report['sources'])==1 and report['sources'][0]['task_id']==tid
    custom=client.post(f'/api/v1/projects/{pid}/report',json={'time_scope':'自定义','start_date':str(old),'end_date':str(old)}).json()
    assert '旧日期专属实验结果' in custom['markdown'] and '今日专属实验结果' not in custom['markdown']
    assert client.post(f'/api/v1/projects/{pid}/report',json={'time_scope':'自定义','start_date':str(today()),'end_date':str(old)}).status_code==422


def test_report_empty_period_is_explicit_and_no_invented_results(client):
    pid=project(client)
    plan(client,pid)
    report=client.post(f'/api/v1/projects/{pid}/report',json={}).json()
    assert report['evidence_count']==0 and '未录入实验结果' in report['markdown']
    assert '当前待办参考（截至生成时）' in report['markdown']


def test_report_save_exact_edits_retry_and_revision(client,monkeypatch):
    pid=project(client)
    tid=plan(client,pid)[0]
    progress(client,tid)
    preview=client.post(f'/api/v1/projects/{pid}/report',json={}).json()
    edited=preview['markdown']+'\n\n导师沟通：需要确认下一步实验范围。'
    monkeypatch.setattr(main,'build_report',lambda *_: (_ for _ in ()).throw(AssertionError('保存不得重新生成')))
    body={'save':True,'draft_id':preview['draft_id'],'markdown':edited}
    first=client.post(f'/api/v1/projects/{pid}/report',json=body).json()
    again=client.post(f'/api/v1/projects/{pid}/report',json=body).json()
    assert first==again and first['markdown']==edited
    history=client.get(f'/api/v1/projects/{pid}/reports').json()
    assert len(history)==1 and history[0]['content']==edited
    assert client.post(f'/api/v1/projects/{pid}/report',json={**body,'markdown':'重复请求中的不同内容'}).status_code==409
    revision=client.post(f"/api/v1/projects/{pid}/reports/{first['report_id']}/revision").json()
    saved=client.post(f'/api/v1/projects/{pid}/report',json={'save':True,'draft_id':revision['draft_id'],'markdown':'修改后的新版本'}).json()
    assert saved['report_id']!=first['report_id'] and len(client.get(f'/api/v1/projects/{pid}/reports').json())==2


def test_project_switch_preserves_preferences_and_isolates_records(client):
    pid=project(client)
    tid=plan(client,pid)[0]
    progress(client,tid)
    client.patch('/api/v1/preferences',json={'habit':'周五整理汇报'})
    other=project(client)
    assert client.get('/api/v1/tasks').json()==[]
    assert client.get('/api/v1/preferences').json()['habit']=='周五整理汇报'
    assert progress(client,tid).status_code==409
    assert client.get(f'/api/v1/tasks/{tid}').json()['project_status']=='archived'
    report=client.post(f'/api/v1/projects/{other}/report',json={}).json()
    assert report['sources']==[]
    client.post(f'/api/v1/projects/{pid}/activate')
    assert client.get(f'/api/v1/tasks/{tid}').json()['logs']


def test_demo_data_relative_dates_and_explicit_labels(client):
    response=client.post('/api/v1/demo-project').json()
    assert response['project_id']
    dashboard=client.get('/api/v1/dashboard').json()
    assert dashboard['active_project']['name'].startswith('示例')
    report=client.post(f"/api/v1/projects/{response['project_id']}/report",json={}).json()
    assert report['evidence_count']==2 and '示例' in report['markdown']


def test_chat_confirmation_uses_shared_draft_and_project_boundary(client):
    pid=project(client)
    preview=client.post('/api/chat',json={'session_id':'test','message':'帮我规划科研任务'}).json()
    assert preview['has_pending'] and preview['action']['project_id']==pid
    assert client.get('/api/v1/tasks').json()==[]
    saved=client.post('/api/chat/confirm',json={'session_id':'test','action':'confirm'}).json()
    assert saved['saved']
    preview=client.post('/api/chat',json={'session_id':'test','message':'帮我规划科研任务'}).json()
    project(client)
    assert client.post('/api/chat/confirm',json={'session_id':'test','action':'confirm'}).status_code==409


def test_literature_existing_validation_and_duplicate_guard(client):
    project(client)
    assert client.post('/api/v1/literatures/analyze-preview',json={'title':'空文献'}).status_code==422
    note={'title':'测试文献','abstract_excerpt':'研究工具调用失败。提出输出校验方法。'}
    assert client.post('/api/v1/literatures/analyze-preview',json=note).json()['temporary']
    assert client.post('/api/v1/literatures',json=note).status_code==200
    assert client.post('/api/v1/literatures',json=note).status_code==409


def test_database_upgrade_keeps_existing_records(client):
    pid=project(client)
    tid=plan(client,pid)[0]
    progress(client,tid)
    before=database.rows('SELECT * FROM tasks')
    database.init_db()
    assert database.rows('SELECT * FROM tasks')==before
    assert len(database.rows('SELECT * FROM task_logs'))==1


def test_new_evidence_invalidates_risk_even_if_percentage_is_unchanged(client):
    tid=plan(client,project(client))[0]
    progress(client,tid,progress=40)
    preview=client.post(f'/api/v1/tasks/{tid}/risk-action',json={}).json()
    progress(client,tid,progress=40,result='新增观察，完成比例不变')
    assert client.post(f'/api/v1/tasks/{tid}/risk-action',json={'confirm':True,'draft_id':preview['draft_id']}).status_code==409


def test_saved_latest_plan_does_not_restore_discarded_older_draft(client):
    pid=project(client)
    client.post(f'/api/v1/projects/{pid}/plan',json={})
    latest=client.post(f'/api/v1/projects/{pid}/plan',json={}).json()
    client.post(f'/api/v1/projects/{pid}/plan',json={'confirm':True,'draft_id':latest['draft_id']})
    assert client.get(f'/api/v1/projects/{pid}/plan-draft').json() is None


def test_previous_schema_migrates_without_removing_user_data(tmp_path,monkeypatch):
    import sqlite3
    path=tmp_path/'legacy.db'
    monkeypatch.setattr(database,'DB_PATH',path)
    with sqlite3.connect(path) as con:
        con.executescript(database.SCHEMA)
        con.execute("INSERT INTO users(id,username) VALUES(1,'legacy')")
        con.execute("INSERT INTO projects(id,name,goal,deadline) VALUES(1,'已有课题','保留原记录','2026-12-31')")
        con.execute("INSERT INTO tasks(project_id,name,description,start_date,deadline) VALUES(1,'已有任务','已有任务','2026-10-01','2026-12-01')")
        assert 'blocker' not in {field[1] for field in con.execute('PRAGMA table_info(tasks)')}
    database.init_db()
    task=database.row('SELECT * FROM tasks')
    assert task['name']=='已有任务' and task['blocker']=='' and task['completed_at'] is None

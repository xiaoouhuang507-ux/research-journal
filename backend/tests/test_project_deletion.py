import pytest

from app.database import connect, row, rows
from app.product_service import create_draft
from app.project_deletion import RELATED_TABLES
from app.schemas import local_today
from test_journal import project, message


def preview(client, pid):
    response = client.get(f'/api/v2/projects/{pid}/deletion-preview')
    assert response.status_code == 200, response.text
    return response.json()


def delete(client, pid, snapshot=None, **changes):
    snapshot = snapshot or preview(client, pid)
    body = {'confirmed': True, 'project_name': snapshot['name'], 'preview_token': snapshot['preview_token'], **changes}
    return client.request('DELETE', f'/api/v2/projects/{pid}', json=body)


def seed_legacy(pid):
    with connect() as con:
        task = con.execute("INSERT INTO tasks(project_id,name,description,start_date,deadline) VALUES(?,?,?,?,?)",
                           (pid, '旧版任务', '实验', str(local_today()), str(local_today()))).lastrowid
        con.execute("INSERT INTO task_logs(client_token,project_id,task_id,occurred_on,progress,status) VALUES(?,?,?,?,?,?)",
                    (f'legacy-{pid}', pid, task, str(local_today()), 20, '进行中'))
        con.execute("INSERT INTO literature_notes(project_id,title) VALUES(?,'旧版笔记')", (pid,))
        con.execute("INSERT INTO agent_memory(memory_type,content,project_id) VALUES('project','课题记忆',?)", (pid,))
    return task


def test_delete_archived_project_removes_all_dependents_and_preserves_other_project(client):
    pid = project(client, '同名课题')
    assert message(client, pid).status_code == 200
    draft = client.post(f'/api/v2/projects/{pid}/report', json={}).json()
    assert client.post(f'/api/v2/projects/{pid}/report', json={'save': True, 'draft_id': draft['draft_id'], 'markdown': '# 已核对'}).status_code == 200
    task_id = seed_legacy(pid)
    other = project(client, '同名课题')
    assert message(client, other, token='other-project-message').status_code == 200
    other_before = client.get(f'/api/v2/projects/{other}/conversation').json()
    reminder_before = row('SELECT * FROM reminder_settings')
    with connect() as con:
        con.execute("INSERT INTO agent_memory(memory_type,content) VALUES('habit','用户习惯')")
    snapshot = preview(client, pid)
    assert snapshot['is_current'] is False
    assert all(snapshot['counts'][table] == 1 for table in RELATED_TABLES if table != 'reference_documents')
    assert snapshot['counts']['reference_documents'] == 0
    result = delete(client, pid, snapshot)
    assert result.status_code == 200, result.text
    assert result.json()['task_ids'] == [task_id]
    assert result.json()['active_project']['id'] == other
    for table in RELATED_TABLES:
        assert rows(f'SELECT id FROM {table} WHERE project_id=?', (pid,)) == []
    assert client.get(f'/api/v2/projects/{pid}').status_code == 404
    assert client.get(f'/api/v2/projects/{pid}/conversation').status_code == 404
    assert client.post(f'/api/v2/projects/{pid}/report', json={'save': True, 'draft_id': draft['draft_id']}).status_code == 404
    assert client.get(f'/api/v2/projects/{other}/conversation').json() == other_before
    assert row('SELECT * FROM reminder_settings') == reminder_before
    assert row("SELECT content FROM agent_memory WHERE project_id IS NULL")['content'] == '用户习惯'
    with connect() as con:
        assert con.execute('PRAGMA foreign_key_check').fetchall() == []


def test_delete_current_switches_to_newest_remaining_and_last_delete_returns_empty_state(client):
    first = project(client, '课题一')
    second = project(client, '课题二')
    third = project(client, '课题三')
    snapshot = preview(client, third)
    assert snapshot['replacement'] == {'id': second, 'name': '课题二'}
    assert delete(client, third, snapshot).json()['active_project']['id'] == second
    assert client.get('/api/v2/home').json()['project']['id'] == second
    assert delete(client, second).json()['active_project']['id'] == first
    assert delete(client, first).json()['active_project'] is None
    assert client.get('/api/v2/projects').json() == []
    assert client.get('/api/v2/home').json()['project'] is None
    assert client.get(f'/api/v2/projects/{first}/deletion-preview').status_code == 404
    assert delete(client, first, snapshot).status_code == 404
    new_id = project(client, '重新开始')
    assert client.get('/api/v2/home').json()['project']['id'] == new_id


def test_delete_requires_explicit_confirmation_and_matching_project_snapshot(client):
    pid = project(client)
    snapshot = preview(client, pid)
    assert client.request('DELETE', f'/api/v2/projects/{pid}').status_code == 422
    assert delete(client, pid, snapshot, confirmed=False).status_code == 422
    assert delete(client, pid, snapshot, project_name='另一个课题').status_code == 409
    assert delete(client, pid, snapshot, preview_token='0' * 64).status_code == 409
    assert client.get(f'/api/v2/projects/{pid}').status_code == 200


@pytest.mark.parametrize('change', ['message', 'profile', 'report', 'replacement'])
def test_changed_data_requires_a_new_confirmation(client, change):
    pid = project(client)
    snapshot = preview(client, pid)
    if change == 'message':
        assert message(client, pid).status_code == 200
    elif change == 'profile':
        assert client.put(f'/api/v2/projects/{pid}', json={'name': snapshot['name'], 'topic': '修改后的主题', 'direction': '修改后的方向'}).status_code == 200
    elif change == 'report':
        assert client.post(f'/api/v2/projects/{pid}/report', json={}).status_code == 200
    else:
        project(client, '新增的当前课题')
    result = delete(client, pid, snapshot)
    assert result.status_code == 409
    assert client.get(f'/api/v2/projects/{pid}').status_code == 200
    assert delete(client, pid).status_code == 200


def test_pending_reply_blocks_deletion_until_it_finishes(client):
    pid = project(client)
    snapshot = preview(client, pid)
    with connect() as con:
        con.execute("INSERT INTO journal_turns(project_id,occurred_on,client_token,user_content) VALUES(?,?,?,'仍在回复')", (pid, str(local_today()), 'pending-reply-token'))
    assert client.get(f'/api/v2/projects/{pid}/deletion-preview').status_code == 409
    assert delete(client, pid, snapshot).status_code == 409
    with connect() as con:
        con.execute("UPDATE journal_turns SET status='complete',assistant_content='已回复' WHERE project_id=?", (pid,))
    assert delete(client, pid).status_code == 200


def test_failure_rolls_back_all_deletes(client):
    pid = project(client)
    seed_legacy(pid)
    snapshot = preview(client, pid)
    with connect() as con:
        con.execute("CREATE TRIGGER reject_project_deletion BEFORE DELETE ON projects BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    with pytest.raises(Exception, match='blocked'):
        delete(client, pid, snapshot)
    assert client.get(f'/api/v2/projects/{pid}').status_code == 200
    assert preview(client, pid)['counts'] == snapshot['counts']


def test_report_generation_after_concurrent_project_deletion_returns_not_found(client):
    pid = project(client)
    assert delete(client, pid).status_code == 200
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        create_draft(pid, 'report', {'markdown': '# 延迟的模型结果'})
    assert error.value.status_code == 404

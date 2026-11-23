"""Explicit, snapshot-confirmed deletion of one project and its dependent data."""
import hashlib
import json

from fastapi import HTTPException

from .database import connect


# Child records must be removed before their parent tasks and project.
RELATED_TABLES = ('task_logs', 'tasks', 'literature_notes', 'agent_memory',
                  'reports', 'drafts', 'project_references', 'reference_documents', 'journal_turns')


def _snapshot(con, project_id):
    project = con.execute('SELECT * FROM projects WHERE id=? AND user_id=1', (project_id,)).fetchone()
    if not project:
        raise HTTPException(404, '课题不存在，可能已经删除，请刷新课题列表')
    pending = con.execute("SELECT 1 FROM journal_turns WHERE project_id=? AND status='pending' AND updated_at > datetime('now','-90 seconds')", (project_id,)).fetchone()
    if pending:
        raise HTTPException(409, '该课题的 AI 正在回复，请等回复结束后再删除')
    records = {table: [dict(item) for item in con.execute(f"SELECT {'id,project_id,filename,title,sha256,page_count,readable_pages,char_count,warning,created_at' if table == 'reference_documents' else '*'} FROM {table} WHERE project_id=? ORDER BY id", (project_id,))]
               for table in RELATED_TABLES}
    replacement = None
    if project['status'] == 'active':
        next_project = con.execute('SELECT id,name FROM projects WHERE user_id=1 AND id<>? ORDER BY id DESC LIMIT 1', (project_id,)).fetchone()
        replacement = dict(next_project) if next_project else None
    snapshot = {'project': dict(project), 'records': records, 'replacement': replacement}
    token = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    return {'project_id': project_id, 'name': project['name'], 'is_current': project['status'] == 'active',
            'counts': {table: len(items) for table, items in records.items()},
            'replacement': replacement, 'preview_token': token}, [item['id'] for item in records['tasks']]


def preview(project_id):
    with connect() as con:
        con.execute('BEGIN')
        result, _ = _snapshot(con, project_id)
        return result


def delete(project_id, body):
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        snapshot, task_ids = _snapshot(con, project_id)
        if body.project_name != snapshot['name'] or body.preview_token != snapshot['preview_token']:
            raise HTTPException(409, '课题资料或记录已变化，请重新点击删除，核对最新内容后确认')
        for table in RELATED_TABLES:
            con.execute(f'DELETE FROM {table} WHERE project_id=?', (project_id,))
        con.execute('DELETE FROM projects WHERE id=?', (project_id,))
        if snapshot['replacement']:
            con.execute("UPDATE projects SET status='active' WHERE id=?", (snapshot['replacement']['id'],))
        active = con.execute("SELECT id,name FROM projects WHERE user_id=1 AND status='active'").fetchone()
        return {'ok': True, 'deleted_project_id': project_id, 'deleted_counts': snapshot['counts'],
                'task_ids': task_ids, 'active_project': dict(active) if active else None}

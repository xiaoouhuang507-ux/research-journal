"""Project-aware daily dialogue. User evidence is persisted before any model call."""
import json
from datetime import date
from fastapi import HTTPException
from . import llm_service, reference_service
from .database import connect, row, rows
from .product_service import require_project, date_range, today


def profile(project_id):
    project = require_project(project_id)
    project['direction'] = project['direction'] or project['goal']
    project['references'] = rows('SELECT * FROM project_references WHERE project_id=? ORDER BY id', (project_id,))
    for reference in project['references']:
        if reference.get('document_id'):
            reference['document'] = reference_service.document_metadata(reference['document_id'])
    return project


def write_project(body, project_id=None):
    data = body.model_dump()
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if project_id:
            if not con.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                raise HTTPException(404, '课题不存在')
            con.execute('UPDATE projects SET name=?,topic=?,direction=?,goal=? WHERE id=?',
                        (data['name'], data['topic'], data['direction'], data['direction'], project_id))
            con.execute('DELETE FROM project_references WHERE project_id=?', (project_id,))
        else:
            con.execute("UPDATE projects SET status='archived' WHERE status='active'")
            cur = con.execute("INSERT INTO projects(user_id,name,topic,direction,goal,deadline,status) VALUES(1,?,?,?,?,?,'active')",
                              (data['name'], data['topic'], data['direction'], data['direction'], '2099-12-31'))
            project_id = cur.lastrowid
        reference_service.attach(con, data['references'], project_id)
        for ref in data['references']:
            con.execute('INSERT INTO project_references(project_id,title,authors,year,url,notes,document_id) VALUES(?,?,?,?,?,?,?)',
                        (project_id, ref['title'], ref['authors'], ref['year'], ref['url'], ref['notes'], ref['document_id']))
        con.execute('DELETE FROM reference_documents WHERE project_id=? AND id NOT IN (SELECT document_id FROM project_references WHERE project_id=? AND document_id IS NOT NULL)', (project_id, project_id))
    return {'ok': True, 'project_id': project_id, 'project': profile(project_id)}


def conversation(project_id, occurred_on):
    project = profile(project_id)
    if occurred_on > today(): raise HTTPException(422, '不能查看未来日期的对话')
    turns = rows('SELECT * FROM journal_turns WHERE project_id=? AND occurred_on=? ORDER BY id', (project_id, str(occurred_on)))
    return {'project': project, 'date': str(occurred_on), 'turns': turns, 'ai_available': llm_service.enabled()}


def days(project_id):
    require_project(project_id)
    return rows('SELECT occurred_on,COUNT(*) AS turn_count,MIN(user_content) AS excerpt FROM journal_turns WHERE project_id=? GROUP BY occurred_on ORDER BY occurred_on DESC', (project_id,))


def basic_reply(project, message, history):
    if any(word in message for word in ('今天结束', '今天就到这', '不想继续', '明天再说', '先这样', '记录完了')):
        return '今天说到的内容已记录。下次可以继续告诉我新的进展，辛苦了。'
    if any(word in message for word in ('卡住', '失败', '报错', '阻碍', '没准备', '未准备', '无法')):
        question = '具体卡在哪一步？有没有报错信息，或已经尝试过的处理办法？'
    elif any(word in message for word in ('准确率', 'F1', '指标', '结果', '提升')):
        question = '这个观察对应什么数据和实验设置？目前有没有可以比较的基线结果？'
    elif any(word in message for word in ('实验', '代码', '运行', '调试', '模型')):
        question = '今天具体跑通了哪一步，观察到什么现象或结果？尚未跑完也可以直接说明。'
    elif any(word in message for word in ('论文', '文献', '阅读')):
        title = project['references'][0]['title'] if project['references'] else '今天读的文献'
        question = f'是参考文献《{title}》吗？其中哪种方法或发现，对你当前的研究方向有帮助？' if project['references'] else '读的是哪篇文献？其中哪种方法或发现，对你当前的研究方向有帮助？'
    elif any(word in message for word in ('没做', '休息', '没有进展')):
        question = '今天是安排休息，还是被某个问题影响了进度？没有新成果也可以记录。'
    elif history:
        question = '这一步对当前课题带来了什么具体变化？还有哪一点需要在组会上请教老师？'
    else:
        question = '今天具体推进了哪件事，目前做到什么程度？'
    return f'已记下你刚才说的内容。围绕“{project["topic"]}”，{question}'


def send_message(project_id, body):
    project = profile(project_id)
    require_project(project_id, active=True)
    day = str(body.occurred_on)
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        current = con.execute('SELECT status FROM projects WHERE id=?', (project_id,)).fetchone()
        if not current: raise HTTPException(404, '课题已删除，请返回课题列表')
        if current['status'] != 'active': raise HTTPException(409, '课题已切换，请回到当前课题再操作')
        existing = con.execute('SELECT * FROM journal_turns WHERE client_token=?', (body.client_token,)).fetchone()
        if existing and (existing['project_id'] != project_id or existing['user_content'] != body.message or existing['occurred_on'] != day):
            raise HTTPException(409, '这条消息已经提交过不同的内容，请刷新对话后重新发送')
        if existing and existing['status'] == 'complete':
            return dict(existing)
        pending = con.execute("SELECT id FROM journal_turns WHERE project_id=? AND status='pending' AND updated_at > datetime('now','-90 seconds')", (project_id,)).fetchone()
        if pending: raise HTTPException(409, '上一条消息正在回复，请稍后重试')
        if existing:
            turn_id = existing['id']
            con.execute("UPDATE journal_turns SET status='pending',updated_at=CURRENT_TIMESTAMP WHERE id=?", (turn_id,))
        else:
            cur = con.execute('INSERT INTO journal_turns(project_id,occurred_on,client_token,user_content) VALUES(?,?,?,?)',
                              (project_id, day, body.client_token, body.message))
            turn_id = cur.lastrowid
    history = rows("SELECT id,occurred_on,user_content,assistant_content FROM journal_turns WHERE project_id=? AND id<? AND occurred_on<=? ORDER BY occurred_on DESC,id DESC LIMIT 20", (project_id, turn_id, day))[::-1]
    for turn in history:
        recorded_day = date.fromisoformat(turn['occurred_on'])
        # Anchor to the selected journal date, including backfills, rather than
        # insertion time or the immediately preceding conversation turn.
        turn['days_before_current'] = (body.occurred_on - recorded_day).days
        turn['record_date_label'] = f'{recorded_day.year}年{recorded_day.month}月{recorded_day.day}日'
    # Read uploaded PDFs from this project only, with page-aware bounded excerpts.
    reference_query = body.message + '\n' + '\n'.join(t['user_content'][-1000:] for t in history[-2:])
    context = {'project': {'name': project['name'], 'topic': project['topic'], 'direction': project['direction'],
                           'references': reference_service.chat_references(project, reference_query)},
               'history': history, 'date': day, 'latest_user_message': body.message}
    mode = 'model' if llm_service.enabled() else 'basic'
    generated = llm_service.invoke_json('daily_dialogue', context)
    reply = generated.get('reply') if isinstance(generated, dict) else None
    if not isinstance(reply, str) or not reply.strip() or len(reply) > 5000:
        if mode == 'model':
            with connect() as con:
                con.execute("UPDATE journal_turns SET status='failed',updated_at=CURRENT_TIMESTAMP WHERE id=?", (turn_id,))
            raise HTTPException(503, '你的内容已保存，但 AI 暂时未能回复。请点击“重试 AI 回复”，无需重新输入。')
        reply = basic_reply(project, body.message, history)
    with connect() as con:
        updated = con.execute("UPDATE journal_turns SET assistant_content=?,ai_mode=?,status='complete',updated_at=CURRENT_TIMESTAMP WHERE id=?", (reply.strip(), mode, turn_id))
        if not updated.rowcount: raise HTTPException(404, '课题已删除，请返回课题列表')
    return row('SELECT * FROM journal_turns WHERE id=?', (turn_id,))


def dialogue_report(project_id, scope, start, end):
    project = profile(project_id)
    begin, finish = date_range(scope, start, end)
    turns = rows('SELECT * FROM journal_turns WHERE project_id=? AND occurred_on BETWEEN ? AND ? ORDER BY occurred_on,id', (project_id, begin, finish))
    sources = [{'kind': 'conversation', 'id': t['id'], 'date': t['occurred_on'], 'title': '每日科研对话',
                'excerpt': t['user_content'], 'assistant_content': t['assistant_content'] or ''} for t in turns]
    evidence = [{'id': t['id'], 'date': t['occurred_on'], 'content': t['user_content']} for t in turns]
    sections = {name: [] for name in ('研究进展', '结果与观察', '问题与阻碍', '后续计划', '待确认事项')}
    generated = None
    if evidence and len(json.dumps(evidence, ensure_ascii=False)) <= 28000:
        generated = llm_service.invoke_json('dialogue_report', {'project': {'name': project['name'], 'topic': project['topic'], 'direction': project['direction']}, 'start_date': begin, 'end_date': finish, 'evidence': evidence})
    valid = isinstance(generated, dict) and isinstance(generated.get('sections'), dict)
    ids = {t['id'] for t in turns}
    used = set()
    if valid:
        for title in sections:
            items = generated['sections'].get(title, [])
            if not isinstance(items, list): valid = False; break
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
                    valid = False; break
                refs = item.get('source_ids')
                if not isinstance(refs, list) or not refs or any(type(i) is not int or i not in ids for i in refs):
                    valid = False; break
                used.update(refs)
                sections[title].append(f"{item['text']}（对话 {', '.join('#' + str(i) for i in refs)}）")
    if not used: valid = False
    mode = 'model' if valid else 'source'
    markdown = f"# 组会汇报\n\n课题：{project['name']}\n\n主题：{project['topic']}\n\n研究方向：{project['direction']}\n\n汇报时间：{begin} 至 {finish}\n\n"
    if valid:
        markdown += '\n\n'.join('## ' + title + '\n' + '\n'.join('- ' + item for item in items or ['本期对话中未明确说明，待补充。']) for title, items in sections.items())
    else:
        markdown += '## 本期科研记录\n'
        markdown += '\n'.join(f"- {s['date']}：{s['excerpt']}（对话 #{s['id']}）" for s in sources) or '- 所选日期内没有科研对话，请先记录或调整日期。'
        markdown += '\n\n## 待确认事项\n- 请核对上述记录中的实际进展、实验结果、阻碍和后续计划；未明确说明的内容未作推测。'
    return {'ok': True, 'temporary': True, 'scope': scope, 'start_date': begin, 'end_date': finish,
            'markdown': markdown, 'sources': sources, 'evidence_count': len(sources), 'ai_mode': mode,
            'limitation': '仅以所选日期内该课题的用户发言为依据。AI 的追问与建议不算作已完成成果。' + ('本次由 AI 归纳，请核对后保存。' if valid else '本次按原始对话整理，尚未进行 AI 归纳。')}


def home():
    current = row("SELECT id FROM projects WHERE status='active'")
    project = profile(current['id']) if current else None
    if not project: return {'project': None, 'ai_available': llm_service.enabled(), 'days': [], 'today_turns': 0, 'recorded_days': 0}
    records = days(project['id'])
    count = row('SELECT COUNT(*) AS n FROM journal_turns WHERE project_id=? AND occurred_on=?', (project['id'], str(today())))['n']
    return {'project': project, 'ai_available': llm_service.enabled(), 'days': records[:7], 'today_turns': count, 'recorded_days': len(records)}

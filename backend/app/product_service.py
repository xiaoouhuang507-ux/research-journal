"""Draft confirmation, dated research evidence and actionable task risks."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from .database import connect, row, rows
from .schemas import PlanItem


def today():
    return datetime.now(timezone(timedelta(hours=8))).date()


def require_project(project_id, active=False):
    project = row("SELECT * FROM projects WHERE id=?", (project_id,))
    if not project:
        raise HTTPException(404, "课题不存在")
    if active and project["status"] != "active":
        raise HTTPException(409, "课题已切换，请回到当前课题再操作")
    return project


def create_draft(project_id, kind, payload):
    draft_id = str(uuid4())
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if not con.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
            raise HTTPException(404, '课题已删除，请返回课题列表')
        con.execute("INSERT INTO drafts(id,project_id,kind,payload) VALUES(?,?,?,?)",
                    (draft_id, project_id, kind, json.dumps(payload, ensure_ascii=False)))
    return {**payload, "draft_id": draft_id}


def load_draft(draft_id, project_id, kind):
    draft = row("SELECT * FROM drafts WHERE id=? AND project_id=? AND kind=?", (draft_id, project_id, kind))
    if not draft:
        raise HTTPException(409, "请先生成预览，再确认保存")
    return draft, json.loads(draft["payload"])


def insert_tasks(con, project_id, items):
    ids = []
    for item in items:
        cur = con.execute(
            "INSERT INTO tasks(project_id,stage,name,description,start_date,deadline,priority,status,progress,deliverable,acceptance_criteria,conflict_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, item["stage"], item["name"], item.get("description", ""), item["start_date"],
             item["deadline"], item.get("priority", "中"), "未开始", 0, item.get("deliverable", ""),
             item.get("acceptance_criteria", ""), "存在时间重叠，请核对可投入时间" if item.get("conflicts") else ""))
        ids.append(cur.lastrowid)
    return ids


def save_plan(project_id, draft_id, items=None):
    project = require_project(project_id, active=True)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        draft = con.execute("SELECT * FROM drafts WHERE id=? AND project_id=? AND kind='plan'", (draft_id, project_id)).fetchone()
        if not draft:
            raise HTTPException(409, "请先生成计划预览")
        if draft["saved_result"]:
            saved = json.loads(draft["saved_result"])
            if items is not None:
                normalized = [PlanItem.model_validate(item).model_dump(mode='json') for item in items]
                if normalized != saved['project_plan']:
                    raise HTTPException(409, '该草稿已经保存，任务内容已改变。请在任务详情中继续修改。')
            return saved
        payload = json.loads(draft["payload"])
        original = items if items is not None else payload["project_plan"]
        try:
            validated = [PlanItem.model_validate(x).model_dump(mode="json") for x in original]
        except ValueError as exc:
            raise HTTPException(422, "请检查任务名称、阶段和日期") from exc
        if not validated:
            raise HTTPException(422, "请至少保留一项任务")
        for item in validated:
            if item["deadline"] > project["deadline"]:
                raise HTTPException(422, "任务截止日期不能晚于课题截止日期")
        ids = insert_tasks(con, project_id, validated)
        result = {"ok": True, "saved": True, "draft_id": draft_id, "project_plan": validated, "task_ids": ids}
        con.execute("UPDATE drafts SET payload=?,saved_result=? WHERE id=?",
                    (json.dumps({**payload, "project_plan": validated}, ensure_ascii=False), json.dumps(result, ensure_ascii=False), draft_id))
    return result


def require_task(task_id):
    task = row("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


def record_progress(task_id, payload):
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT * FROM task_logs WHERE client_token=?", (payload["client_token"],)).fetchone()
        if existing:
            if existing["task_id"] != task_id:
                raise HTTPException(409, "记录标识已被其他任务使用，请重新提交")
            comparable = {**payload, 'progress':100 if payload['status']=='已完成' else payload['progress']}
            if any(existing[key] != comparable[key] for key in ('occurred_on','accomplishment','result','blocker','next_step','progress','status')):
                raise HTTPException(409, "该记录已保存，内容已发生变化，请重新打开任务后记录新的进展")
            return {"ok": True, "log": dict(existing), "duplicate": True}
        current = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not current:
            raise HTTPException(404, "任务不存在")
        project = con.execute("SELECT status FROM projects WHERE id=?", (current["project_id"],)).fetchone()
        if project["status"] != "active":
            raise HTTPException(409, "课题已切换，请回到当前课题再操作")
        last = con.execute("SELECT MAX(occurred_on) FROM task_logs WHERE task_id=?", (task_id,)).fetchone()[0]
        status = payload["status"]
        progress = 100 if status == "已完成" else payload["progress"]
        changed = current["status"] != status
        cur = con.execute(
            "INSERT INTO task_logs(client_token,project_id,task_id,occurred_on,accomplishment,result,blocker,next_step,progress,status,status_changed) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (payload["client_token"], current["project_id"], task_id, payload["occurred_on"],
             payload.get("accomplishment", ""), payload.get("result", ""), payload.get("blocker", ""),
             payload.get("next_step", ""), progress, status, int(changed and (not last or payload["occurred_on"] >= last))))
        # A historical backfill is evidence; it must not roll the current task state back.
        if not last or payload["occurred_on"] >= last:
            completed_at = payload["occurred_on"] if status == "已完成" and changed else current["completed_at"]
            if status != "已完成":
                completed_at = None
            con.execute("UPDATE tasks SET status=?,progress=?,blocker=?,completed_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (status, progress, payload.get("blocker", ""), completed_at, task_id))
        result = dict(con.execute("SELECT * FROM task_logs WHERE id=?", (cur.lastrowid,)).fetchone())
    return {"ok": True, "log": result, "duplicate": False}


def date_range(scope, start=None, end=None):
    current = today()
    if scope == "自定义":
        if not start or not end:
            raise HTTPException(422, "请选择汇报开始和结束日期")
        begin, finish = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    elif scope == "本周":
        begin, finish = current - timedelta(days=current.weekday()), current
    elif scope == "近两周":
        begin, finish = current - timedelta(days=13), current
    elif scope == "本月":
        begin, finish = current.replace(day=1), current
    else:
        raise HTTPException(422, "请选择本周、近两周、本月或自定义范围")
    if finish < begin or finish > current:
        raise HTTPException(422, "结束日期须介于开始日期和今天之间")
    return str(begin), str(finish)


def build_report(project_id, scope="本周", start=None, end=None):
    project = require_project(project_id)
    begin, finish = date_range(scope, start, end)
    logs = rows("SELECT l.*,t.name AS task_name FROM task_logs l JOIN tasks t ON t.id=l.task_id WHERE l.project_id=? AND l.occurred_on BETWEEN ? AND ? ORDER BY l.occurred_on,l.id", (project_id, begin, finish))
    notes = rows("SELECT * FROM literature_notes WHERE project_id=? AND date(created_at,'+8 hours') BETWEEN ? AND ? ORDER BY created_at,id", (project_id, begin, finish))
    sources, completed, advances, results, problems, next_steps = [], [], [], [], [], []
    for log in logs:
        source = f"记录 #{log['id']} · {log['occurred_on']} · {log['task_name']}"
        sources.append({"kind": "progress", "id": log["id"], "task_id": log["task_id"], "date": log["occurred_on"], "title": log["task_name"], "accomplishment": log["accomplishment"], "result": log["result"], "blocker": log["blocker"], "next_step": log["next_step"]})
        if log["status"] == "已完成" and log["status_changed"]:
            completed.append(f"{log['task_name']}（{source}）")
        for key, target in (("accomplishment", advances), ("result", results), ("blocker", problems), ("next_step", next_steps)):
            if log[key]:
                target.append(f"{log[key]}（{source}）")
    literature = []
    for note in notes:
        sources.append({"kind": "literature", "id": note["id"], "date": note["created_at"][:10], "title": note["title"], "excerpt": note["abstract_excerpt"]})
        literature.append(f"{note['title']}：{note['relation'] or note['reference_idea'] or note['summary']}（文献 #{note['id']}）")
    # Current backlog is explicitly separated from historical evidence.
    upcoming = rows("SELECT id,name,deadline FROM tasks WHERE project_id=? AND status NOT IN ('已完成','done') ORDER BY deadline,id LIMIT 3", (project_id,))
    report = {
        "已完成工作": completed or ["所选时间内没有任务完成记录"],
        "研究进展": advances or ["所选时间内尚未记录研究进展"],
        "实验结果": results or ["所选时间内未录入实验结果，不做推测"],
        "期间问题与阻碍": problems or ["所选时间内未记录具体问题"],
        "记录中的下一步": next_steps or ["所选时间内未记录下一步安排"],
        "文献启发": literature or ["所选时间内没有新增文献笔记"],
        "当前待办参考（截至生成时）": [f"{task['name']} · 截止 {task['deadline']}（任务 #{task['id']}）" for task in upcoming] or ["暂无未完成任务"],
    }
    markdown = f"# 科研阶段汇报\n\n课题：{project['name']}\n\n汇报范围：{begin} 至 {finish}\n\n"
    markdown += "\n\n".join("## " + title + "\n" + "\n".join(f"- {line}" for line in content) for title, content in report.items())
    return {"ok": True, "temporary": True, "scope": scope, "start_date": begin, "end_date": finish, "report": report, "markdown": markdown, "sources": sources, "evidence_count": len(sources), "limitation": "历史进展仅依据所选日期内的记录；当前待办单独展示。未录入的结果不会被推测。旧任务需补充进展记录才能计入期间成果。"}


def save_report(project_id, draft_id, markdown, active=True):
    require_project(project_id, active=active)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        draft = con.execute("SELECT * FROM drafts WHERE id=? AND project_id=? AND kind='report'", (draft_id, project_id)).fetchone()
        if not draft:
            raise HTTPException(409, "请先生成汇报草稿")
        if draft["saved_result"]:
            saved = json.loads(draft["saved_result"])
            if markdown is not None and markdown != saved['markdown']:
                raise HTTPException(409, '该草稿已经保存。请从历史汇报中选择“编辑为新版本”。')
            return saved
        payload = json.loads(draft["payload"])
        text = markdown if markdown is not None else payload["markdown"]
        if not text.strip():
            raise HTTPException(422, "汇报内容不能为空")
        cur = con.execute("INSERT INTO reports(project_id,time_scope,content,start_date,end_date,sources) VALUES(?,?,?,?,?,?)",
                          (project_id, payload["scope"], text, payload["start_date"], payload["end_date"], json.dumps(payload["sources"], ensure_ascii=False)))
        result = {**payload, "temporary": False, "draft_id": draft_id, "report_id": cur.lastrowid, "markdown": text}
        con.execute("UPDATE drafts SET saved_result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), draft_id))
    return result


def risk_preview(task_id, deadline=None, priority="高"):
    task = require_task(task_id)
    require_project(task["project_id"], active=True)
    if task["status"] == "已完成":
        raise HTTPException(409, "任务已完成，无需调整")
    project = require_project(task["project_id"])
    proposed = str(deadline) if deadline else max(str(today() + timedelta(days=3)), task["deadline"])
    proposed = min(proposed, project["deadline"]) if not deadline else proposed
    if proposed < str(today()) or proposed < task["start_date"] or proposed > project["deadline"]:
        raise HTTPException(422, "调整后的截止日期须不早于今天和任务开始日，且不晚于课题截止日")
    conflicts = rows("SELECT id,name,deadline FROM tasks WHERE project_id=? AND id!=? AND status!='已完成' AND start_date<=? AND deadline>=?", (task["project_id"], task_id, proposed, task["start_date"]))
    before = {key: task[key] for key in ("deadline", "priority", "status", "progress", "blocker", "updated_at")}
    last_log_id = row('SELECT MAX(id) AS id FROM task_logs WHERE task_id=?', (task_id,))['id']
    return create_draft(task["project_id"], "risk", {"ok": True, "task_id": task_id, "before": before, "last_log_id":last_log_id, "after": {"deadline": proposed, "priority": priority}, "conflicts": conflicts, "reason": "先核对阻碍和可交付范围，再调整当前任务；其他任务保持原有安排。", "requires_confirmation": True})


def confirm_risk(task_id, draft_id):
    task = require_task(task_id)
    require_project(task["project_id"], active=True)
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        draft = con.execute("SELECT * FROM drafts WHERE id=? AND project_id=? AND kind='risk'", (draft_id, task["project_id"])).fetchone()
        if not draft:
            raise HTTPException(409, "请先预览调整建议")
        payload = json.loads(draft["payload"])
        if payload["task_id"] != task_id:
            raise HTTPException(409, "该建议不属于当前任务")
        if draft["saved_result"]:
            return json.loads(draft["saved_result"])
        current = dict(con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
        last_log_id = con.execute('SELECT MAX(id) FROM task_logs WHERE task_id=?', (task_id,)).fetchone()[0]
        if last_log_id != payload.get('last_log_id') or any(current[key] != value for key, value in payload["before"].items()):
            raise HTTPException(409, "任务已有新进展，请重新预览调整建议")
        after = payload["after"]
        con.execute("UPDATE tasks SET deadline=?,priority=?,conflict_note='',updated_at=CURRENT_TIMESTAMP WHERE id=?", (after["deadline"], after["priority"], task_id))
        result = {"ok": True, "saved": True, "task_id": task_id, "after": after}
        con.execute("UPDATE drafts SET saved_result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), draft_id))
    return result


def create_demo_project():
    current = today()
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE projects SET status='archived' WHERE status='active'")
        cur = con.execute("INSERT INTO projects(user_id,name,topic,goal,deadline,stage,background,status) VALUES(1,?,?,?,?,?,?,'active')",
                          ("示例｜Agent 工具调用可靠性研究", "Agent 工具调用可靠性", "完成基线实验，对比重试与输出校验策略", str(current + timedelta(days=28)), "实验验证", "示例数据，仅用于演示，不代表真实科研成果"))
        pid = cur.lastrowid
        specs = [("整理基线错误类型", "已完成", 100, -1), ("运行小样本基线实验", "遇到阻碍", 30, 1), ("完成输出校验对照实验", "未开始", 0, 5)]
        for name, status, progress, delta in specs:
            cur = con.execute("INSERT INTO tasks(project_id,stage,name,description,start_date,deadline,priority,status,progress,deliverable,acceptance_criteria,blocker,completed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (pid, "实验验证", name, "演示任务，可修改内容和时间", str(current - timedelta(days=3)), str(current + timedelta(days=delta)), "高", status, progress, "实验记录与结果表", "记录数据范围、参数和观察结果", "示例：完整数据集暂未准备好" if status == "遇到阻碍" else "", str(current) if status == "已完成" else None))
            tid = cur.lastrowid
            if status != "未开始":
                con.execute("INSERT INTO task_logs(client_token,project_id,task_id,occurred_on,accomplishment,result,blocker,next_step,progress,status,status_changed) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (str(uuid4()), pid, tid, str(current), "示例：整理了现有调用失败记录" if status == "已完成" else "示例：完成小样本环境检查", "示例：观察到参数格式不一致，尚无定量结论" if status == "已完成" else "", "示例：完整数据集暂未准备好" if status == "遇到阻碍" else "", "先验证小样本流程", progress, status, 1))
    return {"ok": True, "project_id": pid, "message": "示例课题已创建，原课题资料保留在课题列表中"}

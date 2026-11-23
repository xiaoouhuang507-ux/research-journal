from contextlib import asynccontextmanager
import asyncio
from contextlib import suppress
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from uuid import uuid4
from .agent import chat, confirm
from .database import connect, init_db, row, rows
from .graph import run_plan, run_report, run_risk
from .schemas import ChatRequest, ConfirmRequest, NoteCreate, PlanRequest, ProjectCreate, ReportRequest, TaskPatch, UserCreate, ProgressCreate, RiskAction
from .tools import NORMALIZE_STATUS, active_project, analyze_literature, check_task_warning, parse_date, persist_plan, save_literature_note
from .product_service import (build_report, confirm_risk, create_demo_project, create_draft,
                              record_progress, require_project, require_task, risk_preview,
                              save_plan, save_report, today)
from .journal_api import router as journal_router
from .reminder_service import scheduler
from .pdf_upload_limit import PDFUploadLimit

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    reminder_task = asyncio.create_task(scheduler())
    try:
        yield
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError): await reminder_task

app=FastAPI(title="科研日记 API",version="3.0.0",description="课题资料 → 每日 AI 对话 → 按日期生成组会汇报")
app.include_router(journal_router)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
app.add_middleware(PDFUploadLimit)
app.router.lifespan_context=lifespan

@app.get("/health")
def health(): return {"status":"ok","version":"3.0.0","workflow":"daily-dialogue","features":["research_projects","references","pdf_references","daily_dialogue","daily_reminder","conversation_reports","project_deletion"]}

@app.post("/api/chat")
@app.post("/api/v1/chat")
def api_chat(body:ChatRequest): return chat(body.session_id,body.message)

@app.post("/api/chat/confirm")
@app.post("/api/v1/chat/confirm")
def api_confirm(body:ConfirmRequest): return confirm(body.session_id,body.action)

@app.post("/api/v1/users")
def create_user(body:UserCreate):
    try:
        with connect() as con:
            cur=con.execute("INSERT INTO users(username) VALUES(?)",(body.username,))
            return {"user_id":cur.lastrowid}
    except Exception as exc:
        raise HTTPException(409,"用户名已存在") from exc

@app.get("/api/projects")
@app.get("/api/v1/projects")
def projects(include_archived:bool=True,user_id:int=1):
    sql="SELECT * FROM projects WHERE user_id=?"+("" if include_archived else " AND status='active'")+" ORDER BY created_at DESC"
    return rows(sql,(user_id,))

@app.post("/api/projects")
@app.post("/api/v1/projects")
def create_project(body:ProjectCreate):
    if not parse_date(body.deadline): raise HTTPException(422,"截止日期须为 YYYY-MM-DD")
    if body.deadline < str(today()): raise HTTPException(422,"课题截止日期不能早于今天")
    if not body.goal.strip(): raise HTTPException(422,"请填写课题目标")
    title=body.name or body.title
    if not title.strip(): raise HTTPException(422,"请填写课题名称")
    with connect() as con:
        if not con.execute("SELECT 1 FROM users WHERE id=?",(body.user_id,)).fetchone(): raise HTTPException(404,"用户不存在")
        con.execute("UPDATE projects SET status='archived' WHERE user_id=? AND status='active'",(body.user_id,))
        cur=con.execute("INSERT INTO projects(user_id,name,topic,background,goal,deadline,stage,status) VALUES(?,?,?,?,?,?,?,'active')",(body.user_id,title,body.topic or title,body.background,body.goal,body.deadline,body.stage))
        return {"ok":True,"project_id":cur.lastrowid,"message":"新课题已激活，原课题已归档"}

@app.post("/api/projects/{project_id}/activate")
@app.post("/api/v1/projects/{project_id}/activate")
def activate_project(project_id:int):
    project=row("SELECT * FROM projects WHERE id=?",(project_id,))
    if not project: raise HTTPException(404,"课题不存在")
    with connect() as con:
        con.execute("UPDATE projects SET status='archived' WHERE user_id=? AND status='active'",(project["user_id"],))
        con.execute("UPDATE projects SET status='active' WHERE id=?",(project_id,))
    return {"ok":True,"message":"已显式调取并激活归档课题"}

@app.post("/api/projects/{project_id}/plan")
@app.post("/api/v1/projects/{project_id}/plan")
def plan_project(project_id:int,body:PlanRequest=PlanRequest()):
    require_project(project_id, active=True)
    if body.confirm:
        return save_plan(project_id,body.draft_id,[item.model_dump(mode='json') for item in body.items] if body.items is not None else None)
    state=run_plan(project_id)
    if state.get("error"): raise HTTPException(404,state["error"])
    result=state["plan"]
    if not result.get("ok"): raise HTTPException(422,result)
    for item in result['project_plan']:
        item['priority'] = body.priority
    return create_draft(project_id,'plan',{**result,"saved":False,"message":"可编辑预览；确认后保存当前这份计划"})


@app.get('/api/v1/projects/{project_id}/plan-draft')
def latest_plan_draft(project_id:int):
    require_project(project_id, active=True)
    import json
    draft=row("SELECT * FROM drafts WHERE project_id=? AND kind='plan' ORDER BY rowid DESC LIMIT 1",(project_id,))
    return {**json.loads(draft['payload']),'draft_id':draft['id']} if draft and not draft['saved_result'] else None


@app.post('/api/v1/demo-project')
def demo_project():
    return create_demo_project()

@app.get("/api/tasks")
@app.get("/api/v1/tasks")
def tasks(project_id:Optional[int]=None,status:Optional[str]=None):
    p=row("SELECT * FROM projects WHERE id=?",(project_id,)) if project_id else active_project()
    if not p:return []
    sql="SELECT * FROM tasks WHERE project_id=?"; params=[p["id"]]
    if status: sql+=" AND status=?"; params.append(NORMALIZE_STATUS.get(status,status))
    return rows(sql+" ORDER BY deadline,id",tuple(params))

def _update_task(task_id:int,body:TaskPatch):
    current=row("SELECT * FROM tasks WHERE id=?",(task_id,))
    if not current: raise HTTPException(404,"任务不存在")
    project = require_project(current['project_id'],active=True)
    data=body.model_dump(exclude_none=True)
    if "status" in data: data["status"]=NORMALIZE_STATUS.get(data["status"],data["status"])
    if data.get("status")=="已完成": data["progress"]=100
    if data.get('name') is not None and not data['name'].strip(): raise HTTPException(422,'任务名称不能为空')
    start, end = data.get('start_date',current['start_date']), data.get('deadline',current['deadline'])
    if not parse_date(start) or not parse_date(end) or start>end: raise HTTPException(422,"请检查任务起止日期")
    if end>project['deadline']: raise HTTPException(422,'任务截止日期不能晚于课题截止日期')
    new_status=data.get('status',current['status'])
    if new_status=='遇到阻碍' and not current['blocker']: raise HTTPException(422,'请在进展记录中说明遇到的阻碍')
    if new_status!='遇到阻碍' and 'status' in data: data['blocker']=''
    state_changed = new_status != current['status']
    if state_changed:
        data['completed_at'] = str(today()) if new_status=='已完成' else None
    if data:
        data["updated_at"]="CURRENT_TIMESTAMP"
        sets=[]; values=[]
        for k,v in data.items():
            if k=="updated_at": sets.append("updated_at=CURRENT_TIMESTAMP")
            else: sets.append(f"{k}=?"); values.append(v)
        with connect() as con:
            con.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?",(*values,task_id))
            if state_changed or ('progress' in data and data['progress']!=current['progress']):
                con.execute('INSERT INTO task_logs(client_token,project_id,task_id,occurred_on,accomplishment,progress,status,status_changed) VALUES(?,?,?,?,?,?,?,?)',
                            (str(uuid4()),current['project_id'],task_id,str(today()),f"任务状态更新为{new_status}",data.get('progress',current['progress']),new_status,int(state_changed)))
    return row("SELECT * FROM tasks WHERE id=?",(task_id,))

@app.patch("/api/tasks/{task_id}")
@app.patch("/api/v1/tasks/{task_id}")
@app.put("/api/v1/tasks/{task_id}")
def update_task(task_id:int,body:TaskPatch): return _update_task(task_id,body)

@app.get("/api/notes")
@app.get("/api/v1/literatures")
def notes(project_id:Optional[int]=None):
    p=row("SELECT * FROM projects WHERE id=?",(project_id,)) if project_id else active_project()
    return [] if not p else rows("SELECT * FROM literature_notes WHERE project_id=? ORDER BY created_at DESC",(p["id"],))

@app.post("/api/notes")
@app.post("/api/v1/literatures")
def add_note(body:NoteCreate):
    if body.project_id:
        p=row("SELECT * FROM projects WHERE id=?",(body.project_id,))
        if not p or p["status"]!="active": raise HTTPException(400,"只能向当前激活课题保存文献")
    result=save_literature_note(body.model_dump())
    if not result["ok"]: raise HTTPException(409 if result.get("code")=="DUPLICATE_NOTE" else 400,detail=result)
    return result

@app.post("/api/v1/literatures/analyze-preview")
def literature_preview(body:NoteCreate):
    result=analyze_literature(body.model_dump())
    if not result["ok"]: raise HTTPException(422,result)
    return {**result,"temporary":True,"message":"分析仅为预览，尚未写入数据库"}

@app.post("/api/v1/literatures/{note_id}/analyze")
def analyze_saved_literature(note_id:int):
    note=row("SELECT * FROM literature_notes WHERE id=?",(note_id,))
    if not note: raise HTTPException(404,"文献不存在")
    return {"note_id":note_id,"summary":note["summary"],"innovation":note["innovation"],"relation":note["relation"]}

@app.get("/api/warnings")
def warnings(): return check_task_warning()

@app.post("/api/projects/{project_id}/risk")
@app.post("/api/v1/projects/{project_id}/risk")
def project_risk(project_id:int):
    state=run_risk(project_id)
    if state.get("error"): raise HTTPException(404,state["error"])
    return state["risk"]

@app.post("/api/projects/{project_id}/report")
@app.post("/api/v1/projects/{project_id}/report")
def project_report(project_id:int,body:ReportRequest=ReportRequest()):
    if body.save:
        return save_report(project_id,body.draft_id,body.markdown)
    require_project(project_id,active=True)
    result=build_report(project_id,body.time_scope,body.start_date,body.end_date)
    return create_draft(project_id,'report',result)

@app.get("/api/v1/projects/{project_id}/reports")
def saved_reports(project_id:int):
    require_project(project_id)
    return rows("SELECT * FROM reports WHERE project_id=? ORDER BY id DESC",(project_id,))


@app.post('/api/v1/projects/{project_id}/reports/{report_id}/revision')
def revise_report(project_id:int, report_id:int):
    import json
    require_project(project_id,active=True)
    report=row('SELECT * FROM reports WHERE id=? AND project_id=?',(report_id,project_id))
    if not report: raise HTTPException(404,'汇报不存在')
    return create_draft(project_id,'report',{'ok':True,'temporary':True,'scope':report['time_scope'],
        'start_date':report['start_date'],'end_date':report['end_date'],'markdown':report['content'],
        'sources':json.loads(report['sources']),'limitation':'此版本基于历史汇报编辑，保留原有来源和汇报日期。'})


@app.get('/api/v1/tasks/{task_id}')
def task_detail(task_id:int):
    task=require_task(task_id)
    project=require_project(task['project_id'])
    return {**task,'project_name':project['name'],'project_status':project['status'],'project_deadline':project['deadline'],
            'logs':rows('SELECT * FROM task_logs WHERE task_id=? ORDER BY occurred_on DESC,id DESC',(task_id,))}


@app.post('/api/v1/tasks/{task_id}/progress')
def add_progress(task_id:int,body:ProgressCreate):
    return record_progress(task_id,body.model_dump(mode='json'))


@app.post('/api/v1/tasks/{task_id}/risk-action')
def task_risk_action(task_id:int,body:RiskAction):
    if body.confirm:
        return confirm_risk(task_id,body.draft_id)
    return risk_preview(task_id,body.deadline,body.priority)

@app.get("/api/dashboard")
@app.get("/api/v1/dashboard")
def dashboard():
    p=active_project()
    if not p:return {"active_project":None,"completion_rate":0,"today_tasks":[],"risk":{"level":"LOW","warnings":[]}}
    ts=tasks(p["id"]); done=len([t for t in ts if t["status"]=="已完成"])
    current=str(today())
    due=[t for t in ts if t['start_date']<=current and t['status']!='已完成']
    due.sort(key=lambda t:(0 if t['status']=='遇到阻碍' else 1,t['deadline'],0 if t['priority']=='高' else 1))
    return {"active_project":p,"completion_rate":round(done/len(ts)*100) if ts else 0,"today_tasks":due[:3],"risk":check_task_warning(p["id"]),"task_count":len(ts),"done_count":done,'recent_logs':rows('SELECT l.*,t.name AS task_name FROM task_logs l JOIN tasks t ON t.id=l.task_id WHERE l.project_id=? ORDER BY l.occurred_on DESC,l.id DESC LIMIT 3',(p['id'],))}

@app.get("/api/preferences")
@app.get("/api/v1/preferences")
def preferences(): return row("SELECT * FROM preferences WHERE id=1")

@app.patch("/api/preferences")
@app.patch("/api/v1/preferences")
def update_preferences(payload:dict):
    allowed={k:v for k,v in payload.items() if k in {"user_identity","research_interest","strengths","weaknesses","habit","warn_days"}}
    if "warn_days" in allowed and not 0<=int(allowed["warn_days"])<=30: raise HTTPException(422,"提醒天数范围为0-30")
    if allowed:
        with connect() as con: con.execute(f"UPDATE preferences SET {','.join(k+'=?' for k in allowed)} WHERE id=1",tuple(allowed.values()))
    return preferences()


from datetime import date
from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from . import journal_service as journal, reminder_service as reminder, project_deletion, reference_service
import json
from .database import row, rows
from fastapi import HTTPException
from .journal_schemas import ResearchProject, ProjectDeletion, DailyMessage, ReminderPreferences, WechatLogin, Subscription
from .product_service import create_draft, save_report
from .schemas import ReportRequest, local_today
from .llm_service import connection_check

router = APIRouter(prefix='/api/v2', tags=['每日科研对话'])


@router.post('/references/pdf')
async def upload_reference(file: UploadFile = File(...), filename: str = Form('')):
    try:
        data = await file.read(reference_service.MAX_PDF_BYTES + 1)
        return await run_in_threadpool(reference_service.store_upload, data, filename or file.filename)
    finally:
        await file.close()


@router.get('/references/pdf/{document_id}')
def download_reference(document_id: str):
    doc = row('SELECT pdf_data FROM reference_documents WHERE id=?', (document_id,))
    if not doc:
        raise HTTPException(404, 'PDF 不存在或已移除，请重新打开课题资料')
    return Response(bytes(doc['pdf_data']), media_type='application/pdf',
                    headers={'Content-Disposition': 'inline; filename="reference.pdf"', 'Cache-Control': 'no-store'})


@router.post('/ai/check')
def check_ai(): return connection_check()


@router.get('/home')
def home(): return {**journal.home(), 'reminder': reminder.preferences()}


@router.get('/projects')
def projects():
    return [journal.profile(p['id']) for p in rows("SELECT id FROM projects WHERE user_id=1 ORDER BY status='active' DESC,id DESC")]


@router.post('/projects')
def create_project(body: ResearchProject): return journal.write_project(body)


@router.get('/projects/{project_id}')
def project(project_id: int): return journal.profile(project_id)


@router.put('/projects/{project_id}')
def update_project(project_id: int, body: ResearchProject): return journal.write_project(body, project_id)


@router.get('/projects/{project_id}/deletion-preview')
def deletion_preview(project_id: int): return project_deletion.preview(project_id)


@router.delete('/projects/{project_id}')
def delete_project(project_id: int, body: ProjectDeletion): return project_deletion.delete(project_id, body)


@router.get('/projects/{project_id}/days')
def days(project_id: int): return journal.days(project_id)


@router.get('/projects/{project_id}/conversation')
def conversation(project_id: int, occurred_on: date = None): return journal.conversation(project_id, occurred_on or local_today())


@router.post('/projects/{project_id}/conversation')
def send(project_id: int, body: DailyMessage): return journal.send_message(project_id, body)


@router.post('/projects/{project_id}/report')
def report(project_id: int, body: ReportRequest):
    if body.save: return save_report(project_id, body.draft_id, body.markdown, active=False)
    return create_draft(project_id, 'report', journal.dialogue_report(project_id, body.time_scope, body.start_date, body.end_date))


@router.post('/projects/{project_id}/reports/{report_id}/revision')
def revision(project_id: int, report_id: int):
    journal.profile(project_id)
    saved = row('SELECT * FROM reports WHERE id=? AND project_id=?', (report_id, project_id))
    if not saved: raise HTTPException(404, '汇报不存在')
    return create_draft(project_id, 'report', {'ok': True, 'temporary': True, 'scope': saved['time_scope'],
        'start_date': saved['start_date'], 'end_date': saved['end_date'], 'markdown': saved['content'],
        'sources': json.loads(saved['sources']), 'limitation': '基于历史汇报编辑的新版本，保留原始日期与对话来源。'})


@router.get('/reminder')
def settings(): return reminder.preferences()


@router.put('/reminder')
def update_reminder(body: ReminderPreferences): return reminder.update(body)


@router.post('/reminder/claim')
def foreground(): return reminder.claim_foreground()


@router.post('/reminder/wechat-login')
def login(body: WechatLogin): return reminder.link_wechat(body.code)


@router.post('/reminder/subscribe')
def subscribe(body: Subscription): return reminder.subscribe(body)

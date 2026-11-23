"""PDF staging, project ownership and bounded page-aware retrieval for daily chat."""
import hashlib
import json
import re
import subprocess
import sys
import threading
import unicodedata
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from .database import connect, row

MAX_PDF_BYTES = 10 * 1024 * 1024
PARSERS = threading.BoundedSemaphore(2)
METADATA = 'id,project_id,filename,title,sha256,page_count,readable_pages,char_count,warning'


def store_upload(data, filename):
    filename = unicodedata.normalize('NFC', (filename or '').replace('\\', '/').split('/')[-1])
    filename = ''.join(c for c in filename if c.isprintable())[:200]
    if not filename.lower().endswith('.pdf') or not data.startswith(b'%PDF-'):
        raise HTTPException(422, '请选择有效的 PDF 文件，修改扩展名不能转换文件格式。')
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, 'PDF 不能超过 10 MB，请压缩或拆分后上传。')
    if not PARSERS.acquire(blocking=False):
        raise HTTPException(429, '正在处理其他 PDF，请稍后再试。')
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('pdf_extract.py'))],
                                input=data, capture_output=True, timeout=25,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        parsed = json.loads(result.stdout.decode('utf-8'))
    except subprocess.TimeoutExpired:
        raise HTTPException(422, 'PDF 解析超时，请重新导出 PDF 或拆分后再试。')
    except Exception:
        raise HTTPException(422, '未能解析 PDF，请重新导出后再试。')
    finally:
        PARSERS.release()
    if parsed.get('error'):
        raise HTTPException(422, parsed['error'])
    document_id = uuid4().hex
    title = parsed.get('title') or Path(filename).stem
    with connect() as con:
        # Unattached uploads are form drafts, retained for seven days only.
        con.execute("DELETE FROM reference_documents WHERE project_id IS NULL AND created_at < datetime('now','-7 days')")
        con.execute('INSERT INTO reference_documents(id,filename,title,sha256,page_count,readable_pages,char_count,warning,pages_json,pdf_data) VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (document_id, filename, title[:500], hashlib.sha256(data).hexdigest(), parsed['page_count'],
                     parsed['readable_pages'], parsed['char_count'], parsed['warning'], json.dumps(parsed['pages'], ensure_ascii=False), data))
    return {'title': title[:500], 'authors': '', 'year': '', 'url': '', 'notes': '',
            'document_id': document_id, 'document': document_metadata(document_id)}


def document_metadata(document_id):
    return row(f'SELECT {METADATA} FROM reference_documents WHERE id=?', (document_id,))


def attach(con, references, project_id):
    ids = [r['document_id'] for r in references if r.get('document_id')]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, '同一份 PDF 只需添加一次，请移除重复文献。')
    for document_id in ids:
        doc = con.execute('SELECT project_id FROM reference_documents WHERE id=?', (document_id,)).fetchone()
        if not doc:
            raise HTTPException(422, 'PDF 上传草稿已失效，请移除该文献后重新上传 PDF。')
        if doc['project_id'] not in (None, project_id):
            raise HTTPException(409, '这份 PDF 属于其他课题，请在当前课题重新上传。')
        con.execute('UPDATE reference_documents SET project_id=? WHERE id=?', (project_id, document_id))


def terms(text):
    text = text.lower()
    english = re.findall(r'[a-z0-9]{2,}', text)
    chinese = re.findall(r'[\u4e00-\u9fff]+', text)
    return set(english + [word[i:i+2] for word in chinese for i in range(len(word)-1)])


def chat_references(project, query):
    """Original pages remain intact; only selected excerpts are sent to the model."""
    query_terms = terms(query)
    result, remaining, note_budget = [], 18000, 6000
    ranked = sorted(enumerate(project['references']), key=lambda pair: (-len(terms(pair[1]['title']) & query_terms), pair[0]))
    pdf_count = 0
    for _, reference in ranked:
        item = {key: reference[key] for key in ('title', 'authors', 'year')}
        item['notes'] = reference['notes'][:min(note_budget, 2000)]
        note_budget -= len(item['notes'])
        if not reference.get('document_id'):
            item['source_type'] = 'user_notes'
            result.append(item)
            continue
        item['source_type'] = 'pdf_text'
        doc = row('SELECT pages_json,page_count,readable_pages,warning FROM reference_documents WHERE id=? AND project_id=?', (reference['document_id'], project['id']))
        if not doc:
            item['reading_status'] = 'PDF 正文不可用，不得声称已经阅读。'
            result.append(item)
            continue
        item.update(page_count=doc['page_count'], readable_pages=doc['readable_pages'], warning=doc['warning'])
        pages = json.loads(doc['pages_json'])
        chunks = [{'page': p['page'], 'text': p['text'][start:start+1600], 'offset': start}
                  for p in pages for start in range(0, len(p['text']), 1400)]
        if pdf_count >= 6 or remaining < 500:
            item['reading_status'] = '本轮未提供正文，用户可指明文献标题后再分析。'
            result.append(item)
            continue
        pdf_count += 1
        # Title matching happens first; methods/conclusion pages also help broad paper questions.
        def score(chunk):
            relevant = len(terms(chunk['text']) & query_terms)
            section = bool(re.search(r'(?i)abstract|introduction|method|conclusion|摘要|引言|方法|结论', chunk['text']))
            return relevant * 3 + int(section) * 2 + int(chunk['page'] == pages[0]['page'])
        ordered = sorted(chunks, key=lambda chunk: (-score(chunk), chunk['page'], chunk['offset']))
        budget = min(remaining, 14000 if len(ranked) == 1 else 9000)
        selected = []
        for chunk in ordered:
            if budget <= 0:
                break
            excerpt = chunk['text'][:budget]
            selected.append({**chunk, 'text': excerpt})
            budget -= len(excerpt)
            remaining -= len(excerpt)
        item['excerpts'] = sorted(selected, key=lambda chunk: (chunk['page'], chunk['offset']))
        item['reading_status'] = '依据可提取的 PDF 相关段落分析；未提供的页面和图表不得推测。'
        result.append(item)
    return result

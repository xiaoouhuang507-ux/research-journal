import io
import json

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app import journal_service, reference_service
from app.database import row, rows, connect
from app.schemas import local_today


def pdf_bytes(texts=None, title='Reference Pipeline Test Paper', encrypted=False):
    writer = PdfWriter()
    for text in texts or ['Abstract: AnchorBridge selects features using anchors. It addresses missing view information.']:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(('BT /F1 12 Tf 50 700 Td (' + escaped + ') Tj ET').encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    if title:
        writer.add_metadata({'/Title': title})
    if encrypted:
        writer.encrypt('test-password')
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def upload(client, data=None, name='paper.pdf'):
    return client.post('/api/v2/references/pdf', files={'file': (name, data if data is not None else pdf_bytes(), 'application/pdf')})


def profile_body(reference, name='PDF 课题'):
    return {'name': name, 'topic': '特征选择', 'direction': '研究缺失视图与锚点表示', 'references': [reference]}


def create(client, reference, name='PDF 课题'):
    result = client.post('/api/v2/projects', json=profile_body(reference, name))
    assert result.status_code == 200, result.text
    return result.json()['project_id']


def test_upload_extract_save_reload_and_download_without_notes(client):
    data = pdf_bytes()
    response = upload(client, data)
    assert response.status_code == 200, response.text
    reference = response.json()
    assert reference['title'] == 'Reference Pipeline Test Paper'
    assert reference['notes'] == ''
    assert reference['document']['readable_pages'] == reference['document']['page_count'] == 1
    pid = create(client, reference)
    loaded = client.get(f'/api/v2/projects/{pid}').json()['references'][0]
    assert loaded['document_id'] == reference['document_id']
    assert loaded['document']['project_id'] == pid
    assert 'pdf_data' not in loaded['document'] and 'pages_json' not in loaded['document']
    assert client.get('/api/v2/references/pdf/' + loaded['document_id']).content == data
    assert client.put(f'/api/v2/projects/{pid}', json=profile_body(loaded)).status_code == 200
    assert row('SELECT COUNT(*) AS n FROM reference_documents')['n'] == 1


def test_chat_model_receives_pdf_text_page_and_no_other_project(client, monkeypatch):
    first = upload(client, pdf_bytes(['Abstract: ProjectOneSecret is a test method for missing views.'])).json()
    create(client, first, '课题一')
    second = upload(client, pdf_bytes(['Abstract: AnchorBridge addresses incomplete views.', 'Method: Build anchors first. Then propagate reliable feature weights.'])).json()
    pid = create(client, second, '课题二')
    captured = []
    monkeypatch.setattr(journal_service.llm_service, 'enabled', lambda: True)
    def invoke(name, payload):
        captured.append(payload)
        return {'reply': 'AnchorBridge 先建锚点再传播权重（第 2 页）。你打算如何验证？'}
    monkeypatch.setattr(journal_service.llm_service, 'invoke_json', invoke)
    result = client.post(f'/api/v2/projects/{pid}/conversation', json={'message': '分析上传论文的方法', 'client_token': 'pdf-chat-message', 'occurred_on': str(local_today())})
    assert result.status_code == 200, result.text
    refs = captured[0]['project']['references']
    assert refs[0]['source_type'] == 'pdf_text' and refs[0]['notes'] == ''
    assert any(e['page'] == 2 and 'propagate' in e['text'] for e in refs[0]['excerpts'])
    assert 'ProjectOneSecret' not in json.dumps(captured)


def test_pdf_is_background_not_report_achievement(client):
    pid = create(client, upload(client).json())
    report = client.post(f'/api/v2/projects/{pid}/report', json={}).json()
    assert report['evidence_count'] == 0 and report['sources'] == []
    assert 'AnchorBridge' not in report['markdown']


def test_invalid_scan_encryption_partial_and_file_limits(client):
    assert upload(client, b'not pdf').status_code == 422
    assert upload(client, name='paper.txt').status_code == 422
    assert upload(client, b'%PDF-broken').status_code == 422
    scan = upload(client, pdf_bytes([' ']))
    assert scan.status_code == 422 and '扫描版' in scan.json()['detail']
    encrypted = upload(client, pdf_bytes(encrypted=True))
    assert encrypted.status_code == 422 and '加密' in encrypted.json()['detail']
    partial = upload(client, pdf_bytes(['Abstract: Readable content with enough text to extract.', ' '])).json()
    assert partial['document']['page_count'] == 2 and partial['document']['readable_pages'] == 1
    assert '2' in partial['document']['warning']
    many_pages = upload(client, pdf_bytes(['Valid text for each page.'] * 81))
    assert many_pages.status_code == 422 and '80' in many_pages.json()['detail']
    too_large = client.post('/api/v2/references/pdf', content=b'x', headers={'Content-Length': str(11 * 1024 * 1024)})
    assert too_large.status_code == 413
    assert upload(client, b'%PDF-' + b'x' * (10 * 1024 * 1024)).status_code == 413


def test_parser_timeout_does_not_add_document(client, monkeypatch):
    import subprocess
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('pdf', 25)
    monkeypatch.setattr(reference_service.subprocess, 'run', timeout)
    result = upload(client)
    assert result.status_code == 422 and '超时' in result.json()['detail']
    assert rows('SELECT id FROM reference_documents') == []


def test_cross_project_binding_duplicate_and_expired_upload_roll_back(client):
    ref = upload(client).json()
    pid = create(client, ref)
    assert client.post('/api/v2/projects', json=profile_body(ref, '另一个课题')).status_code == 409
    assert len(rows('SELECT id FROM projects')) == 1
    assert row('SELECT status FROM projects WHERE id=?', (pid,))['status'] == 'active'
    duplicate = profile_body(ref)
    duplicate['references'].append(ref)
    assert client.put(f'/api/v2/projects/{pid}', json=duplicate).status_code == 422
    expired = {**ref, 'document_id': '0' * 32}
    assert client.put(f'/api/v2/projects/{pid}', json=profile_body(expired)).status_code == 422
    assert client.get(f'/api/v2/projects/{pid}').json()['references'][0]['document_id'] == ref['document_id']


def test_remove_reference_and_delete_project_clean_pdf_without_touching_others(client):
    ref = upload(client).json()
    pid = create(client, ref)
    other = upload(client).json()
    other_pid = create(client, other, '保留课题')
    body = profile_body(ref)
    body['references'] = []
    assert client.put(f'/api/v2/projects/{pid}', json=body).status_code == 200
    assert client.get('/api/v2/references/pdf/' + ref['document_id']).status_code == 404
    preview = client.get(f'/api/v2/projects/{other_pid}/deletion-preview').json()
    assert preview['counts']['reference_documents'] == 1
    assert client.get('/api/v2/references/pdf/' + other['document_id']).status_code == 200
    deleted = client.request('DELETE', f'/api/v2/projects/{other_pid}', json={'confirmed': True, 'project_name': preview['name'], 'preview_token': preview['preview_token']})
    assert deleted.status_code == 200, deleted.text
    assert client.get('/api/v2/references/pdf/' + other['document_id']).status_code == 404
    assert client.get(f'/api/v2/projects/{pid}').status_code == 200


def test_retrieval_is_bounded_and_selects_late_relevant_pages(client):
    ref = upload(client).json()
    pid = create(client, ref)
    pages = [{'page': i, 'text': ('Generic background description. ' * 300) + (' UniqueTargetMechanism uses anchors.' if i == 20 else '')} for i in range(1, 21)]
    with connect() as con:
        con.execute('UPDATE reference_documents SET pages_json=? WHERE id=?', (json.dumps(pages), ref['document_id']))
    context = reference_service.chat_references(journal_service.profile(pid), 'UniqueTargetMechanism')
    excerpts = context[0]['excerpts']
    assert sum(len(e['text']) for e in excerpts) <= 18000
    assert any(e['page'] == 20 and 'UniqueTargetMechanism' in e['text'] for e in excerpts)


def test_title_fallback_and_filename_sanitizing(client):
    result = upload(client, pdf_bytes(['First readable paper title without metadata. Further method details.'], title=''), name='../paper.pdf').json()
    assert result['title'].startswith('First readable')
    assert result['document']['filename'] == 'paper.pdf'

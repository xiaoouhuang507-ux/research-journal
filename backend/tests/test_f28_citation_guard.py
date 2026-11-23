"""F28: controlled model outputs against isolated project/date evidence."""
from datetime import timedelta

import pytest

from app import llm_service
from app.schemas import local_today


@pytest.mark.parametrize('case', [
    'nonexistent_id', 'other_project_id', 'outside_date_range_id', 'mixed_valid_and_invalid',
])
def test_f28_rejects_invalid_citations_and_recovers(client, monkeypatch, case):
    """Use the real report API and validation; replace only model responses."""
    today = str(local_today())
    yesterday = str(local_today() - timedelta(days=1))

    def create_project(name):
        response = client.post('/api/v2/projects', json={
            'name': name, 'topic': 'F28 引用边界验证',
            'direction': '验证汇报仅使用所选课题及日期内的用户发言', 'references': [],
        })
        assert response.status_code == 200, response.text
        return response.json()['project_id']

    def record(pid, content, day, token):
        response = client.post(f'/api/v2/projects/{pid}/conversation', json={
            'message': content, 'occurred_on': day, 'client_token': token,
        })
        assert response.status_code == 200, response.text
        return response.json()

    project_a = create_project('F28 测试课题 A')
    old = record(project_a, 'F28_日期外记录：昨天安装了环境。', yesterday, 'f28-history')
    actual_content = 'F28_范围内记录：今天检查了20条样本，尚未训练，没有实验指标。'
    actual = record(project_a, actual_content, today, 'f28-current')
    project_b = create_project('F28 测试课题 B')
    foreign = record(project_b, 'F28_其他课题记录：准确率88%，禁止进入课题A。', today, 'f28-foreign')
    bad_ids = {
        'nonexistent_id': [999999],
        'other_project_id': [foreign['id']],
        'outside_date_range_id': [old['id']],
        'mixed_valid_and_invalid': [actual['id'], 999999],
    }
    invented = 'F28_非法模型结论：模型声称已完成训练，准确率99%。'
    captured = []

    def invalid_report(prompt, payload):
        assert prompt == 'dialogue_report'
        captured.append(payload)
        return {'sections': {'结果与观察': [{'text': invented, 'source_ids': bad_ids[case]}]}}

    monkeypatch.setattr(llm_service, 'invoke_json', invalid_report)
    body = {'time_scope': '自定义', 'start_date': today, 'end_date': today}
    rejected = client.post(f'/api/v2/projects/{project_a}/report', json=body)
    assert rejected.status_code == 200, rejected.text
    fallback = rejected.json()
    assert captured[0]['evidence'] == [{'id': actual['id'], 'date': today, 'content': actual_content}]
    assert fallback['ai_mode'] == 'source'
    assert '本次按原始对话整理，尚未进行 AI 归纳。' in fallback['limitation']
    assert fallback['evidence_count'] == 1
    assert [source['id'] for source in fallback['sources']] == [actual['id']]
    assert actual_content in fallback['markdown']
    for forbidden in (invented, '999999', 'F28_日期外记录', 'F28_其他课题记录', '准确率88%'):
        assert forbidden not in fallback['markdown']

    # A later successful generation must work without deleting or rewriting records.
    verified = '今天检查了20条样本，尚未训练，没有实验指标。'

    def valid_report(prompt, payload):
        assert prompt == 'dialogue_report'
        return {'sections': {'研究进展': [{'text': verified, 'source_ids': [actual['id']]}]}}

    monkeypatch.setattr(llm_service, 'invoke_json', valid_report)
    recovered = client.post(f'/api/v2/projects/{project_a}/report', json=body)
    assert recovered.status_code == 200, recovered.text
    draft = recovered.json()
    assert draft['ai_mode'] == 'model'
    assert verified in draft['markdown']
    assert f"对话 #{actual['id']}" in draft['markdown']
    assert [source['id'] for source in draft['sources']] == [actual['id']]
    saved = client.post(f'/api/v2/projects/{project_a}/report', json={
        'save': True, 'draft_id': draft['draft_id'], 'markdown': draft['markdown'],
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()['markdown'] == draft['markdown']
    history = client.get(f'/api/v1/projects/{project_a}/reports')
    assert history.status_code == 200, history.text
    assert any(item['id'] == saved.json()['report_id'] for item in history.json())
    assert len(client.get(f'/api/v2/projects/{project_a}/conversation?occurred_on={today}').json()['turns']) == 1
    assert len(client.get(f'/api/v2/projects/{project_b}/conversation?occurred_on={today}').json()['turns']) == 1

"""Date grounding uses the selected journal day, including backfilled records."""
import json
from datetime import date

import pytest

from app import journal_schemas, journal_service
from test_journal import message, project


@pytest.mark.parametrize('history_day,current_day,days_before,date_label', [
    ('2026-10-23', '2026-10-25', 2, '2026年10月23日'),
    ('2026-10-24', '2026-10-25', 1, '2026年10月24日'),
    ('2026-10-25', '2026-10-25', 0, '2026年10月25日'),
    ('2026-09-30', '2026-10-01', 1, '2026年9月30日'),
    ('2025-12-31', '2026-01-01', 1, '2025年12月31日'),
    ('2024-02-28', '2024-03-01', 2, '2024年2月28日'),
])
def test_history_dates_are_grounded_before_calling_model(
        client, monkeypatch, history_day, current_day, days_before, date_label):
    monkeypatch.setattr(journal_schemas, 'local_today', lambda: date(2026, 10, 25))
    pid = project(client)
    historical = message(client, pid, '今天发现两条样本缺失标签，尚未处理',
                         day=history_day, token='historical-date-record')
    assert historical.status_code == 200, historical.text
    calls = []

    def invoke(messages):
        calls.append(messages)
        return json.dumps({'reply': '已记下今天的处理。你准备如何核对填补后的标签？'}, ensure_ascii=False)

    monkeypatch.setattr(journal_service.llm_service, 'enabled', lambda: True)
    monkeypatch.setattr(journal_service.llm_service, 'invoke_messages', invoke)
    response = message(client, pid, '今天使用标签相关性进行了标签填补',
                       day=current_day, token='current-date-record')
    assert response.status_code == 200, response.text
    system, user = calls[0][0][1], calls[0][1][1]
    payload = json.JSONDecoder().raw_decode(user)[0]
    assert payload['date'] == current_day
    turn = payload['history'][0]
    assert turn['occurred_on'] == history_day
    assert turn['days_before_current'] == days_before
    assert turn['record_date_label'] == date_label
    # Keep source wording intact; recorded day is not necessarily the event day.
    assert turn['user_content'] == '今天发现两条样本缺失标签，尚未处理'
    assert '跨日期' in system and '绝对日期' in system
    assert '上一条' in system and '昨天' in system


def test_backfill_excludes_later_days_and_keeps_relative_source_wording(client, monkeypatch):
    monkeypatch.setattr(journal_schemas, 'local_today', lambda: date(2026, 10, 25))
    pid = project(client)
    assert message(client, pid, '昨天发现了缺失标签，今天仅核对标注来源',
                   day='2026-10-23', token='backfill-earlier-record').status_code == 200
    assert message(client, pid, '25号才完成标签填补',
                   day='2026-10-25', token='backfill-later-record').status_code == 200
    calls = []

    def invoke(messages):
        calls.append(messages)
        return json.dumps({'reply': '已记下24日的检查，尚未填补标签。'}, ensure_ascii=False)

    monkeypatch.setattr(journal_service.llm_service, 'enabled', lambda: True)
    monkeypatch.setattr(journal_service.llm_service, 'invoke_messages', invoke)
    response = message(client, pid, '补记24号：再次核对标注，还没有填补标签',
                       day='2026-10-24', token='backfill-current-record')
    assert response.status_code == 200, response.text
    payload = json.JSONDecoder().raw_decode(calls[0][1][1])[0]
    assert payload['date'] == '2026-10-24'
    assert len(payload['history']) == 1
    turn = payload['history'][0]
    assert turn['occurred_on'] == '2026-10-23'
    assert turn['days_before_current'] == 1  # Relative to the selected 24th, not the real 25th.
    assert turn['user_content'] == '昨天发现了缺失标签，今天仅核对标注来源'
    assert '25号才完成标签填补' not in json.dumps(payload, ensure_ascii=False)
    assert '记录日期' in calls[0][0][1]

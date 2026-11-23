"""Isolated PDF parser. Receives bytes on stdin, never executes embedded PDF actions."""
import io
import json
import re
import sys

from pypdf import PdfReader

MAX_PAGES = 80
MAX_TEXT = 600000


def extract(data):
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            return {'error': 'PDF 已加密，请先解除密码后重新上传。'}
        total = len(reader.pages)
        if total == 0 or total > MAX_PAGES:
            return {'error': '请上传 1 至 80 页的论文 PDF；较长资料请拆分后上传。'}
        pages, warnings, char_count = [], [], 0
        for number, page in enumerate(reader.pages, 1):
            try:
                content = page.get_contents()
                if content and len(content.get_data()) > 8 * 1024 * 1024:
                    warnings.append(number)
                    continue
                text = (page.extract_text() or '').replace('\x00', '')
                text = re.sub(r'[ \t]+', ' ', text)
                text = re.sub(r'\n{3,}', '\n\n', text).strip()
                # A nearly empty image page is not evidence of successful reading.
                if len(re.sub(r'\s', '', text)) < 20:
                    warnings.append(number)
                    continue
                if char_count + len(text) > MAX_TEXT:
                    return {'error': 'PDF 可提取文字过多，请拆分后上传。'}
                pages.append({'page': number, 'text': text})
                char_count += len(text)
            except Exception:
                warnings.append(number)
        if not pages:
            return {'error': '未能读取 PDF 正文，可能是扫描版或文字不可识别。请上传可选中文字的 PDF，或先进行 OCR 识别。'}
        metadata_title = str((reader.metadata or {}).get('/Title', '')).strip()
        if not (4 <= len(metadata_title) <= 500) or re.search(r'(?i)^(untitled|microsoft|word|latex|template|document)', metadata_title):
            first_lines = pages[0]['text'].splitlines()[:12]
            metadata_title = next((line.strip() for line in first_lines if 10 <= len(line.strip()) <= 200 and not re.match(r'(?i)^(arxiv|doi|https?://|proceedings|copyright|www\.)', line.strip())), '')
        return {'title': metadata_title, 'page_count': total, 'readable_pages': len(pages),
                'char_count': char_count, 'pages': pages,
                'warning': ('第 ' + '、'.join(map(str, warnings)) + ' 页文字未能完整读取。' if warnings else '') + '图片、复杂公式和表格可能不完整；分析时请核对原文页码。'}
    except Exception:
        return {'error': 'PDF 文件损坏或格式无法解析，请用 PDF 阅读器重新导出后上传。'}


if __name__ == '__main__':
    result = extract(sys.stdin.buffer.read(10 * 1024 * 1024 + 1))
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode('utf-8'))

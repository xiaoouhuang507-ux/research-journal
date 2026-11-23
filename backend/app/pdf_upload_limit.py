"""Bound multipart input before it reaches the form parser, including chunked uploads."""
import asyncio
from starlette.responses import JSONResponse
from .reference_service import MAX_PDF_BYTES


class PDFUploadLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] != '/api/v2/references/pdf' or scope['method'] != 'POST':
            return await self.app(scope, receive, send)
        limit = MAX_PDF_BYTES + 256 * 1024
        headers = dict(scope.get('headers', []))
        try:
            if int(headers.get(b'content-length', b'0')) > limit:
                return await JSONResponse({'detail': 'PDF 不能超过 10 MB，请压缩或拆分后上传。'}, status_code=413)(scope, receive, send)
        except ValueError:
            return await JSONResponse({'detail': '文件请求格式无效。'}, status_code=400)(scope, receive, send)
        chunks, size = [], 0
        try:
            while True:
                message = await asyncio.wait_for(receive(), timeout=30)
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > limit:
                    return await JSONResponse({'detail': 'PDF 不能超过 10 MB，请压缩或拆分后上传。'}, status_code=413)(scope, receive, send)
                chunks.append(chunk)
                if not message.get('more_body'):
                    break
        except asyncio.TimeoutError:
            return await JSONResponse({'detail': '上传超时，请重试。'}, status_code=408)(scope, receive, send)
        body = b''.join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)

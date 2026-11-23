# 本地运行指南

以下命令从仓库根目录开始，在 Windows PowerShell 中执行。自动化流程配置为 Python 3.11、Node.js 20；具体通过记录见测试说明。无需配置模型即可体验基础模式。

## 一 配置后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

保持终端运行。访问 `http://127.0.0.1:8000/health`，应看到 `status: ok` 和版本 `3.0.0`；`http://127.0.0.1:8000/docs` 可查看接口。

首次运行生成空数据库，不包含作者的课题与对话。之后可在根目录用 `./start-backend.ps1` 启动。

macOS/Linux 可改用 `python3 -m venv .venv`、`.venv/bin/python` 与 `cp .env.example .env`，从 backend 目录运行同一 uvicorn 命令。微信模拟器和真机的最终体验需独立验证。

## 二 构建微信前端

另开终端，进入仓库的 frontend 目录：

```powershell
npm ci
npm run build:preview
```

微信开发者工具导入 `frontend/dist/dev/mp-weixin`，使用自己的 AppID 或工具允许的测试配置；源文件保留 `touristappid` 占位。电脑模拟器使用“我的”中的 `http://127.0.0.1:8000`。本地测试可在开发者工具关闭域名校验；这不适用于正式发布。

正式构建与编译产物测试：

```powershell
npm run build:mp-weixin
npm run build:preview
npm run test:mp-weixin
```

真机访问需要手机可达的后端地址和合适的网络/域名配置，不能直接使用手机自己的 127.0.0.1。

## 三 可选的真实 AI

编辑自己的 `backend/.env`：将 `LLM_PROVIDER` 改为 `openai`（表示兼容接口），填写自己的 `LLM_API_KEY`、`LLM_BASE_URL`、可用的 `LLM_MODEL`。模板示例使用 DeepSeek 地址；模型名称以你的服务账号为准。保存后重启后端，点击“我的 → 测试 AI 连接”。

非 Windows 使用 `LLM_TRANSPORT=python`。Windows 若 Python HTTPS 连接异常，可改为 `LLM_TRANSPORT=windows` 使用系统 HTTPS 组件。密钥只配置在本机，不提交到 Git。

## 四 演示与样例

按 `demo-data/scenario.json` 填入公开合成内容，即可演示两轮对话和日期汇报。可在根目录用后端环境执行：

```powershell
.\backend\.venv\Scripts\python.exe scripts/make_sample_pdf.py
```

生成 `demo-data/sample-reference.pdf`（两页英文合成材料）。它仅用于演示读取和页码引用，不是发表论文，也不代表真实实验。生成文件不会进入 Git。

未配置真实模型时，会明确显示基础追问和按原文整理汇报；请勿将其作为真实 AI 内容质量演示。

## 五 本地自动检查

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

前端目录执行 `npm run test:ui`；完整编译产物检查前先生成 dev 与 build 两个目录。模型与微信消息自动化使用替身，不需要真实密钥。GitHub Actions 状态以线上运行结果为准。

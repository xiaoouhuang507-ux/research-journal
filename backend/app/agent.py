"""Conversational shortcuts into the same reviewable product workflows."""
from .graph import run_plan, run_risk, run_report
from .product_service import create_draft, save_plan
from .tools import active_project

SESSIONS = {}


def chat(session_id, message):
    project = active_project()
    state = SESSIONS.setdefault(session_id, {"pending": None, "project_id": None})
    if state["project_id"] != (project["id"] if project else None):
        state.update(pending=None, project_id=project["id"] if project else None)
    action = None
    if not project:
        reply = "请先创建课题，补充研究目标、当前阶段和截止时间。"
    elif any(word in message for word in ("清空记忆", "删除所有记忆")):
        reply = "当前版本保留课题历史。你可以创建新课题并切换，原有资料会保留在“我的”中。"
    elif any(word in message for word in ("组会", "汇报", "总结")):
        result = run_report(project["id"], "本周")["report"]
        reply = result.get("markdown", "请先记录本周进展，再整理汇报。")
        action = {"type": "report", "project_id": project["id"]}
    elif any(word in message for word in ("预警", "风险", "延期", "阻碍", "截止")):
        risk = run_risk(project["id"])["risk"]
        reply = "\n".join(f"{item['task_name']}：{item['reason']}。{item['suggestion']}" for item in risk.get("warnings", [])) or "当前没有达到提醒阈值的任务。"
        action = {"type": "tasks", "project_id": project["id"]}
    elif any(word in message for word in ("计划", "规划", "路线", "安排", "拆解")):
        if any(word in message for word in ("过段时间", "以后再说", "日期不确定")):
            reply = "请提供明确日期；也可以按当前课题已确认的截止时间生成计划。"
        else:
            result = run_plan(project["id"])["plan"]
            if not result.get("ok"):
                reply = result.get("message", "请检查课题的截止时间")
            else:
                draft = create_draft(project["id"], "plan", result)
                state["pending"] = {"project_id": project["id"], "draft_id": draft["draft_id"]}
                reply = "已按当前课题生成待确认计划：\n\n" + "\n\n".join(f"{index + 1}. {item['name']}\n{item['start_date']} 至 {item['deadline']}\n产出：{item['deliverable']}" for index, item in enumerate(result["project_plan"])) + "\n\n可进入计划页编辑、选择任务，确认后保存。"
                action = {"type": "plan", "project_id": project["id"]}
    else:
        reply = "我可以根据当前课题生成科研计划、检查风险，或整理本周组会汇报。也可以进入任务详情记录实验结果与阻碍。"
    return {"reply": reply, "has_pending": bool(state["pending"]), "active_project": project["name"] if project else None, "action": action, "workflow": "langgraph"}


def confirm(session_id, action):
    state = SESSIONS.get(session_id, {})
    pending = state.get("pending")
    if not pending:
        return {"ok": False, "message": "当前没有待确认计划。"}
    if action == "discard":
        state["pending"] = None
        return {"ok": True, "message": "已放弃本次对话确认，计划任务未保存。"}
    result = save_plan(pending["project_id"], pending["draft_id"])
    state["pending"] = None
    return {**result, "message": "已保存确认的科研计划。"}

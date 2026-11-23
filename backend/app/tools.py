"""Domain tools used by the LangGraph workflow and REST API."""
from datetime import date, datetime, timedelta
from .database import connect, row, rows
from .product_service import build_report, insert_tasks, today as local_today

NORMALIZE_STATUS = {"todo":"未开始", "doing":"进行中", "done":"已完成", "overdue":"延期"}

def active_project():
    return row("SELECT * FROM projects WHERE status='active'")

def parse_date(value: str):
    try: return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError): return None

def project_tasks(project_id):
    return rows("SELECT * FROM tasks WHERE project_id=? ORDER BY deadline,id", (project_id,))

def build_research_plan(project: dict, priority="中"):
    deadline = parse_date(project["deadline"])
    today = local_today()
    if not deadline: return {"ok":False,"code":"INVALID_DATE","message":"请提供 YYYY-MM-DD 格式的明确截止日期。"}
    if deadline < today: return {"ok":False,"code":"PAST_DATE","message":"课题截止日期早于今天，请先修改日期。"}
    stages = [
        ("文献调研","完成领域调研并明确研究空白","检索并精读代表性论文，形成分类与研究缺口","文献综述与技术路线表","覆盖核心方法、公开数据集和评价指标"),
        ("方案设计","形成可验证的研究方案","确定baseline、实验变量、数据集与评价指标","实验方案文档","变量、对照组、指标和资源约束明确"),
        ("实验验证","完成baseline及核心方案实验","搭建环境、运行实验并记录可复现实验结果","实验记录与结果表","关键配置、日志和结果可追溯"),
        ("结果总结","完成分析与阶段汇报","分析结果、归纳局限并形成论文或组会材料","阶段报告与汇报提纲","结论有数据依据且明确下一步")]
    stage_order = [x[0] for x in stages]
    if project.get("stage") in stage_order:
        stages = stages[stage_order.index(project["stage"]):]
    total = (deadline-today).days + 1
    stages = stages[:total]
    count = len(stages)
    existing = project_tasks(project["id"])
    items=[]
    for i,(stage,goal,desc,deliverable,criteria) in enumerate(stages):
        start=today+timedelta(days=total*i//count)
        end=today+timedelta(days=total*(i+1)//count-1)
        conflicts=[t for t in existing if t["status"] not in ("已完成","done") and parse_date(t["start_date"])<=end and parse_date(t["deadline"])>=start]
        name=f"{stage}：{project['topic'] or project['name']}"
        items.append({"stage":stage,"stage_goal":goal,"name":name,"description":desc,"start_date":str(start),"deadline":str(end),"priority":priority,"deliverable":deliverable,"acceptance_criteria":criteria,"conflicts":[{"task_id":t["id"],"name":t.get("name") or t["description"]} for t in conflicts]})
    high_count=len([t for t in existing if t["priority"]=="高" and t["status"] not in ("已完成","done")])+(count if priority=="高" else 0)
    return {"ok":True,"project_id":project["id"],"project_plan":items,"overload":high_count>=5,"requires_confirmation":True}

def decompose_research_task(task_desc: str, dead_line: str, priority="中"):
    project=active_project()
    if not project: return {"ok":False,"code":"NO_ACTIVE_PROJECT","message":"请先新建或激活一个课题。"}
    if not parse_date(dead_line): return {"ok":False,"code":"INVALID_DATE","message":"请提供明确日期，格式为 YYYY-MM-DD。"}
    temp=dict(project); temp["goal"]=task_desc; temp["topic"]=task_desc; temp["deadline"]=dead_line
    result=build_research_plan(temp,priority)
    if result.get("ok"): result["items"]=result["project_plan"]
    return result

def persist_plan(project_id, items):
    with connect() as con:
        return insert_tasks(con, project_id, items)

def analyze_literature(payload, project=None):
    """Deterministic Demo analysis; never fabricates bibliographic facts."""
    project=project or active_project()
    if not project:
        return {"ok":False,"code":"NO_ACTIVE_PROJECT","message":"请先创建或激活课题，再整理文献。"}
    abstract=payload.get("abstract_excerpt","").strip()
    note=payload.get("note","").strip()
    source=abstract or note
    if not source:
        return {"ok":False,"code":"INSUFFICIENT_TEXT","message":"请至少填写摘要或个人笔记，系统不会编造论文内容。"}
    sentences=[x.strip() for x in source.replace("。","。|").split("|") if x.strip()]
    analysis={"summary":"；".join(sentences[:2]),"research_problem":sentences[0] if sentences else "待用户补充","method":sentences[1] if len(sentences)>1 else "摘要中未明确说明","innovation":payload.get("reference_idea") or "待用户判断创新性","limitation":payload.get("research_gap") or "摘要中未明确说明","relation":f"可用于支撑“{project['topic'] or project['name']}”的文献调研，具体关联需用户确认。"}
    from .llm_service import invoke_json
    llm=invoke_json("literature",{"title":payload["title"],"abstract":abstract,"personal_note":note,"project_topic":project["topic"] or project["name"]})
    allowed={"summary","research_problem","method","innovation","limitation","relation"}
    if isinstance(llm,dict) and allowed.issubset(llm): analysis={k:str(llm[k]) for k in allowed}
    return {"ok":True,"analysis":analysis}

def save_literature_note(payload):
    project=active_project()
    if not project: return {"ok":False,"code":"NO_ACTIVE_PROJECT","message":"当前没有激活课题，请先建立课题。"}
    duplicates=rows("SELECT id,title FROM literature_notes WHERE project_id=? AND (lower(title)=lower(?) OR lower(title) LIKE lower(?))",(project["id"],payload["title"],f"%{payload['title'][:12]}%"))
    if duplicates: return {"ok":False,"code":"DUPLICATE_NOTE","message":"已存在相似文献笔记，请选择覆盖或放弃。","duplicates":duplicates}
    analysis=analyze_literature(payload,project)
    if not analysis["ok"]: return analysis
    a=analysis["analysis"]
    with connect() as con:
        cur=con.execute("INSERT INTO literature_notes(project_id,title,abstract_excerpt,personal_note,summary,research_problem,method,innovation,research_gap,reference_idea,relation) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(project["id"],payload["title"],payload.get("abstract_excerpt",""),payload.get("note",""),a["summary"],a["research_problem"],a["method"],a["innovation"],payload.get("research_gap") or a["limitation"],payload.get("reference_idea") or a["innovation"],a["relation"]))
        return {"ok":True,"note_id":cur.lastrowid,"analysis":a}

def report_for_project(project_id, time_scope="本周"):
    return build_report(project_id, time_scope)

def generate_group_report(time_scope="本周"):
    project=active_project()
    return {"ok":False,"message":"请先激活课题。"} if not project else report_for_project(project["id"],time_scope)

def check_task_warning(project_id=None, today=None):
    today=today or local_today(); project=row("SELECT * FROM projects WHERE id=?",(project_id,)) if project_id else active_project()
    if not project: return {"ok":False,"message":"当前没有激活课题。"}
    pref=row("SELECT * FROM preferences WHERE id=1") or {"warn_days":3}
    tasks=project_tasks(project["id"]); warnings=[]
    for task in tasks:
        if task["status"] in ("已完成","done"): continue
        deadline=parse_date(task["deadline"]); remaining=(deadline-today).days
        blocked = task["status"] == "遇到阻碍" or bool(task.get("blocker"))
        if blocked or remaining<0 or remaining<=pref["warn_days"] or (remaining<=7 and task["progress"]<50):
            level="HIGH" if blocked or remaining<0 or (remaining<=3 and task["progress"]<50) else "MEDIUM"
            timing = f"已逾期{-remaining}天" if remaining<0 else f"距离截止还有{remaining}天"
            reason = task.get("blocker") or f"{timing}，任务完成{task['progress']}%"
            warnings.append({"task_id":task["id"],"task_name":task["name"],"remaining_days":remaining,"progress":task["progress"],"level":level,"reason":reason,"suggestion":"先记录阻碍及最小可交付成果，再预览时间调整建议" if blocked else "核对当前进展，预览新的截止时间和优先级","actions":["记录进展","预览调整建议"]})
    high=[t for t in tasks if t["priority"]=="高" and t["status"] not in ("已完成","done")]
    return {"ok":True,"project_id":project["id"],"level":"HIGH" if any(x["level"]=="HIGH" for x in warnings) else ("MEDIUM" if warnings else "LOW"),"warnings":warnings,"overload":len(high)>=5,"warn_days":pref["warn_days"]}

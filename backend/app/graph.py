"""Executable LangGraph workflow matching the Workflow V1.0 document.

The graph is deterministic by default so the local Demo works without a key.
Prompts and provider settings are kept separately for later GPT/DeepSeek use.
"""
from typing import Any, TypedDict
from langgraph.graph import END, START, StateGraph
from .database import row
from .llm_service import invoke_json
from .tools import build_research_plan, check_task_warning, project_tasks, report_for_project
from .schemas import PlanItem

class ResearchState(TypedDict, total=False):
    user_id: int
    project_id: int
    goal: str
    project: dict[str, Any]
    parsed_goal: dict[str, Any]
    tasks: list[dict[str, Any]]
    plan: dict[str, Any]
    risk: dict[str, Any]
    report: dict[str, Any]
    mode: str
    time_scope: str
    error: str

def goal_parser(state: ResearchState):
    project=row("SELECT * FROM projects WHERE id=?",(state["project_id"],))
    if not project: return {"error":"课题不存在"}
    return {"project":project,"goal":project["goal"],"parsed_goal":{"topic":project["topic"] or project["name"],"goal":project["goal"],"stage":project["stage"],"deadline":project["deadline"],"background":project["background"]}}

def planner_agent(state: ResearchState):
    if state.get("error"): return {}
    validated=build_research_plan(state["project"])
    if not validated.get("ok"):
        return {"plan": validated}
    llm=invoke_json("planner",{"project":state["parsed_goal"],"deterministic_plan":validated.get("project_plan",[])})
    # Only accept the expected list shape. Confirmation remains mandatory.
    if isinstance(llm,dict) and isinstance(llm.get("project_plan"),list) and llm["project_plan"]:
        candidate=llm["project_plan"]
        required={"stage","name","description","start_date","deadline","deliverable","acceptance_criteria"}
        try:
            valid=all(required.issubset(x) and PlanItem.model_validate(x) and x['deadline'] <= state['project']['deadline'] for x in candidate)
        except (TypeError,ValueError):
            valid=False
        if valid:
            for x in candidate: x.setdefault("priority","中"); x.setdefault("conflicts",[])
            validated={**validated,"project_plan":candidate,"source":"llm"}
    validated.setdefault("source","local_rules")
    return {"plan":validated}

def task_manager(state: ResearchState):
    if state.get("error"): return {}
    return {"tasks":project_tasks(state["project_id"])}

def risk_checker(state: ResearchState):
    if state.get("error"): return {}
    result=check_task_warning(state["project_id"])
    llm=invoke_json("risk",{"tasks":state.get("tasks",[]),"rule_result":result})
    if isinstance(llm,dict): result["llm_advice"]=llm
    return {"risk":result}

def report_generator(state: ResearchState):
    if state.get("error"): return {}
    result=report_for_project(state["project_id"],state.get("time_scope","本周"))
    # LLM can improve wording but may not add facts; deterministic report is the evidence payload.
    llm=invoke_json("summary",{"project":state["project"],"evidence_report":result.get("report",{}),"time_scope":state.get("time_scope","本周")})
    if isinstance(llm,dict) and result.get("ok"): result["llm_draft"]=llm
    return {"report":result}

def route_after_goal(state: ResearchState):
    return state.get("mode","plan")

builder=StateGraph(ResearchState)
builder.add_node("goal_parser",goal_parser)
builder.add_node("planner_agent",planner_agent)
builder.add_node("task_manager",task_manager)
builder.add_node("risk_checker",risk_checker)
builder.add_node("report_generator",report_generator)
builder.add_edge(START,"goal_parser")
builder.add_conditional_edges("goal_parser",route_after_goal,{"plan":"planner_agent","risk":"task_manager","report":"task_manager"})
builder.add_edge("planner_agent",END)
builder.add_conditional_edges("task_manager",route_after_goal,{"risk":"risk_checker","report":"report_generator"})
builder.add_edge("risk_checker",END)
builder.add_edge("report_generator",END)
research_graph=builder.compile()

def run_plan(project_id:int): return research_graph.invoke({"project_id":project_id,"mode":"plan"})
def run_risk(project_id:int): return research_graph.invoke({"project_id":project_id,"mode":"risk"})
def run_report(project_id:int,time_scope="本周"): return research_graph.invoke({"project_id":project_id,"mode":"report","time_scope":time_scope})

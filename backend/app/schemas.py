from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

TaskStatus = Literal["未开始", "进行中", "已完成", "延期", "遇到阻碍", "todo", "doing", "done", "overdue"]

class ChatRequest(BaseModel):
    session_id: str = "demo"
    message: str = Field(min_length=1, max_length=10000)

class ConfirmRequest(BaseModel):
    session_id: str
    action: Literal["confirm", "discard"]

class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)

class ProjectCreate(BaseModel):
    user_id: int = 1
    name: Optional[str] = None
    title: Optional[str] = None
    topic: str = ""
    goal: str
    deadline: str
    background: str = ""
    stage: str = "研究探索"

    @model_validator(mode="after")
    def require_title(self):
        if not (self.name or self.title): raise ValueError("name 或 title 至少填写一个")
        return self

class PlanItem(BaseModel):
    stage: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=5000)
    start_date: date
    deadline: date
    priority: Literal["高", "中", "低"] = "中"
    deliverable: str = Field(default="", max_length=2000)
    acceptance_criteria: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_dates(self):
        if not self.name.strip() or not self.stage.strip():
            raise ValueError("任务名称和阶段不能为空")
        if self.deadline < self.start_date:
            raise ValueError("截止日期不能早于开始日期")
        return self


class PlanRequest(BaseModel):
    confirm: bool = False
    priority: Literal["高", "中", "低"] = "中"
    draft_id: Optional[str] = None
    items: Optional[list[PlanItem]] = Field(default=None, min_length=1, max_length=50)

class TaskPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_date: Optional[str] = None
    deadline: Optional[str] = None
    priority: Optional[Literal["高", "中", "低"]] = None
    status: Optional[TaskStatus] = None
    progress: Optional[int] = Field(default=None, ge=0, le=100)
    deliverable: Optional[str] = None
    acceptance_criteria: Optional[str] = None

class NoteCreate(BaseModel):
    project_id: Optional[int] = None
    title: str
    abstract_excerpt: str = ""
    note: str = ""
    research_gap: str = ""
    reference_idea: str = ""

class ReportRequest(BaseModel):
    time_scope: str = "本周"
    save: bool = False
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    draft_id: Optional[str] = None
    markdown: Optional[str] = Field(default=None, min_length=1, max_length=100000)


def local_today():
    return datetime.now(timezone(timedelta(hours=8))).date()


class ProgressCreate(BaseModel):
    client_token: str = Field(min_length=1, max_length=100)
    occurred_on: date = Field(default_factory=local_today)
    accomplishment: str = Field(default="", max_length=5000)
    result: str = Field(default="", max_length=5000)
    blocker: str = Field(default="", max_length=3000)
    next_step: str = Field(default="", max_length=3000)
    progress: int = Field(ge=0, le=100)
    status: Literal["未开始", "进行中", "已完成", "延期", "遇到阻碍"]

    @model_validator(mode="after")
    def meaningful(self):
        if not any(x.strip() for x in (self.accomplishment, self.result, self.blocker, self.next_step)):
            raise ValueError("请至少填写进展、结果、阻碍或下一步中的一项")
        if self.status == "遇到阻碍" and not self.blocker.strip():
            raise ValueError("请说明遇到的阻碍")
        if self.occurred_on > local_today():
            raise ValueError("进展记录不能填写未来日期")
        return self


class RiskAction(BaseModel):
    confirm: bool = False
    draft_id: Optional[str] = None
    deadline: Optional[date] = None
    priority: Literal["高", "中", "低"] = "高"


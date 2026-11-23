from datetime import date
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from .schemas import local_today


class Reference(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    authors: str = Field(default='', max_length=500)
    year: str = Field(default='', max_length=20)
    url: str = Field(default='', max_length=2000)
    notes: str = Field(default='', max_length=6000)
    document_id: Optional[str] = Field(default=None, pattern=r'^[a-f0-9]{32}$')

    @field_validator('title')
    @classmethod
    def title_present(cls, value):
        if not value.strip(): raise ValueError('请填写文献标题')
        return value.strip()

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        if value and not value.startswith(('https://', 'http://')):
            raise ValueError('文献链接须以 https:// 或 http:// 开头')
        return value


class ResearchProject(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    topic: str = Field(min_length=1, max_length=1000)
    direction: str = Field(min_length=1, max_length=6000)
    references: List[Reference] = Field(default_factory=list, max_length=50)

    @field_validator('name', 'topic', 'direction')
    @classmethod
    def not_blank(cls, value):
        if not value.strip(): raise ValueError('课题名称、主题和具体方向不能为空')
        return value.strip()


class ProjectDeletion(BaseModel):
    confirmed: Literal[True]
    project_name: str = Field(min_length=1, max_length=150)
    preview_token: str = Field(pattern=r'^[a-f0-9]{64}$')


class DailyMessage(BaseModel):
    occurred_on: date = Field(default_factory=local_today)
    message: str = Field(min_length=1, max_length=8000)
    client_token: str = Field(min_length=8, max_length=100)

    @field_validator('message')
    @classmethod
    def not_blank(cls, value):
        if not value.strip(): raise ValueError('请简短说说今天做了什么')
        return value.strip()

    @field_validator('occurred_on')
    @classmethod
    def no_future(cls, value):
        if value > local_today(): raise ValueError('不能记录未来日期的对话')
        return value


class ReminderPreferences(BaseModel):
    enabled: bool = True
    reminder_time: str = Field(default='20:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')


class WechatLogin(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class Subscription(BaseModel):
    device_token: str = Field(min_length=20, max_length=200)
    template_id: str = Field(min_length=1, max_length=200)

"""SQLite persistence for confirmed long-term research data."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1]/".env")
DB_PATH = Path(os.getenv("DATABASE_PATH", Path(__file__).resolve().parents[1] / "research_agent.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS preferences(id INTEGER PRIMARY KEY CHECK(id=1), user_id INTEGER NOT NULL DEFAULT 1, user_identity TEXT NOT NULL, research_interest TEXT DEFAULT '', strengths TEXT DEFAULT '', weaknesses TEXT DEFAULT '', habit TEXT NOT NULL, warn_days INTEGER NOT NULL DEFAULT 3, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1, name TEXT NOT NULL, topic TEXT DEFAULT '', background TEXT DEFAULT '', goal TEXT NOT NULL, deadline TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '研究探索', status TEXT NOT NULL DEFAULT 'active', difficulties TEXT DEFAULT '', constraints_text TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE UNIQUE INDEX IF NOT EXISTS one_active_project ON projects(status) WHERE status='active';
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, stage TEXT NOT NULL DEFAULT '未分组', name TEXT NOT NULL DEFAULT '', description TEXT NOT NULL, start_date TEXT NOT NULL, deadline TEXT NOT NULL, priority TEXT NOT NULL DEFAULT '中', status TEXT NOT NULL DEFAULT '未开始', progress INTEGER NOT NULL DEFAULT 0, deliverable TEXT DEFAULT '', acceptance_criteria TEXT DEFAULT '', conflict_note TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(project_id) REFERENCES projects(id));
CREATE TABLE IF NOT EXISTS literature_notes(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, title TEXT NOT NULL, abstract_excerpt TEXT NOT NULL DEFAULT '', personal_note TEXT DEFAULT '', summary TEXT DEFAULT '', research_problem TEXT DEFAULT '', method TEXT DEFAULT '', innovation TEXT DEFAULT '', research_gap TEXT NOT NULL DEFAULT '', reference_idea TEXT NOT NULL DEFAULT '', relation TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(project_id) REFERENCES projects(id));
CREATE TABLE IF NOT EXISTS agent_memory(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 1, memory_type TEXT NOT NULL, content TEXT NOT NULL, project_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(project_id) REFERENCES projects(id));
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL, time_scope TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(project_id) REFERENCES projects(id));
CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, saved_result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(project_id) REFERENCES projects(id));
CREATE TABLE IF NOT EXISTS task_logs(id INTEGER PRIMARY KEY AUTOINCREMENT, client_token TEXT UNIQUE NOT NULL, project_id INTEGER NOT NULL, task_id INTEGER NOT NULL, occurred_on TEXT NOT NULL, accomplishment TEXT NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '', blocker TEXT NOT NULL DEFAULT '', next_step TEXT NOT NULL DEFAULT '', progress INTEGER NOT NULL, status TEXT NOT NULL, status_changed INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(project_id) REFERENCES projects(id), FOREIGN KEY(task_id) REFERENCES tasks(id));
CREATE INDEX IF NOT EXISTS logs_by_project_date ON task_logs(project_id,occurred_on);
CREATE TABLE IF NOT EXISTS project_references(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id), title TEXT NOT NULL, authors TEXT NOT NULL DEFAULT '', year TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS reference_documents(id TEXT PRIMARY KEY, project_id INTEGER REFERENCES projects(id), filename TEXT NOT NULL, title TEXT NOT NULL, sha256 TEXT NOT NULL, page_count INTEGER NOT NULL, readable_pages INTEGER NOT NULL, char_count INTEGER NOT NULL, warning TEXT NOT NULL DEFAULT '', pages_json TEXT NOT NULL, pdf_data BLOB NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS journal_turns(id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id), occurred_on TEXT NOT NULL, client_token TEXT UNIQUE NOT NULL, user_content TEXT NOT NULL, assistant_content TEXT, ai_mode TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS journal_project_date ON journal_turns(project_id,occurred_on,id);
CREATE TABLE IF NOT EXISTS reminder_settings(user_id INTEGER PRIMARY KEY REFERENCES users(id), enabled INTEGER NOT NULL DEFAULT 1, reminder_time TEXT NOT NULL DEFAULT '20:00', openid TEXT NOT NULL DEFAULT '', device_token TEXT NOT NULL DEFAULT '', credits INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS reminder_deliveries(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id), local_date TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,local_date,channel));
"""

@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def _columns(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}

def _migrate(con):
    """Non-destructively upgrade databases created by the previous archive."""
    additions = {
        "projects": {"user_id":"INTEGER NOT NULL DEFAULT 1", "topic":"TEXT DEFAULT ''", "stage":"TEXT NOT NULL DEFAULT '研究探索'", "direction":"TEXT NOT NULL DEFAULT ''"},
        "tasks": {"stage":"TEXT NOT NULL DEFAULT '未分组'", "name":"TEXT NOT NULL DEFAULT ''", "progress":"INTEGER NOT NULL DEFAULT 0", "deliverable":"TEXT DEFAULT ''", "acceptance_criteria":"TEXT DEFAULT ''", "updated_at":"TEXT DEFAULT ''", "completed_at":"TEXT", "blocker":"TEXT NOT NULL DEFAULT ''"},
        "literature_notes": {"personal_note":"TEXT DEFAULT ''", "summary":"TEXT DEFAULT ''", "research_problem":"TEXT DEFAULT ''", "method":"TEXT DEFAULT ''", "innovation":"TEXT DEFAULT ''", "relation":"TEXT DEFAULT ''"},
        "preferences": {"user_id":"INTEGER NOT NULL DEFAULT 1", "research_interest":"TEXT DEFAULT ''"},
        "reports": {"start_date":"TEXT", "end_date":"TEXT", "sources":"TEXT NOT NULL DEFAULT '[]'"},
        "project_references": {"document_id":"TEXT REFERENCES reference_documents(id)"},
    }
    for table, fields in additions.items():
        existing = _columns(con, table)
        for name, definition in fields.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    con.execute("UPDATE tasks SET name=description WHERE name='' OR name IS NULL")

def init_db():
    with connect() as con:
        con.executescript(SCHEMA)
        _migrate(con)
        con.execute("INSERT OR IGNORE INTO users(id,username) VALUES(1,'student01')")
        con.execute("INSERT OR IGNORE INTO preferences(id,user_id,user_identity,habit,warn_days) VALUES(1,1,'研究生','',3)")
        con.execute("INSERT OR IGNORE INTO reminder_settings(user_id) VALUES(1)")
        # if not con.execute("SELECT 1 FROM preferences").fetchone():
        #     con.execute("INSERT INTO preferences(id,user_id,user_identity,research_interest,habit,warn_days) VALUES(1,1,?,?,?,3)", ("计算机专业研二学生", "LLM Agent与应用可靠性", "周内优先做实验，周末集中写文档论文"))
        # if not con.execute("SELECT 1 FROM projects").fetchone():
        #     cur = con.execute("INSERT INTO projects(user_id,name,topic,background,goal,deadline,stage,status) VALUES(1,?,?,?,?,?,?,?)", ("大模型Agent应用容错策略研究", "LLM Agent应用可靠性", "大模型工具调用可靠性", "针对Agent工具调用幻觉，研究应用层的容错方案", "2026-11-30", "文献调研", "active"))
        #     pid = cur.lastrowid
        #     con.executemany("INSERT INTO tasks(project_id,stage,name,description,start_date,deadline,priority,status,progress,deliverable,acceptance_criteria) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
        #         (pid,"文献调研","调研Agent容错论文","调研现有Agent容错相关论文","2026-09-01","2026-09-15","高","进行中",40,"文献分类表与综述笔记","覆盖不少于10篇代表性论文"),
        #         (pid,"方案设计","整理容错方案对比表","整理容错方案对比表格","2026-09-16","2026-09-25","中","未开始",0,"方案对比表","至少覆盖Prompt、重试、校验三类方案")])
        #     con.execute("INSERT INTO literature_notes(project_id,title,abstract_excerpt,summary,research_problem,method,innovation,research_gap,reference_idea,relation) VALUES(?,?,?,?,?,?,?,?,?,?)", (pid,"Agent Tool-calling Failure Mitigation Survey","调研Agent工具调用失败的各类成因，分为幻觉、参数错误、规划错误三类","归纳工具调用失败类型及缓解策略","Agent工具调用为何失败","按失败环节分类比较","形成统一分类框架","缺少面向应用层低成本落地的容错策略，大多算法方案改底层框架","可以从prompt、重试策略、输出校验三层构建应用侧容错","直接支撑当前课题的容错框架设计"))
        #     con.execute("INSERT INTO agent_memory(user_id,memory_type,content) VALUES(1,'research_interest','LLM Agent与应用可靠性')")

def rows(sql, params=()):
    with connect() as con:
        return [dict(x) for x in con.execute(sql, params).fetchall()]

def row(sql, params=()):
    with connect() as con:
        value = con.execute(sql, params).fetchone()
        return dict(value) if value else None

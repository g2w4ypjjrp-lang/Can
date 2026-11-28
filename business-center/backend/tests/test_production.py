from datetime import UTC, datetime

import pytest
from conftest import SECRET, auth, make_user
from test_operations import Recorder

from bizcenter.config import Settings
from bizcenter.db import Database
from bizcenter.main import create_app
from bizcenter.scheduler import tick


def test_production_settings_are_enforced():
    bad = Settings(database_url="x", environment="production", supabase_jwt_secret="kısa",
                   cors_origins=["http://localhost:3000"], inline_scheduler=True)
    problems = bad.production_problems()
    assert len(problems) == 4
    with pytest.raises(RuntimeError, match="Güvensiz production"):
        create_app(bad)
    good = Settings(database_url="x", environment="production", supabase_url="https://p.supabase.co",
                    cors_origins=["https://panel.example.com"], redis_url="redis://r:6379/0")
    assert good.production_problems() == []
    assert Settings(database_url="x", supabase_jwt_secret=SECRET).production_problems() == []


async def test_stuck_tasks_are_reaped(client, admin, dsn):
    uid = make_user(admin, "reap@test")
    org = (await client.post("/api/organizations", json={"name": "R"}, headers=auth(uid))).json()["id"]
    agent = admin.execute("select id from agents where organization_id=%s and code='ceo'", (org,)).fetchone()["id"]
    old = admin.execute("""insert into tasks(organization_id,title,command,status,created_by,updated_at)
                           values (%s,'eski','x','running',%s, now() - interval '2 hour') returning id""", (org, uid)).fetchone()["id"]
    fresh = admin.execute("""insert into tasks(organization_id,title,command,status,created_by)
                             values (%s,'yeni','x','running',%s) returning id""", (org, uid)).fetchone()["id"]
    admin.execute("insert into agent_runs(organization_id, agent_id, task_id, status) values (%s,%s,%s,'running')",
                  (org, agent, old))
    db = Database(dsn, 2)
    await db.open()
    out = await tick(db, Recorder(), max_active=3, now=datetime.now(UTC), task_timeout_minutes=30)
    await db.close()
    assert out["reaped"] == 1
    assert admin.execute("select status from tasks where id=%s", (old,)).fetchone()["status"] == "failed"
    assert admin.execute("select status from tasks where id=%s", (fresh,)).fetchone()["status"] == "running"
    assert admin.execute("select status from agent_runs where task_id=%s", (old,)).fetchone()["status"] == "failed"

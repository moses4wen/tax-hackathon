"""Tenant/role regressions: exercised with the production authentication middleware."""
import base64

from fastapi.testclient import TestClient

from app.server import app
from app.storage import connect, init_db
from app.auth import create_org, create_user


def h(user, password):
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": "Basic " + encoded}


def test_three_roles_and_org_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path/"rbac.db"))
    monkeypatch.delenv("APP_ENV", raising=False)
    init_db()
    with connect() as c:
        create_org(c,"team-b","Team B")
        create_user(c,"view-a","demo","viewer","viewer-password-123")
        create_user(c,"edit-a","demo","editor","editor-password-123")
        create_user(c,"review-a","demo","reviewer","reviewer-password-123")
        create_user(c,"review-b","team-b","reviewer","review-b-password-123")
    monkeypatch.setenv("APP_ENV","production")
    with TestClient(app) as client:
        a=h("view-a","viewer-password-123")
        e=h("edit-a","editor-password-123")
        r=h("review-a","reviewer-password-123")
        b=h("review-b","review-b-password-123")
        assert client.get("/api/graphs",headers=a).status_code==200
        assert client.get("/api/graphs").status_code==401
        assert client.get("/api/config",headers=a).json()["capabilities"]["edit_process"] is False
        assert client.get("/api/config",headers=e).json()["capabilities"]["create_process"]
        assert client.get("/api/config",headers=r).json()["capabilities"]["publish_process"]
        assert client.post("/api/graphs/umwstg20-v1/draft",headers=a,json={"actor":"x"}).status_code==403
        assert client.post("/api/graphs/umwstg20-v1/draft",headers=b,json={"actor":"x"}).status_code==404
        new_proc=client.post("/api/processes",headers=e,json={"label":"Neue Fallprüfung"}).json()
        assert new_proc["meta"]["status"]=="draft"
        assert new_proc["meta"]["org_id"]=="demo"
        assert client.post("/api/processes",headers=r,json={"label":"Unzulässig"}).status_code==403
        assert client.post("/api/processes",headers=a,json={"label":"Unzulässig"}).status_code==403
        draft=client.post("/api/graphs/umwstg20-v1/draft",headers=e,json={"actor":"spoof"}).json()
        assert draft["meta"]["created_by"]=="edit-a"
        did=draft["meta"]["id"]
        assert client.get(f"/api/graphs/{did}",headers=a).status_code==404
        assert client.get(f"/api/graphs/{did}",headers=b).status_code==404
        assert client.post(f"/api/graphs/{did}/publish",headers=e,
            json={"actor":"spoof","confirm_expert_review":True}).status_code==403
        assert client.post(f"/api/graphs/{did}/publish",headers=r,
            json={"actor":"spoof","confirm_expert_review":True}).status_code==200
        assert client.get(f"/api/graphs/{did}",headers=a).status_code==200
        assert client.post("/api/cases",headers=a,json={"title":"Testfall"}).status_code==403
        case=client.post("/api/cases",headers=e,json={"title":"Testfall"}).json()
        assert case["org_id"]=="demo"
        assert client.get(f"/api/cases/{case['id']}",headers=b).status_code==404
        assert client.get("/api/cases",headers=b).json()["cases"]
        assert all(row["org_id"]=="team-b" for row in client.get("/api/cases",headers=b).json()["cases"])
        assert client.post(f"/api/cases/{case['id']}/run",headers=b,
            json={"graph_version":"umwstg20-v1"}).status_code==404


def test_password_rejection(tmp_path,monkeypatch):
    monkeypatch.setenv("DATABASE_PATH",str(tmp_path/"rbac2.db"))
    monkeypatch.delenv("APP_ENV",raising=False)
    init_db()
    with connect() as c:
        create_user(c,"reader","demo","viewer","correct-password-123")
    monkeypatch.setenv("APP_ENV","production")
    with TestClient(app) as client:
        assert client.get("/api/graphs",headers=h("reader","wrong-password-123")).status_code==401
        mapping=client.get("/api/procedural-map",headers=h("reader","correct-password-123")).json()
        assert mapping["source"]["version"]=="v3"
        assert any(x["external_id"]=="c_aufstockung" for x in mapping["mapping"])


def test_demo_role_switch_is_cookie_controlled_and_nonproduction_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path/"demo-role.db"))
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_USER", "demo-user")
    monkeypatch.setenv("APP_LOCAL_ROLE", "editor")
    monkeypatch.setenv("APP_DEMO_ROLE_SWITCH", "1")
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    init_db()
    with TestClient(app) as client:
        default = client.get("/api/config").json()
        assert default["identity"]["role"] == "editor"
        assert default["demo_role_switch"] is True
        assert {role["value"] for role in default["demo_roles"]} == {"viewer", "editor", "reviewer"}
        assert default["capabilities"]["edit_case"] is True
        assert default["capabilities"]["publish_process"] is False
        reviewer = client.get("/api/config", cookies={"demo_role": "reviewer"}).json()
        assert reviewer["identity"]["role"] == "reviewer"
        assert reviewer["capabilities"]["publish_process"] is True
        viewer = client.get("/api/config", cookies={"demo_role": "viewer"}).json()
        assert viewer["identity"]["role"] == "viewer"
        assert viewer["capabilities"]["edit_case"] is False
        invalid = client.get("/api/config", cookies={"demo_role": "owner"}).json()
        assert invalid["identity"]["role"] == "editor"
        monkeypatch.setenv("APP_ENV", "production")
        assert client.get("/api/config", cookies={"demo_role": "reviewer"}).status_code == 401

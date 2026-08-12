import os
import re
from datetime import date
from pathlib import Path

TEST_DB = Path("test_iker_care.db")
TEST_DB.unlink(missing_ok=True)

os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB}")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("SEED_SAMPLE_DATA", "false")

from fastapi.testclient import TestClient

from app.v2_main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_login_page_is_available():
    with TestClient(app) as client:
        response = client.get("/login")
        assert response.status_code == 200
        assert "IkerCare" in response.text


def test_authenticated_medication_workflow():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        home = client.get("/")
        assert home.status_code == 200
        match = re.search(r'data-csrf="([^"]+)"', home.text)
        assert match
        csrf = match.group(1)

        medication = client.post(
            "/api/medications",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "Medicamento de prueba",
                "medication_type": "Prueba",
                "purpose": "Validar el flujo",
                "dose": "1 unidad",
                "route": "Oral",
                "instructions": "Solo prueba automática",
                "times": ["08:00"],
            },
        )
        assert medication.status_code == 201

        today = date.today().isoformat()
        dashboard = client.get(f"/api/dashboard?date={today}")
        assert dashboard.status_code == 200
        item = next(row for row in dashboard.json()["medications"] if row["medication"]["name"] == "Medicamento de prueba")
        assert item["status"] == "pending"

        marked = client.post(
            "/api/medication-logs/toggle",
            headers={"X-CSRF-Token": csrf},
            json={
                "schedule_id": item["schedule_id"],
                "log_date": today,
                "status": "taken",
            },
        )
        assert marked.status_code == 200
        assert marked.json()["status"] == "taken"


def test_unscheduled_medication_administration_workflow():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        home = client.get("/")
        match = re.search(r'data-csrf="([^"]+)"', home.text)
        assert match
        csrf = match.group(1)

        medication = client.post(
            "/api/medications",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "Medicamento SOS de prueba",
                "medication_type": "Rescate",
                "purpose": "Validar administraciones sin hora fija",
                "dose": "1 unidad",
                "route": "Endovenosa",
                "frequency": "SOS",
                "instructions": "Solo prueba automática",
                "times": [],
            },
        )
        assert medication.status_code == 201
        medication_id = medication.json()["id"]

        today = date.today().isoformat()
        dashboard = client.get(f"/api/dashboard?date={today}")
        unscheduled = dashboard.json()["unscheduled_medications"]
        item = next(row for row in unscheduled if row["medication"]["id"] == medication_id)
        assert item["administrations"] == []

        administration = client.post(
            f"/api/medications/{medication_id}/event-logs",
            headers={"X-CSRF-Token": csrf},
            json={"occurred_at": f"{today}T10:30", "notes": "Administrado en prueba"},
        )
        assert administration.status_code == 201

        dashboard = client.get(f"/api/dashboard?date={today}")
        item = next(
            row
            for row in dashboard.json()["unscheduled_medications"]
            if row["medication"]["id"] == medication_id
        )
        assert len(item["administrations"]) == 1
        assert item["administrations"][0]["notes"] == "Administrado en prueba"


def test_mobile_shell_and_service_worker_are_available():
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "admin", "password": "test-password"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        home = client.get("/")
        assert home.status_code == 200
        assert 'bottom-nav mobile-nav' in home.text
        assert '/static/v2.js' in home.text
        assert '/static/manifest.webmanifest' in home.text

        worker = client.get("/service-worker.js")
        assert worker.status_code == 200
        assert "ikercare-static-v2." in worker.text

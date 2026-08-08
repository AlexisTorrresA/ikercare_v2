import io
import re
from datetime import date
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.v2_main import app


def csrf_from_home(client: TestClient) -> str:
    response = client.get("/v2")
    assert response.status_code == 200
    match = re.search(r'data-csrf="([^"]+)"', response.text)
    assert match
    return match.group(1)


def test_v2_registration_patient_and_care_flow():
    with TestClient(app) as client:
        registered = client.post(
            "/api/v2/auth/register",
            json={
                "username": "family_test",
                "email": "family_test@example.test",
                "display_name": "Familia Test",
                "password": "StrongPassword2026",
                "accept_privacy": True,
                "guardian_attestation": True,
            },
        )
        assert registered.status_code == 201, registered.text
        csrf = csrf_from_home(client)
        # Un usuario recién registrado nunca hereda el paciente legado de otra cuenta.
        assert client.get("/api/v2/patients").json() == []

        patient_response = client.post(
            "/api/v2/patients",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "Paciente Test",
                "birth_date": "2024-01-10",
                "primary_hospital": "Hospital Test",
                "diagnoses": "Antecedente de prueba",
            },
        )
        assert patient_response.status_code == 201, patient_response.text
        patient_id = patient_response.json()["id"]

        med_search = client.get("/api/v2/medications/search?q=leveti")
        assert med_search.status_code == 200
        assert any("Levetiracetam" in row["name"] for row in med_search.json())

        medication = client.post(
            f"/api/v2/patients/{patient_id}/medications",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "Medicamento Test",
                "medication_type": "Prueba",
                "purpose": "Registro de prueba, no indicación médica",
                "dose": "1 unidad",
                "route": "VO",
                "frequency": "Cada 24 horas",
                "instructions": "Solo prueba automatizada",
                "times": ["08:00"],
            },
        )
        assert medication.status_code == 201, medication.text

        day = client.get(f"/api/v2/patients/{patient_id}/day?date={date.today().isoformat()}")
        assert day.status_code == 200, day.text
        schedule_id = day.json()["medications"][0]["schedule_id"]

        marked = client.post(
            f"/api/v2/patients/{patient_id}/medication-logs/toggle",
            headers={"X-CSRF-Token": csrf},
            json={"schedule_id": schedule_id, "log_date": date.today().isoformat(), "status": "taken", "notes": "test"},
        )
        assert marked.status_code == 200
        assert marked.json()["status"] == "taken"

        elimination = client.post(
            f"/api/v2/patients/{patient_id}/elimination",
            headers={"X-CSRF-Token": csrf},
            json={"occurred_at": "2026-08-08T08:30:00", "diaper_status": "wet", "urine_amount": "medium", "notes": "test"},
        )
        assert elimination.status_code == 201, elimination.text

        food = client.post(
            f"/api/v2/patients/{patient_id}/food",
            headers={"X-CSRF-Token": csrf},
            json={"occurred_at": "2026-08-08T09:00:00", "meal_type": "desayuno", "item": "leche", "amount": "100", "unit": "ml", "tolerated": True, "vomiting": False},
        )
        assert food.status_code == 201, food.text

        summary = client.get(f"/api/v2/patients/{patient_id}/summary?language=en&detail=complete")
        assert summary.status_code == 200
        assert summary.json()["language"] == "en"

        share = client.post(
            f"/api/v2/patients/{patient_id}/shares",
            headers={"X-CSRF-Token": csrf},
            json={"detail": "simple", "language": "en", "include_documents": False, "expires_hours": 1},
        )
        assert share.status_code == 201, share.text
        share_data = share.json()
        assert share_data["url"].startswith("http")
        assert share_data["qr_data_uri"].startswith("data:image/png;base64,")
        parsed = urlsplit(share_data["url"])
        assert parsed.fragment  # el secreto no viaja al servidor en el URL HTTP
        public = client.get(parsed.path)
        assert public.status_code == 200
        assert "noindex" in public.text
        opened = client.post(f"{parsed.path}/open", json={"token": parsed.fragment})
        assert opened.status_code == 200, opened.text
        assert opened.json()["language"] == "en"


def test_v2_document_and_photo_are_private_and_extractable():
    with TestClient(app) as client:
        login = client.post("/api/v2/auth/native-login", json={"username": "family_test", "password": "StrongPassword2026"})
        assert login.status_code == 200, login.text
        csrf = csrf_from_home(client)
        patients = client.get("/api/v2/patients").json()
        patient_id = next(row["id"] for row in patients if row["name"] == "Paciente Test")

        image = Image.new("RGB", (900, 240), "white")
        ImageDraw.Draw(image).text((30, 80), "HEMOGLOBINA 12.3 TEST", fill="black")
        raw = io.BytesIO()
        image.save(raw, format="PNG")
        raw.seek(0)

        uploaded = client.post(
            f"/api/v2/patients/{patient_id}/documents",
            headers={"X-CSRF-Token": csrf},
            data={"exam_name": "Hemograma test", "exam_date": "2026-08-08", "document_type": "laboratorio", "hospital": "Hospital Test", "notes": "Prueba OCR"},
            files={"file": ("hemograma.png", raw.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["id"]

        docs = client.get(f"/api/v2/patients/{patient_id}/documents")
        assert docs.status_code == 200
        row = next(doc for doc in docs.json() if doc["id"] == document_id)
        assert row["exam_name"] == "Hemograma test"
        assert row["extraction_status"] in {"text_extracted", "ocr_completed", "partial", "failed"}

        download = client.get(f"/api/v2/patients/{patient_id}/documents/{document_id}/download")
        assert download.status_code == 200
        assert download.content.startswith(b"\x89PNG")

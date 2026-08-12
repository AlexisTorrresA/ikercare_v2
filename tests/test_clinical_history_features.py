from __future__ import annotations

import subprocess

from app.medical_catalog import search_medications
from app.v2_clinical_history import _pdf_bytes
from app.v2_main import app


def test_new_clinical_routes_are_registered():
    paths = {route.path for route in app.routes}
    required = {
        "/api/v2/patients/{patient_id}/medications/{medication_id}/treatment-history",
        "/api/v2/patients/{patient_id}/medications/{medication_id}/history-update",
        "/api/v2/patients/{patient_id}/medications/{medication_id}/status",
        "/api/v2/patients/{patient_id}/chemo/{chemo_id}/events",
        "/api/v2/patients/{patient_id}/documents/group",
        "/api/v2/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report",
        "/api/v2/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report.pdf",
        "/api/v2/medications/ai-enrich",
    }
    assert required <= paths


def test_expanded_medication_catalog_contains_common_entries():
    levetiracetam = search_medications("Levetiracetam", limit=3)[0]
    assert levetiracetam["name"] == "Levetiracetam"
    assert "Anticonvulsivo" in levetiracetam["type"]
    assert levetiracetam["unit"] == "mg"
    vincristine = search_medications("Vincristina", limit=3)[0]
    assert vincristine["name"] == "Vincristina"
    assert vincristine["route"] == "Endovenosa"


def test_hospitalization_pdf_is_valid_pdf():
    report = {
        "facts": {
            "patient": {"name": "Paciente Test"},
            "hospitalization": {
                "hospital": "Hospital Test",
                "admission_at": "2026-08-01T10:00",
                "discharge_at": "2026-08-02T12:00",
            },
            "days": [
                {
                    "date": "2026-08-01",
                    "medications": [{"time": "10:00", "name": "Medicamento", "dose": "1 mg", "route": "Oral", "status": "taken"}],
                    "treatment_changes": [], "chemotherapy": [], "chemo_events": [], "events": [], "vitals": [], "food": [], "elimination": [], "documents": [], "notes": [],
                }
            ],
        },
        "narrative": "Resumen basado únicamente en datos registrados.",
    }
    data = _pdf_bytes(report)
    assert data.startswith(b"%PDF")
    assert len(data) > 500


def test_new_frontend_javascript_syntax():
    for path in ("app/static/v2-clinical-history.js", "app/static/v2-report-download-fix.js", "app/static/v2.js"):
        subprocess.run(["node", "--check", path], check=True)

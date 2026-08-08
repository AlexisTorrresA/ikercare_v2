
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

CATALOG = [
    {"name": "Levetiracetam", "generic_name": "levetiracetam", "type": "Anticonvulsivo", "purpose": "Medicamento anticonvulsivo utilizado para prevenir o controlar crisis epilépticas."},
    {"name": "Clobazam", "generic_name": "clobazam", "type": "Benzodiacepina anticonvulsiva", "purpose": "Puede utilizarse como tratamiento complementario para el control de ciertas crisis epilépticas."},
    {"name": "Lacosamida", "generic_name": "lacosamida", "type": "Anticonvulsivo", "purpose": "Medicamento utilizado para el control de determinados tipos de crisis epilépticas."},
    {"name": "Gabapentina", "generic_name": "gabapentina", "type": "Neuromodulador / anticonvulsivo", "purpose": "Puede utilizarse para dolor neuropático y, en algunos casos, como anticonvulsivo."},
    {"name": "Captopril", "generic_name": "captopril", "type": "Antihipertensivo / IECA", "purpose": "Medicamento utilizado para disminuir la presión arterial y en determinadas condiciones cardiovasculares."},
    {"name": "Amlodipino", "generic_name": "amlodipino", "type": "Antihipertensivo / bloqueador de canales de calcio", "purpose": "Medicamento utilizado para controlar la presión arterial."},
    {"name": "Ondansetrón", "generic_name": "ondansetron", "type": "Antiemético", "purpose": "Se utiliza para prevenir o tratar náuseas y vómitos, incluidos los asociados a algunos tratamientos oncológicos."},
    {"name": "Dexametasona", "generic_name": "dexametasona", "type": "Corticoide", "purpose": "Corticoide con efectos antiinflamatorios e inmunomoduladores; su finalidad concreta depende de la indicación clínica."},
    {"name": "Piridoxina", "generic_name": "piridoxina / vitamina B6", "type": "Vitamina B6", "purpose": "Vitamina B6 utilizada como suplemento o como parte de indicaciones específicas definidas por el equipo tratante."},
    {"name": "Paracetamol", "generic_name": "paracetamol / acetaminofén", "type": "Analgésico / antipirético", "purpose": "Se utiliza para aliviar dolor y disminuir fiebre."},
    {"name": "Lorazepam", "generic_name": "lorazepam", "type": "Benzodiacepina", "purpose": "Puede utilizarse para ansiedad, sedación o como medicación de rescate en determinadas crisis, según indicación médica."},
    {"name": "Polietilenglicol (PEG)", "generic_name": "macrogol / polietilenglicol", "type": "Laxante osmótico", "purpose": "Se utiliza para tratar o prevenir estreñimiento."},
    {"name": "Vincristina", "generic_name": "vincristina", "type": "Antineoplásico", "purpose": "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos."},
    {"name": "Ciclofosfamida", "generic_name": "ciclofosfamida", "type": "Antineoplásico / agente alquilante", "purpose": "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos."},
    {"name": "Mesna", "generic_name": "mesna", "type": "Uroprotector", "purpose": "Se utiliza para reducir el riesgo de toxicidad urinaria asociada a determinados medicamentos de quimioterapia."},
    {"name": "Carboplatino", "generic_name": "carboplatino", "type": "Antineoplásico / compuesto de platino", "purpose": "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos."},
    {"name": "Cisplatino", "generic_name": "cisplatino", "type": "Antineoplásico / compuesto de platino", "purpose": "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos."},
    {"name": "Etopósido", "generic_name": "etopósido", "type": "Antineoplásico", "purpose": "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos."},
    {"name": "Metotrexato", "generic_name": "metotrexato", "type": "Antimetabolito / antineoplásico", "purpose": "Se utiliza en determinados protocolos oncológicos y otras enfermedades; la indicación depende del contexto clínico."},
    {"name": "Filgrastim", "generic_name": "filgrastim", "type": "Factor estimulante de colonias", "purpose": "Puede utilizarse para estimular la recuperación de neutrófilos después de ciertos tratamientos."},
    {"name": "Omeprazol", "generic_name": "omeprazol", "type": "Inhibidor de bomba de protones", "purpose": "Disminuye la producción de ácido gástrico."},
    {"name": "Esomeprazol", "generic_name": "esomeprazol", "type": "Inhibidor de bomba de protones", "purpose": "Disminuye la producción de ácido gástrico."},
    {"name": "Furosemida", "generic_name": "furosemida", "type": "Diurético de asa", "purpose": "Aumenta la eliminación de agua y sodio; puede utilizarse en edema o ciertas situaciones cardiovasculares."},
    {"name": "Morfina", "generic_name": "morfina", "type": "Analgésico opioide", "purpose": "Se utiliza para el tratamiento de dolor moderado a intenso bajo supervisión clínica."},
    {"name": "Metoclopramida", "generic_name": "metoclopramida", "type": "Antiemético / procinético", "purpose": "Puede utilizarse para náuseas, vómitos o problemas de motilidad gastrointestinal según indicación médica."},
]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def search_medications(query: str, limit: int = 8) -> list[dict]:
    q = normalize(query)
    if len(q) < 2:
        return []

    ranked: list[tuple[float, dict]] = []
    for item in CATALOG:
        haystack = normalize(f"{item['name']} {item['generic_name']}")
        if haystack.startswith(q):
            score = 2.0
        elif q in haystack:
            score = 1.5
        else:
            score = SequenceMatcher(None, q, normalize(item["name"])).ratio()
        if score >= 0.45:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return [dict(item, source="curated_catalog") for _, item in ranked[:limit]]

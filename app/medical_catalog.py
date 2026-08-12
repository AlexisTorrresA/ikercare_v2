from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def med(name: str, generic_name: str, type_: str, purpose: str, route: str | None = None, unit: str | None = None) -> dict:
    return {"name": name, "generic_name": generic_name, "type": type_, "purpose": purpose, "route": route, "unit": unit}


CATALOG = [
    med("Levetiracetam", "levetiracetam", "Anticonvulsivo", "Medicamento anticonvulsivo utilizado para prevenir o controlar crisis epilépticas.", "Oral / endovenosa", "mg"),
    med("Clobazam", "clobazam", "Benzodiacepina anticonvulsiva", "Puede utilizarse como tratamiento complementario para el control de ciertas crisis epilépticas.", "Oral", "mg"),
    med("Lacosamida", "lacosamida", "Anticonvulsivo", "Medicamento utilizado para el control de determinados tipos de crisis epilépticas.", "Oral / endovenosa", "mg"),
    med("Gabapentina", "gabapentina", "Neuromodulador / anticonvulsivo", "Puede utilizarse para dolor neuropático y, en algunos casos, como anticonvulsivo.", "Oral", "mg"),
    med("Captopril", "captopril", "Antihipertensivo / IECA", "Medicamento utilizado para disminuir la presión arterial y en determinadas condiciones cardiovasculares.", "Oral", "mg"),
    med("Amlodipino", "amlodipino", "Antihipertensivo / bloqueador de canales de calcio", "Medicamento utilizado para controlar la presión arterial.", "Oral", "mg"),
    med("Ondansetrón", "ondansetron", "Antiemético", "Se utiliza para prevenir o tratar náuseas y vómitos, incluidos los asociados a algunos tratamientos oncológicos.", "Oral / endovenosa", "mg"),
    med("Dexametasona", "dexametasona", "Corticoide", "Corticoide con efectos antiinflamatorios e inmunomoduladores; su finalidad concreta depende de la indicación clínica.", "Oral / endovenosa", "mg"),
    med("Piridoxina", "piridoxina / vitamina B6", "Vitamina B6", "Vitamina B6 utilizada como suplemento o como parte de indicaciones específicas definidas por el equipo tratante.", "Oral", "mg"),
    med("Paracetamol", "paracetamol / acetaminofén", "Analgésico / antipirético", "Se utiliza para aliviar dolor y disminuir fiebre.", "Oral / rectal / endovenosa", "mg"),
    med("Lorazepam", "lorazepam", "Benzodiacepina", "Puede utilizarse para ansiedad, sedación o como medicación de rescate en determinadas crisis, según indicación médica.", "Oral / endovenosa", "mg"),
    med("Diazepam", "diazepam", "Benzodiacepina anticonvulsiva", "Puede utilizarse para el control agudo de convulsiones u otras indicaciones definidas por el equipo tratante.", "Oral / rectal / endovenosa", "mg"),
    med("Midazolam", "midazolam", "Benzodiacepina / sedante", "Puede utilizarse para sedación o como medicamento de rescate en determinadas crisis según indicación clínica.", "Endovenosa / intranasal / bucal", "mg"),
    med("Polietilenglicol (PEG)", "macrogol / polietilenglicol", "Laxante osmótico", "Se utiliza para tratar o prevenir estreñimiento.", "Oral", "g"),
    med("Lactulosa", "lactulosa", "Laxante osmótico", "Se utiliza para facilitar la evacuación intestinal en determinadas situaciones de estreñimiento.", "Oral", "mL"),
    med("Vincristina", "vincristina", "Antineoplásico", "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos.", "Endovenosa", "mg"),
    med("Ciclofosfamida", "ciclofosfamida", "Antineoplásico / agente alquilante", "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos.", "Endovenosa", "mg"),
    med("Mesna", "mesna", "Uroprotector", "Se utiliza para reducir el riesgo de toxicidad urinaria asociada a determinados medicamentos de quimioterapia.", "Endovenosa / oral", "mg"),
    med("Carboplatino", "carboplatino", "Antineoplásico / compuesto de platino", "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos.", "Endovenosa", "mg"),
    med("Cisplatino", "cisplatino", "Antineoplásico / compuesto de platino", "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos.", "Endovenosa", "mg"),
    med("Etopósido", "etopósido", "Antineoplásico", "Medicamento de quimioterapia utilizado en distintos protocolos oncológicos.", "Endovenosa / oral", "mg"),
    med("Metotrexato", "metotrexato", "Antimetabolito / antineoplásico", "Se utiliza en determinados protocolos oncológicos y otras enfermedades; la indicación depende del contexto clínico.", "Según protocolo", "mg"),
    med("Filgrastim", "filgrastim", "Factor estimulante de colonias", "Puede utilizarse para estimular la recuperación de neutrófilos después de ciertos tratamientos.", "Subcutánea", "mcg"),
    med("Omeprazol", "omeprazol", "Inhibidor de bomba de protones", "Disminuye la producción de ácido gástrico.", "Oral / endovenosa", "mg"),
    med("Esomeprazol", "esomeprazol", "Inhibidor de bomba de protones", "Disminuye la producción de ácido gástrico.", "Oral / endovenosa", "mg"),
    med("Furosemida", "furosemida", "Diurético de asa", "Aumenta la eliminación de agua y sodio; puede utilizarse en edema o ciertas situaciones cardiovasculares.", "Oral / endovenosa", "mg"),
    med("Morfina", "morfina", "Analgésico opioide", "Se utiliza para el tratamiento de dolor moderado a intenso bajo supervisión clínica.", "Oral / endovenosa / subcutánea", "mg"),
    med("Metoclopramida", "metoclopramida", "Antiemético / procinético", "Puede utilizarse para náuseas, vómitos o problemas de motilidad gastrointestinal según indicación médica.", "Oral / endovenosa", "mg"),
    med("Domperidona", "domperidona", "Procinético / antiemético", "Puede utilizarse para determinadas alteraciones de motilidad digestiva o náuseas según indicación clínica.", "Oral", "mg"),
    med("Ibuprofeno", "ibuprofeno", "Antiinflamatorio no esteroideo", "Se utiliza para aliviar dolor, inflamación y fiebre en situaciones donde esté indicado.", "Oral", "mg"),
    med("Salbutamol", "salbutamol / albuterol", "Broncodilatador", "Se utiliza para aliviar broncoespasmo y facilitar la respiración en determinadas enfermedades respiratorias.", "Inhalatoria", "mcg"),
    med("Mometasona", "mometasona", "Corticoide", "Puede utilizarse para disminuir inflamación local, por ejemplo en vías respiratorias o piel, según la presentación indicada.", "Nasal / inhalatoria / tópica", "mcg"),
    med("Vancomicina", "vancomicina", "Antibiótico glicopéptido", "Antibiótico utilizado para tratar determinadas infecciones bacterianas.", "Endovenosa / oral", "mg"),
    med("Ceftriaxona", "ceftriaxona", "Antibiótico cefalosporínico", "Antibiótico utilizado para tratar determinadas infecciones bacterianas.", "Endovenosa / intramuscular", "mg"),
    med("Cefotaxima", "cefotaxima", "Antibiótico cefalosporínico", "Antibiótico utilizado para tratar determinadas infecciones bacterianas.", "Endovenosa", "mg"),
    med("Aciclovir", "aciclovir", "Antiviral", "Antiviral utilizado para tratar determinadas infecciones por virus herpes.", "Oral / endovenosa", "mg"),
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

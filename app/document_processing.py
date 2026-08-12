
from __future__ import annotations

import io
import os
import re
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(int(os.getenv("MAX_UPLOAD_MB", "12")) * 1024 * 1024)))
MAX_OCR_PAGES = int(os.getenv("MAX_OCR_PAGES", "8"))


def safe_filename(value: str) -> str:
    name = Path(value or "documento").name.replace("\x00", "")
    name = re.sub(r'[\x00-\x1f\x7f"\\]', "_", name).strip()
    return name[:240] or "documento"


def validate_upload(filename: str, mime_type: str, data: bytes) -> None:
    if not data:
        raise ValueError("El archivo está vacío.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"El archivo supera el máximo permitido de {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if mime_type not in ALLOWED_MIME_TYPES:
        raise ValueError("Solo se permiten PDF, JPEG, PNG o WebP.")
    suffix = Path(filename).suffix.lower()
    expected = {
        "application/pdf": {".pdf"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/png": {".png"},
        "image/webp": {".webp"},
    }[mime_type]
    if suffix and suffix not in expected:
        raise ValueError("La extensión del archivo no coincide con el tipo declarado.")


def extract_text(data: bytes, mime_type: str) -> tuple[str, str, str | None]:
    """Devuelve (texto, estado, error). OCR se ejecuta localmente en el servidor."""
    try:
        if mime_type == "application/pdf":
            text = _extract_pdf_text(data)
            if len(text.strip()) >= 80:
                return text.strip(), "text_extracted", None
            ocr = _ocr_pdf(data)
            merged = "\n\n".join(part for part in (text.strip(), ocr.strip()) if part)
            if merged:
                return merged, "ocr_completed", None
            return "", "no_text_detected", None

        if mime_type.startswith("image/"):
            text = _ocr_image(data)
            return text.strip(), "ocr_completed" if text.strip() else "no_text_detected", None
    except Exception as exc:  # El archivo se conserva aunque falle la extracción.
        # Mantiene un estado público simple/estable; el detalle técnico queda en extraction_error/logs.
        return "", "failed", str(exc)[:500]

    return "", "unsupported", "Tipo de archivo no soportado para extracción."


def _extract_pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    for page in reader.pages[:MAX_OCR_PAGES]:
        chunks.append(page.extract_text() or "")
    return "\n\n".join(chunks)


def _ocr_image(data: bytes) -> str:
    import pytesseract

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        return pytesseract.image_to_string(image, lang="spa+eng")


def _ocr_pdf(data: bytes) -> str:
    import fitz
    import pytesseract

    document = fitz.open(stream=data, filetype="pdf")
    chunks: list[str] = []
    for index in range(min(len(document), MAX_OCR_PAGES)):
        page = document.load_page(index)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        chunks.append(pytesseract.image_to_string(image, lang="spa+eng"))
    return "\n\n".join(chunks)


def sanitize_profile_photo(data: bytes, mime_type: str) -> tuple[bytes, str]:
    """Elimina EXIF y limita tamaño de foto de perfil; no se usa para exámenes."""
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("La foto de perfil debe ser JPEG, PNG o WebP.")
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        image.thumbnail((1024, 1024))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        output = io.BytesIO()
        if image.mode == "RGBA":
            image.save(output, format="PNG", optimize=True)
            return output.getvalue(), "image/png"
        image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue(), "image/jpeg"

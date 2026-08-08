# IkerCare 2.0

IkerCare 2.0 es una plataforma familiar de seguimiento de salud orientada a cuidadores y padres. Permite administrar varios usuarios y pacientes, registrar tratamientos y cuidados diarios, conservar documentos clínicos y compartir resúmenes temporales de forma controlada.

> **Importante:** IkerCare es una herramienta de apoyo familiar y organización. No reemplaza la ficha clínica oficial, las indicaciones médicas, una alarma clínica, un diagnóstico ni las instrucciones del equipo tratante.

## Novedades principales de la versión 2.0

- Arquitectura multiusuario y multipaciente.
- Roles por paciente: propietario, editor y lector.
- Login y registro desde la APK Android.
- Recordatorios locales Android para horarios de medicamentos.
- Registro de pañales, orina y deposiciones.
- Registro de alimentación, tolerancia y vómitos.
- Equipo tratante con médicos, especialidades, hospitales y contacto.
- Catálogo de medicamentos con autocompletado de nombre, tipo y uso general; **no completa dosis**.
- Carga de exámenes e informes en PDF e imágenes.
- Extracción de texto de PDF y OCR local para documentos escaneados o fotografías.
- Cifrado de archivos clínicos y fotografías del paciente con AES-GCM.
- Foto y ficha del paciente.
- Hospitalizaciones y línea de tiempo clínica.
- Resúmenes simples o completos, filtrables por fechas u hospitalización.
- Resúmenes en español o inglés.
- Enlaces/QR temporales y revocables para compartir resúmenes.
- Auditoría de acciones y controles de acceso por paciente.
- Eliminación de cuenta/paciente y consentimientos versionados.
- Cabeceras de seguridad, cookies seguras, CSRF y límites básicos de login.
- Android target/compile SDK 36.

## Arquitectura recomendada

Para despliegue en Internet:

```text
Android / navegador
        ↓ HTTPS
Render / servicio FastAPI
        ↓ TLS
Neon PostgreSQL
```

Los documentos se cifran antes de almacenarse. Para una publicación comercial a gran escala se recomienda migrar posteriormente los archivos a almacenamiento de objetos privado con URLs firmadas y gestión de claves dedicada.

## Requisitos

Para desarrollo local:

- Python 3.12+
- Docker Desktop o Docker Engine + Docker Compose
- Git

Comprueba:

```bash
git --version
docker --version
docker compose version
```

## Configuración local

Copia el archivo de ejemplo:

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### Linux/macOS/WSL

```bash
cp .env.example .env
```

Genera una clave de sesión:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Genera la clave de cifrado de archivos:

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Configura como mínimo en `.env`:

```env
SECRET_KEY=...
FIELD_ENCRYPTION_KEY=...
ADMIN_USERNAME=alexis
ADMIN_PASSWORD=...
CHILD_NAME=Iker
APP_TIMEZONE=America/Santiago
COOKIE_SECURE=false
SEED_SAMPLE_DATA=true
```

> **No pierdas `FIELD_ENCRYPTION_KEY`.** Los documentos cifrados con una clave anterior no se podrán recuperar si la cambias sin una migración de claves.

Levanta la aplicación:

```powershell
docker compose up -d --build
```

Abre:

```text
http://localhost:8080
```

La raíz redirige a la experiencia V2.

## Despliegue en Render + Neon

En producción usa una base PostgreSQL externa y configura en Render:

```env
DATABASE_URL=postgresql+psycopg://...
SECRET_KEY=...
FIELD_ENCRYPTION_KEY=...
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
CHILD_NAME=...
APP_TIMEZONE=America/Santiago
COOKIE_SECURE=true
SEED_SAMPLE_DATA=true
PUBLIC_BASE_URL=https://TU-SERVICIO.onrender.com
MAX_UPLOAD_MB=12
OCR_MAX_PAGES=8
LEGAL_ENTITY_NAME=...
PRIVACY_CONTACT_EMAIL=...
SECURITY_CONTACT_EMAIL=...
```

Health check:

```text
/health
```

## APK Android 2.0

El proyecto Android está en `android-wrapper/`.

La APK V2:

- usa una URL de servidor configurada en `BuildConfig`;
- presenta login/registro nativo;
- mantiene la sesión con cookies;
- sincroniza los horarios de medicamentos con recordatorios locales;
- solicita permiso de notificaciones cuando corresponde;
- reconstruye recordatorios tras reinicio del dispositivo;
- carga la interfaz V2 dentro de WebView endurecido para producción HTTPS.

Antes de compilar para tu servidor, actualiza `IKERCARE_BASE_URL` en:

```text
android-wrapper/app/build.gradle.kts
```

Ejemplo:

```kotlin
buildConfigField("String", "IKERCARE_BASE_URL", "\"https://ikercare-v2.onrender.com\"")
```

### Generar APK con GitHub Actions

1. Sube el repositorio a GitHub.
2. Entra en **Actions > Build Android APK**.
3. Ejecuta **Run workflow**.
4. Descarga el artefacto `IkerCare-Android-v2-debug`.
5. Descomprime e instala `app-debug.apk`.

Para publicación en Google Play se debe generar y firmar un **AAB release**, no distribuir el APK debug como versión comercial.

## Documentos y OCR

Tipos admitidos incluyen PDF e imágenes comunes. Los documentos se validan, cifran y el sistema intenta extraer texto:

```text
PDF con texto → extracción directa
PDF escaneado / imagen → OCR local
```

El OCR es una ayuda de transcripción y puede contener errores. El texto extraído debe verificarse contra el documento original antes de utilizarlo como referencia clínica.

## Medicamentos

El autocompletado usa un catálogo de referencia para completar nombre, categoría y finalidad general. Por seguridad:

- no calcula dosis;
- no recomienda dosis;
- no decide si debe administrarse un medicamento;
- no reemplaza la indicación vigente del equipo clínico.

## Privacidad y seguridad

La V2 incorpora controles técnicos iniciales para información sensible:

- autorización por paciente en backend;
- roles y auditoría;
- CSRF;
- cookies seguras en HTTPS;
- cifrado AES-GCM de documentos y fotos;
- cabeceras de seguridad;
- límites de tamaño y OCR;
- enlaces compartidos temporales y revocables;
- separación entre usuarios/pacientes;
- eliminación de cuenta/paciente.

Consulta también:

```text
SECURITY.md
docs/LEGAL_AND_PRIVACY_CL.md
docs/PRIVACY_POLICY_TEMPLATE.md
docs/PLAY_STORE_CHECKLIST.md
docs/THREAT_MODEL.md
```

Antes de publicar comercialmente se recomienda revisión jurídica chilena, pentest, recuperación de contraseña, verificación de correo, almacenamiento de objetos privado, gestión de secretos/KMS, backups probados, monitoreo y respuesta a incidentes.

## Pruebas

```bash
pytest -q
```

GitHub Actions también ejecuta pruebas automáticas.

## Estructura principal

```text
iker-care-tracker/
├── app/
│   ├── main.py
│   ├── v2_main.py
│   ├── v2_router.py
│   ├── models.py
│   ├── auth.py
│   ├── db.py
│   ├── templates/
│   └── static/
├── android-wrapper/
├── docs/
├── tests/
├── scripts/
├── SECURITY.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── VERSION
```

## Versión

```text
2.0.0
```

## Licencia

MIT.

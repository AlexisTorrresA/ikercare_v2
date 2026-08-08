# Threat model resumido — IkerCare 2

## Activos críticos

1. Identidad y credenciales de usuarios.
2. Datos clínicos, medicamentos, crisis, signos y alimentación.
3. Documentos/imágenes de exámenes y fotografías.
4. Relaciones cuidador-paciente y permisos.
5. Tokens de compartición.
6. Claves de sesión y cifrado.

## Amenazas principales

- credential stuffing y fuerza bruta;
- IDOR/BOLA entre pacientes;
- robo de sesión/XSS/CSRF;
- exposición accidental de archivos clínicos;
- QR reenviado o capturado;
- subida de archivo malicioso;
- abuso de cuentas compartidas;
- filtración en logs/backups/analítica;
- compromiso de proveedor cloud;
- extracción de secretos desde repositorio/CI;
- alteración concurrente de datos por múltiples cuidadores;
- recomendaciones médicas incorrectas generadas automáticamente.

## Decisiones de diseño

- todos los recursos clínicos llevan `patient_id` y se autorizan en servidor;
- enlaces públicos son read-only, temporales y revocables;
- documentos se cifran antes de persistir y no son públicos;
- autocompletado farmacológico usa catálogo curado; no propone dosis;
- IA sobre datos clínicos está deshabilitada por defecto;
- notificaciones Android se presentan como recordatorios de apoyo, no como alarma clínica;
- operaciones sensibles quedan en auditoría;
- la colaboración V2 usa detección de cambios periódica para evitar complejidad de sockets en hosting gratuito; la consistencia final sigue en PostgreSQL.

# Seguridad de IkerCare 2

IkerCare procesa datos de salud. El objetivo es reducir el riesgo mediante defensa en profundidad; ningún sistema puede prometer ser “inhackeable”.

## Controles implementados en V2

- HTTPS obligatorio en Android productivo; tráfico HTTP deshabilitado.
- Cookies de sesión `Secure` en producción, `SameSite=Lax` y CSRF para operaciones autenticadas.
- PBKDF2-SHA256 para contraseñas del sistema legado; plan de migración a Argon2id antes del lanzamiento masivo.
- Separación multiusuario/multipaciente y RBAC (`owner`, `editor`, `viewer`).
- Autorización comprobada en servidor; la interfaz nunca se considera frontera de seguridad.
- AES-GCM para documentos y fotografías almacenados por la aplicación.
- Hash SHA-256 de archivos para integridad/deduplicación futura.
- Validación de MIME, tamaño y límites de páginas OCR.
- OCR local en servidor por defecto; no se envían exámenes automáticamente a un proveedor de IA.
- Auditoría de creación/cambio/compartición/borrado.
- Enlaces de compartición con token aleatorio, hash almacenado, vencimiento, revocación y `noindex/no-store`.
- Cabeceras CSP, HSTS, X-Content-Type-Options, Referrer-Policy y Permissions-Policy.
- Rate limit básico del login. Para producción con escala debe migrar a Redis/WAF/rate limit distribuido.
- Android WebView sin acceso a archivos/contenido local, sin mixed content y con enlaces externos fuera de la WebView.
- Backups Android deshabilitados para evitar copiar sesiones/datos de la app mediante mecanismos de backup del sistema.

## Pendientes obligatorios antes de Google Play / producción masiva

- Argon2id o proveedor de identidad administrado con email verificado, recuperación segura y MFA/passkeys opcional.
- Rate limiting distribuido y protección WAF/bot.
- Escaneo antimalware de documentos (por ejemplo, servicio AV aislado) antes de servir archivos a terceros.
- Mover blobs clínicos desde PostgreSQL a almacenamiento de objetos privado cifrado con URLs firmadas y política de ciclo de vida.
- Rotación/versionado de claves; KMS/secret manager; no guardar claves en repositorio.
- Backups cifrados, pruebas de restauración y objetivos RPO/RTO.
- SAST, dependency scanning, secret scanning, DAST y pentest externo antes de producción.
- Logs sin PII clínica, alertas de acceso anómalo, plan de respuesta a incidentes y canal de reporte de vulnerabilidades.
- Sesiones revocables por dispositivo y registro de dispositivos.
- Verificación de email y flujo seguro de recuperación de cuenta.
- Revisión de seguridad de cada proveedor y contrato de tratamiento/subtratamiento.

## Reporte responsable

Antes del lanzamiento público se debe configurar un correo real de seguridad y publicar `/.well-known/security.txt`.

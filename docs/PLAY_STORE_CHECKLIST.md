# Checklist Google Play — IkerCare 2

## Técnico

- [x] `targetSdk`/`compileSdk` 36 en V2.
- [x] HTTPS-only en Android productivo.
- [x] Permiso de notificaciones solicitado en runtime.
- [ ] Crear clave de firma de producción y guardar secretos fuera del repositorio.
- [ ] Generar AAB firmado de release (no publicar el APK debug de CI).
- [ ] Configurar Play App Signing.
- [ ] Pruebas internas/cerradas en dispositivos Android reales.
- [ ] Automated pre-launch report sin errores críticos.

## Salud y privacidad

- [ ] Health Apps declaration: declarar gestión de medicamentos/tratamientos, seguimiento de salud y las demás categorías que correspondan al comportamiento final.
- [ ] Privacy Policy pública, completa, no editable, accesible dentro de la app y desde Play Console.
- [ ] Data Safety consistente con SDKs, hosting, archivos, identificadores y datos de salud realmente tratados.
- [x] Ruta de eliminación dentro de la app.
- [x] Recurso web `/account/delete`; antes de publicar agregar canal real para usuarios bloqueados fuera de su cuenta.
- [ ] Completar identidad del responsable, correo de privacidad y soporte.
- [ ] Disclaimer no dispositivo médico / no diagnóstico / no reemplaza profesional de salud en onboarding, ficha Play y áreas relevantes.
- [ ] Revisar clasificación de contenido/edad y público objetivo. No diseñar la cuenta para que un niño pequeño sea el usuario contractual.

## Seguridad/operaciones

- [ ] Base de datos y almacenamiento productivos con backups probados.
- [ ] KMS/secret manager y rotación de claves.
- [ ] WAF/rate limit distribuido.
- [ ] Escaneo de archivos y pentest.
- [ ] Plan y contacto de respuesta a incidentes.
- [ ] Política de retención/borrado respaldada por procesos automáticos.

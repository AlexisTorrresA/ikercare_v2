# Migración 1.2 → 2.0

La V2 fue diseñada para probarse en una rama antes de reemplazar la aplicación que ya está en Render.

## 1. Respaldo

Antes del primer despliegue V2 realiza un backup de Neon desde las herramientas del proveedor y, si tienes una copia local, conserva también un `pg_dump`.

## 2. Secretos nuevos de Render

Agrega sin eliminar tus variables actuales:

- `FIELD_ENCRYPTION_KEY`: 32 bytes aleatorios codificados en base64 URL-safe.
- `PUBLIC_BASE_URL=https://care-app-j73n.onrender.com` (o tu dominio definitivo).
- `LEGAL_ENTITY_NAME` (antes del lanzamiento público).
- `PRIVACY_CONTACT_EMAIL` (antes del lanzamiento público).
- `SECURITY_CONTACT_EMAIL` (antes del lanzamiento público).
- `COOKIE_SECURE=true`.

Generador de clave:

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Guárdala también en un gestor de secretos fuera de Render. Si se pierde, no podrán descifrarse los documentos/fotos existentes.

## 3. Tablas y datos

La V2 crea nuevas tablas con prefijo `care_` usando SQLAlchemy. No borra las tablas V1. La primera apertura de V2 migra una copia de medicamentos, tomas, quimioterapia, signos, crisis y notas al paciente histórico.

Por seguridad, el paciente V1 se asigna **solo** al usuario que coincide con `ADMIN_USERNAME`; los usuarios nuevos nunca reciben acceso automático al paciente histórico.

## 4. Despliegue gradual recomendado

1. Deploy de la rama V2 a un servicio Render de staging o Preview Environment.
2. Probar login, datos históricos y creación de paciente.
3. Probar carga/descarga de un documento no real.
4. Probar QR con expiración corta y revocación.
5. Construir APK debug y probar notificaciones en dos teléfonos.
6. Revisar seguridad/legal.
7. Recién entonces fusionar a `main` y desplegar producción.

## 5. Rollback

Como V1 se conserva en tablas originales, un rollback del código a 1.2 puede seguir usando los datos V1 existentes. Los registros nuevos creados exclusivamente en tablas `care_*` no aparecerán en V1. Por eso, después de comenzar uso real en V2, el rollback debe tratarse como emergencia y considerar exportación/migración inversa.

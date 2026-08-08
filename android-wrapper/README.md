# IkerCare Android 2.0

Cliente Android de IkerCare 2.0. La APK se conecta al backend HTTPS de IkerCare y presenta autenticación nativa antes de cargar la experiencia principal.

## Cambios respecto de 1.2

- La URL del servidor se configura en `BuildConfig`; ya no se solicita una IP local al usuario final.
- Login y registro desde Android.
- Recordatorios locales de medicamentos.
- Solicitud de permiso de notificaciones.
- Reprogramación de recordatorios tras reinicio.
- WebView endurecido para HTTPS de producción.
- `compileSdk` y `targetSdk` 36.
- `versionName` 2.0.0.

## Configurar servidor

Edita:

```text
app/build.gradle.kts
```

y cambia:

```kotlin
buildConfigField("String", "IKERCARE_BASE_URL", "\"https://TU-SERVIDOR.onrender.com\"")
```

No uses `localhost` ni una IP privada si la APK será distribuida públicamente.

## Crear APK con GitHub Actions

1. Sube el proyecto completo a GitHub.
2. Abre **Actions**.
3. Selecciona **Build Android APK**.
4. Ejecuta **Run workflow** sobre `main`.
5. Descarga el artefacto `IkerCare-Android-v2-debug`.
6. Descomprime e instala `app-debug.apk`.

## Android Studio

Abre la carpeta `android-wrapper` como proyecto y sincroniza Gradle. Para una APK de desarrollo usa **Build APK(s)**.

Para Google Play debe configurarse firma de release y generar un **Android App Bundle (.aab)** firmado.

## Seguridad

- La versión de producción debe usar HTTPS.
- No deshabilites la validación TLS.
- Mantén `android:allowBackup="false"` para datos sensibles.
- No guardes contraseñas o secretos del backend en el repositorio.
- La URL del servidor no es un secreto; las claves de base de datos y cifrado sí lo son.

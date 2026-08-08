# IkerCare 2 — notas legales y de privacidad para Chile (borrador técnico)

> Documento de ingeniería, no asesoría jurídica. Antes de publicar la aplicación a terceros debe ser revisado por un abogado chileno especializado en privacidad/salud digital y completado con la identidad real del responsable del tratamiento, contactos, proveedores y plazos de conservación.

## Posicionamiento del producto

IkerCare debe describirse como **organizador personal/familiar de salud y apoyo al cuidado**. No debe presentarse como la ficha clínica oficial de un prestador, dispositivo médico, sistema de diagnóstico, prescriptor, calculador de dosis ni sustituto de indicaciones del equipo tratante.

## Datos especialmente protegidos

La aplicación trata información de salud y puede tratar datos de niños, niñas y adolescentes. El diseño V2 incorpora:

- consentimiento/aceptación versionada;
- declaración de autorización o representación para administrar el perfil;
- control de acceso por paciente;
- minimización de permisos Android;
- cifrado de documentos y fotografías;
- enlaces de compartición temporales y revocables;
- auditoría de acciones relevantes;
- eliminación de cuenta y paciente;
- textos comprensibles y avisos de uso no clínico.

## Marco chileno a validar antes de lanzamiento

- Ley N.º 19.628 y sus modificaciones.
- Ley N.º 21.719, que entra en vigor el 1 de diciembre de 2026 y crea la Agencia de Protección de Datos Personales.
- Ley N.º 21.430 sobre garantías y protección integral de los derechos de la niñez y adolescencia.
- Ley N.º 20.584 sobre derechos y deberes de las personas en relación con acciones vinculadas a su atención de salud.
- Ley N.º 21.663 Marco de Ciberseguridad, según corresponda al rol/actividad del responsable y proveedores.
- Reglas contractuales y de transferencia internacional aplicables a los proveedores cloud utilizados.

## Antes de producción pública

1. Identificar responsable del tratamiento y domicilio/contacto de privacidad.
2. Definir bases de licitud y finalidades por cada categoría de datos.
3. Documentar proveedores/subencargados (hosting, base de datos, correo, analítica, IA si se habilita).
4. Realizar una evaluación de impacto de privacidad y seguridad por tratar datos de salud y menores.
5. Definir retención/borrado, backups y restauración.
6. Definir procedimiento de ejercicio de derechos, verificación de identidad y respuesta a incidentes.
7. Definir mecanismo de autorización de padres/representantes/cuidadores y manejo de conflictos de custodia/representación.
8. Revisar transferencias internacionales y contratos con proveedores.
9. No habilitar IA de terceros sobre documentos clínicos hasta completar consentimiento específico, evaluación de proveedor y condiciones contractuales.
10. Validar textos de Play Store, política de privacidad y Data Safety contra el comportamiento real de la app.

## Compartición por QR

Un QR de IkerCare no debe considerarse equivalente a un mecanismo formal de interoperabilidad hospitalaria ni a una autorización legal universal. Es una herramienta voluntaria del usuario para compartir un resumen de solo lectura. Los enlaces deben:

- usar tokens de alta entropía;
- expirar;
- poder revocarse;
- no incluir datos clínicos directamente en el QR;
- evitar indexación y caché;
- registrar accesos de forma mínima;
- permitir compartir solo lo estrictamente necesario.

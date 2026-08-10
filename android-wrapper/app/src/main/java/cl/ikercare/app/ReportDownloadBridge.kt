package cl.ikercare.app

import android.content.ContentValues
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import android.webkit.JavascriptInterface
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import java.io.File
import java.io.FileOutputStream

class ReportDownloadBridge(private val activity: AppCompatActivity) {
    @JavascriptInterface
    fun savePdf(fileName: String, base64Data: String) {
        Thread {
            try {
                val safeName = fileName.replace(Regex("[^A-Za-z0-9._-]"), "_").ifBlank { "IkerCare-informe.pdf" }
                val data = Base64.decode(base64Data, Base64.DEFAULT)

                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val resolver = activity.contentResolver
                    val values = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, safeName)
                        put(MediaStore.MediaColumns.MIME_TYPE, "application/pdf")
                        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/IkerCare")
                        put(MediaStore.MediaColumns.IS_PENDING, 1)
                    }
                    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                        ?: throw IllegalStateException("No se pudo crear el archivo PDF")
                    resolver.openOutputStream(uri)?.use { it.write(data) }
                        ?: throw IllegalStateException("No se pudo escribir el archivo PDF")
                    values.clear()
                    values.put(MediaStore.MediaColumns.IS_PENDING, 0)
                    resolver.update(uri, values, null, null)
                } else {
                    val directory = activity.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS) ?: activity.filesDir
                    if (!directory.exists()) directory.mkdirs()
                    FileOutputStream(File(directory, safeName)).use { it.write(data) }
                }

                activity.runOnUiThread {
                    Toast.makeText(activity, "PDF guardado en Descargas/IkerCare", Toast.LENGTH_LONG).show()
                }
            } catch (_: Exception) {
                activity.runOnUiThread {
                    Toast.makeText(activity, "No se pudo guardar el PDF", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }
}

package cl.ikercare.app

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.MediaStore
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.FileProvider
import java.io.File

class IkerCareWebChromeClient(
    private val activity: AppCompatActivity,
    private val onProgress: (Int) -> Unit,
) : WebChromeClient() {
    private var pendingCallback: ValueCallback<Array<Uri>>? = null
    private var cameraUri: Uri? = null

    private val launcher = activity.activityResultRegistry.register(
        "ikercare_document_file_chooser",
        activity,
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val callback = pendingCallback ?: return@register
        val uris = mutableListOf<Uri>()
        if (result.resultCode == Activity.RESULT_OK) {
            val data = result.data
            val clip = data?.clipData
            if (clip != null) {
                for (index in 0 until clip.itemCount) uris.add(clip.getItemAt(index).uri)
            } else if (data?.data != null) {
                uris.add(data.data!!)
            } else {
                cameraUri?.let { uris.add(it) }
            }
        }
        callback.onReceiveValue(if (uris.isEmpty()) null else uris.take(10).toTypedArray())
        pendingCallback = null
        cameraUri = null
    }

    override fun onProgressChanged(view: WebView?, newProgress: Int) {
        onProgress(newProgress)
    }

    override fun onShowFileChooser(
        webView: WebView?,
        filePathCallback: ValueCallback<Array<Uri>>?,
        fileChooserParams: FileChooserParams?,
    ): Boolean {
        if (filePathCallback == null) return false
        pendingCallback?.onReceiveValue(null)
        pendingCallback = filePathCallback

        val contentIntent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/pdf", "image/jpeg", "image/png", "image/webp"))
        }

        val cameraDirectory = File(activity.cacheDir, "camera_uploads").apply { mkdirs() }
        val cameraFile = File.createTempFile("ikercare_exam_", ".jpg", cameraDirectory)
        cameraUri = FileProvider.getUriForFile(
            activity,
            "${activity.packageName}.fileprovider",
            cameraFile,
        )
        val cameraIntent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
            putExtra(MediaStore.EXTRA_OUTPUT, cameraUri)
            addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }

        val chooser = Intent.createChooser(contentIntent, "Seleccionar examen, informe o foto").apply {
            putExtra(Intent.EXTRA_INITIAL_INTENTS, arrayOf(cameraIntent))
        }
        return try {
            launcher.launch(chooser)
            true
        } catch (_: Exception) {
            pendingCallback?.onReceiveValue(null)
            pendingCallback = null
            cameraUri = null
            false
        }
    }
}

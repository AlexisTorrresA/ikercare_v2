package cl.ikercare.app

import android.Manifest
import android.app.DownloadManager
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.webkit.CookieManager
import android.webkit.DownloadListener
import android.webkit.ServiceWorkerController
import android.webkit.URLUtil
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private lateinit var swipeRefresh: SwipeRefreshLayout
    private lateinit var progressBar: ProgressBar
    private lateinit var errorPanel: LinearLayout
    private lateinit var loginPanel: ScrollView
    private lateinit var loginProgress: ProgressBar
    private lateinit var usernameInput: EditText
    private lateinit var passwordInput: EditText
    private val serverUrl = BuildConfig.IKERCARE_BASE_URL.trimEnd('/')

    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        swipeRefresh = findViewById(R.id.swipeRefresh)
        progressBar = findViewById(R.id.progressBar)
        errorPanel = findViewById(R.id.errorPanel)
        loginPanel = findViewById(R.id.loginPanel)
        loginProgress = findViewById(R.id.loginProgress)
        usernameInput = findViewById(R.id.usernameInput)
        passwordInput = findViewById(R.id.passwordInput)

        configureWebView()
        requestNotificationPermissionIfNeeded()

        swipeRefresh.setOnRefreshListener { loadFreshApp() }
        findViewById<Button>(R.id.retryButton).setOnClickListener { loadFreshApp() }
        findViewById<Button>(R.id.errorLogoutButton).setOnClickListener { showNativeLogin(clearSession = true) }
        findViewById<Button>(R.id.loginButton).setOnClickListener { performLogin() }
        findViewById<Button>(R.id.registerButton).setOnClickListener { showRegistrationDialog() }
        findViewById<Button>(R.id.privacyButton).setOnClickListener {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$serverUrl/privacy")))
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                when {
                    loginPanel.visibility == View.VISIBLE -> finish()
                    webView.canGoBack() -> webView.goBack()
                    else -> finish()
                }
            }
        })

        if (CookieManager.getInstance().getCookie(serverUrl).isNullOrBlank()) {
            showNativeLogin(clearSession = false)
        } else {
            loadFreshApp()
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    @Suppress("SetJavaScriptEnabled")
    private fun configureWebView() {
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            cacheMode = WebSettings.LOAD_NO_CACHE
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            builtInZoomControls = false
            displayZoomControls = false
            allowFileAccess = false
            allowContentAccess = true
            userAgentString = "$userAgentString IkerCareAndroid/2.0.4"
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            ServiceWorkerController.getInstance().serviceWorkerWebSettings.cacheMode = WebSettings.LOAD_NO_CACHE
        }
        webView.clearCache(true)
        webView.addJavascriptInterface(NativeBridge(), "IkerCareNative")
        webView.webChromeClient = IkerCareWebChromeClient(this) { newProgress ->
            progressBar.progress = newProgress
            progressBar.visibility = if (newProgress in 1..99) View.VISIBLE else View.GONE
            if (newProgress == 100) swipeRefresh.isRefreshing = false
        }
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val uri = request?.url ?: return false
                val base = Uri.parse(serverUrl)
                val sameServer = base.scheme == uri.scheme && base.host == uri.host && effectivePort(base) == effectivePort(uri)
                if (uri.scheme == "tel" || uri.scheme == "mailto") {
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                    return true
                }
                if ((uri.scheme == "https" || uri.scheme == "http") && !sameServer) {
                    startActivity(Intent(Intent.ACTION_VIEW, uri))
                    return true
                }
                return false
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                swipeRefresh.isRefreshing = false
                errorPanel.visibility = View.GONE
                val path = runCatching { Uri.parse(url).path.orEmpty() }.getOrDefault("")
                if (path == "/login" || path.startsWith("/login/")) {
                    showNativeLogin(clearSession = false)
                    return
                }
                loginPanel.visibility = View.GONE
                swipeRefresh.visibility = View.VISIBLE
                webView.visibility = View.VISIBLE
                view?.evaluateJavascript("document.documentElement.classList.add('native-app');", null)
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) showConnectionError()
            }
        }

        webView.setDownloadListener(DownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            try {
                val fileName = URLUtil.guessFileName(url, contentDisposition, mimeType)
                val request = DownloadManager.Request(Uri.parse(url)).apply {
                    setMimeType(mimeType)
                    addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url))
                    addRequestHeader("User-Agent", userAgent)
                    setTitle(fileName)
                    setDescription("Descarga segura desde IkerCare")
                    setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName)
                }
                (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
                Toast.makeText(this, "Descarga iniciada", Toast.LENGTH_SHORT).show()
            } catch (_: Exception) {
                Toast.makeText(this, "No se pudo iniciar la descarga", Toast.LENGTH_LONG).show()
            }
        })
    }

    private fun effectivePort(uri: Uri): Int {
        if (uri.port >= 0) return uri.port
        return if (uri.scheme == "https") 443 else 80
    }

    private fun performLogin() {
        val username = usernameInput.text.toString().trim()
        val password = passwordInput.text.toString()
        if (username.isBlank() || password.isBlank()) {
            Toast.makeText(this, "Completa usuario y contraseña", Toast.LENGTH_SHORT).show()
            return
        }
        setLoginBusy(true)
        val payload = JSONObject().put("username", username).put("password", password)
        postAuth("/api/v2/auth/native-login", payload) { ok, message ->
            setLoginBusy(false)
            if (ok) {
                passwordInput.setText("")
                loadFreshApp()
            } else {
                Toast.makeText(this, message, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun showRegistrationDialog() {
        val density = resources.displayMetrics.density
        val padding = (20 * density).toInt()
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(padding, 0, padding, 0)
        }
        fun field(hint: String, password: Boolean = false): EditText = EditText(this).apply {
            this.hint = hint
            inputType = if (password) android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD else android.text.InputType.TYPE_CLASS_TEXT
            container.addView(this)
        }
        val displayName = field("Nombre para mostrar")
        val username = field("Usuario")
        val email = field("Correo")
        val password = field("Contraseña (mínimo 12 caracteres, letras y números)", password = true)
        val privacy = CheckBox(this).apply {
            text = "Acepto la política de privacidad y el tratamiento de datos sensibles descrito."
            container.addView(this)
        }
        val guardian = CheckBox(this).apply {
            text = "Declaro que soy titular o tengo autorización/representación suficiente para administrar los datos de los pacientes que incorporaré."
            container.addView(this)
        }

        val dialog = AlertDialog.Builder(this)
            .setTitle("Crear cuenta")
            .setMessage("No ingreses datos de un menor si no estás autorizado para administrarlos.")
            .setView(container)
            .setPositiveButton("Crear", null)
            .setNegativeButton("Cancelar", null)
            .setNeutralButton("Ver privacidad") { _, _ -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$serverUrl/privacy"))) }
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                if (!privacy.isChecked || !guardian.isChecked) {
                    Toast.makeText(this, "Debes revisar y aceptar las condiciones", Toast.LENGTH_LONG).show()
                    return@setOnClickListener
                }
                val payload = JSONObject()
                    .put("display_name", displayName.text.toString().trim().ifBlank { username.text.toString().trim() })
                    .put("username", username.text.toString().trim())
                    .put("email", email.text.toString().trim())
                    .put("password", password.text.toString())
                    .put("accept_privacy", true)
                    .put("guardian_attestation", true)
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = false
                postAuth("/api/v2/auth/register", payload) { ok, message ->
                    if (ok) {
                        dialog.dismiss()
                        loadFreshApp()
                    } else {
                        dialog.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled = true
                        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
                    }
                }
            }
        }
        dialog.show()
    }

    private fun postAuth(path: String, payload: JSONObject, callback: (Boolean, String) -> Unit) {
        Thread {
            var connection: HttpURLConnection? = null
            try {
                connection = (URL(serverUrl + path).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 15_000
                    readTimeout = 20_000
                    doOutput = true
                    instanceFollowRedirects = false
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    setRequestProperty("Accept", "application/json")
                    setRequestProperty("User-Agent", "IkerCareAndroid/2.0.4")
                }
                connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                val code = connection.responseCode
                val stream = if (code in 200..299) connection.inputStream else connection.errorStream
                val body = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
                if (code in 200..299) {
                    connection.headerFields
                        .filterKeys { key -> key?.equals("Set-Cookie", ignoreCase = true) == true }
                        .values.flatten()
                        .forEach { cookie -> CookieManager.getInstance().setCookie(serverUrl, cookie) }
                    CookieManager.getInstance().flush()
                    runOnUiThread { callback(true, "OK") }
                } else {
                    val detail = runCatching { JSONObject(body).optString("detail") }.getOrNull().orEmpty()
                    runOnUiThread { callback(false, detail.ifBlank { "No se pudo completar la solicitud ($code)" }) }
                }
            } catch (_: Exception) {
                runOnUiThread { callback(false, "No se pudo conectar con el servidor") }
            } finally {
                connection?.disconnect()
            }
        }.start()
    }

    private fun setLoginBusy(busy: Boolean) {
        loginProgress.visibility = if (busy) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.loginButton).isEnabled = !busy
        findViewById<Button>(R.id.registerButton).isEnabled = !busy
    }

    private fun loadFreshApp() {
        errorPanel.visibility = View.GONE
        loginPanel.visibility = View.GONE
        swipeRefresh.visibility = View.VISIBLE
        webView.visibility = View.VISIBLE
        swipeRefresh.isRefreshing = true
        webView.stopLoading()
        webView.clearCache(true)
        val versionToken = System.currentTimeMillis()
        webView.loadUrl(
            "$serverUrl/v2?native_refresh=$versionToken",
            mapOf("Cache-Control" to "no-cache, no-store, max-age=0", "Pragma" to "no-cache")
        )
    }

    private fun showNativeLogin(clearSession: Boolean) {
        if (clearSession) {
            CookieManager.getInstance().removeAllCookies(null)
            CookieManager.getInstance().flush()
        }
        swipeRefresh.isRefreshing = false
        progressBar.visibility = View.GONE
        errorPanel.visibility = View.GONE
        swipeRefresh.visibility = View.GONE
        webView.visibility = View.GONE
        loginPanel.visibility = View.VISIBLE
        setLoginBusy(false)
    }

    private fun showConnectionError() {
        swipeRefresh.isRefreshing = false
        progressBar.visibility = View.GONE
        loginPanel.visibility = View.GONE
        swipeRefresh.visibility = View.GONE
        webView.visibility = View.GONE
        errorPanel.visibility = View.VISIBLE
    }

    private inner class NativeBridge {
        @android.webkit.JavascriptInterface
        fun syncMedicationReminders(json: String) {
            runOnUiThread {
                MedicationReminderScheduler.sync(this@MainActivity, json)
            }
        }

        @android.webkit.JavascriptInterface
        fun downloadAuthenticatedFile(url: String, fileName: String, mimeType: String) {
            runOnUiThread {
                try {
                    val uri = Uri.parse(url)
                    val base = Uri.parse(serverUrl)
                    val sameServer = base.scheme == uri.scheme && base.host == uri.host && effectivePort(base) == effectivePort(uri)
                    if (!sameServer || !uri.path.orEmpty().startsWith("/api/v2/")) {
                        Toast.makeText(this@MainActivity, "Descarga no permitida", Toast.LENGTH_LONG).show()
                        return@runOnUiThread
                    }
                    val safeName = fileName.ifBlank { URLUtil.guessFileName(url, null, mimeType) }
                    val request = DownloadManager.Request(uri).apply {
                        setMimeType(mimeType.ifBlank { "application/octet-stream" })
                        addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url))
                        addRequestHeader("User-Agent", webView.settings.userAgentString)
                        setTitle(safeName)
                        setDescription("Descarga segura desde IkerCare")
                        setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                        setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, safeName)
                    }
                    (getSystemService(DOWNLOAD_SERVICE) as DownloadManager).enqueue(request)
                    Toast.makeText(this@MainActivity, "Descarga iniciada", Toast.LENGTH_SHORT).show()
                } catch (_: Exception) {
                    Toast.makeText(this@MainActivity, "No se pudo iniciar la descarga", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    override fun onDestroy() {
        webView.removeJavascriptInterface("IkerCareNative")
        webView.destroy()
        super.onDestroy()
    }
}

package com.chauhan.clipping

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.view.WindowManager
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.webkit.WebViewAssetLoader
import java.io.File
import java.io.FileInputStream

class MainActivity : ComponentActivity() {
    lateinit var web: WebView
    lateinit var bridge: Bridge
    private var pickCallback: ((Uri?) -> Unit)? = null
    private var storageCallback: (() -> Unit)? = null

    private val pickLauncher = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val cb = pickCallback
        pickCallback = null
        cb?.invoke(uri)
    }
    private val permLauncher = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        val cb = storageCallback
        storageCallback = null
        cb?.invoke()
    }
    private val settingsLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        val cb = storageCallback
        storageCallback = null
        cb?.invoke()
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = 0xFF0E0E0E.toInt()
        window.navigationBarColor = 0xFF0E0E0E.toInt()
        WebView.setWebContentsDebuggingEnabled(true)
        web = WebView(this)
        setContentView(web)
        bridge = Bridge(this)
        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
            allowContentAccess = false
            cacheMode = WebSettings.LOAD_DEFAULT
            textZoom = 100
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            // keep the page running at full speed while an export runs in the background
            web.setRendererPriorityPolicy(WebView.RENDERER_PRIORITY_IMPORTANT, false)
        }
        web.addJavascriptInterface(bridge, "AndroidBridge")
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url
                if (url.host == "appassets.androidplatform.net" && url.path == "/file") {
                    return serveFile(url.getQueryParameter("p") ?: "")
                }
                return loader.shouldInterceptRequest(url)
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url
                if (u.host == "appassets.androidplatform.net") return false
                try { startActivity(Intent(Intent.ACTION_VIEW, u)) } catch (e: Exception) { }
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                Log.i("CCJS", "${m.messageLevel()} ${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                return true
            }
        }
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("(window.onAndroidBack && window.onAndroidBack()) ? 'yes' : 'no'") { r ->
                    if (r == null || r.contains("no")) moveTaskToBack(true)
                }
            }
        })
        val selftest = intent?.getBooleanExtra("selftest", false) == true
        web.loadUrl("https://appassets.androidplatform.net/assets/web/index.html" + if (selftest) "#selftest" else "")
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            permLauncher.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS))
        }
    }

    private fun serveFile(path: String): WebResourceResponse {
        val f = File(path)
        if (path.isEmpty() || !f.isFile || !f.canRead()) {
            return WebResourceResponse("text/plain", "utf-8", 404, "Not Found", mapOf("Cache-Control" to "no-store"), "".byteInputStream())
        }
        val name = f.name.lowercase()
        val mime = when {
            name.endsWith(".jpg") || name.endsWith(".jpeg") -> "image/jpeg"
            name.endsWith(".png") -> "image/png"
            name.endsWith(".webp") -> "image/webp"
            name.endsWith(".gif") -> "image/gif"
            name.endsWith(".bmp") -> "image/bmp"
            name.endsWith(".mp4") -> "video/mp4"
            else -> "application/octet-stream"
        }
        return WebResourceResponse(mime, null, 200, "OK", mapOf("Cache-Control" to "no-store", "Access-Control-Allow-Origin" to "*"), FileInputStream(f))
    }

    fun pickDocument(mimes: Array<String>, cb: (Uri?) -> Unit) {
        runOnUiThread {
            pickCallback = cb
            try { pickLauncher.launch(mimes) } catch (e: Exception) { pickCallback = null; cb(null) }
        }
    }

    fun hasStorageAccess(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) Environment.isExternalStorageManager()
        else ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    }

    fun askStorage(cb: () -> Unit) {
        runOnUiThread {
            storageCallback = cb
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                    val i = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName"))
                    try { settingsLauncher.launch(i) } catch (e: Exception) {
                        settingsLauncher.launch(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                    }
                } else {
                    permLauncher.launch(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE))
                }
            } catch (e: Exception) {
                storageCallback = null
                cb()
            }
        }
    }

    fun keepScreenOn(on: Boolean) {
        runOnUiThread {
            if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    fun js(code: String) {
        runOnUiThread { try { web.evaluateJavascript(code, null) } catch (e: Exception) { } }
    }

    override fun onPause() {
        super.onPause()
        js("window.onAppPause && window.onAppPause()")
    }

    override fun onDestroy() {
        bridge.shutdown()
        super.onDestroy()
    }
}

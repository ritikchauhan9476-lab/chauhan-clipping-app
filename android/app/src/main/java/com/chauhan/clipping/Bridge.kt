package com.chauhan.clipping

import android.content.ContentUris
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Base64
import android.webkit.JavascriptInterface
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/**
 * Everything the web app asks the phone for: running FFmpeg / FFprobe, files, the phone's media, pickers,
 * playing / sharing, and keeping the phone awake during long exports. Every synchronous method returns JSON.
 */
class Bridge(private val act: MainActivity) {
    private val pool = Executors.newCachedThreadPool()
    private val procs = ConcurrentHashMap<String, Process>()

    private fun cb(id: String, json: String) = act.js("window.__bridgeCb && window.__bridgeCb(${JSONObject.quote(id)}, ${JSONObject.quote(json)})")
    private fun ok(v: Boolean) = if (v) "true" else "false"

    private fun binary(tool: String): File {
        val name = if (tool == "ffprobe") "libffprobe.so" else "libffmpeg.so"
        return File(act.applicationInfo.nativeLibraryDir, name)
    }

    // ------------------------------------------------------------------ FFmpeg
    @JavascriptInterface
    fun run(id: String, tool: String, argsJson: String) {
        pool.execute {
            val res = JSONObject()
            try {
                val arr = JSONArray(argsJson)
                val cmd = ArrayList<String>()
                cmd.add(binary(tool).absolutePath)
                for (i in 0 until arr.length()) cmd.add(arr.getString(i))
                val pb = ProcessBuilder(cmd)
                pb.directory(workDir())
                pb.environment()["TMPDIR"] = workDir().absolutePath
                val p = pb.start()
                procs[id] = p
                val out = StringBuilder()
                val outThread = Thread {
                    try { p.inputStream.bufferedReader().use { r -> val buf = CharArray(8192); while (true) { val n = r.read(buf); if (n < 0) break; out.append(buf, 0, n) } } } catch (e: Exception) { }
                }
                outThread.start()
                val err = StringBuilder()
                val batch = JSONArray()
                var last = System.currentTimeMillis()
                fun flush() {
                    if (batch.length() == 0) return
                    val lines = batch.toString()
                    act.js("(function(){var a=$lines;for(var i=0;i<a.length;i++){window.__bridgeLog&&window.__bridgeLog(${JSONObject.quote(id)},a[i]);}})()")
                    while (batch.length() > 0) batch.remove(0)
                    last = System.currentTimeMillis()
                }
                p.errorStream.bufferedReader().use { r ->
                    while (true) {
                        val line = r.readLine() ?: break
                        err.append(line).append('\n')
                        if (err.length > 3_000_000) err.delete(0, err.length - 1_500_000)
                        batch.put(line)
                        if (batch.length() >= 60 || System.currentTimeMillis() - last > 250) flush()
                    }
                }
                flush()
                val code = p.waitFor()
                outThread.join(3000)
                res.put("code", code)
                res.put("stdout", out.toString())
                res.put("stderr", if (err.length > 1_000_000) err.substring(err.length - 1_000_000) else err.toString())
            } catch (e: Exception) {
                res.put("code", -1)
                res.put("stdout", "")
                res.put("stderr", "Could not start $tool: ${e.message}")
            } finally {
                procs.remove(id)
            }
            cb(id, res.toString())
        }
    }

    @JavascriptInterface
    fun cancel(id: String) {
        val p = procs[id] ?: return
        try { p.destroy() } catch (e: Exception) { }
        pool.execute {
            try { Thread.sleep(800); if (p.isAlive) p.destroyForcibly() } catch (e: Exception) { }
        }
    }

    fun shutdown() {
        for (p in procs.values) try { p.destroyForcibly() } catch (e: Exception) { }
    }

    // ------------------------------------------------------------------ files
    fun workDir(): File = File(act.cacheDir, "work").apply { mkdirs() }

    @JavascriptInterface
    fun readText(path: String): String = try { JSONObject.quote(File(path).readText()) } catch (e: Exception) { "null" }

    @JavascriptInterface
    fun writeText(path: String, text: String): String = try {
        val f = File(path); f.parentFile?.mkdirs(); f.writeText(text); "true"
    } catch (e: Exception) { "false" }

    @JavascriptInterface
    fun writeBase64(path: String, b64: String, append: Boolean): String = try {
        val f = File(path); f.parentFile?.mkdirs()
        FileOutputStream(f, append).use { it.write(Base64.decode(b64, Base64.DEFAULT)) }
        "true"
    } catch (e: Exception) { "false" }

    @JavascriptInterface
    fun readBase64(path: String, offset: Double, length: Double): String = try {
        RandomAccessFile(File(path), "r").use { raf ->
            val size = raf.length()
            val off = offset.toLong().coerceIn(0, size)
            val len = (if (length < 0) size - off else minOf(length.toLong(), size - off)).toInt()
            val buf = ByteArray(len)
            raf.seek(off)
            raf.readFully(buf)
            Base64.encodeToString(buf, Base64.NO_WRAP)
        }
    } catch (e: Exception) { "" }

    @JavascriptInterface
    fun exists(path: String): String = ok(File(path).exists())

    @JavascriptInterface
    fun stat(path: String): String {
        val f = File(path)
        if (!f.exists()) return "null"
        return JSONObject().put("size", f.length()).put("mtime", f.lastModified()).put("isDir", f.isDirectory).toString()
    }

    @JavascriptInterface
    fun list(path: String): String {
        val arr = JSONArray()
        File(path).listFiles()?.forEach { f ->
            arr.put(JSONObject().put("name", f.name).put("path", f.absolutePath).put("isDir", f.isDirectory).put("size", f.length()).put("mtime", f.lastModified()))
        }
        return arr.toString()
    }

    @JavascriptInterface
    fun mkdirs(path: String): String = ok(File(path).let { it.isDirectory || it.mkdirs() })

    @JavascriptInterface
    fun remove(path: String, recursive: Boolean): String {
        val f = File(path)
        if (!f.exists()) return "true"
        return ok(if (recursive) f.deleteRecursively() else f.delete())
    }

    @JavascriptInterface
    fun rename(a: String, b: String): String {
        val src = File(a); val dst = File(b)
        if (src.renameTo(dst)) return "true"
        return try { src.copyTo(dst, overwrite = true); src.delete(); "true" } catch (e: Exception) { "false" }
    }

    @JavascriptInterface
    fun copy(id: String, a: String, b: String) {
        pool.execute {
            val r = try { File(a).copyTo(File(b), overwrite = true); true } catch (e: Exception) { false }
            cb(id, JSONObject().put("ok", r).toString())
        }
    }

    @JavascriptInterface
    fun paths(): String {
        val full = act.hasStorageAccess()
        val root = Environment.getExternalStorageDirectory()
        val out = if (full) File(root, "Movies/ChauhanClipping") else File(act.getExternalFilesDir(Environment.DIRECTORY_MOVIES), "ChauhanClipping")
        val projects = if (full) File(root, "Documents/ChauhanClipping/projects") else File(act.getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS), "projects")
        out.mkdirs(); projects.mkdirs()
        return JSONObject().put("out", out.absolutePath).put("projects", projects.absolutePath)
            .put("cache", workDir().absolutePath).put("full", full).toString()
    }

    @JavascriptInterface
    fun storageAccess(): String = ok(act.hasStorageAccess())

    @JavascriptInterface
    fun askStorage(id: String) { act.askStorage { cb(id, ok(act.hasStorageAccess())) } }

    // ------------------------------------------------------------------ the phone's media
    @JavascriptInterface
    fun media(id: String, kind: String) {
        pool.execute {
            val arr = JSONArray()
            try {
                val uris = when (kind) {
                    "audio" -> listOf(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI)
                    "image_video" -> listOf(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
                    else -> listOf(MediaStore.Video.Media.EXTERNAL_CONTENT_URI)
                }
                val rows = ArrayList<JSONObject>()
                for (u in uris) {
                    val proj = arrayOf(MediaStore.MediaColumns.DISPLAY_NAME, MediaStore.MediaColumns.DATA, MediaStore.MediaColumns.SIZE,
                        MediaStore.MediaColumns.DATE_MODIFIED, "duration")
                    val cur = try { act.contentResolver.query(u, proj, null, null, MediaStore.MediaColumns.DATE_MODIFIED + " DESC") }
                    catch (e: Exception) { act.contentResolver.query(u, proj.sliceArray(0 until 4), null, null, MediaStore.MediaColumns.DATE_MODIFIED + " DESC") }
                    cur?.use { c ->
                        val iName = c.getColumnIndex(MediaStore.MediaColumns.DISPLAY_NAME)
                        val iData = c.getColumnIndex(MediaStore.MediaColumns.DATA)
                        val iSize = c.getColumnIndex(MediaStore.MediaColumns.SIZE)
                        val iDate = c.getColumnIndex(MediaStore.MediaColumns.DATE_MODIFIED)
                        val iDur = c.getColumnIndex("duration")
                        while (c.moveToNext()) {
                            val path = if (iData >= 0) c.getString(iData) else null
                            if (path.isNullOrEmpty() || !File(path).canRead()) continue
                            val f = File(path)
                            rows.add(JSONObject().put("name", c.getString(iName) ?: f.name).put("path", path)
                                .put("size", if (iSize >= 0) c.getLong(iSize) else f.length())
                                .put("date", if (iDate >= 0) c.getLong(iDate) else 0)
                                .put("duration", if (iDur >= 0) c.getLong(iDur) else 0)
                                .put("folder", f.parentFile?.name ?: ""))
                        }
                    }
                }
                rows.sortByDescending { it.optLong("date") }
                for (r in rows) arr.put(r)
            } catch (e: Exception) { }
            cb(id, arr.toString())
        }
    }

    @JavascriptInterface
    fun pick(id: String, kind: String) {
        val mimes = when (kind) {
            "video" -> arrayOf("video/*")
            "image_video" -> arrayOf("image/*", "video/*")
            "audio" -> arrayOf("audio/*")
            else -> arrayOf("*/*")
        }
        act.pickDocument(mimes) { uri ->
            if (uri == null) { cb(id, "null"); return@pickDocument }
            pool.execute {
                val res = JSONObject()
                try {
                    var path = resolvePath(uri)
                    if (path == null || !File(path).canRead()) {
                        act.runOnUiThread { Toast.makeText(act, "Copying the file into the app ...", Toast.LENGTH_SHORT).show() }
                        path = copyIn(uri)
                        res.put("copied", true)
                    }
                    res.put("path", path)
                } catch (e: Exception) {
                    res.put("error", "This file could not be opened: ${e.message}")
                }
                cb(id, res.toString())
            }
        }
    }

    private fun queryData(uri: Uri, sel: String? = null, args: Array<String>? = null): String? = try {
        act.contentResolver.query(uri, arrayOf(MediaStore.MediaColumns.DATA), sel, args, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        }
    } catch (e: Exception) { null }

    private fun resolvePath(uri: Uri): String? {
        if (uri.scheme == "file") return uri.path
        try {
            if (DocumentsContract.isDocumentUri(act, uri)) {
                val docId = DocumentsContract.getDocumentId(uri)
                when (uri.authority) {
                    "com.android.externalstorage.documents" -> {
                        val (type, rel) = docId.split(":", limit = 2).let { it[0] to it.getOrElse(1) { "" } }
                        return if (type.equals("primary", true)) "${Environment.getExternalStorageDirectory()}/$rel" else "/storage/$type/$rel"
                    }
                    "com.android.providers.downloads.documents" -> {
                        if (docId.startsWith("raw:")) return docId.removePrefix("raw:")
                        if (docId.startsWith("msf:")) {
                            val n = docId.removePrefix("msf:")
                            return queryData(MediaStore.Files.getContentUri("external"), "_id=?", arrayOf(n))
                        }
                        docId.toLongOrNull()?.let { n ->
                            queryData(ContentUris.withAppendedId(Uri.parse("content://downloads/public_downloads"), n))?.let { return it }
                        }
                    }
                    "com.android.providers.media.documents" -> {
                        val (type, n) = docId.split(":", limit = 2).let { it[0] to it.getOrElse(1) { "" } }
                        val base = when (type) {
                            "video" -> MediaStore.Video.Media.EXTERNAL_CONTENT_URI
                            "image" -> MediaStore.Images.Media.EXTERNAL_CONTENT_URI
                            "audio" -> MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
                            else -> MediaStore.Files.getContentUri("external")
                        }
                        return queryData(base, "_id=?", arrayOf(n))
                    }
                }
            }
            if (uri.scheme == "content") return queryData(uri)
        } catch (e: Exception) { }
        return null
    }

    private fun copyIn(uri: Uri): String {
        var name = "imported"
        act.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) name = c.getString(0) ?: name
        }
        val dir = File(act.getExternalFilesDir(null), "imported").apply { mkdirs() }
        val dst = File(dir, name.replace(Regex("[\\\\/:*?\"<>|]"), "_"))
        act.contentResolver.openInputStream(uri)!!.use { inp -> FileOutputStream(dst).use { inp.copyTo(it, 1 shl 20) } }
        return dst.absolutePath
    }

    // ------------------------------------------------------------------ play / share / scan
    private fun uriFor(path: String): Uri = FileProvider.getUriForFile(act, "${act.packageName}.files", File(path))

    @JavascriptInterface
    fun openFile(path: String, mime: String): String = try {
        val i = Intent(Intent.ACTION_VIEW).setDataAndType(uriFor(path), mime.ifEmpty { "video/*" })
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        act.startActivity(Intent.createChooser(i, "Play with").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); "true"
    } catch (e: Exception) { "false" }

    @JavascriptInterface
    fun share(path: String, mime: String): String = try {
        val i = Intent(Intent.ACTION_SEND).setType(mime.ifEmpty { "video/*" }).putExtra(Intent.EXTRA_STREAM, uriFor(path))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        act.startActivity(Intent.createChooser(i, "Share").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); "true"
    } catch (e: Exception) { "false" }

    @JavascriptInterface
    fun openFolder(path: String): String = try {
        val rel = path.removePrefix(Environment.getExternalStorageDirectory().absolutePath).trimStart('/')
        val u = DocumentsContract.buildDocumentUri("com.android.externalstorage.documents", "primary:$rel")
        act.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(u, DocumentsContract.Document.MIME_TYPE_DIR)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)); "true"
    } catch (e: Exception) { toast(path); "false" }

    @JavascriptInterface
    fun scanFile(path: String): String { MediaScannerConnection.scanFile(act, arrayOf(path), null, null); return "true" }

    // ------------------------------------------------------------------ misc
    @JavascriptInterface
    fun keepAwake(on: Boolean, title: String, text: String): String {
        val i = Intent(act, WorkService::class.java).putExtra("title", title).putExtra("text", text)
        try {
            if (on) ContextCompat.startForegroundService(act, i) else act.stopService(i)
        } catch (e: Exception) { }
        act.keepScreenOn(on)
        return "true"
    }

    @JavascriptInterface
    fun toast(msg: String): String { act.runOnUiThread { Toast.makeText(act, msg, Toast.LENGTH_LONG).show() }; return "true" }

    @JavascriptInterface
    fun appInfo(): String {
        val v = try { act.packageManager.getPackageInfo(act.packageName, 0).versionName } catch (e: Exception) { "" }
        return JSONObject().put("version", v).put("abi", Build.SUPPORTED_ABIS.firstOrNull() ?: "").put("sdk", Build.VERSION.SDK_INT)
            .put("ffmpeg", binary("ffmpeg").exists()).toString()
    }
}

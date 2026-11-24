package com.chauhan.clipping

import org.json.JSONArray
import org.json.JSONObject
import org.schabi.newpipe.extractor.NewPipe
import org.schabi.newpipe.extractor.downloader.Downloader
import org.schabi.newpipe.extractor.downloader.Request
import org.schabi.newpipe.extractor.downloader.Response
import org.schabi.newpipe.extractor.stream.DeliveryMethod
import org.schabi.newpipe.extractor.stream.StreamInfo
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/**
 * Network for the web app (no browser CORS limits): AI services (JSON requests, file uploads),
 * YouTube / other video links (NewPipe Extractor finds the stream links) and downloads in pieces.
 */
object Net {
    const val UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"

    // ------------------------------------------------------------------ NewPipe
    private class Dl : Downloader() {
        override fun execute(request: Request): Response {
            val c = URL(request.url()).openConnection() as HttpURLConnection
            c.requestMethod = request.httpMethod()
            c.instanceFollowRedirects = true
            c.connectTimeout = 30000
            c.readTimeout = 30000
            c.setRequestProperty("User-Agent", UA)
            for ((k, vs) in request.headers()) {
                c.setRequestProperty(k, vs.joinToString(", "))
            }
            val data = request.dataToSend()
            if (data != null) {
                c.doOutput = true
                c.outputStream.use { it.write(data) }
            }
            val code = c.responseCode
            val stream = if (code >= 400) c.errorStream else c.inputStream
            val body = stream?.use { it.readBytes().toString(Charsets.UTF_8) } ?: ""
            val headers = HashMap<String, List<String>>()
            for ((k, v) in c.headerFields) if (k != null) headers[k] = v
            return Response(code, c.responseMessage ?: "", headers, body, c.url.toString())
        }
    }

    @Volatile private var inited = false
    private fun init() {
        if (!inited) synchronized(this) { if (!inited) { NewPipe.init(Dl()); inited = true } }
    }

    /** Title, length and every directly downloadable stream of a video link. */
    fun linkInfo(url: String): String {
        init()
        val info = StreamInfo.getInfo(url)
        val out = JSONObject()
        out.put("title", info.name ?: "video")
        out.put("duration", info.duration)
        out.put("uploader", info.uploaderName ?: "")
        val vids = JSONArray()
        fun addVideo(s: org.schabi.newpipe.extractor.stream.VideoStream, only: Boolean) {
            if (!s.isUrl || s.deliveryMethod != DeliveryMethod.PROGRESSIVE_HTTP) return
            vids.put(JSONObject().put("url", s.content).put("height", s.height).put("fps", s.fps)
                .put("ext", s.format?.suffix ?: "mp4").put("mime", s.format?.mimeType ?: "")
                .put("codec", s.codec ?: "").put("bitrate", s.bitrate).put("videoOnly", only))
        }
        for (s in info.videoOnlyStreams) addVideo(s, true)
        for (s in info.videoStreams) addVideo(s, false)
        out.put("video", vids)
        val auds = JSONArray()
        for (s in info.audioStreams) {
            if (!s.isUrl || s.deliveryMethod != DeliveryMethod.PROGRESSIVE_HTTP) continue
            auds.put(JSONObject().put("url", s.content).put("bitrate", s.averageBitrate)
                .put("ext", s.format?.suffix ?: "m4a").put("mime", s.format?.mimeType ?: "").put("codec", s.codec ?: "")
                .put("lang", s.audioLocale?.language ?: "").put("track", s.audioTrackName ?: "")
                .put("type", s.audioTrackType?.name ?: ""))
        }
        out.put("audio", auds)
        return out.toString()
    }

    /** Downloads a URL into a file in 8 MB pieces (YouTube slows down single big requests). */
    fun download(url: String, out: String, headers: JSONObject?, progress: (Long, Long) -> Unit, cancelled: () -> Boolean): Long {
        val f = File(out)
        f.parentFile?.mkdirs()
        if (f.exists()) f.delete()
        var total = -1L
        var got = 0L
        val piece = 8L * 1024 * 1024
        RandomAccessFile(f, "rw").use { raf ->
            while (total < 0 || got < total) {
                if (cancelled()) throw InterruptedException("stopped")
                val c = URL(url).openConnection() as HttpURLConnection
                c.connectTimeout = 30000
                c.readTimeout = 60000
                c.setRequestProperty("User-Agent", UA)
                headers?.keys()?.forEach { k -> c.setRequestProperty(k, headers.getString(k)) }
                c.setRequestProperty("Range", "bytes=$got-${got + piece - 1}")
                val code = c.responseCode
                if (code >= 400) throw RuntimeException("The server refused the download ($code)")
                if (total < 0) {
                    val cr = c.getHeaderField("Content-Range")
                    total = if (code == 206 && cr != null && cr.contains("/")) cr.substringAfterLast("/").toLongOrNull() ?: -1L
                            else c.contentLengthLong
                }
                var n = 0L
                c.inputStream.use { ins ->
                    val buf = ByteArray(256 * 1024)
                    raf.seek(got)
                    while (true) {
                        if (cancelled()) throw InterruptedException("stopped")
                        val r = ins.read(buf)
                        if (r < 0) break
                        raf.write(buf, 0, r)
                        got += r; n += r
                        progress(got, total)
                    }
                }
                if (code == 200) { total = got; break }      // the server sent everything at once
                if (n == 0L) break
            }
        }
        return got
    }

    // ------------------------------------------------------------------ AI services
    /** JSON (or any text) request. Returns {status, body}. */
    fun http(method: String, url: String, headers: JSONObject?, body: String?): String {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 30000
        c.readTimeout = 300000
        headers?.keys()?.forEach { k -> c.setRequestProperty(k, headers.getString(k)) }
        if (body != null && method != "GET") {
            c.doOutput = true
            c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        }
        return answer(c)
    }

    /** multipart/form-data with text fields and one file (speech-to-text uploads). Returns {status, body}. */
    fun upload(url: String, headers: JSONObject?, fields: JSONObject, fileField: String, path: String, mime: String): String {
        val bnd = "----cc" + UUID.randomUUID().toString().replace("-", "")
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.connectTimeout = 30000
        c.readTimeout = 600000
        c.doOutput = true
        headers?.keys()?.forEach { k -> c.setRequestProperty(k, headers.getString(k)) }
        c.setRequestProperty("Content-Type", "multipart/form-data; boundary=$bnd")
        val file = File(path)
        c.setChunkedStreamingMode(256 * 1024)
        c.outputStream.use { os ->
            fun w(s: String) = os.write(s.toByteArray(Charsets.UTF_8))
            for (k in fields.keys()) {
                val v = fields.get(k)
                val vals = if (v is JSONArray) (0 until v.length()).map { v.get(it).toString() } else listOf(v.toString())
                for (x in vals) w("--$bnd\r\nContent-Disposition: form-data; name=\"$k\"\r\n\r\n$x\r\n")
            }
            w("--$bnd\r\nContent-Disposition: form-data; name=\"$fileField\"; filename=\"${file.name}\"\r\nContent-Type: $mime\r\n\r\n")
            file.inputStream().use { it.copyTo(os, 256 * 1024) }
            w("\r\n--$bnd--\r\n")
        }
        return answer(c)
    }

    private fun answer(c: HttpURLConnection): String {
        val code = c.responseCode
        val st = if (code >= 400) c.errorStream else c.inputStream
        val bytes = ByteArrayOutputStream()
        st?.use { it.copyTo(bytes) }
        return JSONObject().put("status", code).put("body", bytes.toString("UTF-8")).toString()
    }

    fun error(e: Throwable): String = JSONObject().put("status", -1).put("error", (e.message ?: e.toString()).take(600)).toString()
}

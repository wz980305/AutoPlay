package com.playport.server

import com.shilapi.xcertplay.airplay.AudioFormat
import com.shilapi.xcertplay.airplay.VideoCodec
import io.ktor.server.application.Application
import io.ktor.server.application.install
import io.ktor.server.plugins.origin
import io.ktor.server.request.receiveText
import io.ktor.server.request.uri
import io.ktor.server.response.respondText
import io.ktor.server.routing.get
import io.ktor.server.routing.post
import io.ktor.server.routing.routing
import io.ktor.websocket.CloseReason
import io.ktor.websocket.Frame
import io.ktor.websocket.close
import io.ktor.websocket.readText
import io.ktor.websocket.send
import io.ktor.server.websocket.WebSockets
import io.ktor.server.websocket.webSocket
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong

@Serializable
data class TouchContactMessage(val id: Int, val x: Double, val y: Double, val down: Boolean)

@Serializable
data class KnobMessage(
    val select: Boolean = false,
    val home: Boolean = false,
    val back: Boolean = false,
    val x: Int = 0,
    val y: Int = 0,
    val wheel: Int = 0,
)

@Serializable
data class ClientMessage(
    val type: String,
    val contacts: List<TouchContactMessage> = emptyList(),
    val media: Int? = null,
    val knob: KnobMessage? = null,
    val night: Boolean? = null,
    val telephony: Int? = null,
    /** "stats": the viewer's own playback counters (frames drawn, decode delay, ...), numbers only. */
    val stats: Map<String, Double>? = null,
    /** "ack": the page answering the box's "mark" of the same number at once (see LagGate). */
    val mark: Long? = null,
)

@Serializable
data class DisplayRequest(
    val width: Int,
    val height: Int,
    // 30 by default: at 60 the iPhone encodes twice the frames on the cable and ran hot (2026-10-12 drive).
    val fps: Int = 30,
    val uiScale: Int = 100,
    val hevc: Boolean = false,
    /** Shapes the page's window takes (each at the stream's top left), and the one in use now. */
    val areas: List<ViewArea> = emptyList(),
    val area: Int = 0,
)

@Serializable
data class ServerMessage(
    val type: String,
    val mark: Long? = null,
    val nowPlaying: NowPlaying? = null,
    val artwork: String? = null,
    val revision: Long? = null,
    val deviceName: String? = null,
    val sessionActive: Boolean = false,
    val width: Int? = null,
    val height: Int? = null,
    val viewers: Int = 0,
    val message: String? = null,
    val micActive: Boolean? = null,
    val micRate: Int? = null,
    val micChannels: Int? = null,
    val micCodec: String? = null,
    val micSamplesPerPacket: Int? = null,
    val micBitrate: Int? = null,
)

private class WsClient(
    val channel: Channel<Frame>,
) {
    val imageReady = java.util.concurrent.atomic.AtomicBoolean(false)
    /** Picture at most 300 ms behind; 192 kB always fits (a fresh session's first keyframe). */
    val lag = LagGate(300_000_000L, 192_000L)
    val nextMark = AtomicLong(0)
    /** Every byte offered to [channel], what [LagGate] counts against what the page confirmed. */
    val queuedBytes = AtomicLong(0)
    fun offer(frame: Frame) = channel.trySend(frame).also {
        if (it.isSuccess) queuedBytes.addAndGet(frame.data.size.toLong())
    }
    val keyframeRequested = AtomicLong(0)
    val id = nextClientId.incrementAndGet()
    /** When anything last came from the page (it answers a mark every 200 ms while it runs). */
    val lastHeard = AtomicLong(System.nanoTime())
    val since: Long = System.nanoTime()
    /** The page instance (a random id the page picks when it loads), so a reconnect replaces its old link at once. */
    @Volatile var page: String = ""
    @Volatile var session: kotlinx.coroutines.CoroutineScope? = null
    /** Silent for 3 s: the browser froze the page (a Tesla away from its browser). Its sound is held back and the
     *  picture waits for a keyframe (LagGate) until it answers again; the link itself is kept (SILENT_VIEWER_MS). */
    fun paused(now: Long = System.nanoTime()) = now - lastHeard.get() > PAUSE_NANOS
    @Volatile var wasPaused = false
    val videoSent = AtomicLong(0)
    val videoDropped = AtomicLong(0)
    val bytesSent = AtomicLong(0)

    private companion object {
        val nextClientId = AtomicLong(0)
        // 3 s, not 1.5: a page just opened was once quiet for 1.6 s (2026-10-14), and a slow car's page may be.
        const val PAUSE_NANOS = 3_000_000_000L
    }
}

/** Fan-out hub: browsers connect here and the media bridge pushes CarPlay frames to all of them. */
class WebHub(
    private val config: ServerConfig,
    private val display: DisplayState,
    private val scope: CoroutineScope = CoroutineScope(Dispatchers.Default),
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val clients = ConcurrentHashMap.newKeySet<WsClient>()
    private val codecsByStream = ConcurrentHashMap<Int, VideoCodec>()
    private val configByStream = ConcurrentHashMap<Int, Pair<VideoCodec, ByteArray>>()
    private val audioFormatByStream = ConcurrentHashMap<Int, AudioFormat>()

    @Volatile var inputHandler: ((ClientMessage) -> Unit)? = null

    /** Invoked (once per client) when a browser is ready to receive; used to request a keyframe. */
    @Volatile var onViewerJoined: ((Int) -> Unit)? = null
    /** Pages connected to watch (the supervisor releases CarPlay when there are none for a while). */
    val viewerCount: Int get() = clients.size

    /** Applies a display change; returns null on success or an error message. */
    @Volatile var onApplyDisplay: ((DisplayRequest) -> String?)? = null

    /** Browser microphone payloads: (isOpus, payload). */
    @Volatile var onMicrophoneData: ((Boolean, ByteArray) -> Unit)? = null

    fun microphoneRequested(uplink: MicUplink) {
        broadcastJson(
            ServerMessage(
                type = "mic",
                deviceName = config.deviceName,
                micActive = true,
                micRate = uplink.sampleRate,
                micChannels = uplink.channels,
                micCodec = uplink.codec,
                micSamplesPerPacket = uplink.samplesPerPacket,
                micBitrate = uplink.bitrate,
            ),
        )
    }

    fun microphoneStopped() {
        broadcastJson(ServerMessage(type = "mic", deviceName = config.deviceName, micActive = false))
    }

    @Volatile private var sessionActive = false
    @Volatile private var nowPlaying = NowPlaying()

    @Volatile private var artwork: String? = null

    @Synchronized fun artwork(revision: Long, bytes: ByteArray): Boolean {
        if (!sessionActive || nowPlaying.revision != revision) return false
        artwork = "data:image/jpeg;base64," + java.util.Base64.getEncoder().encodeToString(bytes)
        broadcastJson(ServerMessage(type = "artwork", artwork = artwork, revision = revision))
        return true
    }

    @Synchronized fun nowPlaying(value: NowPlaying) {
        if (!sessionActive || value == nowPlaying) return
        if (value.revision != nowPlaying.revision) artwork = null
        nowPlaying = value
        broadcastJson(ServerMessage(type = "now-playing", nowPlaying = value.at(System.nanoTime() / 1_000_000)))
    }

    @Volatile private var phoneName: String? = null

    fun setVideoCodec(type: Int, codec: VideoCodec) {
        codecsByStream[type] = codec
    }

    fun hostUiRequested() {
        broadcastJson(ServerMessage(type = "host-ui", sessionActive = sessionActive))
    }

    fun videoCodec(type: Int): VideoCodec? = codecsByStream[type]

    fun setSessionState(active: Boolean, name: String?) {
        if (!active) { nowPlaying = NowPlaying(); artwork = null }
        sessionActive = active
        phoneName = name
        broadcastJson(
            ServerMessage(
                type = "session",
                deviceName = config.deviceName,
                sessionActive = active,
                viewers = clients.size,
                message = name,
            ),
        )
    }

    fun broadcastVideoConfig(type: Int, codecData: ByteArray) {
        val codec = codecsByStream[type] ?: VideoCodec.H264
        configByStream[type] = codec to codecData
        val frame = Wire.videoConfig(type, codec, display.width, display.height, codecData)
        broadcastBinary(frame)
    }

    fun broadcastVideoFrame(type: Int, keyframe: Boolean, naluBytes: ByteArray) {
        val frame = Wire.videoFrame(type, keyframe, naluBytes)
        for (client in clients) {
            if (!client.lag.open(System.nanoTime(), client.queuedBytes.get())) {
                // The page is behind: no picture until it catches up, then a fresh keyframe (below).
                client.imageReady.set(false)
                client.videoDropped.incrementAndGet()
                continue
            }
            if (keyframe) {
                client.imageReady.set(true)
            } else if (!client.imageReady.get()) {
                // Every viewer starts decoding at a keyframe; drop deltas until one arrives.
                maybeRequestKeyframe(client, type)
                continue
            }
            if (client.offer(Frame.Binary(true, frame)).isSuccess) {
                client.videoSent.incrementAndGet()
                client.bytesSent.addAndGet(frame.size.toLong())
            } else {
                client.videoDropped.incrementAndGet()   // send queue full: this viewer cannot keep up
            }
        }
    }

    fun broadcastScreenActive(type: Int, active: Boolean) {
        broadcastBinary(Wire.screenActive(type, active))
    }

    fun broadcastAudioConfig(type: Int, format: AudioFormat) {
        audioFormatByStream[type] = format
        broadcastBinary(Wire.audioConfig(type, format))
    }

    fun broadcastAudioPacket(type: Int, timestampUs: Long, payload: ByteArray) {
        val bytes = Wire.audioPacket(type, timestampUs, payload)
        val now = System.nanoTime()
        for (client in clients) {
            if (!client.paused(now)) client.offer(Frame.Binary(true, bytes))   // a frozen page gets no stale sound
        }
    }

    fun broadcastAudioStopped(type: Int) {
        audioFormatByStream.remove(type)
        broadcastBinary(Wire.audioStopped(type))
    }

    private fun broadcastBinary(bytes: ByteArray) {
        for (client in clients) {
            client.offer(Frame.Binary(true, bytes))
        }
    }

    private fun broadcastJson(message: ServerMessage) {
        val text = json.encodeToString(ServerMessage.serializer(), message)
        for (client in clients) {
            client.offer(Frame.Text(text))
        }
    }

    private fun maybeRequestKeyframe(client: WsClient, type: Int) {
        val now = System.nanoTime()
        val last = client.keyframeRequested.get()
        if (now - last > KEYFRAME_REQUEST_INTERVAL_NS && client.keyframeRequested.compareAndSet(last, now)) {
            onViewerJoined?.invoke(type)
        }
    }

    /** Ktor module: WebSocket endpoint with token auth plus status API. */
    fun install(application: Application, webRoot: Path) {
        application.install(WebSockets)
        application.routing {
            get("/api/status") {
                call.respondText(statusJson(), io.ktor.http.ContentType.Application.Json)
            }
            get("/api/display") {
                call.respondText(displayJson(), io.ktor.http.ContentType.Application.Json)
            }
            post("/api/display") {
                if (call.request.queryParameters["token"] != config.accessToken || !call.fromOwnPage()) {
                    call.respondText(
                        """{"error":"invalid token"}""",
                        io.ktor.http.ContentType.Application.Json,
                        io.ktor.http.HttpStatusCode.Forbidden,
                    )
                    return@post
                }
                val request = try {
                    json.decodeFromString(DisplayRequest.serializer(), call.receiveText())
                } catch (_: Exception) {
                    call.respondText(
                        """{"error":"malformed request"}""",
                        io.ktor.http.ContentType.Application.Json,
                        io.ktor.http.HttpStatusCode.BadRequest,
                    )
                    return@post
                }
                val applier = onApplyDisplay
                if (applier == null) {
                    call.respondText(
                        """{"error":"display control unavailable"}""",
                        io.ktor.http.ContentType.Application.Json,
                        io.ktor.http.HttpStatusCode.ServiceUnavailable,
                    )
                    return@post
                }
                val error = applier(request)
                if (error != null) {
                    call.respondText(
                        "{\"error\":\"$error\"}",
                        io.ktor.http.ContentType.Application.Json,
                        io.ktor.http.HttpStatusCode.BadRequest,
                    )
                    return@post
                }
                call.respondText("""{"ok":true}""", io.ktor.http.ContentType.Application.Json)
            }
            webSocket("/ws") {
                val token = call.request.queryParameters["token"]
                if (token != config.accessToken || !call.fromOwnPage()) {
                    close(CloseReason(CloseReason.Codes.VIOLATED_POLICY, "invalid token"))
                    return@webSocket
                }
                val client = WsClient(Channel(capacity = SEND_QUEUE_CAPACITY))
                client.page = call.request.queryParameters["page"]?.take(32)?.filter { it.isLetterOrDigit() } ?: ""
                client.session = this
                // The same page connecting again (it came back from a freeze): its old link goes at once, not after
                // SILENT_VIEWER_MS, so the two never share the stream.
                if (client.page.isNotEmpty()) clients.filter { it.page == client.page }.forEach { old ->
                    log.info("viewer client={} replaced by client={}", old.id, client.id)
                    old.session?.cancel()
                }
                clients.add(client)
                val from = "${call.request.origin.remoteHost}:${call.request.origin.remotePort}"
                log.info("viewer connected client={} from={} page={} viewers={}", client.id, from, client.page, clients.size)
                var ending = "page closed"
                val wsSession = this
                val writer = launch {
                    try {
                        for (frame in client.channel) {
                            wsSession.send(frame)
                        }
                    } catch (_: Exception) {
                        // The reader loop below handles disconnects.
                    }
                }
                val marker = launch {
                    while (true) {
                        delay(MARK_INTERVAL_MS)
                        // A page that stopped answering marks was frozen (a Tesla's reverse gear, 2026-10-14) or lost:
                        // close it, so it holds nothing and the log says when.
                        val silentMs = (System.nanoTime() - client.lastHeard.get()) / 1_000_000
                        if (client.paused() && !client.wasPaused) {
                            client.wasPaused = true
                            log.info("viewer paused client={} (silent {} ms)", client.id, silentMs)
                        }
                        if (silentMs > SILENT_VIEWER_MS) {
                            ending = "silent ${silentMs} ms"
                            // Cancel, not close(): a close frame waits behind a frozen page's full socket and never
                            // finished (Tesla, 2026-10-14: the frozen viewer stayed listed next to its successor).
                            wsSession.cancel()
                            break
                        }
                        val id = client.nextMark.incrementAndGet()
                        val frame = Frame.Text("""{"type":"mark","mark":$id}""")
                        // Counted with the mark itself, so its answer confirms everything up to here.
                        client.lag.marked(id, System.nanoTime(), client.queuedBytes.get() + frame.data.size)
                        client.offer(frame)
                    }
                }
                try {
                    wsSession.send(
                        Frame.Text(
                            json.encodeToString(
                                ServerMessage.serializer(),
                                ServerMessage(
                                    type = "hello",
                                    nowPlaying = nowPlaying.at(System.nanoTime() / 1_000_000),   // not where it was when reported
                                    artwork = artwork,
                                    revision = nowPlaying.revision,
                                    deviceName = config.deviceName,
                                    sessionActive = sessionActive,
                                    width = display.width,
                                    height = display.height,
                                    viewers = clients.size,
                                    message = phoneName,
                                ),
                            ),
                        ),
                    )
                    // Replay codec/audio setup so a viewer that joins late can decode.
                    configByStream.forEach { (type, value) ->
                        client.offer(
                            Frame.Binary(true, Wire.videoConfig(type, value.first, display.width, display.height, value.second)),
                        )
                    }
                    audioFormatByStream.forEach { (type, format) ->
                        client.offer(Frame.Binary(true, Wire.audioConfig(type, format)))
                    }
                    configByStream.keys.forEach { streamType -> onViewerJoined?.invoke(streamType) }
                    for (frame in incoming) {
                        val heardAt = System.nanoTime()
                        if (client.wasPaused) {
                            // Back from a freeze on the same link: a fresh keyframe at once.
                            client.wasPaused = false
                            log.info("viewer resumed client={} after {} ms", client.id, (heardAt - client.lastHeard.get()) / 1_000_000)
                            configByStream.keys.forEach { streamType -> onViewerJoined?.invoke(streamType) }
                        }
                        client.lastHeard.set(heardAt)
                        if (frame is Frame.Binary) {
                            val data = frame.data
                            if (data.size >= 2) {
                                val kind = data[0].toInt() and 0xff
                                val payload = data.copyOfRange(1, data.size)
                                when (kind) {
                                    MIC_FRAME_LPCM -> onMicrophoneData?.invoke(false, payload)
                                    MIC_FRAME_OPUS -> onMicrophoneData?.invoke(true, payload)
                                }
                            }
                            continue
                        }
                        val text = (frame as? Frame.Text)?.readText() ?: continue
                        val message = try {
                            json.decodeFromString(ClientMessage.serializer(), text)
                        } catch (_: Exception) {
                            continue
                        }
                        if (message.type == "ack") {
                            message.mark?.let { client.lag.acked(it, System.nanoTime()) }
                        } else if (message.type == "keyframe") {
                            configByStream.keys.forEach { streamType -> onViewerJoined?.invoke(streamType) }
                        } else if (message.type == "stats") {
                            log.info(statsLine(client.id, client.videoSent.get(), client.videoDropped.get(),
                                client.bytesSent.get(), message.stats.orEmpty()))
                        } else if (message.type == "ping") {
                            client.offer(Frame.Text("""{"type":"pong"}"""))
                        } else {
                            inputHandler?.invoke(message)
                        }
                    }
                } catch (error: Exception) {
                    if (ending == "page closed") ending = "${error.javaClass.simpleName}: ${error.message}"
                    throw error
                } finally {
                    clients.remove(client)
                    client.channel.close()
                    writer.cancel()
                    marker.cancel()
                    log.info("viewer closed client={} after {} s ({}) viewers={}", client.id,
                        (System.nanoTime() - client.since) / 1_000_000_000, ending, clients.size)
                }
            }
            get("/{path...}") {
                val relative = call.request.uri.substringBefore('?').trimStart('/').ifEmpty { "index.html" }
                if (relative == ACCESS_FILE) {
                    // The viewer token for pages on this network: only to this box's own page, never cached.
                    val file = webRoot.resolve(ACCESS_FILE)
                    if (!call.fromOwnPage() || !Files.isRegularFile(file)) {
                        call.respondText("{}", io.ktor.http.ContentType.Application.Json, io.ktor.http.HttpStatusCode.Forbidden)
                        return@get
                    }
                    call.response.headers.append("Cross-Origin-Resource-Policy", "same-origin")
                    call.response.headers.append("Cache-Control", "no-store")
                    call.respondText(Files.readString(file), io.ktor.http.ContentType.Application.Json)
                    return@get
                }
                val resolved = webRoot.resolve(relative).normalize()
                val file = if (resolved.startsWith(webRoot) && Files.isRegularFile(resolved)) resolved else webRoot.resolve("index.html")
                if (!Files.isRegularFile(file)) {
                    call.respondText(
                        "playport: the browser client is not built yet. Run `cd web && npm install && npm run build`, then reload.",
                    )
                    return@get
                }
                call.respondText(Files.readString(file), contentTypeFor(file.fileName.toString()))
            }
        }
    }

    private fun contentTypeFor(name: String): io.ktor.http.ContentType = when {
        name.endsWith(".html") -> io.ktor.http.ContentType.Text.Html
        name.endsWith(".js") -> io.ktor.http.ContentType.Text.JavaScript
        name.endsWith(".css") -> io.ktor.http.ContentType.Text.CSS
        name.endsWith(".svg") -> io.ktor.http.ContentType.Image.SVG
        name.endsWith(".png") -> io.ktor.http.ContentType.Image.PNG
        name.endsWith(".json") -> io.ktor.http.ContentType.Application.Json
        name.endsWith(".wasm") -> io.ktor.http.ContentType.Application.OctetStream
        else -> io.ktor.http.ContentType.Application.OctetStream
    }

    private fun displayJson(): String = kotlinx.serialization.json.buildJsonObject {
        put("width", kotlinx.serialization.json.JsonPrimitive(display.width))
        put("height", kotlinx.serialization.json.JsonPrimitive(display.height))
        put("fps", kotlinx.serialization.json.JsonPrimitive(display.fps))
        put("uiScale", kotlinx.serialization.json.JsonPrimitive(display.uiScale))
        put("hevc", kotlinx.serialization.json.JsonPrimitive(display.hevc))
        put("areas", kotlinx.serialization.json.buildJsonArray {
            display.areas.forEach { area -> add(kotlinx.serialization.json.buildJsonObject {
                put("width", kotlinx.serialization.json.JsonPrimitive(area.width))
                put("height", kotlinx.serialization.json.JsonPrimitive(area.height))
            }) }
        })
        put("area", kotlinx.serialization.json.JsonPrimitive(display.area))
        put("orientation", kotlinx.serialization.json.JsonPrimitive(display.orientation))
        put(
            "presets",
            kotlinx.serialization.json.buildJsonArray {
                DisplayState.PRESETS.forEach { preset ->
                    add(
                        kotlinx.serialization.json.buildJsonObject {
                            put("label", kotlinx.serialization.json.JsonPrimitive(preset.label))
                            put("width", kotlinx.serialization.json.JsonPrimitive(preset.width))
                            put("height", kotlinx.serialization.json.JsonPrimitive(preset.height))
                            put("orientation", kotlinx.serialization.json.JsonPrimitive(preset.orientation))
                        },
                    )
                }
            },
        )
    }.toString()

    private fun statusJson(): String = kotlinx.serialization.json.buildJsonObject {
        put("deviceName", kotlinx.serialization.json.JsonPrimitive(config.deviceName))
        put("sessionActive", kotlinx.serialization.json.JsonPrimitive(sessionActive))
        put("phone", phoneName?.let { kotlinx.serialization.json.JsonPrimitive(it) } ?: kotlinx.serialization.json.JsonNull)
        put("viewers", kotlinx.serialization.json.JsonPrimitive(clients.size))
        put(
            "display",
            kotlinx.serialization.json.buildJsonObject {
                put("width", kotlinx.serialization.json.JsonPrimitive(display.width))
                put("height", kotlinx.serialization.json.JsonPrimitive(display.height))
                put("fps", kotlinx.serialization.json.JsonPrimitive(display.fps))
                put("uiScale", kotlinx.serialization.json.JsonPrimitive(display.uiScale))
                put("hevc", kotlinx.serialization.json.JsonPrimitive(display.hevc))
                put("orientation", kotlinx.serialization.json.JsonPrimitive(display.orientation))
            },
        )
    }.toString()

    companion object {
        private val log = org.slf4j.LoggerFactory.getLogger("viewer")

        /** One diagnostics line per viewer report: receiver-side totals, then the viewer's own numbers. */
        internal fun statsLine(id: Long, sent: Long, dropped: Long, bytes: Long, stats: Map<String, Double>): String =
            buildString {
                append("viewer stats client=").append(id)
                append(" sentFrames=").append(sent).append(" droppedFrames=").append(dropped)
                append(" sentKB=").append(bytes / 1024)
                stats.toSortedMap().forEach { (key, value) ->
                    if (key.matches(Regex("[A-Za-z]{1,24}")) && value.isFinite()) {
                        append(' ').append(key).append('=')
                        append(if (value == Math.rint(value)) value.toLong().toString() else String.format(java.util.Locale.ROOT, "%.1f", value))
                    }
                }
            }

        /**
         * Whether a request comes from this box's own page: [origin] (absent on a same-origin GET or outside a browser)
         * must be the address the request went to, [host], and [fetchSite] (Sec-Fetch-Site) must not name another
         * site. Another site could load the viewer token and open the viewer channel (audit 2026-10-13, A2).
         */
        internal fun ownPage(origin: String?, host: String?, fetchSite: String?): Boolean {
            if (fetchSite != null && fetchSite != "same-origin" && fetchSite != "none") return false
            if (origin == null) return true
            val uri = runCatching { java.net.URI(origin) }.getOrNull() ?: return false
            val defaultPort = when (uri.scheme) { "https" -> 443; "http" -> 80; else -> return false }
            val wanted = runCatching { java.net.URI("${uri.scheme}://$host") }.getOrNull() ?: return false
            return uri.host != null && uri.host.equals(wanted.host, ignoreCase = true) &&
                (if (uri.port == -1) defaultPort else uri.port) == (if (wanted.port == -1) defaultPort else wanted.port)
        }

        // The address the request went to: the Host header (HTTP/1.1) or :authority (HTTP/2, no Host header,
        // so the phone's display request got a 403 on 2026-10-13), from the connection point of either.
        private fun io.ktor.server.application.ApplicationCall.fromOwnPage(): Boolean = ownPage(
            request.headers["Origin"], "${request.local.serverHost}:${request.local.serverPort}", request.headers["Sec-Fetch-Site"])

        const val MIC_FRAME_LPCM = 0x10
        const val MIC_FRAME_OPUS = 0x11
        private const val SEND_QUEUE_CAPACITY = 1024
        /** Written by the box's startup (run-receiver.py): {"token": ..., "settingsPort": ...}. */
        const val ACCESS_FILE = "receiver-access.json"
        private const val KEYFRAME_REQUEST_INTERVAL_NS = 1_000_000_000L
        private const val MARK_INTERVAL_MS = 200L
        /** No answer to marks for this long: the page is gone. A shorter silence only pauses it (WsClient.paused):
         *  a Tesla page back within 10 minutes goes on over the same link. */
        private const val SILENT_VIEWER_MS = 600_000L
    }
}

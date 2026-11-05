package com.shilapi.xcertplay.airplay

import com.shilapi.xcertplay.platform.Log
import java.io.Closeable
import java.io.InputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

enum class VideoCodec { H264, H265 }

/**
 * Receives one CarPlay screen stream on a TCP data port.
 *
 * Each message is a 128-byte AirPlayScreenHeader followed by a body: a clear VideoConfig
 * (avcC/hvcC) or a ChaCha20-Poly1305 sealed VideoFrame. The key is the DataStream output key
 * and the per-frame nonce is an 8-byte little-endian counter.
 *
 * A quiet screen may wait as long as it likes before its next header, but once a message has begun it must be
 * complete within [packetTimeoutNanos]: a Wi-Fi link that dies in the middle of a frame (the TCP connection
 * half-open, no FIN, no RST) otherwise left the session "live" with a frozen picture until something else noticed.
 * The timeout ends the stream as a failure, and the session ends and reconnects like any other lost link. After
 * DashPlay 2026.11.04 (`playport-screen-read-deadline`, GPL-3.0).
 */
class ScreenStream(
    private val key: ByteArray,
    private val onDiagnostic: (String) -> Unit = {},
    private val packetTimeoutNanos: Long = PACKET_TIMEOUT_NS,
) : Closeable {
    interface Listener {
        fun onCodec(codec: VideoCodec) {}
        fun onConfig(codecData: ByteArray) {}
        fun onFrame(naluBytes: ByteArray) {}
        fun onClosed(cause: Throwable?) {}
    }

    private val closed = AtomicBoolean(false)
    private val frameCounter = AtomicLong(0)
    private val firstFrameLogged = AtomicBoolean(false)
    private var server: ServerSocket? = null
    private var socket: Socket? = null
    private var thread: Thread? = null
    @Volatile private var listener: Listener = object : Listener {}

    fun listen(listener: Listener): Int {
        this.listener = listener
        val bound = ServerSocket()
        bound.reuseAddress = true
        bound.bind(InetSocketAddress(InetAddress.getByName("::"), 0))
        server = bound
        thread = Thread({ accept(bound) }, "airplay-screen").apply { isDaemon = true; start() }
        return bound.localPort
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        safeClose(socket)
        safeClose(server)
        thread?.interrupt()
    }

    private fun accept(bound: ServerSocket) {
        try {
            val accepted = bound.accept()
            serve(accepted, listener)
        } catch (error: Exception) {
            if (!closed.get()) listener.onClosed(error)
        }
    }

    /** The receive loop on an accepted connection (tests drive it over loopback). */
    internal fun serve(sock: Socket, listener: Listener) {
        this.listener = listener
        socket = sock
        run(sock)
    }

    private fun run(sock: Socket) {
        var failure: Throwable? = null
        val stats = StreamReceiveStats("video", onDiagnostic)
        try {
            val input = sock.getInputStream()
            while (!closed.get()) {
                stats.reading()
                val header = readFully(sock, input, HEADER_LEN, idleAllowed = true) ?: break
                val bodySize = readU32Le(header, 0)
                if (bodySize > MAX_BODY) break
                val body = readFully(sock, input, bodySize) ?: break
                stats.received(HEADER_LEN + bodySize)
                onMessage(header, body)
                stats.processed()
            }
        } catch (error: Exception) {
            failure = error
        } finally {
            stats.flush(ended = true)
            if (socket === sock) socket = null
            safeClose(sock)
            if (!closed.get()) listener.onClosed(failure)
        }
    }

    private fun onMessage(header: ByteArray, body: ByteArray) {
        when (header[OPCODE_OFFSET].toInt() and 0xff) {
            OP_VIDEO_FRAME -> {
                val payload = if (body.size >= ScreenCodec.TAG_SIZE) {
                    ScreenCodec.decryptFrame(key, frameCounter.get(), header, body)
                        .also { frameCounter.incrementAndGet() }
                } else {
                    body
                }
                if (firstFrameLogged.compareAndSet(false, true)) {
                    Log.i(
                        TAG,
                        "video first decrypted frame sealed=${body.size} plain=${payload.size} " +
                        "head=${payload.hexPrefix(16)}",
                    )
                }
                listener.onFrame(ScreenCodec.lengthPrefixedToAnnexB(payload))
            }
            OP_VIDEO_CONFIG -> {
                val (codec, codecData) = ScreenCodec.detectConfig(body)
                Log.i(TAG, "video codec config codec=$codec body=${body.size} data=${codecData.size}")
                listener.onCodec(codec)
                listener.onConfig(codecData)
            }
        }
    }

    /**
     * Reads [length] bytes. Before the first byte of a header ([idleAllowed]) it waits without limit; from then on,
     * and for a body from the start, the whole read must finish within [packetTimeoutNanos]. The socket timeout is
     * only the poll interval (at most 1 s), so close() and the deadline are both noticed promptly.
     */
    private fun readFully(sock: Socket, input: InputStream, length: Int, idleAllowed: Boolean = false): ByteArray? {
        if (length < 0) return null
        val output = ByteArray(length)
        var offset = 0
        var deadline = if (idleAllowed) 0L else System.nanoTime() + packetTimeoutNanos
        while (offset < length) {
            if (closed.get()) return null
            if (deadline != 0L) {
                val remaining = deadline - System.nanoTime()
                if (remaining <= 0) throw incomplete(idleAllowed, offset, length)
                sock.soTimeout = ((remaining + 999_999) / 1_000_000).coerceIn(1, 1000).toInt()
            } else {
                sock.soTimeout = 1000
            }
            val read = try {
                input.read(output, offset, length - offset)
            } catch (_: SocketTimeoutException) {
                continue
            }
            if (read < 0) return null
            if (read > 0 && deadline == 0L) deadline = System.nanoTime() + packetTimeoutNanos
            offset += read
        }
        return output
    }

    private fun incomplete(header: Boolean, received: Int, expected: Int) = SocketTimeoutException(
        "video ${if (header) "header" else "body"} incomplete after " +
            "${packetTimeoutNanos / 1_000_000} ms: received=$received expected=$expected",
    )

    private companion object {
        const val TAG = "xcertplay-usb"
        const val HEADER_LEN = 128
        const val OPCODE_OFFSET = 4
        const val OP_VIDEO_FRAME = 0
        const val OP_VIDEO_CONFIG = 1
        const val MAX_BODY = 8 * 1024 * 1024
        /** A started message must be complete within this (10 s; a 1080p key frame takes well under 1 s on Wi-Fi). */
        const val PACKET_TIMEOUT_NS = 10_000_000_000L
    }
}

private fun ByteArray.hexPrefix(length: Int): String =
    take(length).joinToString("") { "%02x".format(it.toInt() and 0xff) }

/** Extracts the avcC/hvcC codec-data record from a VideoConfig payload. */
object ScreenCodec {
    fun decryptFrame(key: ByteArray, counter: Long, header: ByteArray, body: ByteArray): ByteArray =
        if (body.size < TAG_SIZE) body
        else AirPlayCrypto.chachaOpen(key, AirPlayCrypto.nonce64(counter), body, header)

    /**
     * Replaces each four-byte NAL length with an Annex B start code in place.
     *
     * The payload is left untouched unless every length-prefixed NAL is valid, so malformed
     * input keeps its original bytes for the normal decoder error path.
     */
    fun lengthPrefixedToAnnexB(payload: ByteArray): ByteArray {
        if (payload.size < 4 || payload.startsWithStartCode()) return payload

        var offset = 0
        while (offset + 4 <= payload.size) {
            val length = readU32Be(payload, offset)
            offset += 4
            if (length <= 0 || length > payload.size - offset) return payload
            offset += length
        }
        if (offset != payload.size) return payload

        offset = 0
        while (offset + 4 <= payload.size) {
            val length = readU32Be(payload, offset)
            payload[offset] = 0
            payload[offset + 1] = 0
            payload[offset + 2] = 0
            payload[offset + 3] = 1
            offset += 4 + length
        }
        return payload
    }

    fun detectConfig(payload: ByteArray): Pair<VideoCodec, ByteArray> {
        for (index in 4..payload.size - 4) {
            val fourcc = String(payload, index, 4, Charsets.US_ASCII)
            when (fourcc) {
                "hvcC" -> return VideoCodec.H265 to payload.copyOfRange(index + 4, payload.size)
                "avcC" -> return VideoCodec.H264 to payload.copyOfRange(index + 4, payload.size)
            }
        }
        return if (looksLikeAvcC(payload)) VideoCodec.H264 to payload else VideoCodec.H265 to payload
    }

    private fun looksLikeAvcC(payload: ByteArray): Boolean {
        if (payload.size < 9) return false
        if ((payload[5].toInt() and 0x1f) < 1) return false
        val spsLength = readU16Be(payload, 6)
        if (8 + spsLength > payload.size) return false
        return (payload[8].toInt() and 0x1f) == 7
    }

    private fun readU16Be(source: ByteArray, offset: Int): Int =
        ((source[offset].toInt() and 0xff) shl 8) or (source[offset + 1].toInt() and 0xff)

    const val TAG_SIZE = 16
}

private fun ByteArray.startsWithStartCode(): Boolean =
    size >= 4 &&
        this[0] == 0.toByte() &&
        this[1] == 0.toByte() &&
        this[2] == 0.toByte() &&
        this[3] == 1.toByte()

private fun readU32Be(source: ByteArray, offset: Int): Int =
    ((source[offset].toInt() and 0xff) shl 24) or
        ((source[offset + 1].toInt() and 0xff) shl 16) or
        ((source[offset + 2].toInt() and 0xff) shl 8) or
        (source[offset + 3].toInt() and 0xff)

private fun readU32Le(source: ByteArray, offset: Int): Int =
    (source[offset].toInt() and 0xff) or
        ((source[offset + 1].toInt() and 0xff) shl 8) or
        ((source[offset + 2].toInt() and 0xff) shl 16) or
        ((source[offset + 3].toInt() and 0xff) shl 24)

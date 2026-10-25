package com.playport.server

import com.shilapi.xcertplay.transport.BlockingDuplexByteStream
import java.io.Closeable
import java.io.InputStream
import java.io.OutputStream
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * A [BlockingDuplexByteStream] over a child process' standard input/output.
 *
 * Used for the bt-bridge Bluetooth helper: the helper owns the RFCOMM channel and pipes its
 * bytes through stdin/stdout while this side speaks the iAP2 link.
 */
class ProcessByteStream(
    private val process: Process,
    private val label: String,
) : BlockingDuplexByteStream, Closeable {
    private val inbound = LinkedBlockingQueue<ByteArray>()
    private val input: InputStream = process.inputStream
    private val output: OutputStream = process.outputStream
    private val writeLock = Any()
    private val closing = AtomicBoolean(false)
    @Volatile private var ended = false
    private var remainder = ByteArray(0)
    private var remainderOffset = 0

    init {
        Thread({ pump() }, "$label-reader").apply {
            isDaemon = true
            start()
        }
        Thread({ drainErrors() }, "$label-stderr").apply {
            isDaemon = true
            start()
        }
    }

    private fun pump() {
        val buffer = ByteArray(8192)
        try {
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (count > 0) inbound.put(buffer.copyOf(count))
            }
        } catch (_: Exception) {
            // Falls through to the end marker.
        } finally {
            ended = true
            inbound.offer(ByteArray(0))
        }
    }

    private fun drainErrors() {
        val logger = org.slf4j.LoggerFactory.getLogger("bt-bridge")
        try {
            process.errorStream.bufferedReader().forEachLine { line ->
                if (line.isNotBlank()) logger.info("$label: $line")
            }
        } catch (_: Exception) {
        }
    }

    override fun send(data: ByteArray) {
        synchronized(writeLock) {
            output.write(data)
            output.flush()
        }
    }

    @Synchronized
    override fun recv(maxBytes: Int, timeoutMillis: Long): ByteArray? {
        require(maxBytes > 0) { "maxBytes must be positive" }
        require(timeoutMillis >= 0) { "timeoutMillis must not be negative" }
        if (remainderOffset == remainder.size) {
            remainder = ByteArray(0)
            remainderOffset = 0
            if (ended && inbound.isEmpty()) return ByteArray(0)
            val chunk = if (timeoutMillis == Long.MAX_VALUE) {
                inbound.take()
            } else {
                inbound.poll(timeoutMillis, TimeUnit.MILLISECONDS) ?: return null
            }
            if (chunk.isEmpty()) return ByteArray(0)
            remainder = chunk
        }
        val end = remainderOffset + minOf(maxBytes, remainder.size - remainderOffset)
        val result = remainder.copyOfRange(remainderOffset, end)
        remainderOffset = end
        return result
    }

    override fun close() {
        if (!closing.compareAndSet(false, true)) return
        // EOF lets the Linux bridge release its RFCOMM fd and unregister its BlueZ profile.
        // Do not start a replacement while the old helper is still cleaning up.
        runCatching { output.close() }
        try {
            if (!process.waitFor(5, TimeUnit.SECONDS)) {
                process.destroy()
                if (!process.waitFor(2, TimeUnit.SECONDS)) {
                    process.destroyForcibly()
                    process.waitFor(2, TimeUnit.SECONDS)
                }
            }
        } catch (_: InterruptedException) {
            process.destroyForcibly()
            Thread.currentThread().interrupt()
        } finally {
            ended = true
            inbound.offer(ByteArray(0))
            runCatching { input.close() }
        }
    }
}

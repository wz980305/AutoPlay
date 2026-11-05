package com.shilapi.xcertplay.airplay

import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Loopback sockets, a synthetic key and media; a 400 ms deadline stands in for the real 10 s. */
class ScreenStreamReadDeadlineTest {
    private class Connection : AutoCloseable {
        val screen = ScreenStream(ByteArray(32), packetTimeoutNanos = 400_000_000L)
        val cause = AtomicReference<Throwable?>()
        val ended = CountDownLatch(1)
        val frames = LinkedBlockingQueue<ByteArray>()
        val sender: Socket
        val receiver: Socket
        val worker: Thread

        init {
            ServerSocket(0, 1, InetAddress.getByName("127.0.0.1")).use { server ->
                sender = Socket("127.0.0.1", server.localPort)
                receiver = server.accept()
            }
            val listener = object : ScreenStream.Listener {
                override fun onFrame(naluBytes: ByteArray) { frames.add(naluBytes) }
                override fun onClosed(cause: Throwable?) { this@Connection.cause.set(cause); ended.countDown() }
            }
            worker = Thread({ screen.serve(receiver, listener) }, "screen-deadline-test").apply { isDaemon = true; start() }
        }

        fun send(bytes: ByteArray) {
            sender.getOutputStream().write(bytes)
            sender.getOutputStream().flush()
        }

        fun timedOut(started: Long) {
            assertTrue("an incomplete message never ended the stream", ended.await(5, TimeUnit.SECONDS))
            assertTrue("expected a read timeout, got ${cause.get()}", cause.get() is SocketTimeoutException)
            assertTrue("ended before the deadline", (System.nanoTime() - started) / 1_000_000 >= 350)
        }

        fun endsCleanly() {
            sender.shutdownOutput()
            assertTrue("EOF did not end the stream", ended.await(3, TimeUnit.SECONDS))
            assertNull("a valid stream was failed", cause.get())
        }

        override fun close() {
            screen.close()
            sender.close()
            receiver.close()
            worker.join(3_000)
            assertFalse("the receive thread leaked", worker.isAlive)
        }
    }

    /** A 128-byte header declaring [size] body bytes; [opcode] 255 is ignored by the receiver. */
    private fun header(size: Int, opcode: Int = 255) = ByteArray(128).also {
        for (i in 0 until 4) it[i] = (size ushr (8 * i)).toByte()
        it[4] = opcode.toByte()
    }

    @Test
    fun aHeaderThatStopsHalfwayEndsTheStream() = Connection().use { c ->
        val started = System.nanoTime()
        c.send(header(4).copyOf(20))
        c.timedOut(started)
    }

    @Test
    fun aBodyThatStopsHalfwayEndsTheStream() = Connection().use { c ->
        c.send(header(100))
        val started = System.nanoTime()
        c.send(ByteArray(10))
        c.timedOut(started)
    }

    @Test
    fun aQuietScreenMayWaitLongerThanTheDeadlineBetweenMessages() = Connection().use { c ->
        Thread.sleep(900)
        c.send(header(3) + byteArrayOf(1, 2, 3))
        Thread.sleep(900)
        c.send(header(0))
        c.endsCleanly()
    }

    @Test
    fun aMessageArrivingInPiecesWithinTheDeadlineIsFine() = Connection().use { c ->
        // An unencrypted frame (shorter than a tag) goes through as is: 4-byte length prefix -> Annex B start code.
        val nal = byteArrayOf(0, 0, 0, 2, 0x65, 1)
        val message = header(nal.size, opcode = 0) + nal
        for (piece in message.toList().chunked(40)) {
            c.send(piece.toByteArray())
            Thread.sleep(50)
        }
        assertArrayEquals(byteArrayOf(0, 0, 0, 1, 0x65, 1), c.frames.poll(3, TimeUnit.SECONDS))
        c.endsCleanly()
    }
}

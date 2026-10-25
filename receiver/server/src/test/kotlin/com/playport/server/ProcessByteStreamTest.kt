package com.playport.server

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class ProcessByteStreamTest {
    private class Child : Process() {
        val drained = CountDownLatch(1)
        private val chunks = ArrayDeque(listOf("abcd".toByteArray(), "EFGH".toByteArray()))
        private val input = object : InputStream() {
            override fun read(): Int = error("bulk reads only")
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                if (chunks.isEmpty()) { drained.countDown(); return -1 }
                val next = chunks.removeFirst()
                next.copyInto(buffer, offset)
                return next.size
            }
        }
        override fun getInputStream() = input
        override fun getErrorStream() = ByteArrayInputStream(byteArrayOf())
        override fun getOutputStream() = ByteArrayOutputStream()
        override fun waitFor() = 0
        override fun exitValue() = 0
        override fun destroy() {}
    }

    @Test fun partialReadsPreserveOrderAheadOfAlreadyQueuedChunks() {
        val child = Child()
        ProcessByteStream(child, "test").use { stream ->
            assertTrue(child.drained.await(2, TimeUnit.SECONDS))
            for (expected in listOf("ab", "cd", "EF", "GH")) {
                assertArrayEquals(expected.toByteArray(), stream.recv(2, 1000))
            }
            assertArrayEquals(byteArrayOf(), stream.recv(2, 1000))
            assertArrayEquals(byteArrayOf(), stream.recv(2, 0))
        }
    }
}

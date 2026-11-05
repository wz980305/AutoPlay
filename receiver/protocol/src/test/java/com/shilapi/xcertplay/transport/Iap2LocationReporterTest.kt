package com.shilapi.xcertplay.transport

import com.shilapi.xcertplay.iap2.wire.Iap2Frame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Iap2LocationReporterTest {
    private class FakeProvider(var fix: String? = "\$GPGGA\r\n") : Iap2LocationProvider {
        var started = 0
        var stopped = 0
        var requested: Set<Int>? = null
        var asked = 0
        var startResult = true
        override fun onRequested(components: Set<Int>) { requested = components }
        override fun start(): Boolean { started++; return startResult }
        override fun stop() { stopped++ }
        override fun latestNmea(): String? { asked++; return fix }
    }

    private var nowNanos = 0L
    private val sent = mutableListOf<Iap2Frame>()
    private fun advance(millis: Long) { nowNanos += millis * 1_000_000 }

    /** 0xFFFA asking for sentence types 0 and 1 (void parameters: length 4, id). */
    private val start = Iap2Frame(Iap2LocationMessages.START_LOCATION_INFORMATION, byteArrayOf(0, 4, 0, 0, 0, 4, 0, 1))
    private val stop = Iap2Frame(Iap2LocationMessages.STOP_LOCATION_INFORMATION, ByteArray(0))

    @Test
    fun startsOnRequestAndSendsAtOnce() {
        val provider = FakeProvider()
        val reporter = Iap2LocationReporter(provider, {}, { nowNanos })

        assertTrue(reporter.handle(start) { sent += it })

        assertEquals(setOf(0, 1), provider.requested)
        assertEquals(1, provider.started)
        assertTrue(reporter.active)
        assertEquals(1, sent.size)
        assertEquals(Iap2LocationMessages.LOCATION_INFORMATION, sent.single().messageId)
    }

    @Test
    fun asksAgainOnlyAfterTheInterval() {
        val provider = FakeProvider()
        val reporter = Iap2LocationReporter(provider, {}, { nowNanos }, intervalMillis = 250)
        reporter.handle(start) { sent += it }

        advance(100)
        reporter.tick { sent += it }
        assertEquals(1, provider.asked)
        assertEquals(150, reporter.pollTimeout(10_000))

        advance(150)
        reporter.tick { sent += it }
        assertEquals(2, provider.asked)
        assertEquals(2, sent.size)
    }

    @Test
    fun sendsNothingWhenTheProviderHasNoFreshFix() {
        val provider = FakeProvider(fix = null)
        val reporter = Iap2LocationReporter(provider, {}, { nowNanos })
        reporter.handle(start) { sent += it }
        advance(1_000)
        reporter.tick { sent += it }

        assertTrue(sent.isEmpty())
        assertEquals(2, provider.asked)
    }

    @Test
    fun stopsOnRequestAndOnClose() {
        val provider = FakeProvider()
        val reporter = Iap2LocationReporter(provider, {}, { nowNanos })
        reporter.handle(start) { sent += it }

        assertTrue(reporter.handle(stop) { sent += it })
        assertFalse(reporter.active)
        assertEquals(1, provider.stopped)
        advance(5_000)
        reporter.tick { sent += it }
        assertEquals(1, sent.size)
        assertEquals(10_000, reporter.pollTimeout(10_000))

        reporter.handle(start) { sent += it }
        reporter.close()
        assertEquals(2, provider.stopped)
    }

    @Test
    fun withoutAProviderOrWhenItDoesNotStartNothingIsActive() {
        val none = Iap2LocationReporter(null, {}, { nowNanos })
        none.handle(start) { sent += it }
        assertFalse(none.active)

        val refusing = FakeProvider().apply { startResult = false }
        val reporter = Iap2LocationReporter(refusing, {}, { nowNanos })
        reporter.handle(start) { sent += it }
        assertFalse(reporter.active)
        assertTrue(sent.isEmpty())
    }

    @Test
    fun otherMessagesAreNotItsBusiness() {
        val reporter = Iap2LocationReporter(FakeProvider(), {}, { nowNanos })
        assertFalse(reporter.handle(Iap2Frame(0x4e0d, ByteArray(0))) { sent += it })
    }

    @Test
    fun unreadableRequestStillStarts() {
        val provider = FakeProvider()
        val reporter = Iap2LocationReporter(provider, {}, { nowNanos })
        reporter.handle(Iap2Frame(Iap2LocationMessages.START_LOCATION_INFORMATION, byteArrayOf(0, 9))) { sent += it }
        assertEquals(emptySet<Int>(), provider.requested)
        assertTrue(reporter.active)
    }
}

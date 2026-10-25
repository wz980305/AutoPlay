package com.playport.server

import org.junit.Assert.*
import org.junit.Test

class WirelessReconnectTest {
    @Test fun absentPhoneNeverInvitedRegardlessOfBluetoothOrTime() {
        for (running in listOf(true, false)) {
            assertFalse(CarPlayServer.shouldRestartWireless(false, running, 3600_000, false))
        }
    }
    @Test fun manualReturnStartsPromptlyAndActiveSessionWins() {
        assertTrue(CarPlayServer.shouldRestartWireless(false, false, 5_000, true))
        assertFalse(CarPlayServer.shouldRestartWireless(false, false, 4_999, true))
        assertFalse(CarPlayServer.shouldRestartWireless(true, false, 90_000, true))
    }
    @Test fun acceptedHandoffIsNotInterruptedWhileThePhoneJoinsTheWifi() {
        val accepted = 100_000L
        assertTrue(CarPlayServer.joiningAfterHandoff(accepted + 9_000, accepted))
        assertTrue(CarPlayServer.joiningAfterHandoff(accepted + 24_999, accepted))
        assertFalse(CarPlayServer.joiningAfterHandoff(accepted + 25_000, accepted))
        assertFalse(CarPlayServer.joiningAfterHandoff(accepted, Long.MIN_VALUE / 2))
    }
    @Test fun stalledHandoffIsRetriedRightAfterTheJoinGraceOnly() {
        val accepted = 100_000L
        assertFalse(CarPlayServer.handoffStalled(accepted + 24_999, accepted))
        assertTrue(CarPlayServer.handoffStalled(accepted + 25_000, accepted))
        assertTrue(CarPlayServer.handoffStalled(accepted + 44_999, accepted))
        assertFalse(CarPlayServer.handoffStalled(accepted + 45_000, accepted))
        assertFalse(CarPlayServer.handoffStalled(accepted, Long.MIN_VALUE / 2))
    }
    @Test fun presentPhoneWithStaleBootstrapRetriesAfterBoundedHandshakeGrace() {
        assertFalse(CarPlayServer.shouldRestartWireless(false, true, 14_999, true))
        assertTrue(CarPlayServer.shouldRestartWireless(false, true, 15_000, true))
    }
    @Test fun knownEndedSessionRecoversWithoutCooldownButNeverWithoutPresence() {
        assertTrue(CarPlayServer.shouldRestartWireless(false, true, 0, true, true))
        assertFalse(CarPlayServer.shouldRestartWireless(false, true, 90_000, false, true))
        assertFalse(CarPlayServer.shouldRestartWireless(true, true, 90_000, true, true))
    }
    @Test fun aFailedInvitationRightAfterADisplayChangeIsRepeatedAFewTimesOnly() {
        val armed = 100_000L + CarPlayServer.QUICK_RETRY_WINDOW_MS
        assertTrue(CarPlayServer.quickRetry(100_000L + 1_200, armed, CarPlayServer.QUICK_RETRIES))
        assertTrue(CarPlayServer.quickRetry(100_000L + 4_000, armed, 1))
        assertFalse("retries used up", CarPlayServer.quickRetry(100_000L + 5_000, armed, 0))
        assertFalse("too long after the change", CarPlayServer.quickRetry(armed, armed, CarPlayServer.QUICK_RETRIES))
        assertFalse("never armed", CarPlayServer.quickRetry(100_000L, Long.MIN_VALUE / 2, 0))
    }
    @Test fun bridgeCloseAllowsProfileCleanupBeforeDestroy() {
        val child = object : Process() {
            var stdinClosed = false
            var cleaned = false
            var destroyed = false
            override fun getOutputStream() = object : java.io.ByteArrayOutputStream() {
                override fun close() { stdinClosed = true }
            }
            override fun getInputStream() = java.io.ByteArrayInputStream(byteArrayOf())
            override fun getErrorStream() = java.io.ByteArrayInputStream(byteArrayOf())
            override fun waitFor(): Int { cleaned = true; return 0 }
            override fun waitFor(timeout: Long, unit: java.util.concurrent.TimeUnit): Boolean {
                assertTrue("EOF requests graceful bridge cleanup", stdinClosed)
                cleaned = true
                return true
            }
            override fun exitValue() = if (cleaned) 0 else throw IllegalThreadStateException()
            override fun destroy() { destroyed = true }
        }
        ProcessByteStream(child, "cleanup-test").close()
        assertTrue("close must wait for DisconnectProfile/UnregisterProfile", child.cleaned)
        assertFalse("a clean exit must not be killed", child.destroyed)
    }
}

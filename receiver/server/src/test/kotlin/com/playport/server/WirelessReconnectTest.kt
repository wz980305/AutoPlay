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
    @Test fun presentPhoneWithStaleBootstrapRetriesAfterBoundedHandshakeGrace() {
        assertFalse(CarPlayServer.shouldRestartWireless(false, true, 14_999, true))
        assertTrue(CarPlayServer.shouldRestartWireless(false, true, 15_000, true))
    }
    @Test fun knownEndedSessionRecoversWithoutCooldownButNeverWithoutPresence() {
        assertTrue(CarPlayServer.shouldRestartWireless(false, true, 0, true, true))
        assertFalse(CarPlayServer.shouldRestartWireless(false, true, 90_000, false, true))
        assertFalse(CarPlayServer.shouldRestartWireless(true, true, 90_000, true, true))
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

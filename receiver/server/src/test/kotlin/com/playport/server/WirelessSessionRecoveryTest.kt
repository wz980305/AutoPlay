package com.playport.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WirelessSessionRecoveryTest {
    private val phone = "02:00:00:00:00:A1"

    @Test fun theOwnerOfADroppedSessionGetsExactlyOneInvitation() {
        val recovery = WirelessSessionRecovery()
        recovery.active(phone)
        recovery.ended(1_000)
        assertEquals(phone, recovery.candidate(2_000))
        assertFalse("another phone cannot use it", recovery.take(2_000, "02:00:00:00:00:B2"))
        assertTrue(recovery.take(2_000, phone))
        assertFalse("used up", recovery.take(2_001, phone))
        assertNull(recovery.candidate(2_001))
    }

    @Test fun aFailedInvitationDoesNotRenewIt() {
        val recovery = WirelessSessionRecovery()
        recovery.active(phone)
        recovery.ended(0)
        assertTrue(recovery.take(10, phone))
        // The invitation led to nothing; a second "end" without a new live session grants nothing.
        recovery.ended(5_000)
        assertNull(recovery.candidate(5_001))
    }

    @Test fun itExpiresAfterTheWindow() {
        val recovery = WirelessSessionRecovery(windowMs = 45_000)
        recovery.active(phone)
        recovery.ended(1_000)
        assertEquals(phone, recovery.candidate(45_999))
        assertNull(recovery.candidate(46_000))
        assertFalse(recovery.take(46_001, phone))
    }

    @Test fun whatTheBoxDoesOnPurposeCancelsIt() {
        val recovery = WirelessSessionRecovery()
        recovery.active(phone)
        recovery.cancel()                       // idle release, display or location change, shutdown
        recovery.ended(1_000)
        assertNull(recovery.candidate(1_001))

        recovery.active(phone)
        recovery.ended(2_000)
        recovery.cancel()
        assertNull(recovery.candidate(2_001))
    }

    @Test fun aSessionWithoutAKnownOwnerGrantsNothing() {
        val recovery = WirelessSessionRecovery()
        recovery.active(null)
        recovery.ended(0)
        assertNull(recovery.candidate(1))
        recovery.ended(0)                       // ended twice, or before any session
        assertNull(recovery.candidate(1))
    }

    @Test fun aNewLiveSessionReplacesAnOldGrant() {
        val recovery = WirelessSessionRecovery()
        recovery.active(phone)
        recovery.ended(0)
        recovery.active("02:00:00:00:00:B2")    // another phone connected meanwhile
        assertNull(recovery.candidate(1))
        recovery.ended(10)
        assertEquals("02:00:00:00:00:B2", recovery.candidate(11))
    }
}

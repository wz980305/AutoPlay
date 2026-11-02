package com.playport.server

import org.junit.Assert.assertEquals
import org.junit.Test

/** Nobody watching for 5 min: the iPhone leaves CarPlay until a page opens (it ran hot at home, 2026-10-13). */
class IdleReleaseTest {
    private val wait = CarPlayServer.IDLE_RELEASE_MS

    @Test fun aSessionNobodyWatchesIsReleasedAfterTheWait() {
        assertEquals(IdleAction.NONE, CarPlayServer.idleAction(now = wait - 1, viewerSeenAt = 0, session = true, parked = false))
        assertEquals(IdleAction.RELEASE, CarPlayServer.idleAction(now = wait, viewerSeenAt = 0, session = true, parked = false))
        assertEquals(IdleAction.NONE, CarPlayServer.idleAction(now = wait, viewerSeenAt = 0, session = false, parked = false))
    }

    @Test fun aSettingChangesTheWaitOrTurnsItOff() {
        // A trade-off left to the owner: a cool iPhone, or the picture at once when a page opens again.
        assertEquals(IdleAction.RELEASE, CarPlayServer.idleAction(now = 30_000, viewerSeenAt = 0, session = true, parked = false, releaseMs = 30_000))
        assertEquals(IdleAction.NONE, CarPlayServer.idleAction(now = 100 * wait, viewerSeenAt = 0, session = true, parked = false, releaseMs = 0))
    }

    @Test fun parkedUntilAViewerComesBack() {
        assertEquals(IdleAction.WAIT, CarPlayServer.idleAction(now = 10 * wait, viewerSeenAt = 0, session = false, parked = true))
        assertEquals(IdleAction.RESUME, CarPlayServer.idleAction(now = 10 * wait, viewerSeenAt = 10 * wait, session = false, parked = true))
    }

    // IdleReleaseTimer (DashPlay 2026.10.29): every accepted connection gets its own full grace period.

    @Test fun lateFirstConnectionGetsTheFullWaitToAuthenticate() {
        val timer = IdleReleaseTimer(0, wait)
        assertEquals(IdleAction.NONE, timer.action(2 * wait, false, null))
        val authenticating = Any()
        assertEquals(IdleAction.NONE, timer.action(2 * wait + 1, false, authenticating))
        assertEquals(IdleAction.NONE, timer.action(3 * wait, false, authenticating))
        assertEquals(IdleAction.RELEASE, timer.action(3 * wait + 1, false, authenticating))
        assertEquals(IdleAction.WAIT, timer.action(3 * wait + 2, false, null))
        assertEquals(IdleAction.RESUME, timer.action(3 * wait + 3, true, null))
    }

    @Test fun replacementConnectionGetsItsOwnGraceWithoutAnEmptyPoll() {
        val timer = IdleReleaseTimer(0, wait)
        val first = Any()
        val second = Any()
        assertEquals(IdleAction.NONE, timer.action(0, false, first))
        assertEquals(IdleAction.NONE, timer.action(wait - 1, false, first))
        assertEquals(IdleAction.NONE, timer.action(wait, false, second))
        assertEquals(IdleAction.NONE, timer.action(2 * wait - 1, false, second))
        assertEquals(IdleAction.RELEASE, timer.action(2 * wait, false, second))
    }

    @Test fun openingThePageExtendsTheWaitAndZeroStillDisablesRelease() {
        val session = Any()
        val timer = IdleReleaseTimer(0, wait)
        timer.action(0, false, session)
        assertEquals(IdleAction.NONE, timer.action(wait, true, session))
        assertEquals(IdleAction.NONE, timer.action(2 * wait - 1, false, session))
        assertEquals(IdleAction.RELEASE, timer.action(2 * wait, false, session))
        val disabled = IdleReleaseTimer(0, 0)
        assertEquals(IdleAction.NONE, disabled.action(0, false, session))
        assertEquals(IdleAction.NONE, disabled.action(100 * wait, false, session))
    }

    @Test fun explicitNewConnectionWhileParkedGetsOneGracePeriod() {
        val timer = IdleReleaseTimer(0, 30_000)
        val first = Any()
        timer.action(0, false, first)
        assertEquals(IdleAction.RELEASE, timer.action(30_000, false, first))
        assertEquals(IdleAction.WAIT, timer.action(30_001, false, first))
        timer.action(30_002, false, null)
        val newlyPaired = Any()
        assertEquals(IdleAction.NONE, timer.action(60_000, false, newlyPaired))
        assertEquals(IdleAction.RELEASE, timer.action(90_000, false, newlyPaired))
    }
}

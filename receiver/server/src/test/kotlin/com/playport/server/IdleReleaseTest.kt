package com.playport.server

import org.junit.Assert.assertEquals
import org.junit.Test

/** Nobody watching for 2 min: the iPhone leaves CarPlay until a page opens (it ran hot at home, 2026-10-13). */
class IdleReleaseTest {
    private val wait = CarPlayServer.IDLE_RELEASE_MS

    @Test fun aSessionNobodyWatchesIsReleasedAfterTheWait() {
        assertEquals(IdleAction.NONE, CarPlayServer.idleAction(now = wait - 1, viewerSeenAt = 0, session = true, parked = false))
        assertEquals(IdleAction.RELEASE, CarPlayServer.idleAction(now = wait, viewerSeenAt = 0, session = true, parked = false))
        assertEquals(IdleAction.NONE, CarPlayServer.idleAction(now = wait, viewerSeenAt = 0, session = false, parked = false))
    }

    @Test fun parkedUntilAViewerComesBack() {
        assertEquals(IdleAction.WAIT, CarPlayServer.idleAction(now = 10 * wait, viewerSeenAt = 0, session = false, parked = true))
        assertEquals(IdleAction.RESUME, CarPlayServer.idleAction(now = 10 * wait, viewerSeenAt = 10 * wait, session = false, parked = true))
    }
}

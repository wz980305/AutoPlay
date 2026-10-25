package com.playport.server

import org.junit.Assert.assertEquals
import org.junit.Test

class ViewerStatsTest {
    @Test fun formatsReceiverTotalsAndOnlySafeViewerNumbers() {
        val line = WebHub.statsLine(3, 1200, 7, 5 * 1024 * 1024,
            mapOf("fps" to 29.6, "decodeMs" to 12.0, "bad key!" to 1.0, "nan" to Double.NaN))
        assertEquals("viewer stats client=3 sentFrames=1200 droppedFrames=7 sentKB=5120 decodeMs=12 fps=29.6", line)
    }
}

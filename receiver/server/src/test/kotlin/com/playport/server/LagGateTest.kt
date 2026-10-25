package com.playport.server

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LagGateTest {
    private val ms = 1_000_000L

    @Test fun aPageThatNeverAnswersIsNeverHeldBack() {
        val gate = LagGate(300 * ms, 192_000)
        gate.marked(1, 0, 0)
        assertTrue(gate.open(10_000 * ms, 50_000_000))
    }

    @Test fun picturePausesOnceMoreIsOnTheWayThanThePageTakesIn300Ms() {
        val gate = LagGate(300 * ms, 64_000)
        // The page took 100 kB in 400 ms: 250 kB/s, so 300 ms is 75 kB.
        gate.marked(1, 0, 0); gate.acked(1, 0)
        gate.marked(2, 0, 100_000); gate.acked(2, 400 * ms)
        assertTrue(gate.open(400 * ms, 100_000 + 70_000))
        assertFalse(gate.open(400 * ms, 100_000 + 80_000))
    }

    @Test fun aFastPageGetsAWideWindowAndASmallWindowStillPassesAKeyframe() {
        val gate = LagGate(300 * ms, 192_000)
        gate.marked(1, 0, 0); gate.acked(1, 0)
        gate.marked(2, 0, 2_000_000); gate.acked(2, 1_000 * ms)   // 2 MB/s
        assertTrue(gate.open(1_000 * ms, 2_000_000 + 590_000))
        assertFalse(gate.open(1_000 * ms, 2_000_000 + 610_000))
        // Nothing measured yet: the floor still lets a keyframe of a fresh session through.
        val fresh = LagGate(300 * ms, 192_000)
        fresh.marked(1, 0, 0); fresh.acked(1, 5 * ms)
        assertTrue(fresh.open(5 * ms, 150_000))
    }

    @Test fun aBurstAfterAStillScreenPassesWhileThePageAnswersAtOnce() {
        // 2026-10-12 drive: a still screen sends little, so the intake measured over 2 s is low; a page swipe's
        // burst then went over it and frames were dropped (64 of 66 times) while the page was 47 ms behind.
        val gate = LagGate(300 * ms, 192_000)
        gate.marked(1, 0, 0); gate.acked(1, 40 * ms)
        gate.marked(2, 200 * ms, 20_000); gate.acked(2, 240 * ms)          // about 100 kB/s: window is the floor
        assertTrue(gate.open(300 * ms, 20_000 + 600_000))                  // answered in 40 ms: let it through
        gate.marked(3, 400 * ms, 700_000)
        assertTrue(gate.open(450 * ms, 20_000 + 800_000))                  // its mark is out for only 50 ms
        assertFalse(gate.open(600 * ms, 20_000 + 900_000))                 // 200 ms without an answer: behind
    }

    @Test fun aPageThatAnswersLateIsHeldBackAsBefore() {
        val gate = LagGate(300 * ms, 192_000)
        gate.marked(1, 0, 0); gate.acked(1, 0)
        gate.marked(2, 200 * ms, 100_000); gate.acked(2, 600 * ms)         // its last answer took 400 ms
        assertFalse(gate.open(600 * ms, 100_000 + 300_000))
    }

    @Test fun anAnswerClearsEveryEarlierMark() {
        val gate = LagGate(300 * ms, 64_000)
        gate.marked(1, 0, 0); gate.marked(2, 100 * ms, 10_000); gate.marked(3, 200 * ms, 20_000)
        gate.acked(3, 250 * ms)
        // Delivered up to mark 3: 5 kB on the way is within the floor.
        assertTrue(gate.open(250 * ms, 25_000))
    }
}

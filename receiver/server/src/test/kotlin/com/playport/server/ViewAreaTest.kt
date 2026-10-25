package com.playport.server

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** View areas (2026-10-14): the page's window shapes, switched without reconnecting CarPlay. */
class ViewAreaTest {
    private val windowed = ViewArea(1280, 996)
    private val full = ViewArea(1920, 1080)

    @Test
    fun areasMustFitTheStream() {
        assertNull(DisplayState.validateAreas(1920, 1080, listOf(full, windowed), 1))
        assertNotNull(DisplayState.validateAreas(1280, 996, listOf(full, windowed), 0))
        assertNotNull(DisplayState.validateAreas(1920, 1080, listOf(full, ViewArea(1281, 996)), 0))
        assertNotNull(DisplayState.validateAreas(1920, 1080, listOf(full, windowed), 2))
        assertNull(DisplayState.validateAreas(1920, 1080, List(DisplayState.MAX_AREAS) { windowed }, 0))
        assertNotNull(DisplayState.validateAreas(1920, 1080, List(DisplayState.MAX_AREAS + 1) { windowed }, 0))
    }

    @Test
    fun onlyTheAreaInUseMayChangeWithoutReconnecting() {
        val display = DisplayState(1920, 1080, 30, 100, true, listOf(windowed, full), 0)
        assertTrue(display.sameStream(1920, 1080, 30, 100, true, listOf(windowed, full)))
        assertFalse(display.sameStream(1920, 1080, 30, 100, false, listOf(windowed, full)))
        assertFalse(display.sameStream(1920, 1080, 30, 100, true, listOf(windowed)))
        display.useArea(1)
        assertEquals(1, display.area)
        display.useArea(7)
        assertEquals(1, display.area)
    }

    @Test
    fun theNarrowestAreaKeepsThePlainDensity() {
        assertEquals(300, DisplayState(1920, 1080, 30, 100, true, listOf(windowed, full), 0).physicalWidthMm())
        assertNull(DisplayState(1280, 996, 30, 100).physicalWidthMm())
    }

    @Test
    fun theRequestAndTheSavedSettingsCarryTheAreas() {
        val request = Json.decodeFromString(DisplayRequest.serializer(),
            """{"width":1920,"height":1080,"fps":30,"uiScale":100,"hevc":true,"areas":[{"width":1280,"height":996},{"width":1920,"height":1080}],"area":1}""")
        assertEquals(listOf(windowed, full), request.areas)
        assertEquals(1, request.area)
        val old = Json.decodeFromString(DisplayRequest.serializer(), """{"width":1280,"height":720}""")
        assertTrue("an older page sends no areas", old.areas.isEmpty())

        val prefs = DisplayPrefs(1920, 1080, 30, 100, true, listOf(windowed, full), 1)
        val json = Json { encodeDefaults = true }
        assertEquals(prefs, json.decodeFromString(DisplayPrefs.serializer(), json.encodeToString(DisplayPrefs.serializer(), prefs)))
        assertTrue("an older config.json has no areas",
            json.decodeFromString(DisplayPrefs.serializer(), """{"width":1280,"height":720}""").areas.isEmpty())
    }

    @Test
    fun aChangeThatCanWaitIsTakenUpWhenTheSessionEnds() {
        val display = DisplayState(1280, 996, 60, 100, false)
        val sharper = Json.decodeFromString(DisplayRequest.serializer(),
            """{"width":1920,"height":1140,"fps":60,"hevc":true,"defer":true,"reason":"quality"}""")
        assertTrue(sharper.defer)
        display.defer(sharper)
        assertEquals("the running session keeps what the phone was told", 1280, display.width)
        assertTrue(display.applyPending())
        assertEquals(listOf(1920, 1140, 60), listOf(display.width, display.height, display.fps))
        assertTrue(display.hevc)
        assertNull(display.pending)
        assertFalse("nothing left to take up", display.applyPending())

        display.defer(sharper.copy(width = 1280, height = 996))
        display.update(1920, 1080, 30, 100, false)
        assertNull("a change that could not wait replaces the waiting one", display.pending)
        assertFalse(display.applyPending())
        assertEquals(1920, display.width)

        display.defer(sharper.copy(width = 7))
        assertFalse("a bad waiting change is dropped", display.applyPending())
        assertEquals(1920, display.width)
    }

    @Test
    fun aWaitingChangeIsWhatTheNextStartUses() {
        val display = DisplayState(1280, 720, 30, 100, false)
        assertEquals(DisplayPrefs(1280, 720, 30, 100, false), display.forNextStart())
        display.defer(DisplayRequest(1372, 1260, 30, 100, hevc = true, defer = true, reason = "quality"))
        assertEquals("the box may lose power before the session ends", DisplayPrefs(1372, 1260, 30, 100, true),
            display.forNextStart())
        assertEquals("the running session keeps its own", 1280, display.width)
        display.defer(DisplayRequest(1920, 1080, 30, 100, areas = listOf(full, windowed), area = 1, defer = true))
        assertEquals(DisplayPrefs(1920, 1080, 30, 100, false, listOf(full, windowed), 1), display.forNextStart())
    }
}

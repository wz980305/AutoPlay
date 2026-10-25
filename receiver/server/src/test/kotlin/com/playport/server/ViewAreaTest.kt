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
        assertNotNull(DisplayState.validateAreas(1920, 1080, List(5) { windowed }, 0))
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
}

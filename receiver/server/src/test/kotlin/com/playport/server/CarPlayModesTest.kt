package com.playport.server

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CarPlayModesTest {
    @Test
    fun aCallAndNavigationOnTheIphoneAreNamedAndKeptAsTheyCame() {
        val params = mapOf<String, Any?>(
            "resources" to listOf(mapOf("resourceID" to 2L, "entity" to 1L)),
            "appStates" to listOf(
                mapOf("appStateID" to 1L, "entity" to 0L, "speechMode" to -1L),
                mapOf("appStateID" to 2L, "entity" to 1L),
                mapOf("appStateID" to 3L, "entity" to 1L),
            ),
        )
        assertEquals(
            "call=iPhone speech=none(mode -1) navigation=iPhone " +
                "[appStateID=1,entity=0,speechMode=-1, appStateID=2,entity=1, appStateID=3,entity=1]",
            CarPlayModes.appStates(params),
        )
    }

    @Test
    fun whatIsNotKnownIsStillLoggedByItsNumbers() {
        val params = mapOf<String, Any?>(
            "appStates" to listOf(
                mapOf("appStateID" to 2, "state" to false),
                mapOf("appStateID" to 9L, "entity" to 7L),
                mapOf("appStateID" to 3L, "entity" to 5L),
                "not a map",
            ),
        )
        assertEquals(
            "call=off navigation=entity5 [appStateID=2,state=false, appStateID=9,entity=7, appStateID=3,entity=5]",
            CarPlayModes.appStates(params),
        )
    }

    @Test
    fun noAppStatesNoLine() {
        assertNull(CarPlayModes.appStates(emptyMap()))
        assertNull(CarPlayModes.appStates(mapOf("appStates" to emptyList<Any>())))
        assertNull(CarPlayModes.appStates(mapOf("appStates" to "garbage")))
    }
}

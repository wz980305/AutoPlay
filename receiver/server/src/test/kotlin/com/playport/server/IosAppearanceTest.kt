package com.playport.server

import org.junit.Assert.*
import org.junit.Test

class IosAppearanceTest {
    @Test fun ios272SelectsAppearanceUpdates() {
        val major = CarPlayServer.iosMajorVersion("27.2")
        assertEquals(27, major)
        assertTrue(CarPlayServer.appearanceUpdatesForMajor(major))
    }

    @Test fun ios26RetainsLegacyNightModeAndUnknownRetainsExistingDefault() {
        assertFalse(CarPlayServer.appearanceUpdatesForMajor(CarPlayServer.iosMajorVersion("26.4.1")))
        assertNull(CarPlayServer.iosMajorVersion(""))
        assertTrue(CarPlayServer.appearanceUpdatesForMajor(null))
    }
}

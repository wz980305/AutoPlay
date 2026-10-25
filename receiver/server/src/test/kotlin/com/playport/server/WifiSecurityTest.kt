package com.playport.server

import com.shilapi.xcertplay.transport.Iap2WirelessSecurity
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class WifiSecurityTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun handsTheIphoneTheHotspotsRealSecurity() {
        val root = temporary.root.toPath()
        val expected = mapOf(
            "open" to Iap2WirelessSecurity.NONE,
            "wpa2" to Iap2WirelessSecurity.WPA_WPA2,
            "wpa3-transition" to Iap2WirelessSecurity.WPA3_TRANSITION,
            "wpa3" to Iap2WirelessSecurity.WPA3_ONLY,
        )
        for ((name, security) in expected) {
            val config = PersistentConfig(wifiSecurity = name).toServerDefaults(root, root)
            assertEquals(name, security, config.wifiSecurity)
            val display = DisplayState(1280, 720, 30, 100)
            assertEquals(name, PersistentConfig.of(config, display).wifiSecurity)
        }
    }
}

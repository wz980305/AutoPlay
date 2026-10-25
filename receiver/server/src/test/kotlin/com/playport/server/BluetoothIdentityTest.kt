package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayInfoPlist
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class BluetoothIdentityTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun wirelessInfoUsesActualAdapterInsteadOfGeneratedAirPlayId() {
        val root = temporary.root.toPath()
        val bridge = root.resolve("fake-bridge")
        java.nio.file.Files.writeString(bridge, "#!/bin/sh\nprintf '02:11:22:33:44:55\\n'\n")
        check(bridge.toFile().setExecutable(true))
        val server = CarPlayServer(ServerConfig(
            identityDir = root, stateDir = root.resolve("state"), bindAddress = "127.0.0.1",
            wireless = true, bluetoothBridge = bridge,
        ))
        server.use {
            assertNotEquals("02:11:22:33:44:55", it.deviceId)
            assertEquals(listOf("02:11:22:33:44:55"), AirPlayInfoPlist.build(it.airPlayConfig)["bluetoothIDs"])
            assertEquals(it.deviceId, it.airPlayConfig.deviceId)
        }
    }
}

package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayInfoPlist
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class OemSettingsTest {
    @get:Rule val temporary = TemporaryFolder()
    @Test fun advertisesRealSettingsIconToPhone() {
        val root = temporary.root.toPath()
        CarPlayServer(ServerConfig(identityDir = root, stateDir = root.resolve("state"), bindAddress = "127.0.0.1")).use { server ->
            val info = AirPlayInfoPlist.build(server.airPlayConfig)
            assertEquals(true, info["oemIconVisible"])
            assertEquals("盒子设置", info["oemIconLabel"])
            val icon = (info["oemIcons"] as List<*>).single() as Map<*, *>
            val bytes = icon["imageData"] as ByteArray
            assertArrayEquals(byteArrayOf(-119,80,78,71,13,10,26,10), bytes.take(8).toByteArray())
            assertEquals(180, java.nio.ByteBuffer.wrap(bytes,16,4).int)
            assertEquals(180, java.nio.ByteBuffer.wrap(bytes,20,4).int)
        }
    }
}

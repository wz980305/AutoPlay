package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayInfoPlist
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class AudioCapabilitiesTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun declaresDuplexFormatsForTheEnabledMicrophoneUplink() {
        val root = temporary.root.toPath()
        CarPlayServer(ServerConfig(identityDir = root, stateDir = root.resolve("state"), bindAddress = "127.0.0.1")).use { server ->
            val formats = AirPlayInfoPlist.build(server.airPlayConfig)["audioFormats"] as List<*>
            for (name in listOf("default", "telephony", "speechRecognition")) {
                val format = formats.map { it as Map<*, *> }.first { it["type"] == 100 && it["audioType"] == name }
                assertTrue("$name must advertise microphone input", (format["audioInputFormats"] as? Number)?.toInt()?.let { it != 0 } == true)
            }
        }
    }
}

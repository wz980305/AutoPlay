package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayInfoPlist
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class AudioCapabilitiesTest {
    @get:Rule val temporary = TemporaryFolder()

    /** Tesla-only: calls, Siri and the microphone stay on the car's Bluetooth; the page gets prompts, alerts and music. */
    @Test fun offersNoMicrophoneAndNoVoiceStreams() {
        val root = temporary.root.toPath()
        CarPlayServer(ServerConfig(identityDir = root, stateDir = root.resolve("state"), bindAddress = "127.0.0.1")).use { server ->
            val formats = (AirPlayInfoPlist.build(server.airPlayConfig)["audioFormats"] as List<*>).map { it as Map<*, *> }
            val names = formats.map { it["audioType"] }
            assertFalse("telephony" in names)
            assertFalse("speechRecognition" in names)
            assertTrue("default" in names && "alert" in names && "media" in names)
            for (format in formats) assertFalse("${format["audioType"]} must not advertise microphone input", format.containsKey("audioInputFormats"))
        }
    }
}

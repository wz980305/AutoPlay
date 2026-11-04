package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayInfoPlist
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class AudioCapabilitiesTest {
    @get:Rule val temporary = TemporaryFolder()

    /** 1.3.0 (docs/AUDIO.md, ADR-16): the receiver offers the iPhone no audio at all, so music, navigation prompts,
     *  calls and Siri stay on the car's Bluetooth; the feature bits lose their audio flags as well (DiPlay's
     *  "CarPlay audio over the car's Bluetooth"), and no microphone input is ever advertised. */
    @Test fun offersNoAudioAtAll() {
        val root = temporary.root.toPath()
        CarPlayServer(ServerConfig(identityDir = root, stateDir = root.resolve("state"), bindAddress = "127.0.0.1")).use { server ->
            val info = AirPlayInfoPlist.build(server.airPlayConfig)
            assertFalse(info.containsKey("audioFormats"))
            assertFalse(info.containsKey("audioLatencies"))
            assertTrue(server.airPlayConfig.disableAudioOutput)
            val without = info["features"] as Long
            val withAudio = AirPlayInfoPlist.build(server.airPlayConfig.copy(disableAudioOutput = false))["features"] as Long
            assertTrue("audio feature bits are cleared", without and withAudio.inv() == 0L && without != withAudio)
            assertFalse(AirPlayInfoPlist.build(server.airPlayConfig).toString().contains("audioInputFormats"))
        }
    }

    /** The flags the box's launcher still passes for receiver builds before 1.3.0 are accepted and change nothing. */
    @Test fun theOldAudioFlagsAreAcceptedAndIgnored() {
        val root = temporary.root.toPath()
        val base = ServerConfig(identityDir = root, stateDir = root.resolve("state"))
        assertEquals(base, ServerConfig.fromArgs(arrayOf("--car-voice", "--audio-route-navigation", "bluetooth"), base))
        assertEquals(base, ServerConfig.fromArgs(arrayOf("--audio-route-navigation=carplay"), base))
    }
}

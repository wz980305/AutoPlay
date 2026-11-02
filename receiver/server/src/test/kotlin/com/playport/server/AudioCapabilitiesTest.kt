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

    /** audio_route_navigation=bluetooth (1.1.0): nothing is offered, so the iPhone keeps every sound on the Tesla's
     *  Bluetooth; the feature bits lose their audio flags as well (DiPlay's "CarPlay audio over the car's Bluetooth"). */
    @Test fun bluetoothRouteOffersNoAudioAtAll() {
        val root = temporary.root.toPath()
        val carplay = ServerConfig(identityDir = root, stateDir = root.resolve("state"), bindAddress = "127.0.0.1")
        CarPlayServer(carplay.copy(audioRouteNavigation = ServerConfig.AUDIO_ROUTE_BLUETOOTH)).use { server ->
            val info = AirPlayInfoPlist.build(server.airPlayConfig)
            assertFalse(info.containsKey("audioFormats"))
            assertFalse(info.containsKey("audioLatencies"))
            assertTrue(server.config.audioOverBluetooth)
        }
        CarPlayServer(carplay).use { server ->
            val info = AirPlayInfoPlist.build(server.airPlayConfig)
            assertTrue(info.containsKey("audioFormats"))
            assertFalse(server.config.audioOverBluetooth)
            val withAudio = info["features"] as Long
            val without = AirPlayInfoPlist.build(server.airPlayConfig.copy(disableAudioOutput = true))["features"] as Long
            assertTrue("audio feature bits are cleared", without and withAudio.inv() == 0L && without != withAudio)
        }
    }

    @Test fun theFlagIsParsedAndChecked() {
        val root = temporary.root.toPath()
        val base = ServerConfig(identityDir = root, stateDir = root.resolve("state"))
        assertEquals("bluetooth", ServerConfig.fromArgs(arrayOf("--audio-route-navigation", "Bluetooth"), base).audioRouteNavigation)
        assertEquals("carplay", ServerConfig.fromArgs(arrayOf("--audio-route-navigation=carplay"), base).audioRouteNavigation)
        assertEquals("carplay", ServerConfig.fromArgs(arrayOf(), base).audioRouteNavigation)
        try {
            ServerConfig.fromArgs(arrayOf("--audio-route-navigation", "page"), base)
            org.junit.Assert.fail("an unknown route must be refused")
        } catch (_: IllegalArgumentException) {}
    }
}

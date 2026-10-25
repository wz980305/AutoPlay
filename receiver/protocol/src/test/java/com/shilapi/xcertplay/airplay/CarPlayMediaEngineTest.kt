package com.shilapi.xcertplay.airplay

import java.io.Closeable
import java.net.Socket
import java.math.BigInteger
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CarPlayMediaEngineTest {
    @Test
    fun streamConnectionIdUsesUnsignedDecimalForHkdfSalt() {
        assertEquals("18446744073709551615", unsignedPlistDecimal(-1L))
        assertEquals(
            BigInteger("18446744073709551615"),
            unsignedPlistInteger(-1L),
        )
    }

    @Test
    fun feedbackCountsSpeechInItsOwnRtpClock() {
        // audioFormat values from an F50 drive (2026-10-13): navigation prompts and Siri, both Opus decoded at 48 kHz.
        val navigation = AudioStreamCodec.fromFormatBits(268_435_456L, 101, "default")
        val siri = AudioStreamCodec.fromFormatBits(536_870_912L, 100, "speechrecognition")
        assertEquals(48_000, navigation.sampleRate)
        assertEquals(16_000, navigation.rtpClockRate)
        assertEquals(24_000, siri.rtpClockRate)
        assertEquals(1_000L + 320_000L, feedbackSampleTime(1_000, 20.0, navigation))
        assertEquals(480_000L, feedbackSampleTime(0, 20.0, siri))
    }

    @Test
    fun feedbackKeepsMusicAndWrapsLikeRtp() {
        val music = AudioStreamCodec.fromFormatBits(0x800000L, 102, "media")
        assertEquals(48_000, music.rtpClockRate)
        assertEquals(96_000L - 1L, feedbackSampleTime(-1, 2.0, music))   // 0xffffffff + 96000 wraps
        assertEquals(48_000, AudioStreamCodec.fromFormatBits(0x40000000L, 100).rtpClockRate)
    }

    @Test
    fun screenStreamTeardownReportsInactive() {
        val events = mutableListOf<Pair<Int, Boolean>>()
        val sink = object : MediaSink {
            override fun onScreenStreamActive(type: Int, active: Boolean) {
                events += type to active
            }
        }
        val session = testSession()

        try {
            val engine = CarPlayMediaEngine(sink)
            engine.onTeardown(session, 110)
            engine.onTeardown(session, 100)
        } finally {
            session.close()
        }

        assertEquals(listOf(110 to false), events)
    }

    @Test
    fun sessionCloseReportsAllScreenStreamsInactive() {
        val events = mutableListOf<Pair<Int, Boolean>>()
        val sink = object : MediaSink {
            override fun onScreenStreamActive(type: Int, active: Boolean) {
                events += type to active
            }
        }
        val session = testSession()
        val engine = CarPlayMediaEngine(sink)
        val streamsField = CarPlayMediaEngine::class.java.getDeclaredField("streams").apply {
            isAccessible = true
        }
        @Suppress("UNCHECKED_CAST")
        val streams = streamsField.get(engine) as
            MutableMap<CarPlayMediaEngine.StreamKey, Closeable>
        streams[CarPlayMediaEngine.StreamKey(session, 110)] = Closeable {}
        streams[CarPlayMediaEngine.StreamKey(session, 111)] = Closeable {}
        streams[CarPlayMediaEngine.StreamKey(session, 100)] = Closeable {}

        engine.onSessionClosed(session)
        session.close()

        assertEquals(setOf(110 to false, 111 to false), events.toSet())
        assertTrue(streams.isEmpty())
    }

    private fun testSession(): AirPlaySession = AirPlaySession(
        socket = Socket(),
        config = AirPlayConfig(
            deviceName = "test",
            deviceId = "02:00:00:00:00:02",
            btMac = "02:00:00:00:00:01",
            sourceVersion = "1.0",
            main = AirPlayDisplayConfig(widthPixels = 800, heightPixels = 480),
        ),
        identity = AirPlayIdentity.generate(),
        pairings = PairingStore(),
        mfi = null,
        listener = object : AirPlaySessionListener {},
        media = object : AirPlayMediaHandler {},
    )
}

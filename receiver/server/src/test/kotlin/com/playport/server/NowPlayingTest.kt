package com.playport.server
import com.shilapi.xcertplay.iap2.message.Iap2Messages
import org.junit.Assert.*
import org.junit.Test
class NowPlayingTest {
    @Test fun durationPositionAndArtworkArePartialAndBoundToTrack() {
        val state = NowPlayingState()
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { u64(0,1); u32(4,200000); u8(26,128) }; group(1) { u32(1,50000) } })
        assertEquals(200000L,state.value.durationMs)
        assertEquals(50000L,state.value.positionMs)
        assertEquals(128,state.artworkId)
        state.accept(Iap2Messages.buildRaw(0x5001) { group(1) { u32(1,52000) } })
        assertEquals(200000L,state.value.durationMs)
        assertEquals(52000L,state.value.positionMs)
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { u64(0,2) } })
        assertNull(state.value.durationMs); assertNull(state.value.positionMs); assertNull(state.artworkId)
    }

    @Test fun positionRunsOnFromTheLastReportWhilePlaying() {
        var now = 0L
        val state = NowPlayingState { now }
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { u64(0,1); u32(4,200000) }; group(1) { u8(0,1); u32(1,50000); u16(12,100) } })
        now = 10_000
        // An update without the elapsed time (here: a new title) keeps the clock running, not the old position.
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { string(1,"Song") } })
        assertEquals(60000L, state.value.at(now).positionMs)
        assertEquals(true, state.value.playing)
        state.accept(Iap2Messages.buildRaw(0x5001) { group(1) { u8(0,2) } })   // paused, no elapsed time
        now = 20_000
        assertEquals(60000L, state.value.at(now).positionMs)
        state.accept(Iap2Messages.buildRaw(0x5001) { group(1) { u8(0,1) } })   // playing again
        now = 25_000
        assertEquals(65000L, state.value.at(now).positionMs)
        now = 500_000
        assertEquals(200000L, state.value.at(now).positionMs)   // never past the end of the song
    }

    @Test fun partialUpdatesAndTrackChanges() {
        val state = NowPlayingState { 0L }
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { u64(0,1); string(1,"Song"); string(12,"Artist"); string(6,"Album") } })
        state.accept(Iap2Messages.buildRaw(0x5001) { group(1) { u8(0,2) } })
        assertEquals(NowPlaying("Song","Artist","Album",playing = false),state.value)
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { string(1,"Updated title") } })
        assertEquals("Artist",state.value.artist)
        state.accept(Iap2Messages.buildRaw(0x5001) { group(0) { u64(0,2); string(1,"Next") } })
        assertEquals(NowPlaying("Next",playing = false,revision = 1),state.value)   // the player state outlives the song
    }
}

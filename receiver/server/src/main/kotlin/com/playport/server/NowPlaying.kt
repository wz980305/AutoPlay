package com.playport.server

import com.shilapi.xcertplay.iap2.body.Iap2BodyReader
import com.shilapi.xcertplay.iap2.wire.Iap2Frame
import kotlinx.serialization.Serializable

@Serializable
data class NowPlaying(val title: String = "", val artist: String = "", val album: String = "", val durationMs: Long? = null, val positionMs: Long? = null, val speed: Double = 1.0, val revision: Long = 0)

/** Merge partial iPhone updates; clear stale song fields only at a confirmed item boundary. */
class NowPlayingState {
    @Volatile var value = NowPlaying(); private set
    @Volatile var artworkId: Int? = null; private set
    private var persistentId: Long? = null
    private var queueIndex: Long? = null
    private var player: String? = null
    @Synchronized fun accept(frame: Iap2Frame): NowPlaying? {
        if (frame.messageId != 0x5001) return null
        val body = Iap2BodyReader.of(frame)
        val item = body.optionalGroup(0)
        val playback = body.optionalGroup(1)
        val id = item?.optionalU64(0)
        val queue = playback?.optionalU32(2)
        val app = playback?.optionalString(16)
        // Parse everything before mutating state, so malformed input is atomic.
        val title = item?.optionalString(1)?.take(1024)
        val artist = item?.optionalString(12)?.take(1024)
        val album = item?.optionalString(6)?.take(1024)
        val duration = item?.optionalU32(4)
        val position = playback?.optionalU32(1)
        val speed = playback?.optionalU16(12)?.div(100.0)
        val artwork = item?.optionalU8(26)?.also { require(it >= 128) }
        val changed = (app != null && player != null && app != player) ||
            (if (id != null && persistentId != null) id != persistentId else queue != null && queueIndex != null && queue != queueIndex)
        if (changed) { value = NowPlaying(revision = value.revision + 1); persistentId = null; queueIndex = null; artworkId = null }
        persistentId = id ?: persistentId
        queueIndex = queue ?: queueIndex
        player = app ?: player
        if (artwork != null && artworkId != null && artwork != artworkId && !changed) value = value.copy(revision = value.revision + 1)
        artworkId = artwork ?: artworkId
        value = value.copy(title = title ?: value.title, artist = artist ?: value.artist, album = album ?: value.album,
            durationMs = duration ?: value.durationMs, positionMs = position ?: value.positionMs, speed = speed ?: value.speed)
        return value
    }
}

package com.playport.server

import io.ktor.websocket.Frame
import kotlinx.coroutines.channels.Channel
import org.junit.Assert.*
import org.junit.Test

class ViewerBackpressureTest {
    @Test fun droppedDeltaRequiresANewKeyframe() {
        val queue = Channel<Frame>(1)
        val client = WsClient(queue)
        assertTrue(client.offerVideo(Frame.Binary(true, byteArrayOf(1)), true))
        assertTrue(client.imageReady.get())
        assertFalse(client.offerVideo(Frame.Binary(true, byteArrayOf(2)), false))
        assertFalse("a decoder missing a reference frame must not receive later deltas", client.imageReady.get())
        queue.tryReceive()
        assertTrue(client.offerVideo(Frame.Binary(true, byteArrayOf(3)), true))
        assertTrue(client.imageReady.get())
        queue.close()
    }

    @Test fun droppedKeyframeDoesNotUnlockDeltas() {
        val queue = Channel<Frame>(1)
        val client = WsClient(queue)
        client.offer(Frame.Text("control"))
        assertFalse(client.offerVideo(Frame.Binary(true, byteArrayOf(1)), true))
        assertFalse(client.imageReady.get())
        queue.close()
    }
}

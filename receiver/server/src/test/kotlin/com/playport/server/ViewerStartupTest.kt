package com.playport.server

import com.shilapi.xcertplay.airplay.VideoCodec
import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.URI
import java.net.http.HttpClient
import java.net.http.WebSocket
import java.nio.file.Files
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class ViewerStartupTest {
    @Test fun slowPhoneKeyframeRequestDoesNotBlockViewerAcknowledgements() {
        val dir = Files.createTempDirectory("viewer-startup")
        val scope = CoroutineScope(Dispatchers.Default)
        val token = "0123456789abcdef0123456789abcdef"
        val hub = WebHub(ServerConfig(identityDir=dir,stateDir=dir,accessToken=token),DisplayState(640,480,30,100),scope)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val pong = CountDownLatch(1)
        hub.setVideoCodec(110,VideoCodec.H264)
        hub.broadcastVideoConfig(110,byteArrayOf())
        hub.onViewerJoined = { entered.countDown(); release.await(5,TimeUnit.SECONDS) }
        val server = embeddedServer(Netty,port=0,host="127.0.0.1") { hub.install(this,dir) }.start(false)
        var socket: WebSocket? = null
        try {
            val port = runBlocking { server.engine.resolvedConnectors().first().port }
            socket = HttpClient.newHttpClient().newWebSocketBuilder().buildAsync(
                URI("ws://127.0.0.1:$port/ws?token=$token"),object:WebSocket.Listener {
                    override fun onOpen(ws:WebSocket) { ws.request(100); ws.sendText("{\"type\":\"ping\"}",true) }
                    override fun onText(ws:WebSocket,data:CharSequence,last:Boolean):java.util.concurrent.CompletionStage<*>? {
                        if (data.toString().contains("\"pong\"")) pong.countDown()
                        ws.request(1); return null
                    }
                }).get(3,TimeUnit.SECONDS)
            assertTrue("phone recovery request started",entered.await(2,TimeUnit.SECONDS))
            assertTrue("viewer ping is handled while phone command remains blocked",pong.await(2,TimeUnit.SECONDS))
        } finally {
            release.countDown(); socket?.abort(); server.stop(0,1000); scope.cancel(); dir.toFile().deleteRecursively()
        }
    }
}

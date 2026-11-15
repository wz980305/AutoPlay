package com.playport.server

import io.ktor.server.engine.applicationEnvironment
import io.ktor.server.engine.embeddedServer
import io.ktor.server.engine.sslConnector
import io.ktor.server.netty.Netty
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import org.junit.Test
import java.nio.file.Files

/**
 * Not a test of its own: the real WebHub on Netty with TLS (HTTP/1.1 and HTTP/2), as Main starts it but without
 * CarPlay, for box/tests/net/receiver_lab.py, which puts it behind the box's nft rules and asks it through
 * https://name/ (1.6.8). Does nothing unless AUTOPLAY_LAB_PORT is set; then it serves on that port for
 * AUTOPLAY_LAB_SECONDS (60). The token is a fixed lab value and the certificate the receiver's own self-signed one.
 */
class LabServeTest {
    @Test fun serve() {
        val port = System.getenv("AUTOPLAY_LAB_PORT")?.toIntOrNull() ?: return
        val dir = Files.createTempDirectory("autoplay-lab")
        Files.writeString(dir.resolve("index.html"), "<!doctype html>lab page")
        Files.writeString(dir.resolve(WebHub.ACCESS_FILE), """{"token":"$TOKEN","settingsPort":18080}""")
        val scope = CoroutineScope(Dispatchers.Default)
        val hub = WebHub(ServerConfig(identityDir = dir, stateDir = dir, accessToken = TOKEN), DisplayState(640, 480, 30, 100), scope)
        val tls = TlsCertificate.loadOrCreate(dir, listOf(java.net.InetAddress.getByName("100.96.0.1")))
        val server = embeddedServer(Netty, environment = applicationEnvironment { }, configure = {
            sslConnector(tls.keyStore, tls.alias, { tls.password }, { tls.password }) { host = "0.0.0.0"; this.port = port }
        }) { hub.install(this, dir) }.start(false)
        try {
            println("LAB SERVER UP on $port")
            Thread.sleep((System.getenv("AUTOPLAY_LAB_SECONDS")?.toLongOrNull() ?: 60) * 1000)
        } finally { server.stop(0, 1000); scope.cancel() }
    }

    private companion object { const val TOKEN = "0123456789abcdef0123456789abcdef" }
}

package com.playport.server

import io.ktor.server.engine.embeddedServer
import io.ktor.server.netty.Netty
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files

class StaticAssetsTest {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun binaryAssetsAreServedByteForByte() {
        val dir = temporary.root.toPath()
        // Includes invalid UTF-8: the old Files.readString path raised MalformedInputException.
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0xff.toByte(), 0x00)
        Files.write(dir.resolve("icon.png"), png)
        val scope = CoroutineScope(Dispatchers.Default)
        val hub = WebHub(ServerConfig(identityDir=dir,stateDir=dir), DisplayState(640,480,30,100), scope)
        val server = embeddedServer(Netty,port=0,host="127.0.0.1") { hub.install(this,dir) }.start(false)
        try {
            val port = runBlocking { server.engine.resolvedConnectors().first().port }
            val response = HttpClient.newHttpClient().send(
                HttpRequest.newBuilder(URI("http://127.0.0.1:$port/icon.png")).GET().build(),
                HttpResponse.BodyHandlers.ofByteArray(),
            )
            assertEquals(200, response.statusCode())
            assertArrayEquals(png, response.body())
            assertTrue(response.headers().firstValue("Content-Type").orElse("").startsWith("image/png"))
        } finally { server.stop(0,1000); scope.cancel() }
    }

    /** 1.6.7: the page and the files beside it are asked for each time, so a page that reloads for an upgraded box
     *  (web/src/fresh.ts) gets the new ones; hashed files under assets/ may be kept by the browser. */
    @Test fun thePageIsNeverTakenFromTheCacheButHashedAssetsMayBe() {
        val dir = temporary.root.toPath()
        Files.writeString(dir.resolve("index.html"), "<!doctype html><script type=module src=./assets/index-1a2b3c.js></script>")
        Files.writeString(dir.resolve("browser-check.js"), "/* check */")
        Files.createDirectories(dir.resolve("assets"))
        Files.writeString(dir.resolve("assets/index-1a2b3c.js"), "/* page */")
        val scope = CoroutineScope(Dispatchers.Default)
        val hub = WebHub(ServerConfig(identityDir=dir,stateDir=dir), DisplayState(640,480,30,100), scope)
        val server = embeddedServer(Netty,port=0,host="127.0.0.1") { hub.install(this,dir) }.start(false)
        try {
            val port = runBlocking { server.engine.resolvedConnectors().first().port }
            fun cacheControl(path: String): String {
                val response = HttpClient.newHttpClient().send(
                    HttpRequest.newBuilder(URI("http://127.0.0.1:$port$path")).GET().build(),
                    HttpResponse.BodyHandlers.ofString(),
                )
                assertEquals(path, 200, response.statusCode())
                return response.headers().firstValue("Cache-Control").orElse("")
            }
            assertEquals("no-cache", cacheControl("/"))
            assertEquals("no-cache", cacheControl("/index.html"))
            assertEquals("no-cache", cacheControl("/browser-check.js"))
            assertEquals("no-cache", cacheControl("/some/page/the/viewer/does/not/have"))   // falls back to index.html
            assertEquals("", cacheControl("/assets/index-1a2b3c.js"))
        } finally { server.stop(0,1000); scope.cancel() }
    }
}

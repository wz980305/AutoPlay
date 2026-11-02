package com.playport.server

import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.file.Files
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class PairingFileStoreTest {
    @get:Rule val temporary = TemporaryFolder()
    private val key = ByteArray(32) { it.toByte() }

    @Test fun firstPairingHasRecoverableBackupAndLoadingDoesNotRewriteIt() {
        val dir = temporary.root.toPath()
        PairingFileStore(dir).load().save("phone", key)
        val backup = Files.readAllBytes(dir.resolve("pairings.properties.bak"))
        val primary = Files.readAllBytes(dir.resolve("pairings.properties"))
        assertArrayEquals(key, PairingFileStore(dir).load().get("phone"))
        assertArrayEquals(primary, Files.readAllBytes(dir.resolve("pairings.properties")))
        assertArrayEquals(backup, Files.readAllBytes(dir.resolve("pairings.properties.bak")))
        Files.writeString(dir.resolve("pairings.properties"), "")
        assertArrayEquals(key, PairingFileStore(dir).load().get("phone"))
    }

    @Test fun corruptPrimaryDoesNotDestroyBackupWhenAnotherPhonePairs() {
        val dir = temporary.root.toPath()
        PairingFileStore(dir).load().save("first", key)
        Files.writeString(dir.resolve("pairings.properties"), "first=xyz\n")
        val recovered = PairingFileStore(dir).load()
        assertArrayEquals(key, recovered.get("first"))
        recovered.save("second", ByteArray(32) { 42 })
        assertArrayEquals(key, PairingFileStore(dir).load().get("first"))
        assertArrayEquals(ByteArray(32) { 42 }, PairingFileStore(dir).load().get("second"))
        Files.writeString(dir.resolve("pairings.properties"), "")
        assertArrayEquals("healthy backup survives another primary loss", key, PairingFileStore(dir).load().get("first"))
    }

    @Test fun truncatedHexKeyFallsBackToTheBackup() {
        val dir = temporary.root.toPath()
        PairingFileStore(dir).load().save("phone", key)
        Files.writeString(dir.resolve("pairings.properties"), "phone=0102\n")
        assertArrayEquals(key, PairingFileStore(dir).load().get("phone"))
    }

    @Test fun concurrentSavesDoNotLosePhones() {
        val dir = temporary.root.toPath()
        val store = PairingFileStore(dir).load()
        val workers = Executors.newFixedThreadPool(4)
        try {
            val saves = (0 until 20).map { index -> workers.submit { store.save("phone-$index", ByteArray(32) { index.toByte() }) } }
            saves.forEach { it.get(10, TimeUnit.SECONDS) }
            val loaded = PairingFileStore(dir).load()
            (0 until 20).forEach { assertArrayEquals(ByteArray(32) { _ -> it.toByte() }, loaded.get("phone-$it")) }
        } finally { workers.shutdownNow() }
    }
}

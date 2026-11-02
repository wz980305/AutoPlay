package com.playport.server

import com.shilapi.xcertplay.airplay.PairingStore
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.channels.FileChannel
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption.ATOMIC_MOVE
import java.nio.file.StandardCopyOption.REPLACE_EXISTING
import java.nio.file.StandardOpenOption.READ
import java.nio.file.StandardOpenOption.WRITE
import java.util.Properties

/** Durable pairing snapshots. Never promote an empty/corrupt primary to the known-good backup. */
internal class PairingFileStore(private val directory: Path) {
    private val file = directory.resolve("pairings.properties")
    private val backup = directory.resolve("pairings.properties.bak")
    private val log = org.slf4j.LoggerFactory.getLogger("playport")

    fun load(): PairingStore {
        val primary = read(file)
        val properties = primary ?: read(backup)?.also {
            log.warn("pairings.properties empty or invalid; using the .bak copy")
        } ?: Properties()
        var loading = true
        // PairingStore serializes saves, including this callback, so snapshots cannot overwrite each other.
        val store = PairingStore { identifier, key ->
            if (!loading) {
                val previous = Properties().apply { putAll(properties) }
                properties.setProperty(identifier, key.joinToString("") { "%02x".format(it) })
                runCatching {
                    Files.createDirectories(directory)
                    // On the first pairing both copies contain the new identity. On subsequent writes the
                    // backup is our previous validated in-memory snapshot, never the possibly corrupt disk file.
                    atomicWrite(backup, if (previous.isEmpty) properties else previous)
                    atomicWrite(file, properties)
                }.onFailure { log.warn("pairings not saved: {}", it.message) }
            }
        }
        properties.forEach { (id, key) -> store.save(id.toString(), decode(key.toString())!!) }
        loading = false
        return store
    }

    private fun read(path: Path): Properties? = runCatching {
        val loaded = Properties().apply { Files.newInputStream(path).use { load(it) } }
        loaded.takeIf { it.isNotEmpty() && it.all { (id, key) -> id.toString().isNotBlank() && decode(key.toString()) != null } }
    }.getOrNull()

    private fun decode(value: String): ByteArray? {
        // pair-verify uses an Ed25519 public key: a truncated key must not mask a healthy backup.
        if (!value.matches(Regex("[0-9a-fA-F]{64}"))) return null
        return ByteArray(32) { value.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    }

    private fun atomicWrite(destination: Path, properties: Properties) {
        val temporary = Files.createTempFile(directory, ".pairings-", ".tmp")
        try {
            val bytes = ByteArrayOutputStream().also { properties.store(it, "AutoPlay paired controllers") }.toByteArray()
            FileChannel.open(temporary, WRITE).use { channel ->
                val buffer = ByteBuffer.wrap(bytes)
                while (buffer.hasRemaining()) channel.write(buffer)
                channel.force(true)
            }
            Files.move(temporary, destination, REPLACE_EXISTING, ATOMIC_MOVE)
            // The rename itself also needs to reach persistent storage on the F50's Linux filesystem.
            FileChannel.open(directory, READ).use { it.force(true) }
        } finally {
            Files.deleteIfExists(temporary)
        }
    }
}

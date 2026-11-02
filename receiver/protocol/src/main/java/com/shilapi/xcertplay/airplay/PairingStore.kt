package com.shilapi.xcertplay.airplay

/** Store of paired controllers keyed by their long-term Ed25519 public key. */
class PairingStore(private val onSave: ((String, ByteArray) -> Unit)? = null) {
    private val entries = HashMap<String, ByteArray>()

    @Synchronized fun save(identifier: String, longTermPublicKey: ByteArray) {
        val copy = longTermPublicKey.copyOf()
        entries[identifier] = copy
        onSave?.invoke(identifier, copy)
    }

    @Synchronized fun get(identifier: String): ByteArray? = entries[identifier]?.copyOf()

    @Synchronized fun clear() = entries.clear()
}

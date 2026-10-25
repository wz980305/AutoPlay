package com.shilapi.xcertplay.airplay

import java.math.BigInteger
import java.security.SecureRandom
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The iPhone's SRP client (like HomeKit's) hashes the shared secret S padded to the modulus. When S
 * happens to start with a zero byte (about 1 in 256 sessions), an unpadded server key no longer
 * matches and the phone drops pair-setup; seen once on a OneCloud cold boot (2026-10-11).
 */
class Srp6aTest {
    private val random = SecureRandom()

    @Test fun acceptsTheIphoneProofAlsoWhenTheSharedSecretHasALeadingZeroByte() {
        var withLeadingZero = 0
        var sessions = 0
        while (withLeadingZero < 2 && sessions < 5000) {
            sessions++
            val server = Srp6a.start("Pair-Setup", "3939")
            val client = client(server.salt, server.publicKey, "Pair-Setup", "3939")
            if (client.sharedSecretHasLeadingZero) withLeadingZero++
            val result = server.verify(client.publicKeyA, client.proof)
            assertTrue("session $sessions (leading zero=${client.sharedSecretHasLeadingZero})", result.ok)
            assertTrue(result.serverProof!!.contentEquals(AirPlayCrypto.sha512(Srp6a.pad(BigInteger(1, client.publicKeyA)), client.proof, client.key)))
        }
        assertTrue("no leading-zero secret in $sessions sessions", withLeadingZero >= 2)
    }

    private class Client(val publicKeyA: ByteArray, val proof: ByteArray, val key: ByteArray, val sharedSecretHasLeadingZero: Boolean)

    private fun client(salt: ByteArray, publicKeyB: ByteArray, username: String, password: String): Client {
        val n = Srp6a.modulus()
        val g = Srp6a.generator()
        val k = BigInteger(1, AirPlayCrypto.sha512(Srp6a.toBytes(n), Srp6a.pad(g)))
        val a = BigInteger(1, ByteArray(32).also(random::nextBytes))
        val bigA = g.modPow(a, n)
        val bigB = BigInteger(1, publicKeyB)
        val u = BigInteger(1, AirPlayCrypto.sha512(Srp6a.pad(bigA), Srp6a.pad(bigB)))
        val identity = username.toByteArray()
        val x = BigInteger(1, AirPlayCrypto.sha512(salt, AirPlayCrypto.sha512(identity, ":".toByteArray(), password.toByteArray())))
        val s = (bigB - k * g.modPow(x, n)).mod(n).modPow(a + u * x, n)
        val paddedS = Srp6a.pad(s)
        val key = AirPlayCrypto.sha512(paddedS)
        val hashN = AirPlayCrypto.sha512(Srp6a.toBytes(n))
        val hashG = AirPlayCrypto.sha512(Srp6a.toBytes(g))
        val xor = ByteArray(hashN.size) { (hashN[it].toInt() xor hashG[it].toInt()).toByte() }
        val proof = AirPlayCrypto.sha512(xor, AirPlayCrypto.sha512(identity), salt, Srp6a.pad(bigA), Srp6a.pad(bigB), key)
        return Client(Srp6a.pad(bigA), proof, key, paddedS[0] == 0.toByte())
    }
}

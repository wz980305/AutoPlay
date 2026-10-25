package com.playport.server

import com.shilapi.xcertplay.iap2.session.Iap2Session
import com.shilapi.xcertplay.mfi.Iap2MfiAuthenticationClient
import com.shilapi.xcertplay.transport.Iap2IdentificationConfig
import com.shilapi.xcertplay.transport.Iap2UsbMuxHost
import com.shilapi.xcertplay.transport.Iap2UsbSession
import com.shilapi.xcertplay.transport.Iap2WiredCarPlayEndpoint
import com.shilapi.xcertplay.transport.Iap2WiredControlClient
import com.shilapi.xcertplay.transport.LockdownCarKitClient
import com.shilapi.xcertplay.transport.LockdownPairRecord
import com.shilapi.xcertplay.transport.LockdownPairingClient
import java.io.Closeable
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.EOFException
import java.net.Inet6Address
import java.net.NetworkInterface
import java.nio.file.Files
import java.nio.file.Path
import java.util.Properties
import java.util.UUID
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.TimeUnit
import org.slf4j.LoggerFactory

/**
 * Wired CarPlay with the box as USB host (the Android WheelPlay/LIVI sequence): a helper process
 * (iphone-usb-bridge.py) switches the plugged iPhone to its CarPlay USB configuration and relays the
 * USBMUX bulk pipe; over it run Lockdown pairing (the iPhone asks "Trust this computer?" once), the
 * com.apple.carkit.service TLS stream and iAP2 with the USB host transport. The iPhone then opens
 * AirPlay over the configuration's NCM link, on which [CarPlayServer.listenWired] listens.
 * The box's Wi-Fi only joins the car hotspot, for the head unit's browser.
 */
class WiredBootstrap(private val server: CarPlayServer, private val helper: Path) : Closeable {
    private val log = LoggerFactory.getLogger("wired")
    @Volatile private var stopped = false
    @Volatile private var pipe: UsbBridgePipe? = null
    @Volatile private var mux: Iap2UsbMuxHost? = null
    @Volatile private var session: Iap2Session? = null
    @Volatile private var serial: String? = null   // USB serial (UDID) of the iPhone on the cable
    private val statusFile = System.getenv("CARPLAY_WIRED_STATUS")?.takeIf { it.isNotBlank() }?.let { Path.of(it) }

    fun start() {
        Thread({
            while (!stopped) {
                try {
                    runOnce()
                } catch (error: Exception) {
                    if (!stopped) log.warn("wired CarPlay ended: {}", error.message ?: error.javaClass.simpleName)
                } finally {
                    closeLink()
                    pipe = null
                    mux = null
                    session = null
                }
                if (!stopped) Thread.sleep(RETRY_MILLIS)
            }
        }, "wired-bootstrap").apply { isDaemon = true; start() }
    }

    private fun runOnce() {
        val bridge = UsbBridgePipe.start(helper) { state ->
            // The helper says "usb waiting" (no iPhone) or "usb iphone <serial>" (one plugged in) first.
            val parts = state.split(" ")
            when (parts[0]) {
                "waiting" -> { server.setCablePhone(false); status("cable") }
                "iphone" -> { serial = parts.getOrNull(1); server.setCablePhone(true); status("starting") }
            }
        }.also { pipe = it }
        // The helper exits when the iPhone is unplugged, but the iAP2 session blocked in recv never
        // noticed (2026-10-12: replugging then did nothing). End this run as soon as the helper is gone.
        bridge.onExit {
            if (!stopped && pipe === bridge) {
                log.info("wired: USB helper exited; ending this wired run")
                closeLink()
            }
        }
        val ncm = bridge.awaitNcm(Long.MAX_VALUE) ?: throw EOFException("USB helper exited before an iPhone appeared")
        log.info("wired: iPhone in its CarPlay configuration, NCM interface {}", ncm)
        val mux = Iap2UsbMuxHost.open(bridge).also { this.mux = it }
        log.info("wired: USBMUX open")
        // One record per iPhone (its USB serial): a second iPhone must not replace the first one's
        // "Trust" (2026-10-12). The single file of the first version is still tried.
        val legacy = PairRecordStore(server.config.stateDir.resolve("lockdown-pair-record.properties"))
        val pairing = serial?.takeIf { it.matches(Regex("[0-9A-Za-z-]{8,64}")) }
            ?.let { PairRecordStore(server.config.stateDir.resolve("lockdown-pair-record-$it.properties")) } ?: legacy
        var record = pairing.load() ?: legacy.load() ?: pairNew(mux, pairing)
        val carkit = try {
            LockdownCarKitClient(mux).open(record, LABEL)
        } catch (error: Exception) {
            // InvalidHostID: an iPhone that never trusted this box (another phone's record was tried).
            if (error.message?.contains(Regex("InvalidPairRecord|InvalidHostID", RegexOption.IGNORE_CASE)) != true) throw error
            log.info("wired: the iPhone does not know this box ({}); pairing", error.message)
            record = pairNew(mux, pairing)
            LockdownCarKitClient(mux).open(record, LABEL)
        }
        log.info("wired: com.apple.carkit.service open")
        // Diagnostics only: filtering the iPhone's log took a whole CPU core and shared the cable with
        // the video, adding ~0.3 s to every touch (2026-10-12).
        if (System.getenv("CARPLAY_WIRED_PHONE_LOG") == "1") phoneLog(mux, record)
        val session = Iap2Session.open(carkit, traceContext = "wired", onTrace = { log.debug(it) })
            .also { this.session = it }
        val linkLocal = waitLinkLocal(ncm)
        server.listenWired(linkLocal)
        val identification = Iap2IdentificationConfig(
            name = server.config.deviceName,
            modelIdentifier = server.config.model,
            manufacturer = server.config.manufacturer,
            serialNumber = "CARPLAYWEB-" + server.deviceId.replace(":", ""),
            firmwareVersion = "1.0.0",
            hardwareVersion = "1.0",
            carPlayUsbInterfaceNumber = bridge.ncmInterfaceNumber,
        )
        val endpoint = Iap2WiredCarPlayEndpoint(
            ipv6Addresses = listOf(linkLocal.hostAddress.substringBefore('%')),
            airPlayPort = server.config.airPlayPort,
            publicKey = server.identity.publicKeyHex,
            sourceVersion = server.config.sourceVersion,
            // As the Android app: the NCM MAC the iPhone assigned to this side.
            deviceIdentifier = bridge.ncmMac ?: server.deviceId,
        )
        log.info("wired: iAP2 control starting, AirPlay on [{}]:{}", linkLocal.hostAddress, server.config.airPlayPort)
        val result = Iap2WiredControlClient(session, Iap2MfiAuthenticationClient(server.mfi)).run(
            identification = identification,
            endpoint = endpoint,
            availableCurrentMilliAmps = 1000,
            timeoutMillis = Iap2WiredControlClient.NO_TIMEOUT_MILLIS,
            onReady = { log.info("wired: iAP2 identified and authenticated; CarPlay available"); awaitSession(bridge) },
            // Song, artist, album and artwork for the browser's media session, as over the wireless tunnel.
            onIncoming = server.nowPlayingFeed(session, "wired") { !stopped && this.session === session },
            // NowPlaying updates arrive every ~0.45 s while music plays: debug only.
            onProgress = { if (it.startsWith("iap2 rx=0x5001")) log.debug("wired {}", it) else log.info("wired {}", it) },
        )
        log.info("wired: iAP2 control ended {} at {}", result.terminal, result.stage)
    }

    /**
     * Two minutes of the iPhone's own log about accessories and CarPlay (com.apple.syslog_relay over
     * the same Lockdown pairing), as the Android app captured while bringing wired CarPlay up.
     */
    private fun phoneLog(mux: Iap2UsbMuxHost, record: LockdownPairRecord) {
        val relay = runCatching { LockdownCarKitClient(mux).openService(record, LABEL, "com.apple.syslog_relay") }
            .onFailure { log.info("wired: iPhone log unavailable: {}", it.message) }.getOrNull() ?: return
        val relevant = Regex(" (accessoryd|ACCCarPlay|iap2d|CarPlay|carkitd|AirPlay|airplayd|mDNSResponder|NCM|usbmux)", RegexOption.IGNORE_CASE)
        Thread({
            val phone = LoggerFactory.getLogger("iphone")
            try {
                relay.use {
                    val deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(2)
                    val pending = StringBuilder()
                    while (!stopped && System.nanoTime() < deadline) {
                        val bytes = relay.recv(8192, 1000) ?: continue
                        if (bytes.isEmpty()) break
                        pending.append(bytes.toString(Charsets.UTF_8).replace('\u0000', '\n'))
                        while (true) {
                            val end = pending.indexOf("\n")
                            if (end < 0) break
                            val line = pending.substring(0, end)
                            pending.delete(0, end + 1)
                            if (relevant.containsMatchIn(line)) phone.info(line.take(600))
                        }
                        if (pending.length > 65536) pending.clear()
                    }
                }
            } catch (error: Exception) {
                log.info("wired: iPhone log ended: {}", error.message)
            }
        }, "wired-iphone-log").apply { isDaemon = true; start() }
    }

    private fun pairNew(mux: Iap2UsbMuxHost, store: PairRecordStore): LockdownPairRecord {
        log.info("wired: pairing with the iPhone; tap Trust on its screen")
        status("trust")
        val paired = LockdownPairingClient(mux).pair(
            label = LABEL,
            hostId = UUID.randomUUID().toString().uppercase(),
            systemBuid = UUID.randomUUID().toString().uppercase(),
            totalTimeoutMillis = PAIR_TIMEOUT_MILLIS,
            isCancelled = { stopped },
        )
        store.save(paired.pairRecord)
        log.info("wired: paired; record saved")
        status("starting")
        return paired.pairRecord
    }

    /** The NCM interface's link-local address once the kernel assigned it (interface brought up by the helper). */
    private fun waitLinkLocal(name: String): Inet6Address {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(15)
        while (System.nanoTime() < deadline) {
            // The helper puts fe80::2 on its TAP interface (the Android app's fixed address); the
            // kernel adds its own link-local next to it.
            val addresses = NetworkInterface.getByName(name)?.inetAddresses?.toList()
                ?.filterIsInstance<Inet6Address>()?.filter { it.isLinkLocalAddress }.orEmpty()
            val address = addresses.firstOrNull { it.hostAddress.startsWith("fe80:0:0:0:0:0:0:2%") } ?: addresses.firstOrNull()
            if (address != null) return address
            Thread.sleep(200)
        }
        throw EOFException("NCM interface $name has no IPv6 link-local address")
    }

    /**
     * "live" once the iPhone has opened CarPlay on the cable. An iPhone plugged in right after a wireless
     * session accepted the start but never connected (2026-10-12); starting the run over fixes that.
     */
    private fun awaitSession(bridge: UsbBridgePipe) {
        Thread({
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(SESSION_WAIT_SECONDS)
            while (!stopped && pipe === bridge && System.nanoTime() < deadline) {
                if (server.wiredSessionActive()) {
                    status("live")
                    return@Thread
                }
                Thread.sleep(250)
            }
            if (!stopped && pipe === bridge) {
                log.info("wired: the iPhone did not open CarPlay within {} s; starting over", SESSION_WAIT_SECONDS)
                closeLink()
            }
        }, "wired-session-wait").apply { isDaemon = true; start() }
    }

    /**
     * Phase for the box's settings page (CARPLAY_WIRED_STATUS): cable (no iPhone), starting, trust
     * (waiting for "Trust this computer?"), live (CarPlay available on the cable).
     */
    private fun status(phase: String) {
        val file = statusFile ?: return
        runCatching {
            val temporary = file.resolveSibling(file.fileName.toString() + ".tmp")
            Files.writeString(temporary, "{\"phase\": \"$phase\"}\n")
            Files.move(temporary, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        }.onFailure { log.debug("wired status not written: {}", it.message) }
    }

    /** Ends the current wired run; the loop starts a new one (new iAP2 identification and start session). */
    fun restart() {
        log.info("wired: restarting for the new display")
        closeLink()
    }

    /** The iAP2 session blocks in recv without noticing a closed pipe (2026-10-12), so close it too. */
    private fun closeLink() {
        runCatching { session?.close() }
        runCatching { mux?.close() }
        runCatching { pipe?.close() }
    }

    override fun close() {
        stopped = true
        closeLink()
    }

    private companion object {
        const val LABEL = "DashPlay"
        const val RETRY_MILLIS = 2_000L
        const val PAIR_TIMEOUT_MILLIS = 120_000L
        const val SESSION_WAIT_SECONDS = 8L   // the iPhone normally connects ~2 s after the start
    }
}

/** Lockdown pair record in the state directory (owner-only), hex PEM fields as in the Android app. */
internal class PairRecordStore(private val file: Path) {
    fun load(): LockdownPairRecord? = runCatching {
        if (!Files.exists(file)) return null
        val p = Properties().apply { Files.newInputStream(file).use(::load) }
        fun hex(key: String) = p.getProperty(key).chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        LockdownPairRecord.restore(
            hostId = p.getProperty("hostId"),
            systemBuid = p.getProperty("systemBuid"),
            wifiMacAddress = p.getProperty("wifiMacAddress"),
            devicePublicKeyPem = hex("devicePublicKey"),
            deviceCertificatePem = hex("deviceCertificate"),
            hostPrivateKeyPem = hex("hostPrivateKey"),
            hostCertificatePem = hex("hostCertificate"),
            rootPrivateKeyPem = hex("rootPrivateKey"),
            rootCertificatePem = hex("rootCertificate"),
        )
    }.getOrNull()

    fun save(record: LockdownPairRecord) {
        fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }
        val p = Properties().apply {
            setProperty("hostId", record.hostId)
            setProperty("systemBuid", record.systemBuid)
            setProperty("wifiMacAddress", record.wifiMacAddress)
            setProperty("devicePublicKey", hex(record.devicePublicKeyPem))
            setProperty("deviceCertificate", hex(record.deviceCertificatePem))
            setProperty("hostPrivateKey", hex(record.hostPrivateKeyPem))
            setProperty("hostCertificate", hex(record.hostCertificatePem))
            setProperty("rootPrivateKey", hex(record.rootPrivateKeyPem))
            setProperty("rootCertificate", hex(record.rootCertificatePem))
        }
        val temporary = file.resolveSibling(file.fileName.toString() + ".tmp")
        Files.newOutputStream(temporary).use { p.store(it, "Lockdown pair record for wired CarPlay") }
        runCatching { Files.setPosixFilePermissions(temporary, java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")) }
        Files.move(temporary, file, java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
    }
}

/**
 * The USBMUX pipe through iphone-usb-bridge.py: stdin/stdout carry length-prefixed bulk transfers
 * (u32 big-endian length, then the bytes); stderr carries its log, "usb waiting" / "usb iphone" and
 * "ncm <interface> <number> <mac>".
 */
internal class UsbBridgePipe private constructor(
    private val process: Process,
    private val onState: (String) -> Unit,
) : Iap2UsbSession {
    private val log = LoggerFactory.getLogger("usb-bridge")
    private val output = DataOutputStream(process.outputStream.buffered())
    private val input = DataInputStream(process.inputStream.buffered())
    private val received = ArrayBlockingQueue<ByteArray>(256)
    private val ncm = ArrayBlockingQueue<Triple<String, Int, String?>>(1)
    @Volatile private var ended = false
    var ncmInterfaceNumber: Int = 0
        private set

    /** The MAC the iPhone's NCM descriptor assigns to this side; reported as the CarPlay device id. */
    var ncmMac: String? = null
        private set

    init {
        Thread({
            process.errorStream.bufferedReader().forEachLine { line ->
                if (line.startsWith("usb ")) {
                    log.info(line)
                    runCatching { onState(line.removePrefix("usb ").trim()) }
                } else if (line.startsWith("ncm ")) {
                    val parts = line.split(" ")
                    ncm.offer(Triple(parts[1], parts.getOrNull(2)?.toIntOrNull() ?: 0, parts.getOrNull(3)))
                } else {
                    log.info(line)
                }
            }
        }, "usb-bridge-stderr").apply { isDaemon = true; start() }
        Thread({
            try {
                while (true) {
                    val length = input.readInt()
                    val bytes = ByteArray(length)
                    input.readFully(bytes)
                    received.put(bytes)
                }
            } catch (_: Exception) {
            } finally {
                ended = true
            }
        }, "usb-bridge-reader").apply { isDaemon = true; start() }
    }

    fun awaitNcm(timeoutMillis: Long): String? {
        val deadline = if (timeoutMillis == Long.MAX_VALUE) Long.MAX_VALUE else System.currentTimeMillis() + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            val found = ncm.poll(500, TimeUnit.MILLISECONDS)
            if (found != null) {
                ncmInterfaceNumber = found.second
                ncmMac = found.third?.uppercase()
                return found.first
            }
            if (!process.isAlive) return null
        }
        return null
    }

    @Synchronized
    override fun write(data: ByteArray, timeoutMillis: Int) {
        if (ended || !process.isAlive) throw EOFException("USB helper exited")
        output.writeInt(data.size)
        output.write(data)
        output.flush()
    }

    override fun read(timeoutMillis: Long): ByteArray? {
        val bytes = received.poll(timeoutMillis, TimeUnit.MILLISECONDS)
        if (bytes == null && ended) throw EOFException("USB helper exited")
        return bytes
    }

    fun onExit(action: () -> Unit) {
        process.onExit().thenRun { runCatching(action) }
    }

    override fun close() {
        ended = true
        process.destroy()
        if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly()
    }

    companion object {
        fun start(helper: Path, onState: (String) -> Unit = {}): UsbBridgePipe =
            UsbBridgePipe(ProcessBuilder("python3", helper.toString()).start(), onState)
    }
}

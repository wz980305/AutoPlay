package com.playport.server

import com.shilapi.xcertplay.iap2.session.Iap2Session
import com.shilapi.xcertplay.mfi.Iap2MfiAuthenticationClient
import com.shilapi.xcertplay.transport.Iap2IdentificationConfig
import com.shilapi.xcertplay.transport.Iap2WirelessCarPlayEndpoint
import com.shilapi.xcertplay.transport.Iap2WirelessControlClient
import com.shilapi.xcertplay.transport.Iap2WirelessControlTerminal
import com.shilapi.xcertplay.transport.Iap2WirelessIdentification
import java.io.Closeable
import java.nio.file.Files
import java.nio.file.Path
import org.slf4j.LoggerFactory

/**
 * Wireless CarPlay bring-up: Bluetooth RFCOMM iAP2 bootstrap, Wi-Fi credentials handoff and the
 * tunneled iAP2 handover.
 *
 * Requires the `bt-bridge` helper (`--bt-bridge`, the box's BlueZ RFCOMM relay) with the iPhone already
 * paired, and the Wi-Fi the phone should join named with `--wifi-ssid` (the box's own access point).
 */
class WirelessBootstrap(private val server: CarPlayServer) : Closeable {
    private val log = LoggerFactory.getLogger("wireless")
    @Volatile private var bridgeProcess: ProcessByteStream? = null
    @Volatile private var stopped = false
    @Volatile var running = false
        private set

    @Synchronized
    fun start() {
        if (stopped || running) return
        running = true
        Thread(::run, "wireless-bootstrap").apply {
            isDaemon = true
            start()
        }
    }

    private fun run() {
        var failed = false
        try {
            val config = server.config
            // The box's own access point, as the launcher passes it (the macOS SSID detection went with that build).
            val wifi = config.wifiSsid?.takeIf { it.isNotBlank() }?.let { WifiNetwork(it, config.wifiChannel) }
            if (wifi == null) {
                log.warn(
                    "wireless bootstrap skipped: no Wi-Fi network configured. " +
                        "Pass the Wi-Fi the iPhone should use: --wifi-ssid \"<name>\" --wifi-passphrase \"<password>\"",
                )
                return
            }
            if (config.wifiPassphrase.isNullOrBlank()) {
                log.warn("no --wifi-passphrase configured; the phone must already know network {}", wifi.ssid)
            }
            val bridgePath = BluetoothBridge.resolvePath(config.bluetoothBridge)
            if (bridgePath == null) {
                log.warn("wireless bootstrap skipped: bt-bridge helper not found; pass --bt-bridge <path>")
                return
            }
            val deviceAddress = server.wirelessPhone()?.takeIf { it.isNotBlank() }
                ?: if (System.getenv("CARPLAY_PRESENCE_HELPER") == null) BluetoothBridge.findPairedIphone(bridgePath) else null
            if (deviceAddress == null) {
                log.warn("wireless bootstrap skipped: no paired iPhone found; pass --bt-address AA:BB:CC:DD:EE:FF")
                return
            }
            val hostBluetoothMac = server.hostBluetoothMac
            // Closed meanwhile, e.g. an iPhone was plugged into the USB port: no invitation, and no log
            // line that reads like one (run-receiver.py marks "invitation sent" on it).
            if (stopped) return
            log.info("wireless bootstrap: iPhone={} hostBt={} wifi={} ch={}", deviceAddress, hostBluetoothMac, wifi.ssid, wifi.channel)

            val stream = synchronized(this) {
                if (stopped) return
                BluetoothBridge.open(bridgePath, deviceAddress).also { bridgeProcess = it }
            }
            val channel = Iap2Session.openWireless(stream, traceContext = "wireless-rfcomm", onTrace = { log.debug(it) })
            log.info("wireless iAP2 CSM channel opened over RFCOMM")

            val identification = Iap2IdentificationConfig(
                name = server.config.deviceName,
                modelIdentifier = server.config.model,
                manufacturer = server.config.manufacturer,
                serialNumber = "CARPLAYWEB-" + server.deviceId.replace(":", ""),
                firmwareVersion = "1.0.0",
                hardwareVersion = "1.0",
                wireless = Iap2WirelessIdentification(hostBluetoothMac, wifi.ssid),
            )
            val endpoint = Iap2WirelessCarPlayEndpoint(
                ssid = wifi.ssid,
                passphrase = config.wifiPassphrase.orEmpty(),
                channel = wifi.channel,
                security = config.wifiSecurity,
                ipAddresses = listOf(server.bindAddress.hostAddress),
                airPlayPort = config.airPlayPort,
                deviceIdentifier = server.deviceId,
                publicKey = server.identity.publicKeyHex,
                sourceVersion = config.sourceVersion,
            )
            server.media.setIapTunnelHandler { tunnelStream ->
                server.handleWirelessTunnel(tunnelStream, identification, endpoint)
            }
            val result = Iap2WirelessControlClient(
                session = channel,
                mfi = Iap2MfiAuthenticationClient(server.mfi),
            ).run(
                identification = identification,
                endpoint = endpoint,
                timeoutMillis = Iap2WirelessControlClient.NO_TIMEOUT_MILLIS,
                onReady = {
                    log.info("wireless bootstrap accepted by the iPhone; waiting for the Wi-Fi handoff")
                    server.handoffAccepted()
                },
                onProgress = { log.debug("wireless $it") },
            )
            if (!stopped) {
                when (result.terminal) {
                    Iap2WirelessControlTerminal.CHANNEL_CLOSED ->
                        log.info(
                            "wireless RFCOMM channel closed stage={} handoffSeen={}",
                            result.stage,
                            result.wirelessCarPlayAvailableSeen,
                        )
                    Iap2WirelessControlTerminal.TIMED_OUT -> log.info("wireless bootstrap timed out")
                }
            }
        } catch (error: Exception) {
            if (!stopped) {
                log.warn("wireless bootstrap failed: {}", error.message)
                failed = true
            }
        } finally {
            close()
        }
        if (failed) server.bootstrapFailed(this)
    }

    @Synchronized
    override fun close() {
        stopped = true
        try { bridgeProcess?.close() }
        finally { bridgeProcess = null; running = false }
    }
}

/** The Wi-Fi the iPhone is handed: the box's own access point. */
data class WifiNetwork(val ssid: String, val channel: Int)

/** Helpers around the bt-bridge executable (`--bt-bridge`; the box's BlueZ RFCOMM relay, same CLI as the old
 *  macOS helper: --print-address, --list, --address <mac>). */
object BluetoothBridge {
    /** Only the configured path: the macOS build-tree candidates went with that build. */
    fun resolvePath(configured: Path?): Path? = configured?.takeIf { Files.isExecutable(it) }

    private val log = LoggerFactory.getLogger("bt-bridge")

    fun localAddress(bridgePath: Path): String? = runCatching {
        val process = ProcessBuilder(bridgePath.toString(), "--print-address").start()
        val output = process.inputStream.bufferedReader().readText().trim()
        process.waitFor()
        output.takeIf { it.matches(Regex("[0-9A-Fa-f:]{17}")) }
    }.getOrNull()

    fun findPairedIphone(bridgePath: Path): String? = runCatching {
        val process = ProcessBuilder(bridgePath.toString(), "--list").start()
        val lines = process.inputStream.bufferedReader().readLines()
        process.waitFor()
        lines.firstOrNull { it.contains("iphone", ignoreCase = true) }
            ?.substringBefore(' ')
            ?.trim()
            ?.takeIf { it.matches(Regex("[0-9A-Fa-f:]{17}")) }
    }.onFailure { log.warn("paired-device lookup failed: {}", it.message) }
        .getOrNull()

    fun open(bridgePath: Path, deviceAddress: String): ProcessByteStream {
        val process = ProcessBuilder(bridgePath.toString(), "--address", deviceAddress)
            .redirectErrorStream(false)
            .start()
        return ProcessByteStream(process, "bt-bridge")
    }
}

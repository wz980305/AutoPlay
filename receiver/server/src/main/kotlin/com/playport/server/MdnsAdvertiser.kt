package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayConfig
import com.shilapi.xcertplay.airplay.AirPlayIdentity
import com.shilapi.xcertplay.network.CarPlayBonjourProtocol
import java.io.Closeable
import java.net.InetAddress
import javax.jmdns.JmDNS
import javax.jmdns.ServiceInfo
import org.slf4j.LoggerFactory

/**
 * Publishes the AirPlay service so the iPhone discovers this server as a CarPlay accessory.
 *
 * Uses the same TXT records as the Android head-unit implementation.
 */
class JmDnsAdvertiser(
    private val config: AirPlayConfig,
    private val identity: AirPlayIdentity,
    private val address: InetAddress,
) : ServiceAdvertiser {
    private val log = LoggerFactory.getLogger("mdns")
    @Volatile private var dns: JmDNS? = null
    @Volatile private var serviceInfo: ServiceInfo? = null

    override fun start() {
        val hostLabel = "playport-${config.deviceId.replace(":", "").takeLast(8).lowercase()}"
        val instance = JmDNS.create(address, hostLabel)
        dns = instance
        val txt = CarPlayBonjourProtocol.airPlayTxtRecords(config, identity)
        val info = ServiceInfo.create(
            "${CarPlayBonjourProtocol.AIRPLAY_SERVICE_TYPE}.local.",
            config.deviceName,
            config.port,
            0,
            0,
            txt,
        )
        serviceInfo = info
        instance.registerService(info)
        log.info(
            "mDNS advertised {} on {}:{} records={}",
            config.deviceName,
            address.hostAddress,
            config.port,
            txt.keys.sorted().joinToString(","),
        )
    }

    override fun close() {
        val info = serviceInfo
        val instance = dns
        serviceInfo = null
        dns = null
        if (instance == null) return
        // JmDNS waits up to 5 s, twice, for its announcer to cancel: every stop or restart of the receiver took 10 s
        // more (F50, 2026-10-14). The goodbye goes out first; whatever is left finishes without holding the stop.
        Thread({
            runCatching { info?.let { instance.unregisterService(it) } }
            runCatching { instance.close() }
        }, "mdns-close").apply { isDaemon = true; start() }.join(CLOSE_WAIT_MS)
    }

    private companion object {
        const val CLOSE_WAIT_MS = 1_000L
    }
}

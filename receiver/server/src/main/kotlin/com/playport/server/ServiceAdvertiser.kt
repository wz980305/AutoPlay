package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayConfig
import com.shilapi.xcertplay.airplay.AirPlayIdentity
import com.shilapi.xcertplay.network.CarPlayBonjourProtocol
import java.io.Closeable

/** How the AirPlay service is published on the LAN. */
interface ServiceAdvertiser : Closeable {
    fun start()
}

/**
 * The advertising backend: JmDNS (an in-process multicast responder; the F50 has no system mDNS daemon the receiver
 * could use). `--mdns off` publishes nothing: the Bluetooth handoff hands the iPhone this address directly, so the
 * advertisement is a fallback, not a dependency. The macOS `dns-sd` backend went with the macOS build.
 */
object Advertisers {
    fun create(
        preference: String,
        config: AirPlayConfig,
        identity: AirPlayIdentity,
        address: java.net.InetAddress,
    ): ServiceAdvertiser? = if (preference == "off") null else JmDnsAdvertiser(config, identity, address)
}

package com.playport.server

import io.ktor.server.engine.applicationEnvironment
import io.ktor.server.engine.embeddedServer
import io.ktor.server.engine.sslConnector
import io.ktor.server.netty.Netty
import java.nio.file.Path
import kotlin.system.exitProcess
import org.slf4j.LoggerFactory

fun main(args: Array<String>) {
    val log = LoggerFactory.getLogger("playport")
    val identityDir = Path.of("identity").toAbsolutePath().normalize()
    val stateDir = Path.of(System.getProperty("user.home"), ".playport")

    // First pass: honour --state-dir/--identity-dir before looking for a saved config.
    val bootstrap = ServerConfig.fromArgs(args, ServerConfig(identityDir = identityDir, stateDir = stateDir))
    val store = ConfigStore(bootstrap.stateDir)
    val saved = store.load()
    // Second pass: saved settings are defaults; CLI flags still win.
    val config = saved?.let { persisted ->
        ServerConfig.fromArgs(args, persisted.toServerDefaults(bootstrap.identityDir, bootstrap.stateDir))
    } ?: bootstrap

    if (saved != null) {
        log.info("loaded settings from {}", bootstrap.stateDir.resolve("config.json"))
    }

    val server = CarPlayServer(config, store)
    try {
        server.mfi
    } catch (error: Exception) {
        System.err.println("MFi identity unavailable: ${error.message}")
        System.err.println("Provide identity/offline-mfi/{identity.pk8,certificate.p7b}.")
        exitProcess(1)
    }

    val webRoot = Path.of("web/dist").toAbsolutePath().normalize()
    val tls = TlsCertificate.loadOrCreate(config.stateDir, listOf(server.bindAddress))
    // A box that is a client of the car hotspot and the iPhone's AP at once serves the viewer on every
    // address (the head unit comes through the car hotspot); AirPlay stays on bindAddress.
    val webHost = System.getenv("CARPLAY_WEB_HOST")?.takeIf { it.isNotBlank() } ?: server.bindAddress.hostAddress
    val http = if (config.insecureHttp) {
        embeddedServer(Netty, port = config.httpPort, host = webHost) {
            server.hub.install(this, webRoot)
        }
    } else {
        embeddedServer(
            Netty,
            environment = applicationEnvironment { },
            configure = {
                sslConnector(tls.keyStore, tls.alias, { tls.password }, { tls.password }) {
                    host = webHost
                    port = config.httpPort
                }
                configureBootstrap = {
                    // The kernel grows a socket's send buffer to megabytes, seconds of picture on a slow car Wi-Fi
                    // that WebHub's age check cannot see; a fixed 128 KiB (Linux doubles it) keeps that part short.
                    childOption(io.netty.channel.ChannelOption.SO_SNDBUF, 128 * 1024)
                    // DSCP AF41 (TOS 0x88) on every viewer connection (HTTPS and WSS): the F50's Wi-Fi driver picks
                    // its WMM access category from the TOS byte (0x80/0xA0 -> video), so the picture goes ahead of
                    // the car's and the iPhone's own best-effort internet traffic the box also forwards
                    // (media_performance_audit #6; the dashplay-tesla fork put the same line here, 2026-10-23).
                    childOption(io.netty.channel.ChannelOption.IP_TOS, 0x88)
                }
            },
        ) {
            server.hub.install(this, webRoot)
        }
    }

    try {
        server.start()
    } catch (error: Exception) {
        System.err.println("Could not start the AirPlay listener: ${error.message}")
        exitProcess(1)
    }
    http.start(wait = false)

    val scheme = if (config.insecureHttp) "http" else "https"
    val url = "$scheme://${server.bindAddress.hostAddress}:${config.httpPort}/?token=${config.accessToken}"
    println()
    println("  PlayPort ${projectVersion()}")
    println("  ------------------------------------------------------------------")
    println("  CarPlay device name : ${config.deviceName}")
    println("  AirPlay listener    : ${server.bindAddress.hostAddress}:${config.airPlayPort}")
    println("  Browser UI          : $url")
    if (!config.insecureHttp) {
        println("  (accept the self-signed certificate warning once; WebCodecs needs HTTPS)")
    }
    println("  Pairing PIN         : ${CarPlayServer.PAIRING_PIN}")
    println("  Wireless bootstrap  : ${if (config.wireless) "enabled" else "disabled (start with --wireless)"}")
    println("  ------------------------------------------------------------------")
    println("  On the iPhone: Settings > General > CarPlay > available cars, then")
    println("  enter PIN ${CarPlayServer.PAIRING_PIN} when asked.")
    println()

    Runtime.getRuntime().addShutdownHook(
        Thread {
            log.info("shutting down")
            runCatching { server.close() }
            runCatching { http.stop(1_000, 3_000) }
        },
    )
    Thread.currentThread().join()
}

private fun projectVersion(): String =
    CarPlayServer::class.java.`package`?.implementationVersion ?: "1.6.1"

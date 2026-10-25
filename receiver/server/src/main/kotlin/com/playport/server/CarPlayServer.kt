package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayIcon
import com.shilapi.xcertplay.airplay.AirPlayConfig
import com.shilapi.xcertplay.airplay.AirPlayContact
import com.shilapi.xcertplay.airplay.AirPlayDeviceInfo
import com.shilapi.xcertplay.airplay.AirPlayDisplayConfig
import com.shilapi.xcertplay.airplay.AirPlayKnobState
import com.shilapi.xcertplay.airplay.AirPlayMediaHandler
import com.shilapi.xcertplay.airplay.AirPlaySession
import com.shilapi.xcertplay.airplay.AirPlaySessionListener
import com.shilapi.xcertplay.airplay.CarPlayMediaEngine
import com.shilapi.xcertplay.airplay.PairingStore
import com.shilapi.xcertplay.mfi.MfiAuthenticator
import com.shilapi.xcertplay.transport.BlockingDuplexByteStream
import com.shilapi.xcertplay.transport.Iap2WirelessCarPlayEndpoint
import com.shilapi.xcertplay.transport.Iap2WirelessControlClient
import com.shilapi.xcertplay.transport.Iap2WirelessControlTerminal
import com.shilapi.xcertplay.transport.Iap2IdentificationConfig
import com.shilapi.xcertplay.mfi.Iap2MfiAuthenticationClient
import com.shilapi.xcertplay.iap2.session.Iap2Session
import java.io.Closeable
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.nio.file.Files
import java.nio.file.Path
import java.util.Properties
import java.util.concurrent.atomic.AtomicBoolean
import org.slf4j.LoggerFactory

/**
 * The desktop CarPlay receiver: RTSP listener, mDNS advertisement, media bridge to browsers and
 * (optionally) the wireless Bluetooth bootstrap.
 */
class CarPlayServer(val config: ServerConfig, private val configStore: ConfigStore? = null) : Closeable {
    private val log = LoggerFactory.getLogger("playport")

    val identity = AirPlayIdentityStore.loadOrCreate(config.stateDir)
    val deviceId: String = AirPlayIdentityStore.deviceId(identity)
    // Use one adapter identity for Bluetooth bootstrap and AirPlay /info.
    val hostBluetoothMac: String by lazy {
        if (config.wireless) {
            BluetoothBridge.resolvePath(config.bluetoothBridge)?.let(BluetoothBridge::localAddress) ?: deviceId
        } else deviceId
    }
    val bindAddress: InetAddress = Networks.resolve(config.bindAddress)

    val display = DisplayState(
        config.displayWidth,
        config.displayHeight,
        config.displayFps,
        config.uiScale,
        config.hevc,
    )
    val hub = WebHub(config, display)
    val bridge = WebBridge(hub)
    val media = CarPlayMediaEngine(bridge, microphoneEnabled = true, audioCaptureDirectory = null)

    private val pairings = loadPairings()
    val mfi: MfiAuthenticator by lazy { MfiIdentity.load(config) }

    @Volatile private var activeSession: AirPlaySession? = null
    @Volatile private var serverSocket: ServerSocket? = null
    @Volatile private var advertiser: ServiceAdvertiser? = null
    @Volatile private var wireless: WirelessBootstrap? = null
    @Volatile private var lastBootstrapAt = System.nanoTime() / 1_000_000
    private val closed = AtomicBoolean(false)
    private var wirelessGeneration = 0L
    private val presenceHelper = System.getenv("CARPLAY_PRESENCE_HELPER")
    @Volatile private var sessionEnded = false
    private val closingForDisplay = AtomicBoolean(false)
    @Volatile private var bootInvite = false
    private var bootDeadline = 0L
    @Volatile private var presenceLearned = false
    @Volatile private var lastPeer: String? = null

    @Volatile private var selectedPhone: String? = null
    @Volatile private var invitedPhone: String? = null
    @Volatile private var invitedAt = 0L
    @Volatile private var handoffAcceptedAt = Long.MIN_VALUE / 2
    @Volatile private var handoffRetried = false

    /** The invited iPhone accepted the Bluetooth bootstrap and is about to join the Wi-Fi. */
    fun handoffAccepted() {
        handoffAcceptedAt = System.nanoTime() / 1_000_000
    }
    fun wirelessPhone(): String? = if (presenceHelper == null) config.bluetoothDeviceAddress else selectedPhone

    private fun presenceResult(command: String, vararg args: String): String? {
        val helper = presenceHelper ?: return null
        return runCatching {
            val process = ProcessBuilder(listOf("/usr/bin/python3", helper, command) + args)
                .redirectError(ProcessBuilder.Redirect.DISCARD).start()
            // BlueZ lookups slow down while a phone is being bootstrapped; give the helper room.
            if (!process.waitFor(6, java.util.concurrent.TimeUnit.SECONDS)) {
                process.destroyForcibly()
                null
            } else if (process.exitValue() == 0) process.inputStream.bufferedReader().readText().trim() else null
        }.getOrNull()
    }

    private fun presence(command: String, vararg args: String): Boolean = presenceResult(command, *args) != null
    private fun selectedPresent(): Boolean = selectedPhone?.let { presence("present", it) } == true
    private fun selectPhone(): String? = presenceResult("select")?.takeIf { it.matches(Regex("(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")) }

    val airPlayConfig: AirPlayConfig
        get() = AirPlayConfig(
            deviceName = config.deviceName,
            deviceId = deviceId,
            btMac = hostBluetoothMac,
            sourceVersion = config.sourceVersion,
            main = com.shilapi.xcertplay.airplay.CarPlayUiScale.apply(
                AirPlayDisplayConfig(
                    widthPixels = display.width,
                    heightPixels = display.height,
                    fps = display.fps,
                ),
                display.uiScale,
            ),
            rightHandDrive = config.rightHandDrive,
            port = config.airPlayPort,
            entertainmentSampleRate = 48_000,
            hevc = display.hevc,
            microphone = true,
            manufacturer = config.manufacturer,
            model = config.model,
            oemLabel = "盒子设置",
            icons = listOf(AirPlayIcon(180, 180, checkNotNull(javaClass.getResourceAsStream("/f50-settings.png")).use { it.readBytes() })),
        )

    private val listener = object : AirPlaySessionListener {
        override fun onSessionActive(session: AirPlaySession) {
            log.info("CarPlay session active peer={}", session.host)
            activeSession = session
            bootInvite = false
            invitedPhone = null
            handoffAcceptedAt = Long.MIN_VALUE / 2
            handoffRetried = false
            lastPeer = session.host
            presenceLearned = false
            hub.setSessionState(true, null)
        }

        override fun onSessionEnded(session: AirPlaySession) {
            log.info("CarPlay session ended peer={}", session.host)
            if (activeSession !== session) return
            activeSession = null
            if (presenceHelper != null) presence("idle")
            // A session the receiver closed itself to apply a new display is already being re-invited;
            // flagging it as ended made the supervisor start a second invitation that cut off the first
            // (fullscreen switch took 19 s instead of ~12 s, 2026-10-11).
            sessionEnded = !closingForDisplay.getAndSet(false)
            bridge.endMicrophone()
            hub.setSessionState(false, null)
        }

        override fun onDeviceInfo(session: AirPlaySession, info: AirPlayDeviceInfo) {
            log.info("iPhone connected name={} model={} deviceId={}", info.name, info.model, info.deviceId)
            hub.setSessionState(true, info.name)
        }

        override fun onHostUiRequested(session: AirPlaySession) {
            if (activeSession !== session) return
            log.info("CarPlay requested receiver settings")
            hub.hostUiRequested()
        }

        override fun onTransportError(message: String) {
            log.warn("AirPlay transport error: {}", message)
        }

        override fun onCommand(session: AirPlaySession, type: String, params: Map<String, Any?>) {
            log.debug("AirPlay command type={} params={}", type, params.keys.sorted().joinToString(","))
            if (type == "modesChanged") {
                val resources = (params["resources"] as? List<*>)?.take(8)?.mapNotNull { entry ->
                    val resource = entry as? Map<*, *> ?: return@mapNotNull null
                    listOf("resourceID", "entity", "owner", "borrower").mapNotNull { key ->
                        (resource[key] as? Number)?.let { "$key=${it.toLong()}" }
                    }.joinToString(",")
                }
                log.info("CarPlay resource ownership: {}", resources)
            }
        }

        override fun onDebugLog(message: String) {
            log.debug(message)
        }
    }

    fun start() {
        hub.inputHandler = ::routeInput
        hub.onApplyDisplay = ::applyDisplay
        hub.onMicrophoneData = { opus, payload -> bridge.sendMicrophonePayload(payload, opus) }
        awaitBindAddress()
        selectedPhone = presenceResult("boot")?.takeIf { it.isNotBlank() }
        bootInvite = selectedPhone != null
        if (!bootInvite && presenceHelper != null) selectedPhone = selectPhone()
        bootDeadline = System.nanoTime() / 1_000_000 + BOOTSTRAP_STALE_MS
        hub.onViewerJoined = { streamType ->
            if (bridge.hasRecoveryHandler) {
                log.info("requesting keyframe for stream {}", streamType)
                bridge.requestKeyFrame(streamType)
            }
        }
        startAirPlayListener()
        // The handoff hands the iPhone this address directly, and it accepts the Bluetooth invitation
        // ~5 s later, so mDNS (5.3 s to announce on the S805) need not delay the invitation.
        Thread({
            runCatching { Advertisers.create(config.mdns, airPlayConfig, identity, bindAddress).also { it.start() } }
                .onSuccess { if (closed.get()) runCatching { it.close() } else advertiser = it }
                .onFailure { log.warn("mDNS advertisement failed: {}", it.message) }
        }, "mdns-start").apply { isDaemon = true; start() }
        if (config.wireless && (presenceHelper == null || bootInvite || selectedPresent())) {
            wireless = WirelessBootstrap(this).also { it.start() }
        }
        startSupervisor()
    }

    /**
     * A receiver started before its network is up (CARPLAY_BIND_WAIT_MS, with ip_nonlocal_bind) loads
     * while the box joins the Wi-Fi, then waits here until the address is really configured, so the
     * presence check and the first invitation see the network. Gives up after the limit.
     */
    private fun awaitBindAddress() {
        val limit = System.getenv("CARPLAY_BIND_WAIT_MS")?.toLongOrNull() ?: return
        val deadline = System.nanoTime() / 1_000_000 + limit
        while (runCatching { java.net.NetworkInterface.getByInetAddress(bindAddress) }.getOrNull() == null) {
            if (System.nanoTime() / 1_000_000 >= deadline || closed.get()) {
                log.warn("bind address {} still not configured; continuing", bindAddress.hostAddress)
                return
            }
            Thread.sleep(100)
        }
        log.info("bind address {} configured", bindAddress.hostAddress)
    }

    private fun startAirPlayListener() {
        val server = ServerSocket()
        server.reuseAddress = true
        server.bind(InetSocketAddress(bindAddress, config.airPlayPort))
        serverSocket = server
        Thread({ acceptLoop(server) }, "airplay-accept").apply {
            isDaemon = true
            start()
        }
        log.info("AirPlay RTSP listening on {}:{}", bindAddress.hostAddress, config.airPlayPort)
    }

    private fun acceptLoop(server: ServerSocket) {
        while (!closed.get()) {
            val socket: Socket = try {
                server.accept()
            } catch (error: Exception) {
                if (closed.get()) return
                log.warn("AirPlay accept failed: {}", error.message)
                continue
            }
            try {
                if (presenceHelper != null) {
                    val incomingPhone = presenceResult("admit", socket.inetAddress.hostAddress)
                    val current = activeSession
                    if (current != null) {
                        // A second phone must never replace an active or negotiating session. The
                        // owner returning after a Wi-Fi drop replaces its own stale session instead.
                        if (incomingPhone == null || incomingPhone != selectedPhone) {
                            log.info("receiver busy; rejecting additional AirPlay connection from {}", socket.remoteSocketAddress)
                            socket.close()
                            continue
                        }
                        log.info("current phone reconnected; replacing its stale session")
                        runCatching { current.close() }
                    }
                    val handoff = System.nanoTime() / 1_000_000 - handoffAcceptedAt < HANDOFF_ADMIT_MS
                    if (incomingPhone != null) selectedPhone = incomingPhone
                    else if (handoff) {
                        // A phone that just joined may not answer ARP yet (2026-10-11: rejected twice ~2 s
                        // after accepting the handoff). The phone we invited is the one arriving now;
                        // AirPlay pair-verify still authenticates it and "remember" binds its identity.
                        log.info("admitting {} as the invited phone after its accepted handoff", socket.remoteSocketAddress)
                    } else if (!bootInvite) {
                        log.info("unknown network peer outside first-pairing window; rejecting AirPlay connection from {}", socket.remoteSocketAddress)
                        socket.close()
                        continue
                    }
                }
                socket.tcpNoDelay = true
                socket.keepAlive = true
                socket.setSoLinger(true, 0)
                log.info("AirPlay connection accepted from {}", socket.remoteSocketAddress)
                val session = AirPlaySession(
                    socket = socket,
                    config = airPlayConfig,
                    identity = identity,
                    pairings = pairings,
                    mfi = mfi,
                    listener = listener,
                    media = media,
                )
                activeSession = session
                session.start()
            } catch (error: Exception) {
                log.warn("AirPlay session bring-up failed: {}", error.message)
                runCatching { socket.close() }
            }
        }
    }

    private fun routeInput(message: ClientMessage) {
        val session = activeSession ?: return
        try {
            when (message.type) {
                "touch" -> session.sendTouch(
                    message.contacts.map { AirPlayContact(it.id, it.x, it.y, it.down) },
                )
                "media" -> message.media?.let(session::sendMedia)
                "knob" -> message.knob?.let {
                    session.sendKnob(
                        AirPlayKnobState(
                            select = it.select,
                            home = it.home,
                            back = it.back,
                            x = it.x,
                            y = it.y,
                            wheel = it.wheel,
                        ),
                    )
                }
                "siri" -> session.invokeSiri()
                "telephony" -> message.telephony?.let(session::sendTelephony)
                "night" -> message.night?.let(session::setNightMode)
            }
        } catch (error: Exception) {
            log.warn("Input routing failed type={}: {}", message.type, error.message)
        }
    }

    /** Opens the tunneled iAP2 link after the phone hands the session over to Wi-Fi. */
    fun handleWirelessTunnel(
        stream: BlockingDuplexByteStream,
        identification: Iap2IdentificationConfig,
        endpoint: Iap2WirelessCarPlayEndpoint,
    ): Boolean {
        log.info("wireless iAP2 tunnel accepted")
        val channel = try {
            Iap2Session.openTunnel(stream, traceContext = "wireless-tunnel", onTrace = { log.debug(it) })
        } catch (error: Exception) {
            log.warn("could not open tunneled iAP2 link: {}", error.message)
            return false
        }
        val metadata = NowPlayingState()
        val tunnelSession = activeSession
        val tunnelDone = java.util.concurrent.atomic.AtomicBoolean(false)
        val artwork = com.shilapi.xcertplay.iap2.message.Iap2ArtworkReceiver(
            send = { channel.sendFileTransfer(it) { !tunnelDone.get() && activeSession === tunnelSession } },
            complete = { revision, id, bytes ->
                activeSession === tunnelSession && metadata.value.revision == revision && metadata.artworkId == id && hub.artwork(revision, bytes)
            },
            clock = { System.nanoTime() / 1_000_000 },
            onDiagnostic = { log.debug(it) },
        )
        Thread({
            try {
                while (!tunnelDone.get() && activeSession === tunnelSession && !channel.isClosed) {
                    channel.recvFileTransfer(250)?.let(artwork::receive)
                    artwork.expire()
                }
            } catch (_: Exception) { log.debug("Artwork transport ended") }
        }, "wireless-artwork").apply { isDaemon = true; start() }
        Thread(
            {
                try {
                    val result = Iap2WirelessControlClient(
                        session = channel,
                        mfi = Iap2MfiAuthenticationClient(mfi),
                    ).run(
                        identification = identification,
                        endpoint = endpoint,
                        timeoutMillis = Iap2WirelessControlClient.NO_TIMEOUT_MILLIS,
                        onReady = { log.info("wireless iAP2 tunnel ready; CarPlay is live") },
                        onIncoming = { frame ->
                            if (activeSession === tunnelSession) {
                                try { metadata.accept(frame)?.let {
                                    hub.nowPlaying(it)
                                    artwork.expect(metadata.artworkId, it.revision)
                                } }
                                catch (_: Exception) { log.debug("Ignoring malformed NowPlaying update") }
                            }
                        },
                        onProgress = { log.debug("iAP tunnel $it") },
                    )
                    when (result.terminal) {
                        Iap2WirelessControlTerminal.TIMED_OUT -> log.info("tunneled iAP2 control timed out")
                        Iap2WirelessControlTerminal.CHANNEL_CLOSED -> log.info("tunneled iAP2 channel closed")
                    }
                } catch (error: Exception) {
                    log.warn("tunneled iAP2 control failed: {}", error.message)
                } finally { tunnelDone.set(true) }
            },
            "wireless-tunnel-control",
        ).apply {
            isDaemon = true
            start()
        }
        return true
    }

    /** Only a fresh Wi-Fi presence proof permits re-invitation after the boot attempt. */
    private fun startSupervisor() {
        if (!config.wireless) return
        Thread({
            var absentChecks = 0
            while (!closed.get()) {
                try {
                    Thread.sleep(SUPERVISOR_INTERVAL_MS)
                    if (closed.get()) return@Thread
                    val now = System.nanoTime() / 1_000_000
                    if (activeSession != null) {
                        lastBootstrapAt = now
                        absentChecks = 0
                        if (!presenceLearned) lastPeer?.let { peer ->
                            selectedPhone?.let { phone ->
                                presenceLearned = presence("remember", peer, phone, activeSession?.controllerId.orEmpty())
                            }
                        }
                        continue
                    }
                    if (presenceHelper == null) {
                        // Preserve the legacy policy on receivers that did not opt in.
                        if (wireless?.running != true && now - lastBootstrapAt >= 20_000) restartWireless()
                        continue
                    }
                    if (joiningAfterHandoff(now, handoffAcceptedAt)) continue
                    if (handoffStalled(now, handoffAcceptedAt) && !handoffRetried) {
                        // First time on a hotspot, an iPhone joined the Wi-Fi after accepting but never
                        // opened AirPlay; one more invitation started CarPlay at once (2026-10-11). The
                        // phone's address on this network is not learned yet, so skip the presence check.
                        handoffRetried = true
                        log.info("invited phone accepted the handoff but did not connect; inviting it once more")
                        restartWireless(confirmedPresent = true)
                        continue
                    }
                    if (bootInvite && now < bootDeadline) {
                        if (wireless?.running != true && now - lastBootstrapAt >= 5_000) restartWireless()
                        continue
                    }
                    bootInvite = false
                    invitedPhone?.takeIf { now - invitedAt >= DECLINE_AFTER_MS }?.let { phone ->
                        // An online phone that ignores invitations must not block the next person.
                        invitedPhone = null
                        presence("decline", phone)
                        log.info("invited phone did not start CarPlay; backing off before inviting it again")
                    }
                    val candidate = selectPhone()
                    val present = candidate != null
                    if (!present) {
                        absentChecks++
                        // A single missed ARP must not cancel an in-flight Bluetooth handshake.
                        if (absentChecks < 3 || now - lastBootstrapAt < 15_000) continue
                        synchronized(this@CarPlayServer) {
                            if (activeSession == null && wireless != null) {
                                ++wirelessGeneration
                                val previous = wireless
                                wireless = null
                                previous?.close()
                                log.info("phone absent from receiver Wi-Fi; waiting without invitations")
                            }
                        }
                        continue
                    }
                    absentChecks = 0
                    val changed = candidate != selectedPhone
                    if (!changed && !shouldRestartWireless(activeSession != null, wireless?.running == true,
                            now - lastBootstrapAt, present, sessionEnded)) continue
                    if (activeSession != null) continue
                    selectedPhone = candidate
                    log.info("eligible paired phone selected; restoring CarPlay")
                    restartWireless(confirmedPresent = true)
                } catch (interrupted: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return@Thread
                } catch (error: Exception) {
                    log.warn("connection supervisor error: {}", error.message)
                }
            }
        }, "carplay-supervisor").apply { isDaemon = true; start() }
    }

    /**
     * Applies a new display configuration and restarts CarPlay so the phone re-negotiates the
     * display. Returns null on success or a human-readable error.
     */
    fun applyDisplay(width: Int, height: Int, fps: Int, uiScale: Int, hevc: Boolean): String? {
        DisplayState.validate(width, height, fps)?.let { return it }
        display.update(width, height, fps, uiScale, hevc)
        configStore?.save(PersistentConfig.of(config, display))
        log.info(
            "display changed to {}x{} @{}fps uiScale={} codec={} ({}); restarting CarPlay",
            width, height, fps, display.uiScale, if (display.hevc) "h265" else "h264", display.orientation,
        )
        val wasActive = activeSession != null
        closingForDisplay.set(wasActive)
        activeSession?.close()
        // The phone was just using CarPlay, so skip the ~2.4 s presence re-check before re-inviting it.
        restartWireless(confirmedPresent = wasActive)
        return null
    }

    /** confirmedPresent: the caller has just seen the selected phone on the network (skips a ~2.4 s re-check). */
    @Synchronized
    private fun restartWireless(confirmedPresent: Boolean = false) {
        if (!config.wireless || closed.get()) return
        val generation = ++wirelessGeneration
        sessionEnded = false
        lastBootstrapAt = System.nanoTime() / 1_000_000
        if (presenceHelper != null && selectedPhone != invitedPhone) {
            invitedPhone = selectedPhone
            invitedAt = lastBootstrapAt
        }
        val current = wireless
        wireless = null
        current?.close()
        Thread(
            {
                Thread.sleep(750)
                synchronized(this@CarPlayServer) {
                    if (closed.get() || generation != wirelessGeneration || activeSession != null) return@Thread
                    if (presenceHelper != null && !bootInvite && !confirmedPresent && !selectedPresent()) return@Thread
                    wireless = WirelessBootstrap(this).also { it.start() }
                }
            },
            "wireless-restart",
        ).apply {
            isDaemon = true
            start()
        }
    }

    fun statusLine(): String = buildString {
        append("device=").append(config.deviceName)
        append(" address=").append(bindAddress.hostAddress)
        append(" airplay=").append(config.airPlayPort)
        append(" http=").append(config.httpPort)
        append(" viewers=").append(if (activeSession != null) "1+session" else "0")
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        runCatching { wireless?.close() }
        runCatching { advertiser?.close() }
        runCatching { activeSession?.close() }
        runCatching { serverSocket?.close() }
    }

    // Pair records survive restarts so the phone reconnects without pairing again.
    private fun loadPairings(): PairingStore {
        val file = config.stateDir.resolve("pairings.properties")
        val properties = Properties()
        if (Files.isRegularFile(file)) {
            runCatching { Files.newInputStream(file).use(properties::load) }
        }
        val store = PairingStore { identifier, key ->
            properties.setProperty(identifier, key.joinToString("") { "%02x".format(it) })
            runCatching {
                Files.createDirectories(config.stateDir)
                Files.newOutputStream(file).use { properties.store(it, "playport paired controllers") }
            }
        }
        properties.forEach { (identifier, value) ->
            val bytes = (value as? String)?.hexToBytes()
            if (bytes != null) store.save(identifier.toString(), bytes)
        }
        return store
    }

    private fun String.hexToBytes(): ByteArray? {
        if (length % 2 != 0) return null
        return try {
            ByteArray(length / 2) { index -> substring(index * 2, index * 2 + 2).toInt(16).toByte() }
        } catch (_: NumberFormatException) {
            null
        }
    }

    companion object {
        /**
         * An iPhone that accepted the handoff is joining the Wi-Fi; a first join of an unknown hotspot took
         * longer than the 5 s re-invite delay and was interrupted by a new invitation (2026-10-11).
         */
        internal fun joiningAfterHandoff(now: Long, acceptedAt: Long): Boolean = now - acceptedAt in 0 until HANDOFF_JOIN_MS

        /** Shortly after the join grace: the phone accepted but no session started. */
        internal fun handoffStalled(now: Long, acceptedAt: Long): Boolean =
            now - acceptedAt in HANDOFF_JOIN_MS until HANDOFF_JOIN_MS + HANDOFF_RETRY_WINDOW_MS

        internal fun shouldRestartWireless(active: Boolean, running: Boolean, elapsedMs: Long, present: Boolean, justEnded: Boolean = false): Boolean =
            !active && present && (justEnded || elapsedMs >= (if (running) 15_000L else 5_000L))

        /** AirPlay pair-setup PIN advertised for first-time connections. */
        const val PAIRING_PIN = "3939"
        private const val SUPERVISOR_INTERVAL_MS = 2_000L
        private const val BOOTSTRAP_COOLDOWN_MS = 20_000L
        private const val BOOTSTRAP_STALE_MS = 60_000L
        private const val DECLINE_AFTER_MS = 45_000L
        private const val HANDOFF_ADMIT_MS = 30_000L
        private const val HANDOFF_JOIN_MS = 25_000L
        private const val HANDOFF_RETRY_WINDOW_MS = 20_000L
    }
}

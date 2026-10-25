package com.playport.server

import com.shilapi.xcertplay.airplay.AirPlayIcon
import com.shilapi.xcertplay.airplay.AirPlayConfig
import com.shilapi.xcertplay.airplay.AirPlayContact
import com.shilapi.xcertplay.airplay.AirPlayDeviceInfo
import com.shilapi.xcertplay.airplay.AirPlayDisplayConfig
import com.shilapi.xcertplay.airplay.AirPlayViewArea
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
/** What the supervisor does about a wireless session nobody watches (CarPlayServer.idleAction). */
enum class IdleAction { NONE, RELEASE, WAIT, RESUME }

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
        config.displayAreas.takeIf { DisplayState.validateAreas(config.displayWidth, config.displayHeight, it, config.displayArea) == null }
            ?: emptyList(),
        config.displayArea,
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
    /** Until when, and how many more times, a failed invitation is repeated at once (after a display change). */
    @Volatile private var quickRetryUntil = Long.MIN_VALUE / 2
    @Volatile private var quickRetriesLeft = 0

    /** The invited iPhone accepted the Bluetooth bootstrap and is about to join the Wi-Fi. */
    fun handoffAccepted() {
        handoffAcceptedAt = System.nanoTime() / 1_000_000
    }
    /**
     * The invitation [link] failed. Right after a display change the phone is there and its Bluetooth link from the
     * session just closed was still going down (br-connection-canceled): invite it again at once. The supervisor's
     * next round took the reconnect from ~3 s to 11-13 s (XPeng, 2026-10-13: 3 of 9 display changes).
     */
    fun bootstrapFailed(link: WirelessBootstrap) {
        val generation: Long
        synchronized(this) {
            if (closed.get() || link !== wireless || activeSession != null ||
                !quickRetry(System.nanoTime() / 1_000_000, quickRetryUntil, quickRetriesLeft)) return
            quickRetriesLeft--
            generation = wirelessGeneration
        }
        log.info("invitation failed right after the display change; inviting again in {} ms", QUICK_RETRY_DELAY_MS)
        Thread({
            Thread.sleep(QUICK_RETRY_DELAY_MS)
            synchronized(this@CarPlayServer) {
                if (closed.get() || activeSession != null || generation != wirelessGeneration) return@Thread
                restartWireless(confirmedPresent = true)
            }
        }, "wireless-quick-retry").apply { isDaemon = true; start() }
    }

    private fun armQuickRetry() {
        quickRetryUntil = System.nanoTime() / 1_000_000 + QUICK_RETRY_WINDOW_MS
        quickRetriesLeft = QUICK_RETRIES
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
                    viewAreas = display.areas.takeIf { it.size > 1 }?.map { AirPlayViewArea(it.width, it.height) },
                    initialViewArea = display.area,
                    widthPhysicalMm = display.physicalWidthMm(),
                ),
                display.uiScale,
            ),
            rightHandDrive = config.rightHandDrive,
            port = config.airPlayPort,
            entertainmentSampleRate = 48_000,
            hevc = display.hevc,
            microphone = !config.carVoice,
            callsAndSiri = !config.carVoice,
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
            quickRetriesLeft = 0
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
            val forDisplay = closingForDisplay.getAndSet(false)
            sessionEnded = !forDisplay
            // Ended by itself (the phone left, the car slept): the next session can take up a change that waited.
            if (!forDisplay && display.applyPending()) {
                configStore?.save(PersistentConfig.of(config, display))
                log.info("display changed to {}x{} @{}fps codec={} for the next session (it waited for this one to end)",
                    display.width, display.height, display.fps, if (display.hevc) "h265" else "h264")
            }
            bridge.endMicrophone()
            hub.setSessionState(false, null, restarting = forDisplay)
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
        hub.onViewerJoined = { streamType ->
            if (bridge.hasRecoveryHandler) {
                log.info("requesting keyframe for stream {}", streamType)
                bridge.requestKeyFrame(streamType)
            }
        }
        // Wired CarPlay needs no Wi-Fi: bring the cable up while the box is still joining the car hotspot
        // (22-37 s on the Xpeng), so the picture is there when the head unit's browser connects.
        config.usbBridge?.let { wired = WiredBootstrap(this, it).also(WiredBootstrap::start) }
        awaitBindAddress()
        selectedPhone = presenceResult("boot")?.takeIf { it.isNotBlank() }
        bootInvite = selectedPhone != null
        if (!bootInvite && presenceHelper != null) selectedPhone = selectPhone()
        bootDeadline = System.nanoTime() / 1_000_000 + BOOTSTRAP_STALE_MS
        startAirPlayListener()
        // The handoff hands the iPhone this address directly, and it accepts the Bluetooth invitation
        // ~5 s later, so mDNS (5.3 s to announce on the S805) need not delay the invitation. Without
        // wireless CarPlay nothing looks for the AirPlay service: the cable carries the address over iAP2.
        if (config.wireless) Thread({
            runCatching { Advertisers.create(config.mdns, airPlayConfig, identity, bindAddress).also { it.start() } }
                .onSuccess { if (closed.get()) runCatching { it.close() } else advertiser = it }
                .onFailure { log.warn("mDNS advertisement failed: {}", it.message) }
        }, "mdns-start").apply { isDaemon = true; start() }
        if (config.wireless && !cablePhone && (presenceHelper == null || bootInvite || selectedPresent())) {
            wireless = WirelessBootstrap(this).also { it.start() }
        }
        startSupervisor()
    }

    @Volatile private var wired: WiredBootstrap? = null

    /** An iPhone on the USB cable (WiredBootstrap): no wireless invitations until it is unplugged. */
    @Volatile private var cablePhone = false
    @Volatile private var wiredSession: AirPlaySession? = null

    /** The iPhone on the cable has opened CarPlay (AirPlay over its NCM link) and is the active session. */
    fun wiredSessionActive(): Boolean = wiredSession.let { it != null && it === activeSession }

    fun setCablePhone(present: Boolean) {
        if (cablePhone == present) return
        cablePhone = present
        if (!config.wireless) return
        if (present) {
            synchronized(this) {
                ++wirelessGeneration
                val previous = wireless
                wireless = null
                previous?.close()
                // End a wireless session now: an iPhone switched from Wi-Fi straight to the cable's
                // CarPlay start ignored the first start (2026-10-12, 28 s to picture).
                activeSession?.takeIf { it !== wiredSession }?.let { runCatching { it.close() } }
            }
            log.info("iPhone on the USB cable; wireless invitations paused")
        } else {
            // The cable's session would only end on its 15 s keep-alive timeout and blocked the invitation
            // below (2026-10-12): end it now, the cable is gone.
            wiredSession?.takeIf { it === activeSession }?.let { runCatching { it.close() } }
            wiredSession = null
            // Whom to invite: a phone used on the cable only is not the presence helper's last phone.
            if (presenceHelper != null && selectedPhone == null) {
                selectedPhone = presenceResult("unplugged")?.takeIf { it.matches(Regex("(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")) }
            }
            // Invite at once, as at boot: someone who just pulled the cable is in the car with the phone.
            log.info("no iPhone on the USB cable; wireless invitations resume")
            restartWireless(confirmedPresent = true)
        }
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

    @Volatile private var wiredSocket: ServerSocket? = null

    /**
     * Wired CarPlay: listen on the iPhone's NCM link (see WiredBootstrap). Whoever connects there is
     * the phone on the cable, so there is no network admission; a wired phone replaces a session.
     */
    @Synchronized
    fun listenWired(address: java.net.InetAddress) {
        val current = wiredSocket
        // Each helper run creates the TAP again with a new interface index: InetAddress.equals ignores
        // the scope, and a listener left on the old index never saw the iPhone (2026-10-12).
        val scope = (address as? java.net.Inet6Address)?.scopeId
        if (current != null && !current.isClosed && current.inetAddress == address &&
            (current.inetAddress as? java.net.Inet6Address)?.scopeId == scope) return
        runCatching { current?.close() }
        val server = ServerSocket()
        server.reuseAddress = true
        server.bind(InetSocketAddress(address, config.airPlayPort))
        wiredSocket = server
        Thread({ acceptLoop(server, wired = true) }, "airplay-accept-wired").apply {
            isDaemon = true
            start()
        }
        log.info("AirPlay RTSP listening on [{}]:{} for wired CarPlay", address.hostAddress, config.airPlayPort)
    }

    private fun acceptLoop(server: ServerSocket, wired: Boolean = false) {
        while (!closed.get() && !server.isClosed) {
            val socket: Socket = try {
                server.accept()
            } catch (error: Exception) {
                if (closed.get() || server.isClosed) return
                log.warn("AirPlay accept failed: {}", error.message)
                continue
            }
            try {
                if (wired) {
                    activeSession?.let { current ->
                        log.info("wired iPhone connected; replacing the current session")
                        runCatching { current.close() }
                    }
                } else if (presenceHelper != null) {
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
                if (wired) wiredSession = session
                session.start()
            } catch (error: Exception) {
                log.warn("AirPlay session bring-up failed: {}", error.message)
                runCatching { socket.close() }
            }
        }
    }

    private var touchDownIds = emptySet<Int>()

    private fun routeInput(message: ClientMessage) {
        val session = activeSession ?: return
        try {
            when (message.type) {
                "touch" -> {
                    val down = message.contacts.filter { it.down }.map { it.id }.toSet()
                    val receivedMs = System.currentTimeMillis()
                    val sent = session.sendTouch(message.contacts.map { AirPlayContact(it.id, it.x, it.y, it.down) })
                    // Only down/up transitions, never positions or every drag packet. Correlate with packet counts.
                    if (down != touchDownIds || !sent) log.info("touch forwarded receivedMs={} epochMs={} down={} sent={}",
                        receivedMs, System.currentTimeMillis(), down.size, sent)
                    touchDownIds = down
                }
                "media" -> message.media?.let {
                    // Media keys from the page (1 play, 2 pause, 3 toggle, 4 next, 5 previous): the log then tells a
                    // pause from the car's media card or steering wheel apart from one made on the CarPlay screen.
                    log.info("viewer media key {}", it)
                    session.sendMedia(it)
                }
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
    /**
     * NowPlaying metadata and artwork arriving on an iAP2 link (the wireless tunnel or the USB cable),
     * forwarded to the browser's media session while [current] holds. Returns the link's frame handler.
     */
    fun nowPlayingFeed(channel: Iap2Session, name: String, current: () -> Boolean): (com.shilapi.xcertplay.iap2.wire.Iap2Frame) -> Unit {
        val metadata = NowPlayingState()
        val artwork = com.shilapi.xcertplay.iap2.message.Iap2ArtworkReceiver(
            send = { channel.sendFileTransfer(it) { current() } },
            complete = { revision, id, bytes ->
                (current() && metadata.value.revision == revision && metadata.artworkId == id && hub.artwork(revision, bytes)).also {
                    log.info("artwork id={} revision={} bytes={} sent to the page={} (song revision now {})",
                        id, revision, bytes.size, it, metadata.value.revision)
                }
            },
            clock = { System.nanoTime() / 1_000_000 },
            // A few lines a song: covers are sometimes missing on the car, and the debug log is not kept.
            onDiagnostic = { log.info(it) },
        )
        Thread({
            try {
                while (current() && !channel.isClosed) {
                    channel.recvFileTransfer(250)?.let(artwork::receive)
                    artwork.expire()
                }
            } catch (_: Exception) { log.debug("Artwork transport ended") }
        }, "$name-artwork").apply { isDaemon = true; start() }
        return { frame ->
            if (current()) {
                try { metadata.accept(frame)?.let {
                    hub.nowPlaying(it)
                    artwork.expect(metadata.artworkId, it.revision)
                } }
                catch (_: Exception) { log.debug("Ignoring malformed NowPlaying update") }
            }
        }
    }

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
        val tunnelSession = activeSession
        val tunnelDone = java.util.concurrent.atomic.AtomicBoolean(false)
        val nowPlaying = nowPlayingFeed(channel, "wireless") { !tunnelDone.get() && activeSession === tunnelSession }
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
                        onIncoming = nowPlaying,
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
            var viewerSeenAt = System.nanoTime() / 1_000_000   // the boot invitation has the full wait for a page
            val releaseMs = System.getenv("CARPLAY_IDLE_RELEASE_SECONDS")?.toLongOrNull()?.coerceAtLeast(0)?.times(1000)
                ?: IDLE_RELEASE_MS
            if (releaseMs == 0L) log.info("idle release off: CarPlay stays connected without a viewer")
            var parked = false
            while (!closed.get()) {
                try {
                    Thread.sleep(SUPERVISOR_INTERVAL_MS)
                    if (closed.get()) return@Thread
                    val now = System.nanoTime() / 1_000_000
                    // The phone on the cable owns CarPlay; its session is no Wi-Fi presence either.
                    if (cablePhone) { viewerSeenAt = now; continue }
                    if (hub.viewerCount > 0) viewerSeenAt = now
                    // Learn the phone's Wi-Fi identity before an idle release can end its session: a phone invited
                    // right after pairing, with no page open, was released first and then never invited again,
                    // being unknown on this Wi-Fi (F50, 2026-10-19).
                    if (activeSession != null && !presenceLearned) lastPeer?.let { peer ->
                        selectedPhone?.let { phone ->
                            presenceLearned = presence("remember", peer, phone, activeSession?.controllerId.orEmpty())
                        }
                    }
                    when (idleAction(now, viewerSeenAt, activeSession != null, parked, releaseMs)) {
                        IdleAction.RELEASE -> {
                            parked = true
                            log.info("no viewer for {} s: CarPlay released until a page opens", releaseMs / 1000)
                            synchronized(this@CarPlayServer) {
                                ++wirelessGeneration
                                val link = wireless
                                wireless = null
                                link?.close()
                            }
                            runCatching { activeSession?.close() }
                            continue
                        }
                        IdleAction.WAIT -> continue
                        IdleAction.RESUME -> {
                            parked = false
                            log.info("a viewer opened the page: inviting the iPhone again")
                            restartWireless()
                            continue
                        }
                        IdleAction.NONE -> {}
                    }
                    if (activeSession != null) {
                        lastBootstrapAt = now
                        absentChecks = 0
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
    fun applyDisplay(request: DisplayRequest): DisplayOutcome {
        val (width, height, fps, uiScale, hevc) = request
        DisplayState.validate(width, height, fps)?.let { return DisplayOutcome(it) }
        val areas = request.areas.takeIf { it.size > 1 } ?: emptyList()
        DisplayState.validateAreas(width, height, areas, request.area)?.let { return DisplayOutcome(it) }
        val reason = request.reason.take(16).filter { it.isLetterOrDigit() || it == '-' }.ifEmpty { "-" }
        // Only another of the declared areas (the page's window changed shape): move CarPlay there, no reconnect.
        val session = activeSession
        if (areas.isNotEmpty() && session != null && display.sameStream(width, height, fps, uiScale, hevc, areas)) {
            if (request.area == display.area) return DisplayOutcome()
            display.useArea(request.area)
            configStore?.save(PersistentConfig.of(config, display))
            val sent = session.showViewArea(request.area)
            log.info("view area {} ({}x{}) of {}x{} sent={} ({})", request.area, areas[request.area].width,
                areas[request.area].height, width, height, sent, reason)
            return if (sent) DisplayOutcome() else DisplayOutcome("view area not sent")
        }
        if (session == null && display.pending == null && display.sameStream(width, height, fps, uiScale, hevc, areas)) {
            // Between sessions (CarPlay is coming back, perhaps for this very display): the phone reads the area at its
            // next connection; restarting the invitation cut the reconnection in progress (two restarts within 5 s for
            // the same display, F50 2026-10-19).
            if (request.area != display.area) display.useArea(request.area)
            configStore?.save(PersistentConfig.of(config, display))
            log.info("display {}x{} area {} kept for the next session ({})", width, height, request.area, reason)
            return DisplayOutcome()
        }
        if (request.defer && session != null) {
            display.defer(request.copy(areas = areas))
            log.info("display {}x{} @{}fps codec={} waits for the session to end ({})", width, height, fps,
                if (hevc) "h265" else "h264", reason)
            return DisplayOutcome(deferred = true)
        }
        display.update(width, height, fps, uiScale, hevc, areas, request.area)
        configStore?.save(PersistentConfig.of(config, display))
        log.info(
            "display changed to {}x{} @{}fps uiScale={} codec={} ({}) areas={} ({}); restarting CarPlay",
            width, height, fps, display.uiScale, if (display.hevc) "h265" else "h264", display.orientation,
            areas.joinToString(",") { "${it.width}x${it.height}" }.ifEmpty { "-" }, reason,
        )
        val wasActive = activeSession != null
        closingForDisplay.set(wasActive)
        val keepLink = displayKeepLinkMs()
        if (wasActive && keepLink > 0 && wireless?.running == true) {
            // Keep the Bluetooth iAP2 link: the iPhone, still on the Wi-Fi, may reopen AirPlay by itself
            // and learn the new display without paging, authenticating and handing off again (~4 s).
            // If it has not come back in time, invite it the usual way.
            val generation = wirelessGeneration
            activeSession?.close()
            Thread({
                Thread.sleep(keepLink)
                synchronized(this@CarPlayServer) {
                    if (closed.get() || activeSession != null || generation != wirelessGeneration) return@Thread
                    log.info("phone did not reopen CarPlay within {} ms after the display change; inviting it", keepLink)
                    armQuickRetry()
                    restartWireless(confirmedPresent = true)
                }
            }, "display-keep-link").apply { isDaemon = true; start() }
            return DisplayOutcome()
        }
        activeSession?.close()
        // Wired: start the USB side over (identification, then CarPlayStartSession with the new display).
        wired?.restart()
        // The phone was just using CarPlay, so skip the ~2.4 s presence re-check before re-inviting it.
        if (wasActive) armQuickRetry()
        restartWireless(confirmedPresent = wasActive)
        return DisplayOutcome()
    }

    private fun displayKeepLinkMs(): Long =
        System.getenv("CARPLAY_DISPLAY_KEEP_LINK_MS")?.toLongOrNull()?.coerceIn(0, 20_000) ?: 0L

    /** confirmedPresent: the caller has just seen the selected phone on the network (skips a ~2.4 s re-check). */
    @Synchronized
    private fun restartWireless(confirmedPresent: Boolean = false) {
        if (!config.wireless || closed.get() || cablePhone) return
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
        // The session first: the phone learns at once that CarPlay is over (it stayed open through the 10 s mDNS
        // goodbye on every stop or restart, F50 2026-10-14).
        runCatching { activeSession?.close() }
        runCatching { wireless?.close() }
        runCatching { wired?.close() }
        runCatching { wiredSocket?.close() }
        runCatching { advertiser?.close() }
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

        /** A failed invitation is repeated at once while [now] is before [until] and retries are [left]. */
        internal fun quickRetry(now: Long, until: Long, left: Int): Boolean = left > 0 && now < until

        /** AirPlay pair-setup PIN advertised for first-time connections. */
        const val PAIRING_PIN = "3939"
        private const val SUPERVISOR_INTERVAL_MS = 2_000L
        private const val QUICK_RETRY_DELAY_MS = 1_500L
        internal const val QUICK_RETRY_WINDOW_MS = 15_000L
        internal const val QUICK_RETRIES = 2
        private const val BOOTSTRAP_COOLDOWN_MS = 20_000L
        private const val BOOTSTRAP_STALE_MS = 60_000L
        private const val DECLINE_AFTER_MS = 45_000L
        private const val HANDOFF_ADMIT_MS = 30_000L
        private const val HANDOFF_JOIN_MS = 25_000L
        private const val HANDOFF_RETRY_WINDOW_MS = 20_000L

        /** A wireless session nobody watches ends after this; the iPhone kept encoding and sending its screen and
         *  ran hot and slow at home with the F50 on all day (2026-10-13). A real car ends it at switch-off.
         *  CARPLAY_IDLE_RELEASE_SECONDS sets another wait, 0 never releases (the picture at once on a reopened page). */
        const val IDLE_RELEASE_MS = 300_000L

        /** [viewerSeenAt]: when a page last watched (or the box started). Parked: released, no invitations
         *  until a page opens again. */
        fun idleAction(now: Long, viewerSeenAt: Long, session: Boolean, parked: Boolean,
                       releaseMs: Long = IDLE_RELEASE_MS): IdleAction = when {
            parked -> if (viewerSeenAt >= now) IdleAction.RESUME else IdleAction.WAIT
            session && releaseMs > 0 && now - viewerSeenAt >= releaseMs -> IdleAction.RELEASE
            else -> IdleAction.NONE
        }
    }
}

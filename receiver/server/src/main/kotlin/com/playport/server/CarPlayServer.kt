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

/**
 * Supervisor-owned idle clock: every accepted connection gets a full grace period, including authentication
 * (DashPlay 2026.10.29 `playport-idle-new-session-grace`). Before, one `viewerSeenAt` counted from boot: a first
 * pairing that took longer than the wait, or a replacement phone, inherited the previous phone's idle time and was
 * released at once, with no page having had a chance to open.
 */
internal class IdleReleaseTimer(startedAt: Long, private val releaseMs: Long) {
    private var viewerSeenAt = startedAt
    private var parked = false
    private var observedSession: Any? = null

    fun action(now: Long, viewerPresent: Boolean, session: Any?): IdleAction {
        if (session != null && session !== observedSession) {
            // Startup or the previous phone's idle time must not cut off a new pairing/authentication.
            viewerSeenAt = now
            parked = false
        }
        observedSession = session
        if (viewerPresent) viewerSeenAt = now
        val action = CarPlayServer.idleAction(now, viewerSeenAt, session != null, parked, releaseMs)
        if (action == IdleAction.RELEASE) parked = true
        if (action == IdleAction.RESUME) parked = false
        return action
    }
}

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
    /** The car browser's position for the iPhone (docs/LOCATION.md); the switch is the page's, kept in config.json. */
    val carLocation = CarLocation(config.carLocation, CarLocation.Datum.of(config.carLocationDatum), log = { log.info(it) })
    val bridge = WebBridge(hub)
    val media = CarPlayMediaEngine(bridge, audioCaptureDirectory = null)

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
    /** One invitation for the owner of a session that dropped by itself (1.4.1, WirelessSessionRecovery). */
    private val sessionRecovery = WirelessSessionRecovery()

    /** duckAudio / unduckAudio commands seen, for the log. */
    private val ducks = java.util.concurrent.atomic.AtomicLong(0)
    private val unducks = java.util.concurrent.atomic.AtomicLong(0)

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

    /** The owner chose the datum in the page (an untouched one follows the default, "auto" since 1.5.0). */
    @Volatile private var datumPicked = config.carLocationDatumPicked

    private fun persisted(): PersistentConfig =
        PersistentConfig.of(config, display, carLocation.enabled, carLocation.datum.id, datumPicked)

    /**
     * The page's "car location" switch. On: the iPhone learns that this accessory gives location only when it
     * identifies the accessory, so a running CarPlay session reconnects (as for a new display, ~5 s). Off: nothing more
     * is sent from now on; the declaration goes with the next connection, without cutting this one. Returns whether
     * CarPlay is reconnecting.
     */
    fun setCarLocation(enabled: Boolean, datum: CarLocation.Datum? = null): Boolean {
        val changed = enabled != carLocation.enabled
        datum?.let { carLocation.datum = it; datumPicked = true }
        carLocation.setSwitch(enabled)
        configStore?.save(persisted())
        log.info("car location switched {}{} datum={}", if (enabled) "on" else "off", if (changed) "" else " (unchanged)",
            carLocation.datum.id)
        if (!enabled || !changed || activeSession == null) return false
        synchronized(this) {
            if (activeSession == null) return false
            sessionRecovery.cancel()
            closingForDisplay.set(true)
            activeSession?.close()
            armQuickRetry()
            restartWireless(confirmedPresent = true)
        }
        return true
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

    /**
     * Each phone's iOS major version by its Bluetooth address (SETUP deviceID), kept in phone-ios.properties for its
     * next connection: /info is answered before the phone states its version, and day/night works differently on iOS
     * 26 (setNightMode) and 27 (appearance updates). A phone not seen yet is taken for iOS 27 or newer. Design from
     * the dashplay-tesla fork of DashPlay (GPL-3.0), re-implemented.
     */
    private val iosFile: Path get() = config.stateDir.resolve("phone-ios.properties")
    private fun knownIos(phone: String?): Int? = phone?.takeIf { it.isNotBlank() }?.let { address ->
        runCatching { Properties().apply { Files.newInputStream(iosFile).use { load(it) } }.getProperty(address.uppercase())?.toIntOrNull() }.getOrNull()
    }
    private fun rememberIos(phone: String, version: String) {
        val major = iosMajorVersion(version) ?: return
        if (phone.isBlank() || knownIos(phone) == major) return
        runCatching {
            val all = Properties()
            runCatching { Files.newInputStream(iosFile).use { all.load(it) } }
            all.setProperty(phone.uppercase(), major.toString())
            Files.createDirectories(config.stateDir)
            val temporary = iosFile.resolveSibling("${iosFile.fileName}.tmp")
            Files.newOutputStream(temporary).use { all.store(it, "iPhone iOS major versions by Bluetooth address") }
            Files.move(temporary, iosFile, java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        }.onFailure { log.warn("phone iOS version not saved: {}", it.message) }
        log.info("phone {} runs iOS {}; appearance updates={}", phone, major, major >= APPEARANCE_MIN_IOS)
    }
    private fun appearanceUpdatesFor(phone: String?): Boolean = appearanceUpdatesForMajor(knownIos(phone))

    val airPlayConfig: AirPlayConfig
        get() = AirPlayConfig(
            deviceName = config.deviceName,
            deviceId = deviceId,
            btMac = hostBluetoothMac,
            sourceVersion = config.sourceVersion,
            // The size setting is the physical width (DisplayState.physicalWidthMm), no longer a larger canvas.
            main = AirPlayDisplayConfig(
                widthPixels = display.width,
                heightPixels = display.height,
                fps = display.fps,
                viewAreas = display.areas.takeIf { it.size > 1 }?.map { AirPlayViewArea(it.width, it.height) },
                initialViewArea = display.area,
                widthPhysicalMm = display.physicalWidthMm(),
            ),
            rightHandDrive = config.rightHandDrive,
            port = config.airPlayPort,
            entertainmentSampleRate = 48_000,
            hevc = display.hevc,
            manufacturer = config.manufacturer,
            model = config.model,
            // The icon opens the CarPlay page's settings panel, so it carries the panel's name (1.5.4: was "盒子设置").
            oemLabel = "AutoPlay 设置",
            icons = listOf(AirPlayIcon(180, 180, checkNotNull(javaClass.getResourceAsStream("/f50-settings.png")).use { it.readBytes() })),
            appearanceUpdates = appearanceUpdatesFor(selectedPhone),
            // No audioFormats/audioLatencies and no audio feature bits (1.3.0, always): the iPhone sets up no audio
            // stream and plays everything itself or on the Tesla's Bluetooth (docs/AUDIO.md, ADR-16).
            disableAudioOutput = true,
        )

    private val listener = object : AirPlaySessionListener {
        override fun onSessionActive(session: AirPlaySession) {
            log.info("CarPlay session active peer={}", session.host)
            activeSession = session
            if (presenceHelper != null) sessionRecovery.active(selectedPhone)
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
            // Dropped by itself, not closed by the box: its owner may be invited once (WirelessSessionRecovery). The
            // box's own closes (idle release, display, location, shutdown) cancel the recovery before they close.
            if (!forDisplay && !closed.get()) sessionRecovery.ended(System.nanoTime() / 1_000_000) else sessionRecovery.cancel()
            // Ended by itself (the phone left, the car slept): the next session can take up a change that waited.
            if (!forDisplay && display.applyPending()) {
                configStore?.save(persisted())
                log.info("display changed to {}x{} @{}fps codec={} for the next session (it waited for this one to end)",
                    display.width, display.height, display.fps, if (display.hevc) "h265" else "h264")
            }
            hub.setSessionState(false, null, restarting = forDisplay)
        }

        override fun onDeviceInfo(session: AirPlaySession, info: AirPlayDeviceInfo) {
            log.info("iPhone connected name={} model={} deviceId={} ios={}", info.name, info.model, info.deviceId, info.osVersion.ifEmpty { "-" })
            rememberIos(info.deviceId, info.osVersion)
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
            // duckAudio / unduckAudio (media_performance_audit #2): the iPhone wants the music under a prompt or Siri
            // lower, then back. The page plays both when music goes through it (after Siri; any car-music-off setup),
            // so it gets the level and the ramp. The volume comes as dB (<= 0) or as a linear fraction (0..1]; both
            // are mapped to a gain. Counted and logged so a drive log shows what the phone really sends.
            if (type == "duckAudio" || type == "unduckAudio") {
                val raw = (params["volume"] as? Number)?.toDouble()
                val level = when {
                    type == "unduckAudio" -> 1.0
                    raw == null -> DUCK_DEFAULT_LEVEL
                    raw <= 0.0 -> Math.pow(10.0, raw / 20.0)
                    raw <= 1.0 -> raw
                    else -> DUCK_DEFAULT_LEVEL
                }.coerceIn(0.0, 1.0)
                val durationMs = ((params["durationMs"] as? Number)?.toLong() ?: 0L).coerceIn(0L, 5_000L)
                val count = (if (type == "duckAudio") ducks else unducks).incrementAndGet()
                log.info("audio {} level={} ms={} volume={} count={}", type, String.format(java.util.Locale.ROOT, "%.3f", level), durationMs, raw ?: "-", count)
                hub.duck(level, durationMs)
            }
        }

        override fun onDebugLog(message: String) {
            log.debug(message)
        }
    }

    fun start() {
        hub.inputHandler = ::routeInput
        hub.onApplyDisplay = ::applyDisplay
        hub.onLocation = { carLocation.update(it) }
        hub.onSetLocation = { enabled, datum -> setCarLocation(enabled, datum?.let { CarLocation.Datum.of(it) }) }
        hub.carLocationState = { carLocation.enabled to carLocation.datum.id }
        hub.onViewerJoined = { streamType ->
            if (bridge.hasRecoveryHandler) {
                log.info("requesting keyframe for stream {}", streamType)
                bridge.requestKeyFrame(streamType)
            }
        }
        awaitBindAddress()
        selectedPhone = presenceResult("boot")?.takeIf { it.isNotBlank() }
        bootInvite = selectedPhone != null
        if (!bootInvite && presenceHelper != null) selectedPhone = selectPhone()
        bootDeadline = System.nanoTime() / 1_000_000 + BOOTSTRAP_STALE_MS
        startAirPlayListener()
        // The handoff hands the iPhone this address directly, and it accepts the Bluetooth invitation
        // ~5 s later, so mDNS (5.3 s to announce on the S805) need not delay the invitation. Without
        // wireless CarPlay nothing looks for the AirPlay service.
        if (config.wireless) Thread({
            runCatching { Advertisers.create(config.mdns, airPlayConfig, identity, bindAddress)?.also { it.start() } }
                .onSuccess { if (closed.get()) runCatching { it?.close() } else advertiser = it }
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
        while (!closed.get() && !server.isClosed) {
            val socket: Socket = try {
                server.accept()
            } catch (error: Exception) {
                if (closed.get() || server.isClosed) return
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

    private var touchDownIds = emptySet<Int>()
    /** The last touch report, so a page that vanished mid-press can be lifted where its fingers were. */
    @Volatile private var lastContacts: List<TouchContactMessage> = emptyList()

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
                    lastContacts = message.contacts
                }
                // WebHub: the page closed or froze with a finger down. Lift every contact at its last position ((0,0)
                // can cancel an iPhone button tap, input.ts), as the page itself does on pagehide when it can.
                "touch-release" -> if (touchDownIds.isNotEmpty()) {
                    val sent = session.sendTouch(lastContacts.map { AirPlayContact(it.id, it.x, it.y, false) })
                    log.info("touch released for a vanished page contacts={} sent={}", touchDownIds.size, sent)
                    touchDownIds = emptySet()
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

    /**
     * Drains the iAP2 file transfers (album artwork) the iPhone starts on the tunneled link. Nothing shows them any
     * more (the Tesla's own media card does, over the car's Bluetooth), but an undrained queue of 256 transfers ends
     * the whole tunneled iAP2 link (Iap2LinkChannel: "received-file queue limit exceeded"), so every packet is taken
     * off the link's queue by the receiver, which never expects a transfer: a SETUP waits in its own small queue and
     * is answered CANCEL when that fills (4) or after its 15 s deadline (expire); data for an unknown transfer is
     * answered CANCEL at once.
     */
    private fun artworkDrain(channel: Iap2Session, name: String, current: () -> Boolean) {
        val artwork = com.shilapi.xcertplay.iap2.message.Iap2ArtworkReceiver(
            send = { channel.sendFileTransfer(it) { current() } },
            complete = { _, _, _ -> false },
            clock = { System.nanoTime() / 1_000_000 },
            onDiagnostic = { log.debug(it) },
        )
        Thread({
            try {
                while (current() && !channel.isClosed) {
                    channel.recvFileTransfer(250)?.let(artwork::receive)
                    artwork.expire()
                }
            } catch (_: Exception) { log.debug("Artwork transport ended") }
        }, "$name-artwork").apply { isDaemon = true; start() }
    }

    fun handleWirelessTunnel(
        stream: BlockingDuplexByteStream,
        identification: Iap2IdentificationConfig,
        endpoint: Iap2WirelessCarPlayEndpoint,
    ): Boolean {
        // Location is declared on this long-lived link only, never on the short Bluetooth one: iOS can bind it to
        // the endpoint that declared it and refuse it on Wi-Fi once RFCOMM closes (DiPlay PR #157).
        val withLocation = carLocation.enabled
        val tunnelIdentification = identification.copy(locationInformationEnabled = withLocation)
        log.info("wireless iAP2 tunnel accepted carLocation={}", withLocation)
        val channel = try {
            Iap2Session.openTunnel(stream, traceContext = "wireless-tunnel", onTrace = { log.debug(it) })
        } catch (error: Exception) {
            log.warn("could not open tunneled iAP2 link: {}", error.message)
            return false
        }
        val tunnelSession = activeSession
        val tunnelDone = java.util.concurrent.atomic.AtomicBoolean(false)
        artworkDrain(channel, "wireless") { !tunnelDone.get() && activeSession === tunnelSession }
        Thread(
            {
                try {
                    val result = Iap2WirelessControlClient(
                        session = channel,
                        mfi = Iap2MfiAuthenticationClient(mfi),
                    ).run(
                        identification = tunnelIdentification,
                        endpoint = endpoint,
                        timeoutMillis = Iap2WirelessControlClient.NO_TIMEOUT_MILLIS,
                        locationProvider = carLocation.takeIf { withLocation },
                        onReady = { log.info("wireless iAP2 tunnel ready; CarPlay is live") },
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
            val releaseMs = System.getenv("CARPLAY_IDLE_RELEASE_SECONDS")?.toLongOrNull()?.coerceAtLeast(0)?.times(1000)
                ?: IDLE_RELEASE_MS
            if (releaseMs == 0L) log.info("idle release off: CarPlay stays connected without a viewer")
            // The boot invitation has the full wait for a page; so does every connection accepted later (IdleReleaseTimer).
            val idleTimer = IdleReleaseTimer(System.nanoTime() / 1_000_000, releaseMs)
            while (!closed.get()) {
                try {
                    Thread.sleep(SUPERVISOR_INTERVAL_MS)
                    if (closed.get()) return@Thread
                    val now = System.nanoTime() / 1_000_000
                    // Learn the phone's Wi-Fi identity before an idle release can end its session: a phone invited
                    // right after pairing, with no page open, was released first and then never invited again,
                    // being unknown on this Wi-Fi (F50, 2026-10-19).
                    if (activeSession != null && !presenceLearned) lastPeer?.let { peer ->
                        selectedPhone?.let { phone ->
                            presenceLearned = presence("remember", peer, phone, activeSession?.controllerId.orEmpty())
                        }
                    }
                    when (idleTimer.action(now, hub.viewerCount > 0, activeSession)) {
                        IdleAction.RELEASE -> {
                            sessionRecovery.cancel()
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
                    if (recoverWirelessSession(now)) continue
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
            configStore?.save(persisted().copy(display = display.forNextStart()))
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
            configStore?.save(persisted())
            log.info("display {}x{} area {} kept for the next session ({})", width, height, request.area, reason)
            return DisplayOutcome()
        }
        if (request.defer && session != null) {
            display.defer(request.copy(areas = areas))
            configStore?.save(persisted().copy(display = display.forNextStart()))
            log.info("display {}x{} @{}fps codec={} waits for the session to end ({})", width, height, fps,
                if (hevc) "h265" else "h264", reason)
            return DisplayOutcome(deferred = true)
        }
        display.update(width, height, fps, uiScale, hevc, areas, request.area)
        configStore?.save(persisted())
        log.info(
            "display changed to {}x{} @{}fps uiScale={} codec={} ({}) areas={} ({}); restarting CarPlay",
            width, height, fps, display.uiScale, if (display.hevc) "h265" else "h264", display.orientation,
            areas.joinToString(",") { "${it.width}x${it.height}" }.ifEmpty { "-" }, reason,
        )
        val wasActive = activeSession != null
        sessionRecovery.cancel()
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
        // The phone was just using CarPlay, so skip the ~2.4 s presence re-check before re-inviting it.
        if (wasActive) armQuickRetry()
        restartWireless(confirmedPresent = wasActive)
        return DisplayOutcome()
    }

    private fun displayKeepLinkMs(): Long =
        System.getenv("CARPLAY_DISPLAY_KEEP_LINK_MS")?.toLongOrNull()?.coerceIn(0, 20_000) ?: 0L

    /**
     * The one invitation for the owner of a session that dropped by itself (WirelessSessionRecovery), sent over
     * Bluetooth without first seeing the phone on the Wi-Fi: after a drop the iPhone often stays off the box's Wi-Fi
     * until CarPlay invites it. Only while that phone is still the selected one and still paired. It is not an
     * invitation that can be "declined": a phone that has walked away must not then wait out a back-off when it comes
     * back. Runs on the supervisor thread, outside the server lock (the helper may take seconds).
     */
    private fun recoverWirelessSession(now: Long): Boolean {
        if (closed.get() || activeSession != null || presenceHelper == null) return false
        val phone = sessionRecovery.candidate(now) ?: return false
        if (selectedPhone != phone || !presence("allowed", phone)) {
            sessionRecovery.cancel()
            return false
        }
        if (closed.get() || activeSession != null || selectedPhone != phone) return false
        if (!sessionRecovery.take(System.nanoTime() / 1_000_000, phone)) return false
        log.info("wireless session dropped; inviting its iPhone once without waiting to see it on the Wi-Fi")
        restartWireless(confirmedPresent = true)
        invitedPhone = null
        return true
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
        sessionRecovery.cancel()
        // The session first: the phone learns at once that CarPlay is over (it stayed open through the 10 s mDNS
        // goodbye on every stop or restart, F50 2026-10-14).
        runCatching { activeSession?.close() }
        runCatching { wireless?.close() }
        runCatching { advertiser?.close() }
        runCatching { serverSocket?.close() }
    }

    private fun loadPairings(): PairingStore = PairingFileStore(config.stateDir).load()

    companion object {
        internal fun iosMajorVersion(version: String): Int? = version.substringBefore('.').toIntOrNull()
        internal fun appearanceUpdatesForMajor(major: Int?): Boolean = (major ?: APPEARANCE_MIN_IOS) >= APPEARANCE_MIN_IOS

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
        /** From this iOS major on, day/night goes through the appearance updates (AirPlayConfig.appearanceUpdates). */
        private const val APPEARANCE_MIN_IOS = 27
        /** Music gain under a prompt when duckAudio names no usable volume (about -14 dB). */
        private const val DUCK_DEFAULT_LEVEL = 0.2
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

package com.playport.server

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.attribute.PosixFilePermission
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable
data class DisplayPrefs(
    val width: Int = 1280,
    val height: Int = 720,
    // 30 by default: at 60 the iPhone encodes twice the frames on the cable and ran hot (2026-10-12 drive).
    val fps: Int = 30,
    val uiScale: Int = ServerConfig.DEFAULT_UI_SCALE,
    val hevc: Boolean = false,
    val areas: List<ViewArea> = emptyList(),
    val area: Int = 0,
)

/** Settings persisted between runs in `~/.playport/config.json`. */
@Serializable
data class PersistentConfig(
    val deviceName: String = "PlayPort",
    val model: String = "playport",
    val manufacturer: String = "playport",
    val airPlayPort: Int = 7000,
    val httpPort: Int = 8080,
    val display: DisplayPrefs = DisplayPrefs(),
    val wireless: Boolean = false,
    val wifiSsid: String? = null,
    val wifiPassphrase: String? = null,
    val wifiChannel: Int = 0,
    val wifiSecurity: String = "wpa2",
    val bluetoothDeviceAddress: String? = null,
    val mdns: String = "jmdns",
    /** The page's "car location" switch and the datum of the browser's coordinates (CarLocation). */
    val carLocation: Boolean = false,
    val carLocationDatum: String = "wgs84",
) {
    /** Server defaults from this file (CLI flags are applied on top and override). */
    fun toServerDefaults(identityDir: Path, stateDir: Path): ServerConfig = ServerConfig(
        deviceName = deviceName,
        model = model,
        manufacturer = manufacturer,
        airPlayPort = airPlayPort,
        httpPort = httpPort,
        displayWidth = display.width,
        displayHeight = display.height,
        displayFps = display.fps,
        uiScale = display.uiScale,
        hevc = display.hevc,
        displayAreas = display.areas,
        displayArea = display.area,
        wireless = wireless,
        wifiSsid = wifiSsid,
        wifiPassphrase = wifiPassphrase,
        wifiChannel = wifiChannel,
        wifiSecurity = when (wifiSecurity.lowercase()) {
            "open" -> com.shilapi.xcertplay.transport.Iap2WirelessSecurity.NONE
            "wpa3" -> com.shilapi.xcertplay.transport.Iap2WirelessSecurity.WPA3_ONLY
            "wpa3-transition" -> com.shilapi.xcertplay.transport.Iap2WirelessSecurity.WPA3_TRANSITION
            else -> com.shilapi.xcertplay.transport.Iap2WirelessSecurity.WPA_WPA2
        },
        bluetoothDeviceAddress = bluetoothDeviceAddress,
        mdns = mdns,
        carLocation = carLocation,
        carLocationDatum = carLocationDatum,
        identityDir = identityDir,
        stateDir = stateDir,
    )

    companion object {
        fun of(
            config: ServerConfig,
            display: DisplayState,
            carLocation: Boolean = config.carLocation,
            carLocationDatum: String = config.carLocationDatum,
        ): PersistentConfig = PersistentConfig(
            deviceName = config.deviceName,
            model = config.model,
            manufacturer = config.manufacturer,
            airPlayPort = config.airPlayPort,
            httpPort = config.httpPort,
            display = DisplayPrefs(
                width = display.width,
                height = display.height,
                fps = display.fps,
                uiScale = display.uiScale,
                hevc = display.hevc,
                areas = display.areas,
                area = display.area,
            ),
            wireless = config.wireless,
            wifiSsid = config.wifiSsid,
            wifiPassphrase = config.wifiPassphrase,
            wifiChannel = config.wifiChannel,
            wifiSecurity = when (config.wifiSecurity) {
                com.shilapi.xcertplay.transport.Iap2WirelessSecurity.NONE -> "open"
                com.shilapi.xcertplay.transport.Iap2WirelessSecurity.WPA3_ONLY -> "wpa3"
                com.shilapi.xcertplay.transport.Iap2WirelessSecurity.WPA3_TRANSITION -> "wpa3-transition"
                else -> "wpa2"
            },
            bluetoothDeviceAddress = config.bluetoothDeviceAddress,
            mdns = config.mdns,
            carLocation = carLocation,
            carLocationDatum = carLocationDatum,
        )
    }
}

/** Reads and writes [PersistentConfig] under the state directory. */
class ConfigStore(private val stateDir: Path) {
    private val file: Path get() = stateDir.resolve(FILE_NAME)
    private val json = Json { prettyPrint = true; encodeDefaults = true }

    fun load(): PersistentConfig? {
        if (!Files.isRegularFile(file)) return null
        return runCatching {
            json.decodeFromString(PersistentConfig.serializer(), Files.readString(file))
        }.getOrNull()
    }

    fun save(config: PersistentConfig) {
        runCatching {
            Files.createDirectories(stateDir)
            val temporary = stateDir.resolve("$FILE_NAME.tmp")
            // Flushed before the rename: a power cut right after saving left an empty config.json that
            // stopped every later start (2026-10-11).
            java.nio.channels.FileChannel.open(
                temporary,
                java.nio.file.StandardOpenOption.CREATE,
                java.nio.file.StandardOpenOption.WRITE,
                java.nio.file.StandardOpenOption.TRUNCATE_EXISTING,
            ).use { channel ->
                channel.write(java.nio.ByteBuffer.wrap(json.encodeToString(PersistentConfig.serializer(), config).toByteArray()))
                channel.force(true)
            }
            restrictToOwner(temporary)
            Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING)
        }
    }

    private fun restrictToOwner(path: Path) {
        try {
            Files.setPosixFilePermissions(
                path,
                setOf(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE),
            )
        } catch (_: UnsupportedOperationException) {
            // Non-POSIX filesystems keep default permissions.
        }
    }

    private companion object {
        const val FILE_NAME = "config.json"
    }
}

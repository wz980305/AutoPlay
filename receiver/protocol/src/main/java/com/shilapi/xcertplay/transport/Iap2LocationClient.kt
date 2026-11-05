package com.shilapi.xcertplay.transport

import com.shilapi.xcertplay.iap2.message.Iap2ControlMessages
import com.shilapi.xcertplay.iap2.wire.Iap2Frame
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/** One location sample (from the car browser, see the server's CarLocation) as carried by the NMEA pair. */
data class CarPlayLocationFix(
    val latitudeDegrees: Double,
    val longitudeDegrees: Double,
    val altitudeMeters: Double? = null,
    val bearingDegrees: Double? = null,
    val speedMetersPerSecond: Double? = null,
    val accuracyMeters: Double? = null,
    val timestampMillis: Long? = null,
) {
    init {
        require(latitudeDegrees.isFinite() && latitudeDegrees in -90.0..90.0) {
            "latitudeDegrees must be between -90 and 90"
        }
        require(longitudeDegrees.isFinite() && longitudeDegrees in -180.0..180.0) {
            "longitudeDegrees must be between -180 and 180"
        }
    }
}

/** Supplies location data only while the phone has subscribed to iAP2 LocationInformation. */
interface Iap2LocationProvider : AutoCloseable {
    /** The 0xFFFA parameter ids (the sentence types the iPhone asked for); called before [start]. */
    fun onRequested(components: Set<Int>) = Unit

    /** Starts location updates and returns whether at least one source was subscribed. */
    fun start(): Boolean

    fun stop()

    /** The sentences for the newest fix, or null when there is none fresh enough to send (nothing is sent then). */
    fun latestNmea(): String?

    override fun close() {
        stop()
    }
}

/** LIVI-compatible $GPGGA + $GPRMC encoding used by iAP2 0xFFFB. */
object NmeaLocationEncoder {
    fun encode(fix: CarPlayLocationFix): String {
        val timestamp = fix.timestampMillis
            ?.takeIf { it > 0 }
            ?.let(::ofEpochMilli)
            ?: ofEpochMilli(System.currentTimeMillis())
        // hhmmss.ss: the fix time to the hundredth, as a GNSS receiver writes it (it was cut to whole seconds).
        val time = format("%02d%02d%02d.%02d", timestamp.hour, timestamp.minute, timestamp.second, timestamp.centis)
        val date = format(
            "%02d%02d%02d",
            timestamp.day,
            timestamp.month,
            timestamp.year % 100,
        )

        val latitude = degreesToNmea(fix.latitudeDegrees, latitude = true)
        val longitude = degreesToNmea(fix.longitudeDegrees, latitude = false)
        val hdop = fix.accuracyMeters
            ?.takeIf { it.isFinite() && it > 0 }
            ?.let { min(50.0, max(0.5, it / 5.0)) }
            ?: 1.0
        // Unknown altitude stays empty, as in a receiver's own output: "0.0" claimed sea level.
        val altitude = fix.altitudeMeters
            ?.takeIf { it.isFinite() }
            ?.let { format("%.1f", it) }
            .orEmpty()

        val ggaBody = "GPGGA,$time,${latitude.value},${latitude.hemisphere}," +
            "${longitude.value},${longitude.hemisphere},1,08,${format("%.1f", hdop)}," +
            "$altitude,M,0.0,M,,"
        val speedKnots = fix.speedMetersPerSecond
            ?.takeIf { it.isFinite() && it >= 0 }
            ?.let { format("%.2f", it * KNOTS_PER_METER_PER_SECOND) }
            ?: "0.00"
        // Without a direction (parked) the course stays empty: 0.00 would say north (DiPlay PR #109).
        val course = fix.bearingDegrees
            ?.takeIf { it.isFinite() }
            ?.let { format("%.2f", ((it % 360.0) + 360.0) % 360.0) }
            .orEmpty()
        val rmcBody = "GPRMC,$time,A,${latitude.value},${latitude.hemisphere}," +
            "${longitude.value},${longitude.hemisphere},$speedKnots,$course,$date,,"

        return "$${ggaBody}*${checksum(ggaBody)}\r\n$${rmcBody}*${checksum(rmcBody)}\r\n"
    }

    private fun degreesToNmea(value: Double, latitude: Boolean): NmeaCoordinate {
        val absolute = abs(value)
        var degrees = absolute.toInt()
        var minutes = (absolute - degrees) * MINUTES_PER_DEGREE
        if (minutes >= MINUTES_PER_DEGREE - MINUTE_ROUNDING_TOLERANCE) {
            degrees += 1
            minutes = 0.0
        }
        val degreeText = if (latitude) format("%02d", degrees) else format("%03d", degrees)
        val hemisphere = if (latitude) {
            if (value >= 0) "N" else "S"
        } else {
            if (value >= 0) "E" else "W"
        }
        return NmeaCoordinate("$degreeText${format("%07.4f", minutes)}", hemisphere)
    }

    private fun checksum(body: String): String {
        var value = 0
        for (character in body) value = value xor character.code
        return format("%02X", value)
    }

    private fun ofEpochMilli(millis: Long): Timestamp = Timestamp(millis)

    private fun format(format: String, vararg arguments: Any): String =
        String.format(Locale.US, format, *arguments)

    private data class NmeaCoordinate(val value: String, val hemisphere: String)

    private class Timestamp(millis: Long) {
        private val fields = java.time.Instant.ofEpochMilli(millis)
            .atZone(java.time.ZoneOffset.UTC)

        val hour: Int = fields.hour
        val minute: Int = fields.minute
        val second: Int = fields.second
        val centis: Int = fields.nano / 10_000_000
        val day: Int = fields.dayOfMonth
        val month: Int = fields.monthValue
        val year: Int = fields.year
    }

    private const val KNOTS_PER_METER_PER_SECOND = 1.94384449
    private const val MINUTES_PER_DEGREE = 60.0
    private const val MINUTE_ROUNDING_TOLERANCE = 0.00005
}

/**
 * Accessory side of iAP2 LocationInformation on one link: starts on 0xFFFA, asks the provider every [intervalMillis]
 * while the phone's request stands and sends what it returns, and stops on 0xFFFC. The provider returns each fix once
 * (the server's CarLocation), so asking four times a second passes a fix on within a quarter second of its arrival
 * without repeating it. The state belongs to one iAP2 link. Shaped after DiPlay's `Iap2LocationReporter` (GPL-3.0);
 * before it the wireless loop sent the latest fix again after every frame it received from the phone.
 */
class Iap2LocationReporter(
    private val provider: Iap2LocationProvider?,
    private val onProgress: (String) -> Unit,
    private val nanoTime: () -> Long = System::nanoTime,
    private val intervalMillis: Long = INTERVAL_MILLIS,
) {
    var active = false
        private set
    private var sentLogged = false
    private var lastAttemptNanos: Long? = null

    /** Handles 0xFFFA/0xFFFC; false for any other message. */
    fun handle(frame: Iap2Frame, send: (Iap2Frame) -> Unit): Boolean = when (frame.messageId) {
        Iap2LocationMessages.START_LOCATION_INFORMATION -> {
            val components = Iap2LocationMessages.requestedComponents(frame)
            onProgress("iap2 rx=0xfffa start-location-information components=$components")
            provider?.onRequested(components)
            active = startProvider()
            sentLogged = false
            lastAttemptNanos = null
            if (active) sendLatest(send)
            true
        }
        Iap2LocationMessages.STOP_LOCATION_INFORMATION -> {
            onProgress("iap2 rx=0xfffc stop-location-information")
            if (active) provider?.stop()
            active = false
            sentLogged = false
            true
        }
        else -> false
    }

    /** Sends the newest fix when one is due. */
    fun tick(send: (Iap2Frame) -> Unit) {
        if (active && sinceAttemptMillis() >= intervalMillis) sendLatest(send)
    }

    /** How long the receive loop may wait so that the next fix is not late. */
    fun pollTimeout(remainingMillis: Long): Long =
        if (!active) remainingMillis
        else min(remainingMillis, (intervalMillis - sinceAttemptMillis()).coerceAtLeast(1))

    /** The link ended: release the provider. */
    fun close() {
        if (active) provider?.stop()
        active = false
    }

    private fun sinceAttemptMillis(): Long =
        lastAttemptNanos?.let { (nanoTime() - it) / 1_000_000 } ?: Long.MAX_VALUE

    private fun startProvider(): Boolean {
        if (provider == null) return false
        return try {
            provider.start().also { started -> if (!started) onProgress("iap2 location provider did not start") }
        } catch (error: Exception) {
            onProgress("iap2 location provider start failed: ${error.message}")
            false
        }
    }

    private fun sendLatest(send: (Iap2Frame) -> Unit) {
        lastAttemptNanos = nanoTime()
        val sentences = try {
            provider?.latestNmea()
        } catch (error: Exception) {
            onProgress("iap2 location provider failed: ${error.message}")
            null
        } ?: return
        send(Iap2LocationMessages.locationInformation(sentences))
        if (!sentLogged) {
            sentLogged = true
            onProgress("iap2 tx=0xfffb location-information")
        }
    }

    companion object {
        const val INTERVAL_MILLIS = 250L
    }
}

object Iap2LocationMessages {
    const val START_LOCATION_INFORMATION = 0xfffa
    const val LOCATION_INFORMATION = 0xfffb
    const val STOP_LOCATION_INFORMATION = 0xfffc

    /** The parameter ids of a 0xFFFA request (the sentence types asked for), or none if unreadable. */
    fun requestedComponents(frame: Iap2Frame): Set<Int> =
        runCatching { frame.body().asList().map { it.id }.toSortedSet() }.getOrDefault(emptySet())

    fun locationInformation(nmeaSentence: String): Iap2Frame {
        require(nmeaSentence.isNotEmpty()) { "NMEA sentence must not be empty" }
        return Iap2ControlMessages.locationInformation(nmeaSentence)
    }
}

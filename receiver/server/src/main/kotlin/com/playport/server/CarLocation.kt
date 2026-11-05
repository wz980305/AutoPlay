package com.playport.server

import com.shilapi.xcertplay.transport.CarPlayLocationFix
import com.shilapi.xcertplay.transport.Iap2LocationProvider
import com.shilapi.xcertplay.transport.NmeaLocationEncoder
import java.util.Locale
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt
import kotlinx.serialization.Serializable

/**
 * One fix from the car browser's `navigator.geolocation`, as the page sends it:
 * `{"type":"location","location":{"lat":…,"lon":…,"acc":…,"speed":…,"heading":…,"time":…}}` (receiver/web/src/location.ts).
 */
@Serializable
data class LocationMessage(
    val lat: Double,
    val lon: Double,
    /** `coords.accuracy` in metres; 9999.99 from a 2026 Tesla browser means "not reported". */
    val acc: Double? = null,
    val alt: Double? = null,
    /** m/s. */
    val speed: Double? = null,
    /** Degrees clockwise from true north. */
    val heading: Double? = null,
    /** `position.timestamp`. Diagnostic only: a 2026 Tesla browser reports a constant that is not epoch time. */
    val time: Long? = null,
)

/**
 * The car's position for the iPhone, as iAP2 LocationInformation (`$GPGGA` + `$GPRMC`), taken from the page in the car
 * browser (docs/LOCATION.md). Off unless the owner switched it on in the page's settings.
 *
 * What the Tesla browser gives (docs/LOCATION.md §2): the car's own position with speed, heading and altitude, an
 * accuracy of 9999.99 meaning "not reported", and a `position.timestamp` that is not epoch time and does not advance
 * (Model 3 Highland, Chromium 148, 2026-08). So the box keeps time itself, and a fix is new only when its position
 * is: the same position again is the browser's cached answer, or a browser that stopped updating (it froze while ABRP
 * navigated, 2023-2024 reports) and must not be passed off as "still here" while the car drives on. Standing at a
 * light, the iPhone therefore hears nothing after [staleMillis] and uses its own fix until the car moves. A fix that
 * jumps further than a car can go is held until a second one agrees.
 *
 * Each new fix goes to the iPhone once, stamped with the moment the box received it. When no new fix has come for
 * [staleMillis] (page hidden or closed, browser frozen, no fix) nothing is sent: a GNSS receiver without a fix says
 * nothing either, and the iPhone carries on with its own GNSS and motion sensors.
 */
class CarLocation(
    enabled: Boolean,
    datum: Datum = Datum.WGS84,
    private val staleMillis: Long = STALE_MILLIS,
    private val monotonicMillis: () -> Long = { System.nanoTime() / 1_000_000 },
    private val wallMillis: () -> Long = System::currentTimeMillis,
    private val log: (String) -> Unit = {},
) : Iap2LocationProvider {
    enum class Update { ACCEPTED, REPEATED, JUMPED, REJECTED, OFF }

    /** What the browser's coordinates are in. The iPhone takes GNSS coordinates, WGS-84, everywhere. */
    enum class Datum(val id: String) {
        WGS84("wgs84"),
        /** China's GCJ-02, as Chinese maps use; converted back to WGS-84 inside China. */
        GCJ02("gcj02");

        companion object { fun of(id: String?): Datum = entries.firstOrNull { it.id == id?.lowercase() } ?: WGS84 }
    }

    private class Received(val seq: Long, val fix: CarPlayLocationFix, val lat: Double, val lon: Double, val at: Long)
    private class Point(val lat: Double, val lon: Double, val at: Long)

    private val lock = Any()
    @Volatile var enabled: Boolean = enabled
        private set
    @Volatile var datum: Datum = datum
    /** The iPhone asked for location on the current link (0xFFFA) and has not stopped it (0xFFFC). */
    @Volatile var requested: Boolean = false
        private set
    private var latest: Received? = null
    private var jumpedTo: Point? = null
    private var seq = 0L
    private var sentSeq = 0L
    private var windowStart = -1L
    private val counts = IntArray(Update.entries.size)
    private var sent = 0
    private var withSpeed = 0
    private var lastAccuracy: Double? = null

    /** Switched by the owner. Off drops the last fix at once, so nothing more is sent on the running link. */
    fun setSwitch(value: Boolean) = synchronized(lock) {
        enabled = value
        if (!value) {
            latest = null
            jumpedTo = null
        }
    }

    fun update(message: LocationMessage): Update = synchronized(lock) {
        val result = accept(message)
        counts[result.ordinal]++
        summarize()
        result
    }

    /** Milliseconds since the newest fix arrived, or null without one. */
    fun lastFixAgeMillis(): Long? = synchronized(lock) { latest?.let { monotonicMillis() - it.at } }

    override fun onRequested(components: Set<Int>) {
        log("car location: the iPhone asked for sentence types $components")
    }

    override fun start(): Boolean {
        requested = true
        log("car location: the iPhone started location updates (switch ${if (enabled) "on" else "off"}, datum ${datum.id})")
        return enabled
    }

    override fun stop() {
        if (requested) log("car location: the iPhone stopped location updates")
        requested = false
    }

    override fun latestNmea(): String? = synchronized(lock) {
        val fix = latest ?: return null
        if (!enabled || !requested || fix.seq == sentSeq) return null
        if (monotonicMillis() - fix.at > staleMillis) return null
        sentSeq = fix.seq
        sent++
        NmeaLocationEncoder.encode(fix.fix)
    }

    private fun accept(message: LocationMessage): Update {
        if (!enabled) return Update.OFF
        val (lat, lon) = message.lat to message.lon
        if (!lat.isFinite() || !lon.isFinite() || lat !in -90.0..90.0 || lon !in -180.0..180.0) return Update.REJECTED
        if (lat == 0.0 && lon == 0.0) return Update.REJECTED
        val accuracy = message.acc?.takeIf { it.isFinite() && it > 0 && it < ACCURACY_NOT_REPORTED }
        if (accuracy != null && accuracy > MAX_ACCURACY_METERS) return Update.REJECTED
        val speed = message.speed?.takeIf { it.isFinite() && it >= 0 }
        val now = monotonicMillis()
        val previous = latest?.takeIf { now - it.at <= CONTINUITY_MILLIS }
        if (previous != null && previous.lat == lat && previous.lon == lon) return Update.REPEATED
        if (previous != null) {
            val allowed = MAX_SPEED_METERS_PER_SECOND * (now - previous.at) / 1000.0 + JUMP_SLACK_METERS
            if (meters(previous.lat, previous.lon, lat, lon) > allowed) {
                val agreed = jumpedTo?.let {
                    meters(it.lat, it.lon, lat, lon) <= MAX_SPEED_METERS_PER_SECOND * (now - it.at) / 1000.0 + JUMP_SLACK_METERS
                } == true
                if (!agreed) {
                    jumpedTo = Point(lat, lon, now)
                    return Update.JUMPED
                }
            }
        }
        jumpedTo = null
        val (wgsLat, wgsLon) = if (datum == Datum.GCJ02) ChinaDatum.toWgs84(lat, lon) else lat to lon
        val fix = CarPlayLocationFix(
            latitudeDegrees = wgsLat,
            longitudeDegrees = wgsLon,
            altitudeMeters = message.alt?.takeIf { it.isFinite() },
            // A browser reports no heading (NaN) when standing still.
            bearingDegrees = message.heading?.takeIf { it.isFinite() && it >= 0 },
            speedMetersPerSecond = speed,
            accuracyMeters = accuracy,
            timestampMillis = wallMillis(),
        )
        latest = Received(++seq, fix, lat, lon, now)
        lastAccuracy = accuracy
        if (speed != null) withSpeed++
        return Update.ACCEPTED
    }

    /** One line a minute while fixes come: how many arrived as new, repeated, jumped, dropped, and reached the iPhone. */
    private fun summarize() {
        val now = monotonicMillis()
        if (windowStart < 0) windowStart = now
        if (now - windowStart < SUMMARY_MILLIS) return
        log(
            "car location: last ${(now - windowStart) / 1000} s new=${counts[Update.ACCEPTED.ordinal]} " +
                "repeated=${counts[Update.REPEATED.ordinal]} jumped=${counts[Update.JUMPED.ordinal]} " +
                "dropped=${counts[Update.REJECTED.ordinal]} off=${counts[Update.OFF.ordinal]} sent=$sent " +
                "withSpeed=$withSpeed requested=$requested datum=${datum.id} " +
                "accuracy=${lastAccuracy?.let { String.format(Locale.ROOT, "%.0f m", it) } ?: "not reported"}",
        )
        windowStart = now
        counts.fill(0)
        sent = 0
        withSpeed = 0
    }

    companion object {
        /** A fix older than this is not sent: the page reads once a second. */
        const val STALE_MILLIS = 2_500L
        /** Tesla's "accuracy not reported" (9999.99). */
        const val ACCURACY_NOT_REPORTED = 9_999.0
        /** A real accuracy worse than this is a network guess, not a satellite fix. */
        const val MAX_ACCURACY_METERS = 100.0
        /** 250 km/h, plus slack for the browser's own corrections: anything further is a jump. */
        const val MAX_SPEED_METERS_PER_SECOND = 70.0
        const val JUMP_SLACK_METERS = 100.0
        /** After this long without a fix (page hidden, a garage) the next one starts afresh, whatever the distance. */
        const val CONTINUITY_MILLIS = 30_000L
        const val SUMMARY_MILLIS = 60_000L

        /** Great-circle distance in metres (haversine; a few cm off at these distances). */
        fun meters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
            val p1 = lat1 * PI / 180
            val p2 = lat2 * PI / 180
            val dp = p2 - p1
            val dl = (lon2 - lon1) * PI / 180
            val h = sin(dp / 2) * sin(dp / 2) + cos(p1) * cos(p2) * sin(dl / 2) * sin(dl / 2)
            return 2 * 6_371_008.8 * atan2(sqrt(h), sqrt(1 - h))
        }
    }
}

/**
 * China's GCJ-02 datum: WGS-84 plus a published, deterministic offset of a few hundred metres inside mainland China.
 * [toGcj02] is the usual formula; it gives Tesla's own "native" GCJ-02 for a Shenzhen car to about a metre
 * (teslamotors/fleet-telemetry #392). [toWgs84] inverts it by iteration (to well under a centimetre).
 */
object ChinaDatum {
    private const val A = 6_378_245.0
    private const val EE = 0.00669342162296594323

    fun inChina(lat: Double, lon: Double): Boolean = lon in 72.004..137.8347 && lat in 0.8293..55.8271

    fun toGcj02(lat: Double, lon: Double): Pair<Double, Double> {
        if (!inChina(lat, lon)) return lat to lon
        var dLat = latitudeOffset(lon - 105.0, lat - 35.0)
        var dLon = longitudeOffset(lon - 105.0, lat - 35.0)
        val radLat = lat / 180.0 * PI
        val magic = 1 - EE * sin(radLat) * sin(radLat)
        val sqrtMagic = sqrt(magic)
        dLat = dLat * 180.0 / (A * (1 - EE) / (magic * sqrtMagic) * PI)
        dLon = dLon * 180.0 / (A / sqrtMagic * cos(radLat) * PI)
        return (lat + dLat) to (lon + dLon)
    }

    fun toWgs84(lat: Double, lon: Double): Pair<Double, Double> {
        if (!inChina(lat, lon)) return lat to lon
        var wLat = lat
        var wLon = lon
        repeat(30) {
            val (gLat, gLon) = toGcj02(wLat, wLon)
            val eLat = gLat - lat
            val eLon = gLon - lon
            wLat -= eLat
            wLon -= eLon
            if (abs(eLat) < 1e-10 && abs(eLon) < 1e-10) return wLat to wLon
        }
        return wLat to wLon
    }

    private fun latitudeOffset(x: Double, y: Double): Double {
        var r = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * sqrt(abs(x))
        r += (20.0 * sin(6.0 * x * PI) + 20.0 * sin(2.0 * x * PI)) * 2.0 / 3.0
        r += (20.0 * sin(y * PI) + 40.0 * sin(y / 3.0 * PI)) * 2.0 / 3.0
        r += (160.0 * sin(y / 12.0 * PI) + 320.0 * sin(y * PI / 30.0)) * 2.0 / 3.0
        return r
    }

    private fun longitudeOffset(x: Double, y: Double): Double {
        var r = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * sqrt(abs(x))
        r += (20.0 * sin(6.0 * x * PI) + 20.0 * sin(2.0 * x * PI)) * 2.0 / 3.0
        r += (20.0 * sin(x * PI) + 40.0 * sin(x / 3.0 * PI)) * 2.0 / 3.0
        r += (150.0 * sin(x / 12.0 * PI) + 300.0 * sin(x / 30.0 * PI)) * 2.0 / 3.0
        return r
    }
}

package com.playport.server

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CarLocationTest {
    private var monotonic = 1_000_000L
    private var wall = Instant.parse("2026-11-05T03:04:05.678Z").toEpochMilli()
    private fun advance(millis: Long) { monotonic += millis; wall += millis }

    private fun location(enabled: Boolean = true, datum: CarLocation.Datum = CarLocation.Datum.WGS84) =
        CarLocation(enabled, datum, monotonicMillis = { monotonic }, wallMillis = { wall })

    /** Shenzhen Civic Center, a public landmark, in WGS-84. */
    private val shenzhenWgs = 22.5431 to 114.0579

    private fun fix(
        lat: Double = shenzhenWgs.first,
        lon: Double = shenzhenWgs.second,
        acc: Double? = 9999.99,
        speed: Double? = 12.5,
        heading: Double? = 90.0,
        alt: Double? = 51.35,
    ) = LocationMessage(lat, lon, acc, alt, speed, heading, time = 4_242_424L)   // a constant that is not epoch time, as a 2026 Tesla browser reports

    @Test fun offTakesNothingAndSendsNothing() {
        val car = location(enabled = false)
        car.start()
        assertEquals(CarLocation.Update.OFF, car.update(fix()))
        assertNull(car.latestNmea())
    }

    @Test fun eachNewFixGoesOnceAndOnlyAfterTheIphoneAsked() {
        val car = location()
        assertEquals(CarLocation.Update.ACCEPTED, car.update(fix()))
        assertNull(car.latestNmea())                        // not requested yet
        car.start()
        val sentences = car.latestNmea()
        assertNotNull(sentences)
        assertTrue(sentences!!.startsWith("\$GPGGA,030405.67,2232.5860,N,11403.4740,E,1,08,1.0,51.4,M,0.0,M,,*"))
        assertTrue(sentences.contains("\$GPRMC,030405.67,A,2232.5860,N,11403.4740,E,24.30,90.00,051126,,*"))
        assertNull(car.latestNmea())                        // the same fix is not repeated
        car.stop()
        advance(1_000)
        car.update(fix(lat = shenzhenWgs.first + 0.0001))
        assertNull(car.latestNmea())                        // stopped by the iPhone
    }

    @Test fun aStaleFixIsNotSent() {
        val car = location().apply { start() }
        car.update(fix())
        advance(CarLocation.STALE_MILLIS + 1)
        assertNull(car.latestNmea())
    }

    @Test fun theSamePositionAgainIsNotNew() {
        val car = location().apply { start() }
        car.update(fix())
        assertNotNull(car.latestNmea())
        advance(1_000)
        assertEquals(CarLocation.Update.REPEATED, car.update(fix()))
        assertEquals(CarLocation.Update.REPEATED, car.update(fix(speed = 0.0)))
        assertNull(car.latestNmea())
        advance(2_000)
        assertNull(car.latestNmea())                        // a frozen browser goes stale
    }

    @Test fun teslasPlaceholderAccuracyIsUnknownNotTenKilometres() {
        val car = location().apply { start() }
        assertEquals(CarLocation.Update.ACCEPTED, car.update(fix(acc = 9999.99)))
        assertTrue(car.latestNmea()!!.contains(",1,08,1.0,"))
    }

    @Test fun aRealAccuracyGivesTheHdopAndAPoorOneIsDropped() {
        val car = location().apply { start() }
        car.update(fix(acc = 4.5))
        assertTrue(car.latestNmea()!!.contains(",1,08,0.9,"))
        advance(1_000)
        assertEquals(CarLocation.Update.REJECTED, car.update(fix(lat = shenzhenWgs.first + 0.0001, acc = 500.0)))
    }

    @Test fun unknownAltitudeAndHeadingStayEmpty() {
        val car = location().apply { start() }
        car.update(fix(alt = null, heading = null, speed = null))
        val sentences = car.latestNmea()!!
        assertTrue(sentences, sentences.contains(",1,08,1.0,,M,0.0,M,,*"))
        assertTrue(sentences, sentences.contains(",E,0.00,,051126,,*"))
    }

    @Test fun theBoxKeepsTimeNotTheBrowsersBrokenTimestamp() {
        val car = location().apply { start() }
        car.update(fix())
        assertTrue(car.latestNmea()!!.contains("\$GPRMC,030405.67,A,"))
        advance(1_230)
        car.update(fix(lat = shenzhenWgs.first + 0.0001))
        assertTrue(car.latestNmea()!!.contains("\$GPRMC,030406.90,A,"))
    }

    @Test fun aJumpIsHeldUntilASecondFixAgrees() {
        val car = location().apply { start() }
        car.update(fix())
        car.latestNmea()
        advance(1_000)
        assertEquals(CarLocation.Update.JUMPED, car.update(fix(lat = shenzhenWgs.first + 0.05)))   // 5.5 km in 1 s
        assertNull(car.latestNmea())
        advance(1_000)
        assertEquals(CarLocation.Update.ACCEPTED, car.update(fix(lat = shenzhenWgs.first + 0.0502)))
        assertNotNull(car.latestNmea())
    }

    @Test fun backOnTrackAfterAJumpIsTaken() {
        val car = location().apply { start() }
        car.update(fix())
        advance(1_000)
        assertEquals(CarLocation.Update.JUMPED, car.update(fix(lat = 23.0)))
        advance(1_000)
        assertEquals(CarLocation.Update.ACCEPTED, car.update(fix(lat = shenzhenWgs.first + 0.0003)))
    }

    @Test fun afterALongGapAnyDistanceStartsAfresh() {
        val car = location().apply { start() }
        car.update(fix())
        advance(CarLocation.CONTINUITY_MILLIS + 1)
        assertEquals(CarLocation.Update.ACCEPTED, car.update(fix(lat = shenzhenWgs.first + 0.05)))
    }

    @Test fun badCoordinatesAreDropped() {
        val car = location()
        assertEquals(CarLocation.Update.REJECTED, car.update(fix(lat = 0.0, lon = 0.0)))
        assertEquals(CarLocation.Update.REJECTED, car.update(fix(lat = 91.0)))
        assertEquals(CarLocation.Update.REJECTED, car.update(fix(lon = Double.NaN)))
    }

    @Test fun switchingOffStopsTheRunningLinkAtOnce() {
        val car = location().apply { start() }
        car.update(fix())
        car.setSwitch(false)
        assertNull(car.latestNmea())
        assertEquals(false, car.start())
    }

    /** The position the iPhone is given, read back from the $GPGGA sentence. */
    private fun sent(car: CarLocation): Pair<Double, Double> {
        val fields = car.latestNmea()!!.lineSequence().first().split(',')
        return (fields[2].take(2).toDouble() + fields[2].drop(2).toDouble() / 60) to
            (fields[4].take(3).toDouble() + fields[4].drop(3).toDouble() / 60)
    }

    @Test fun autoConvertsOnlyWhereTheBrowserSaysMainlandChina() {
        // A China-market Model 3 (2026-11-10): its browser's position was GCJ-02. The time zone tells the mainland
        // from Hong Kong, 30 km from Shenzhen and inside the same rectangle, whose cars give WGS-84.
        val (gLat, gLon) = ChinaDatum.toGcj02(shenzhenWgs.first, shenzhenWgs.second)
        val mainland = location(datum = CarLocation.Datum.AUTO).apply { start() }
        mainland.update(fix(lat = gLat, lon = gLon).copy(zone = "Asia/Shanghai"))
        val (lat, lon) = sent(mainland)
        assertTrue("$lat,$lon", CarLocation.meters(lat, lon, shenzhenWgs.first, shenzhenWgs.second) < 0.5)

        for (zone in listOf("Asia/Hong_Kong", "Asia/Macau", "Asia/Taipei", "Asia/Seoul", "UTC", "", null)) {
            val elsewhere = location(datum = CarLocation.Datum.AUTO).apply { start() }
            elsewhere.update(fix(lat = 22.3193, lon = 114.1694).copy(zone = zone))
            val (hkLat, hkLon) = sent(elsewhere)
            assertTrue("zone $zone moved the position", CarLocation.meters(hkLat, hkLon, 22.3193, 114.1694) < 0.5)
        }
        // A mainland time zone far from China (a car that kept its zone abroad): the rectangle still decides.
        val abroad = location(datum = CarLocation.Datum.AUTO).apply { start() }
        abroad.update(fix(lat = -33.8688, lon = 151.2093).copy(zone = "Asia/Shanghai"))
        val (sLat, sLon) = sent(abroad)
        assertTrue(CarLocation.meters(sLat, sLon, -33.8688, 151.2093) < 0.5)
    }

    @Test fun anExplicitDatumIgnoresTheTimeZone() {
        val (gLat, gLon) = ChinaDatum.toGcj02(shenzhenWgs.first, shenzhenWgs.second)
        val wgs = location(datum = CarLocation.Datum.WGS84).apply { start() }
        wgs.update(fix(lat = gLat, lon = gLon).copy(zone = "Asia/Shanghai"))
        val (lat, lon) = sent(wgs)
        assertTrue(CarLocation.meters(lat, lon, gLat, gLon) < 0.5)
        val gcj = location(datum = CarLocation.Datum.GCJ02).apply { start() }
        gcj.update(fix(lat = gLat, lon = gLon).copy(zone = "Asia/Hong_Kong"))
        val (cLat, cLon) = sent(gcj)
        assertTrue(CarLocation.meters(cLat, cLon, shenzhenWgs.first, shenzhenWgs.second) < 0.5)
    }

    @Test fun mainlandZonesAreChinasOwn() {
        for (zone in listOf("Asia/Shanghai", "Asia/Urumqi", "asia/chongqing", " Asia/Harbin ", "PRC")) assertTrue(zone, ChinaDatum.mainlandZone(zone))
        for (zone in listOf("Asia/Hong_Kong", "Asia/Macau", "Asia/Taipei", "Asia/Tokyo", "Etc/UTC", "UTC", "", null)) {
            assertEquals(zone, false, ChinaDatum.mainlandZone(zone))
        }
    }

    @Test fun gcj02CoordinatesGoToTheIphoneAsWgs84() {
        val car = location(datum = CarLocation.Datum.GCJ02).apply { start() }
        val (gLat, gLon) = ChinaDatum.toGcj02(shenzhenWgs.first, shenzhenWgs.second)
        car.update(fix(lat = gLat, lon = gLon))
        // The browser's GCJ-02 goes out as the WGS-84 position again (to the 0.0001' an NMEA field holds, ~0.2 m).
        val gga = car.latestNmea()!!.lineSequence().first()
        val fields = gga.split(',')
        val lat = fields[2].take(2).toDouble() + fields[2].drop(2).toDouble() / 60
        val lon = fields[4].take(3).toDouble() + fields[4].drop(3).toDouble() / 60
        assertTrue("$lat,$lon", CarLocation.meters(lat, lon, shenzhenWgs.first, shenzhenWgs.second) < 0.5)
    }

    @Test fun chinaDatumShiftsByHundredsOfMetresAndInvertsCleanly() {
        // In Shenzhen GCJ-02 lies ~600 m south-east of WGS-84 (it matched a Tesla's own GCJ-02 for a car there to
        // about a metre, teslamotors/fleet-telemetry #392, checked while researching docs/LOCATION.md).
        val (gLat, gLon) = ChinaDatum.toGcj02(shenzhenWgs.first, shenzhenWgs.second)
        assertTrue(CarLocation.meters(shenzhenWgs.first, shenzhenWgs.second, gLat, gLon) in 400.0..800.0)
        assertTrue(gLat < shenzhenWgs.first && gLon > shenzhenWgs.second)
        val (wLat, wLon) = ChinaDatum.toWgs84(gLat, gLon)
        assertTrue(CarLocation.meters(wLat, wLon, shenzhenWgs.first, shenzhenWgs.second) < 0.01)
        // Outside mainland China nothing moves.
        assertEquals(-33.8688 to 151.2093, ChinaDatum.toGcj02(-33.8688, 151.2093))
        assertEquals(-33.8688 to 151.2093, ChinaDatum.toWgs84(-33.8688, 151.2093))
    }

    @Test fun datumIdsReadBack() {
        assertEquals(CarLocation.Datum.GCJ02, CarLocation.Datum.of("GCJ02"))
        assertEquals(CarLocation.Datum.WGS84, CarLocation.Datum.of("wgs84"))
        assertEquals(CarLocation.Datum.AUTO, CarLocation.Datum.of("bd09"))
        assertEquals(CarLocation.Datum.AUTO, CarLocation.Datum.of(null))
    }
}

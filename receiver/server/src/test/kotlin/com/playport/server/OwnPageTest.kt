package com.playport.server

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Only the box's own page may take the viewer token or open the viewer channel (audit 2026-10-13, A2). */
class OwnPageTest {
    @Test fun thePageOfThisBoxIsAccepted() {
        assertTrue(WebHub.ownPage("https://192.168.77.1:18443", "192.168.77.1:18443", "same-origin"))
        assertTrue(WebHub.ownPage("https://dashplay.lan:18443", "DashPlay.lan:18443", null))
        assertTrue(WebHub.ownPage(null, "192.168.77.1:18443", "same-origin"))   // a same-origin GET carries no Origin
        assertTrue(WebHub.ownPage(null, "192.168.77.1:18443", null))            // not a browser: the token still applies
        assertTrue(WebHub.ownPage(null, null, "none"))                          // typed into the address bar
        // HTTP/2 has no Host header: the address comes from the connection point (403 on a phone, 2026-10-13).
        assertTrue(WebHub.ownPage("https://mycar.duckdns.org:18443", "mycar.duckdns.org:18443", "same-origin"))
        assertTrue(WebHub.ownPage("https://dashplay.lan", "dashplay.lan:443", null))   // the default port left out
    }

    /** 1.6.8: port 443 of the box leads to this server, so the Tesla opens https://name/ (the owner, 2026-11-16). */
    @Test fun thePageOpenedWithoutAPortIsAccepted() {
        // HTTP/1.1: `Host: car.example.com`, for which Ktor names the scheme's port
        assertTrue(WebHub.ownPage("https://car.example.com", "car.example.com:443", "same-origin", 17989))
        // HTTP/2: `:authority: car.example.com`, for which Ktor 3.6 names the port the server listens on
        assertTrue(WebHub.ownPage("https://car.example.com", "car.example.com:17989", "same-origin", 17989))
        assertTrue(WebHub.ownPage("https://car.example.com", "CAR.example.com:17989", null, 17989))
        assertTrue(WebHub.ownPage("https://car.example.com:443", "car.example.com:17989", null, 17989))
        // the port itself, and the one of 1.6.7 and before (led here as well), as ever
        assertTrue(WebHub.ownPage("https://car.example.com:17989", "car.example.com:17989", "same-origin", 17989))
        assertTrue(WebHub.ownPage("https://car.example.com:18443", "car.example.com:18443", "same-origin", 17989))
    }

    @Test fun withoutAPortOnlyThisHostOverHttpsOnItsOwnPort() {
        assertFalse(WebHub.ownPage("https://evil.example", "car.example.com:17989", null, 17989))          // another host
        assertFalse(WebHub.ownPage("https://car.example.com", "car.example.com:17989", "cross-site", 17989))
        assertFalse(WebHub.ownPage("https://car.example.com", "car.example.com:17989", "same-site", 17989))
        assertFalse(WebHub.ownPage("http://car.example.com", "car.example.com:17989", null, 17989))        // plain HTTP (LuCI's port 80)
        assertFalse(WebHub.ownPage("http://car.example.com:443", "car.example.com:17989", null, 17989))
        assertFalse(WebHub.ownPage("https://car.example.com:8443", "car.example.com:17989", null, 17989))   // another port
        assertFalse(WebHub.ownPage("https://car.example.com", "car.example.com:18080", null, 17989))       // not this server's port
        assertFalse(WebHub.ownPage("https://car.example.com", "car.example.com:17989", null))              // the port not known
    }

    @Test fun anotherSiteIsRefused() {
        // An external page could load the token and open the channel: 200 and 101 on the F50, 2026-10-12.
        assertFalse(WebHub.ownPage("https://evil.example", "192.168.77.1:18443", "cross-site"))
        assertFalse(WebHub.ownPage("https://evil.example", "192.168.77.1:18443", null))
        assertFalse(WebHub.ownPage(null, "192.168.77.1:18443", "cross-site"))   // <script src> of another site
        assertFalse(WebHub.ownPage(null, "192.168.77.1:18443", "same-site"))
        assertFalse(WebHub.ownPage("https://192.168.77.1:8443", "192.168.77.1:18443", null))   // another port
        assertFalse(WebHub.ownPage("null", "192.168.77.1:18443", null))         // sandboxed or file page
    }
}

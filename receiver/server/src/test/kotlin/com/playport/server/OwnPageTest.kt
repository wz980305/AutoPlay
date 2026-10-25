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

package com.playport.server

/**
 * One invitation for the owner of a wireless CarPlay session that ended by itself (1.4.1, after DashPlay 2026.11.04
 * `playport-wireless-session-recovery`, GPL-3.0).
 *
 * Normally the box invites a phone only once it sees it on its Wi-Fi again. But when the link drops (interference,
 * the car moving out of range of a weak spot) the iPhone often leaves the box's Wi-Fi and does not come back by itself:
 * it rejoins when CarPlay invites it over Bluetooth. So for [WINDOW_MS] after a live session ends on its own, its owner
 * may be invited once without that proof. Exactly once: an invitation that fails does not renew it, and anything the
 * box or the owner does on purpose (idle release, a display or location change, shutting down) cancels it.
 */
internal class WirelessSessionRecovery(private val windowMs: Long = WINDOW_MS) {
    private var owner: String? = null
    private var pending: String? = null
    private var expires = 0L

    /** A session went live; [phone] owns it. */
    @Synchronized fun active(phone: String?) {
        cancel()
        owner = phone
    }

    /** The live session ended by itself at [now]: its owner gets one invitation until now + window. */
    @Synchronized fun ended(now: Long) {
        val phone = owner ?: return
        owner = null
        pending = phone
        expires = now + windowMs
    }

    /** Who may be invited now, if anyone. */
    @Synchronized fun candidate(now: Long): String? {
        if (now >= expires) pending = null
        return pending
    }

    /** Uses up the invitation for [phone]; false if it is not that phone's or has expired. */
    @Synchronized fun take(now: Long, phone: String): Boolean {
        if (candidate(now) != phone) return false
        pending = null
        return true
    }

    @Synchronized fun cancel() {
        owner = null
        pending = null
        expires = 0L
    }

    companion object {
        const val WINDOW_MS = 45_000L
    }
}

package com.playport.server

/**
 * Keeps a viewer's picture at most [targetNs] behind. The box marks the stream every 200 ms with the bytes
 * queued so far and the page answers each mark at once, so the box knows what reached the page and how fast
 * the page takes it in, through every buffer on the way (send queue, Ktor, Netty, TLS, kernel, Wi-Fi). A
 * picture frame goes out only while what is still on its way would arrive within [targetNs]; otherwise it is
 * dropped and the picture restarts at a keyframe. Sound and control messages always go out.
 *
 * Measured at home on 2026-10-12 with a page reading at 4 Mbit/s against about 9 Mbit/s of picture: without
 * this it fell 11 s behind in 20 s and stayed there (nothing was dropped, the backlog sat below the send queue);
 * pausing only once a mark came back late still let it reach 2.7 s. A page that never answers (an older one)
 * is never held back.
 *
 * Over that estimate, a page that answers its marks at once (within [promptNs]) still gets the picture: a still
 * screen sends little, so the intake measured is low, and a page swipe's burst went over it. On a 2026-10-12
 * drive 64 of 66 drops came while the page was 47 ms behind, each a frozen picture and a keyframe.
 */
internal class LagGate(private val targetNs: Long, private val floorBytes: Long, private val promptNs: Long = targetNs / 2) {
    private class Mark(val id: Long, val atNs: Long, val queuedBytes: Long)
    private val pending = ArrayDeque<Mark>()
    private var deliveredBytes = -1L
    private var deliveredAtNs = 0L
    /** How long the page took to answer its latest mark. */
    private var answerNs = Long.MAX_VALUE
    /** Recent intake samples (at, bytes per ns); the best of the last two seconds, as a page that is sent
     *  little (picture paused) takes in little without being slow. */
    private val rates = ArrayDeque<Pair<Long, Double>>()

    @Synchronized fun marked(id: Long, nowNs: Long, queuedBytes: Long) {
        pending.addLast(Mark(id, nowNs, queuedBytes))
        if (pending.size > 64) pending.removeFirst()
    }

    @Synchronized fun acked(id: Long, nowNs: Long) {
        while (pending.isNotEmpty() && pending.first().id <= id) {
            val mark = pending.removeFirst()
            if (mark.id != id) continue
            if (deliveredBytes >= 0 && nowNs > deliveredAtNs) {
                rates.addLast(nowNs to (mark.queuedBytes - deliveredBytes).toDouble() / (nowNs - deliveredAtNs))
            }
            deliveredBytes = mark.queuedBytes
            deliveredAtNs = nowNs
            answerNs = nowNs - mark.atNs
        }
        while (rates.isNotEmpty() && nowNs - rates.first().first > 2_000_000_000L) rates.removeFirst()
    }

    /** Whether a picture frame may join [queuedBytes] already queued for this page. */
    @Synchronized fun open(nowNs: Long, queuedBytes: Long): Boolean {
        if (deliveredBytes < 0) return true
        val rate = rates.maxOfOrNull { it.second } ?: 0.0
        val window = maxOf(floorBytes, (rate * targetNs).toLong())
        if (queuedBytes - deliveredBytes < window) return true
        val outstanding = pending.firstOrNull()?.let { nowNs - it.atNs } ?: 0L
        return answerNs < promptNs && outstanding < promptNs
    }
}

package com.playport.server

import com.shilapi.xcertplay.airplay.CarPlayUiScale

/**
 * Live display configuration advertised to the phone in AirPlay /info.
 *
 * Portrait orientation is simply `height > width`. [uiScale] maps to [CarPlayUiScale]: a larger
 * canvas requests proportionally smaller CarPlay controls.
 */
/** One view area: a width x height rectangle at the stream's top left (a browser window's shape). */
@kotlinx.serialization.Serializable
data class ViewArea(val width: Int, val height: Int)

class DisplayState(width: Int, height: Int, fps: Int, uiScale: Int, hevc: Boolean = false,
                   areas: List<ViewArea> = emptyList(), area: Int = 0) {
    @Volatile var width: Int = width
        private set
    @Volatile var height: Int = height
        private set
    @Volatile var fps: Int = fps
        private set
    @Volatile var uiScale: Int = uiScale
        private set
    @Volatile var hevc: Boolean = hevc
        private set
    /** The view areas declared to the phone (none: the whole stream), and the one in use. */
    @Volatile var areas: List<ViewArea> = areas
        private set
    @Volatile var area: Int = area.coerceIn(0, maxOf(0, areas.lastIndex))
        private set

    fun update(width: Int, height: Int, fps: Int, uiScale: Int, hevc: Boolean, areas: List<ViewArea> = emptyList(), area: Int = 0) {
        pending = null
        this.width = width
        this.height = height
        this.fps = fps
        this.uiScale = CarPlayUiScale.sanitize(uiScale)
        this.hevc = hevc
        this.areas = areas
        this.area = area.coerceIn(0, maxOf(0, areas.lastIndex))
    }

    /** Whether [width]..[areas] are what the phone was told: then only the area in use may differ. */
    fun sameStream(width: Int, height: Int, fps: Int, uiScale: Int, hevc: Boolean, areas: List<ViewArea>): Boolean =
        width == this.width && height == this.height && fps == this.fps && CarPlayUiScale.sanitize(uiScale) == this.uiScale &&
            hevc == this.hevc && areas == this.areas

    fun useArea(index: Int) { area = index.coerceIn(0, maxOf(0, areas.lastIndex)) }

    /**
     * A change that can wait ([DisplayRequest.defer]: a sharper picture or another codec for the same window shapes),
     * kept while a session runs: renegotiating cut the picture for 5-10 s, so it is taken up when the session ends by
     * itself (2026-10-21; a Tesla's page asked for four such restarts within ten minutes, 2026-10-16). A change that
     * cannot wait replaces it.
     */
    @Volatile var pending: DisplayRequest? = null
        private set

    fun defer(request: DisplayRequest) { pending = request }

    /** Takes up the pending change, if any; true when the display changed. */
    fun applyPending(): Boolean {
        val next = pending ?: return false
        pending = null
        val areas = next.areas.takeIf { it.size > 1 } ?: emptyList()
        if (validate(next.width, next.height, next.fps) != null || validateAreas(next.width, next.height, areas, next.area) != null) return false
        update(next.width, next.height, next.fps, next.uiScale, next.hevc, areas, next.area)
        return true
    }

    /**
     * CarPlay sizes its icons by pixels per millimetre. With areas the stream is wider than the window shape it mostly
     * shows, and at the plain 200 mm the windowed area looked crowded (Tesla, 2026-10-14): the narrowest area keeps the
     * plain density, 200 mm per its width. null (the plain 200 mm) without areas.
     */
    fun physicalWidthMm(): Int? = areas.takeIf { it.size > 1 }?.minOf { it.width }?.let {
        com.shilapi.xcertplay.airplay.AirPlayDisplaySettings.DEFAULT_WIDTH_PHYSICAL_MM * width / it
    }

    val orientation: String get() = if (height > width) "portrait" else "landscape"

    data class Preset(val label: String, val width: Int, val height: Int, val orientation: String)

    companion object {
        const val MIN_EDGE = 480
        const val MAX_EDGE = 3840

        /** As many as the page declares (display-fit.ts MAX_AREAS; 4 until 2026-10-21). */
        const val MAX_AREAS = 8

        fun validateAreas(width: Int, height: Int, areas: List<ViewArea>, area: Int): String? = when {
            areas.size > MAX_AREAS -> "at most $MAX_AREAS view areas"
            areas.any { it.width !in 2..width || it.height !in 2..height || it.width % 2 != 0 || it.height % 2 != 0 } ->
                "each view area must be even and fit the stream"
            areas.isNotEmpty() && area !in areas.indices -> "no such view area"
            else -> null
        }

        fun validate(width: Int, height: Int, fps: Int): String? = when {
            width !in MIN_EDGE..MAX_EDGE || height !in MIN_EDGE..MAX_EDGE ->
                "width and height must be between $MIN_EDGE and $MAX_EDGE"
            width % 2 != 0 || height % 2 != 0 -> "width and height must be even"
            fps !in 24..60 -> "fps must be between 24 and 60"
            else -> null
        }

        /** Landscape and portrait presets offered in the web UI. */
        val PRESETS = listOf(
            Preset("1280 x 720", 1280, 720, "landscape"),
            Preset("1920 x 720", 1920, 720, "landscape"),
            Preset("1920 x 1080", 1920, 1080, "landscape"),
            Preset("2560 x 1440", 2560, 1440, "landscape"),
            Preset("3840 x 2160", 3840, 2160, "landscape"),
            Preset("800 x 480", 800, 480, "landscape"),
            Preset("720 x 1280", 720, 1280, "portrait"),
            Preset("1080 x 1920", 1080, 1920, "portrait"),
        )
    }
}

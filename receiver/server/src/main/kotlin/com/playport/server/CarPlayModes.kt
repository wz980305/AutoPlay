package com.playport.server

/**
 * What the iPhone says in a `modesChanged` command besides who holds the screen and the main audio: its three
 * app states, a phone call, Siri (speech) and turn-by-turn navigation (owner's 2026-11-22 drive: after a call the
 * Tesla played nothing while CarPlay showed Apple Music playing, and the record could not say when the call
 * ended). appStateID 1 is speech, 2 the call, 3 navigation, as the receiver declares them in its own modes
 * (`AirPlayInfoPlist.modes`); entity 1 is the iPhone, 2 the accessory, 0 nobody, as for the resources.
 *
 * The line keeps the numbers as they came as well, so a reading of the names that is wrong cannot hide anything:
 * `CarPlay app states: call=iPhone speech=none navigation=iPhone [appStateID=2,entity=1, ...]`. Null when the
 * command has no app states.
 */
object CarPlayModes {
    private val NAMES = mapOf(1L to "speech", 2L to "call", 3L to "navigation")
    private val KEYS = listOf("appStateID", "entity", "speechMode", "state")

    fun appStates(params: Map<String, Any?>): String? {
        val states = (params["appStates"] as? List<*>)?.take(8)?.mapNotNull { it as? Map<*, *> } ?: return null
        if (states.isEmpty()) return null
        val raw = states.joinToString(", ", "[", "]") { state ->
            KEYS.mapNotNull { key ->
                when (val value = state[key]) {
                    is Number -> "$key=${value.toLong()}"
                    is Boolean -> "$key=$value"
                    else -> null
                }
            }.joinToString(",")
        }
        val named = states.mapNotNull { state ->
            val id = (state["appStateID"] as? Number)?.toLong() ?: return@mapNotNull null
            val name = NAMES[id] ?: return@mapNotNull null
            val holder = when (val entity = (state["entity"] as? Number)?.toLong()) {
                null -> (state["state"] as? Boolean)?.let { if (it) "on" else "off" } ?: "-"
                0L -> "none"
                1L -> "iPhone"
                2L -> "accessory"
                else -> "entity$entity"
            }
            val mode = (state["speechMode"] as? Number)?.toLong()?.let { "(mode $it)" } ?: ""
            id to "$name=$holder$mode"
        }.sortedBy { (id, _) -> listOf(2L, 1L, 3L).indexOf(id) }.joinToString(" ") { it.second }
        return listOf(named, raw).filter { it.isNotEmpty() }.joinToString(" ")
    }
}

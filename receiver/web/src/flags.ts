/**
 * Build-time constants of the Tesla-only viewer (AutoPlay, 2026-10-26). They replace the `carMusic`/`tesla` fields the
 * box used to write into receiver-access.json (DashPlay car_music / car_voice / tesla_mode): one product, one mode.
 */

/** Music, calls and Siri go over the car's own Bluetooth (the iPhone is the Tesla's media source); this page plays
 *  navigation prompts and alerts (boosted) and whatever music the iPhone still sends it for a moment (after Siri). */
export const CAR_MUSIC = true;

/** The Tesla browser's ways: no DOM fullscreen (a page shown without the address bar comes through a listed video
 *  site, tesla-fullscreen.ts), the tab frozen in reverse gear or another app (the revive path in main.ts). */
export const TESLA = true;

/**
 * Music (stream 102, AAC) through an HTML media element with MSE (music-output.ts, aac-mp4.ts) rather than through
 * Web Audio. Frozen, not developed (tesla_only_box_delta F1): the iPhone does send ~27 s of music here after Siri,
 * and whether the Web Audio path (AudioDecoder, audio.ts) carries that acceptably is a listening test still to be done.
 * false: no media element, music decodes into Web Audio at a 1.0 s target (audio-timing.ts).
 */
export const MUSIC_ELEMENT = true;

/** Navigation prompts and alerts are boosted this much through a limiter (audio.ts); `?promptgain=1..8` overrides. */
export const PROMPT_BOOST = 3;

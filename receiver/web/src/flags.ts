/**
 * Build-time constants of the Tesla-only viewer (AutoPlay, 2026-10-26). They replace the `carMusic`/`tesla` fields the
 * box used to write into receiver-access.json (DashPlay car_music / car_voice / tesla_mode): one product, one mode.
 */

/** Music, calls and Siri go over the car's own Bluetooth (the iPhone is the Tesla's media source); this page plays
 *  navigation prompts and alerts (boosted); music the iPhone still sends it is dropped (PAGE_PLAYS_MUSIC). */
export const CAR_MUSIC = true;

/** The Tesla browser's ways: no DOM fullscreen (a page shown without the address bar comes through a listed video
 *  site, tesla-fullscreen.ts), the tab frozen in reverse gear or another app (the revive path in main.ts). */
export const TESLA = true;

/**
 * This page never plays music (1.1.0; DashPlay 2026-11-01 in a moving Tesla): a page playing music through a media
 * element gets the car's "video is audio-only while driving" banner, the banner resizes the page and CarPlay
 * renegotiates every ~10 s. Music belongs on the Tesla's Bluetooth; what the iPhone still sends here (type 102 AAC,
 * type 100 "media" PCM; ~27 s after Siri) is dropped by AudioEngine and the driver is told once. The MSE music path
 * of 0.1.0 (music-output.ts, aac-mp4.ts, MUSIC_ELEMENT) is gone with it; docs/AUDIO.md.
 */
export const PAGE_PLAYS_MUSIC = false;

/** Navigation prompts and alerts are boosted this much through a limiter (audio.ts); `?promptgain=1..8` overrides. */
export const PROMPT_BOOST = 3;

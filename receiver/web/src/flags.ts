/**
 * Build-time constants of the Tesla-only viewer (AutoPlay, 2026-10-26). They replace the `carMusic`/`tesla` fields the
 * box used to write into receiver-access.json (DashPlay car_music / car_voice / tesla_mode): one product, one mode.
 *
 * Sound has no flag any more (1.3.0): the receiver offers the iPhone no audio at all, so music, navigation prompts,
 * calls and Siri play on the Tesla's Bluetooth and this page is silent. The page-audio path of 1.0.0–1.2.0
 * (CAR_MUSIC, PAGE_PLAYS_MUSIC, PROMPT_BOOST, audio.ts, the uci key audio_route_navigation) is in git history up to
 * v1.2.0; docs/AUDIO.md says why it went.
 */

/** The Tesla browser's ways: no DOM fullscreen (a page shown without the address bar comes through a listed video
 *  site, tesla-fullscreen.ts), the tab frozen in reverse gear or another app (the revive path in main.ts). */
export const TESLA = true;

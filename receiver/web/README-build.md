# Building the AutoPlay viewer (`receiver/web`)

The viewer is a small TypeScript page (`src/`, `index.html`, `public/browser-check.js`) served by the receiver
JVM from `web/dist`. It can be built two ways; both produce the same `dist/` layout the server expects
(`dist/index.html`, `dist/assets/boot.js` + chunks, `dist/assets/style.css`, `dist/browser-check.js`).

## Online (Vite, the upstream way)

```sh
cd receiver/web
npm ci                 # exact versions from package-lock.json
npm run build          # = tsc && vite build  → dist/ (minified, hashed names)
```

## Offline (esbuild, no registry access)

```sh
cd receiver/web
node scripts/build-esbuild.mjs            # → dist/ ; esbuild found in $ESBUILD, ./node_modules/esbuild or
                                          #   /opt/npm-tools/node_modules/esbuild
```

The esbuild output is not minified and the entry is always `assets/boot.js`; markup and CSS are identical to the
sources, so an offline build is a faithful stand-in for testing in a car.

## Type-check and self-checks

```sh
tsc --noEmit -p tsconfig.offline.json     # src/ only (tsconfig.json also covers vite.config.ts, which needs
                                          # node_modules/vite to resolve)
npm test               # original checks plus check-runtime.mjs
```

The `check*.mjs` scripts import `typescript` as a bare module. Without `npm install`, point them at a preinstalled
copy with a symlink (node_modules/ is gitignored):

```sh
mkdir -p node_modules && ln -sfn /opt/npm-tools/node_modules/typescript node_modules/typescript
```

## Since then (1.1.0 / 1.2.0)

- `npm run build:offline` = `tsc --noEmit -p tsconfig.offline.json && node scripts/build-esbuild.mjs`.
- `npm test` runs five scripts: `check.mjs`, `check-audio.mjs`, `check-car.mjs`, `check-browser.mjs`, `check-runtime.mjs`.
- 1.1.0 deleted the MSE music path (`music-output.ts`, `aac-mp4.ts`; `flags.ts` has `PAGE_PLAYS_MUSIC = false`).
- 1.2.0 added `src/picker.ts` (the in-page option sheet that replaces native `<select>` lists) and
  `scripts/ui-shots.mjs`, which screenshots the viewer and the box page at the Tesla browser's window shapes
  (needs `playwright-core` and a Chromium: `CHROME=/path/to/chromium node scripts/ui-shots.mjs out/ui-shots`;
  `../../docs/UI-1.2.0.md`). `scripts/benchmark-media.mjs` is the media micro-benchmark from 0.1.1.
- Sizes are larger than the numbers below (`index.html` 12.7 KB, `style.css` 20 KB source); those are the
  2026-10-26 snapshot.

## State at the end of the trim (2026-10-26, branch `receiver-trim`)

- `tsc --noEmit -p tsconfig.offline.json`: clean (the `ws.ts` error went with `sendBinary` and the microphone).
- `check.mjs`, `check-audio.mjs`, `check-car.mjs`, `check-browser.mjs`: all pass (`check-flac.mjs` went with wired CarPlay).
- esbuild build: `index.html` 9.4 KB, `main` chunk ≈ 92 KB, `style.css` ≈ 15 KB.

## Baseline before the Tesla-only trim (2026-10-26, DashPlay `e3beae4` state of the tree)

- `tsc -p tsconfig.json`: 2 errors, both environmental — `vite.config.ts` cannot resolve `vite` without
  node_modules, and `ws.ts:125` (`sendBinary`) fails TypeScript 6.0's stricter `Uint8Array<ArrayBufferLike>` typing
  (the project pins `^5.9`). `tsc -p tsconfig.offline.json`: the `ws.ts` error only.
- `check.mjs`, `check-audio.mjs`, `check-car.mjs`, `check-browser.mjs`, `check-flac.mjs`: all pass.
- esbuild build: dist/ 200 KB, `index.html` 41 KB (31 KB of it two base64 QR images), `main` chunk 112 KB.

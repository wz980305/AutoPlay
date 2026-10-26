#!/usr/bin/env node
// AutoPlay viewer: offline build with esbuild (GPL-3.0, see ../../LICENSE).
//
// `vite build` needs the npm registry once (node_modules/vite). On a box or a build machine without network this
// script produces the same dist/ layout from a preinstalled esbuild: src/boot.ts bundled as ESM with code splitting
// (main.ts is a dynamic import, so it stays a separate chunk), src/style.css bundled, public/ copied, and the two
// asset references in index.html rewritten to ./assets/. Markup and CSS are byte-identical to the sources; Vite
// would only add minification and hashed entry names.
//
// Usage:  node scripts/build-esbuild.mjs [path-to-web]        (default: the web/ directory this script lives in)
// esbuild is looked up in: $ESBUILD (a path to esbuild's lib/main.js or package dir), ./node_modules/esbuild,
// then /opt/npm-tools/node_modules/esbuild (the sandbox's preinstalled copy).
import { readFileSync, writeFileSync, mkdirSync, cpSync, rmSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const web = resolve(process.argv[2] ?? join(here, '..'));
const dist = join(web, 'dist');

async function loadEsbuild() {
  const candidates = [process.env.ESBUILD, join(web, 'node_modules/esbuild'), '/opt/npm-tools/node_modules/esbuild'].filter(Boolean);
  for (const candidate of candidates) {
    const main = candidate.endsWith('.js') ? candidate : join(candidate, 'lib/main.js');
    if (existsSync(main)) return import(pathToFileURL(main).href);
  }
  throw new Error(`esbuild not found; tried ${candidates.join(', ')}. Set $ESBUILD or run npm install.`);
}

const { build } = await loadEsbuild();
if (!existsSync(join(web, 'src/boot.ts'))) throw new Error(`${web} is not the viewer's web/ directory`);
rmSync(dist, { recursive: true, force: true });
mkdirSync(join(dist, 'assets'), { recursive: true });

await build({
  entryPoints: [join(web, 'src/boot.ts')],
  bundle: true, splitting: true, format: 'esm', target: 'es2022',
  outdir: join(dist, 'assets'), entryNames: '[name]', chunkNames: '[name]-[hash]',
  minify: false, sourcemap: false, logLevel: 'info',
});
await build({
  entryPoints: [join(web, 'src/style.css')],
  bundle: true, outdir: join(dist, 'assets'), entryNames: '[name]', minify: false, logLevel: 'info',
});
cpSync(join(web, 'public'), dist, { recursive: true });
let html = readFileSync(join(web, 'index.html'), 'utf8');
const before = html;
html = html.replace('href="/src/style.css"', 'href="./assets/style.css"')
           .replace('<script type="module" src="/src/boot.ts"></script>', '<script type="module" src="./assets/boot.js"></script>');
if (html === before) throw new Error('index.html: the /src/style.css and /src/boot.ts references were not found');
writeFileSync(join(dist, 'index.html'), html);
console.log('built to', dist);

#!/usr/bin/env node
// AutoPlay viewer: a check on the built page (GPL-3.0, see ../../LICENSE).
//
// The page reloads itself when the box no longer serves it (src/fresh.ts, 1.6.7), and tells by the file name of its
// own entry script, which boot.ts takes from import.meta.url. That only works when the script index.html names is
// the one that holds boot.ts: if a bundler moved that code into another chunk, every page would find "its" script
// missing from index.html and reload once for nothing. Run on dist/ after a build (release.sh, step 3).
//
// Usage:  node scripts/check-dist.mjs [path-to-dist]        (default: ../dist beside this script)
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = resolve(process.argv[2] ?? join(dirname(fileURLToPath(import.meta.url)), '../dist'));
const html = readFileSync(join(dist, 'index.html'), 'utf8');
const entries = [...html.matchAll(/<script\b[^>]*>/g)].map(match => match[0]).filter(tag => /\btype="?module"?/.test(tag))
  .map(tag => /\bsrc="([^"]+)"/.exec(tag)?.[1] ?? '');
if (entries.length !== 1) throw new Error(`index.html names ${entries.length} module scripts, expected one: ${entries.join(', ')}`);
const entry = entries[0];
if (!/^\.\/assets\/[^/]+\.js$/.test(entry)) throw new Error(`the entry script is not a file under ./assets/: ${entry}`);
const code = readFileSync(join(dist, entry), 'utf8');
if (!code.includes('playportEntry') || !code.includes('import.meta.url')) {
  throw new Error(`${entry} does not hold boot.ts's "playportEntry = …import.meta.url": the page could not tell its own script`);
}
console.log(`dist: ${entry} is the entry and names itself`);

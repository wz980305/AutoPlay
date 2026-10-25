interface BrowserCheck { done: boolean; allowed: boolean; appReady(): void; appFailed(): void }
const check = (window as unknown as { F50BrowserCheck?: BrowserCheck }).F50BrowserCheck;
function start() {
  if (!check) return; // Keep the independent diagnostic visible if its script failed.
  if (!check.done) { setTimeout(start, 50); return; }
  if (check.allowed) void import('./main').then(() => check.appReady()).catch(() => check.appFailed());
}
start();

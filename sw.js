// sw.js (very minimal cache-first)
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open("calc-v1").then(c => c.addAll([".", "index.html", "styles.css", "script.js"])));
});
self.addEventListener("fetch", (e) => {
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)));
});

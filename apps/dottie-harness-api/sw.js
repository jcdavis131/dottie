const CACHE='dottie-v67-CORE20-offline13k-void-080A0F'; const OFFLINE='/offline.html';
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll([OFFLINE,'/','/index.html','/manifest.json']))); self.skipWaiting();});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k))))); self.clients.claim();});
self.addEventListener('fetch',e=>{e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(res=>{if(res.ok&&e.request.method==='GET'){caches.open(CACHE).then(c=>{if(c.keys().then(ks=>{if(ks.length<1000){c.put(e.request,res.clone())}});});}return res;}).catch(()=>caches.match(OFFLINE))));});

/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

import { build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;

const APP_CACHE = `tarotarium-v2-app-${version}`;
const CARD_CACHE = 'tarotarium-v2-cards';
// Versioned: it holds cached navigations, so an unversioned one can serve an
// old app shell pointing at build assets that no longer exist. Card art
// (CARD_CACHE) is deliberately not versioned — art URLs carry their own
// ?v= cache-buster, and re-downloading a deck on every release is wasteful.
const RUNTIME_CACHE = `tarotarium-v2-runtime-${version}`;
const ASSETS = [...build, ...files];

sw.addEventListener('install', (event) => {
	event.waitUntil(
		caches
			.open(APP_CACHE)
			.then((cache) => cache.addAll(ASSETS))
			.then(() => sw.skipWaiting())
	);
});

sw.addEventListener('activate', (event) => {
	event.waitUntil(
		caches
			.keys()
			.then((keys) =>
				Promise.all(
					keys
						// drop every tarotarium cache that isn't one of ours — including
						// all pre-v2 prefixes (auth-era cache contract change)
						.filter(
							(k) =>
								k.startsWith('tarotarium-') &&
								k !== APP_CACHE &&
								k !== CARD_CACHE &&
								k !== RUNTIME_CACHE
						)
						.map((k) => caches.delete(k))
				)
			)
			.then(() => sw.clients.claim())
	);
});

function isCardImage(url: URL): boolean {
	return /^\/api\/decks\/[^/]+\/(cards\/\d+|back)$/.test(url.pathname);
}

sw.addEventListener('fetch', (event) => {
	if (event.request.method !== 'GET') return;
	const url = new URL(event.request.url);
	if (url.origin !== sw.location.origin) return;

	// the OIDC handshake must never be intercepted or cached — redirects,
	// cookies and one-time state all live here
	if (url.pathname.startsWith('/auth/')) return;

	// card images: cache-first; the URL's ?v= art-version busts on change
	if (isCardImage(url)) {
		event.respondWith(
			caches.open(CARD_CACHE).then(async (cache) => {
				const hit = await cache.match(event.request);
				if (hit) return hit;
				const resp = await fetch(event.request);
				if (resp.ok && !resp.redirected) cache.put(event.request, resp.clone());
				return resp;
			})
		);
		return;
	}

	// other API calls: network only
	if (url.pathname.startsWith('/api/')) return;

	// app shell + navigations: cache-first for build assets, network-first with
	// cached fallback for everything else (offline support). Never cache a
	// redirected or non-200 response — a cached login redirect would wedge
	// the app shell.
	event.respondWith(
		caches.match(event.request).then(async (hit) => {
			if (hit) return hit;
			try {
				const resp = await fetch(event.request);
				if (
					resp.ok &&
					!resp.redirected &&
					(event.request.mode === 'navigate' || ASSETS.includes(url.pathname))
				) {
					const cache = await caches.open(RUNTIME_CACHE);
					cache.put(event.request, resp.clone());
				}
				return resp;
			} catch (err) {
				if (event.request.mode === 'navigate') {
					const fallback = await caches.match('/');
					if (fallback) return fallback;
				}
				throw err;
			}
		})
	);
});

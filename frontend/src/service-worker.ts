/// <reference types="@sveltejs/kit" />
/// <reference lib="webworker" />

import { build, files, version } from '$service-worker';

const sw = self as unknown as ServiceWorkerGlobalScope;

const APP_CACHE = `tarotarium-app-${version}`;
const CARD_CACHE = 'tarotarium-cards';
const RUNTIME_CACHE = 'tarotarium-runtime';
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
						.filter((k) => k.startsWith('tarotarium-app-') && k !== APP_CACHE)
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

	// card images: cache-first, they never change for a given deck
	if (isCardImage(url)) {
		event.respondWith(
			caches.open(CARD_CACHE).then(async (cache) => {
				const hit = await cache.match(event.request);
				if (hit) return hit;
				const resp = await fetch(event.request);
				if (resp.ok) cache.put(event.request, resp.clone());
				return resp;
			})
		);
		return;
	}

	// other API calls: network only
	if (url.pathname.startsWith('/api/')) return;

	// app shell + navigations: cache-first for build assets, network-first with
	// cached fallback for everything else (offline support)
	event.respondWith(
		caches.match(event.request).then(async (hit) => {
			if (hit) return hit;
			try {
				const resp = await fetch(event.request);
				if (resp.ok && (event.request.mode === 'navigate' || ASSETS.includes(url.pathname))) {
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

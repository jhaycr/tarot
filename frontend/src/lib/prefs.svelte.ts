// Reading preferences — server-backed so they follow the account across
// devices. localStorage is a device cache: the UI paints from it instantly
// and it carries offline/PWA use; the server profile wins at load time.
// Writes update state + cache immediately and debounce one PUT per burst.
import { api, type UserSettings } from '$lib/api';

let pending: Record<string, unknown> = {};
let timer: ReturnType<typeof setTimeout> | null = null;

function queue(key: string, value: unknown) {
	if (key === 'extras') {
		pending.extras = { ...((pending.extras as object) ?? {}), ...(value as object) };
	} else {
		pending[key] = value;
	}
	if (timer) clearTimeout(timer);
	timer = setTimeout(flush, 500);
}

async function flush() {
	timer = null;
	const batch = pending;
	pending = {};
	try {
		await api.setMySettings(batch as Partial<UserSettings>);
	} catch {
		// Offline or signed-out: the localStorage cache still holds the value;
		// the next successful sync reconciles.
	}
}

// Applied when the server profile arrives; collected for first-login import.
const applyFns: ((s: UserSettings) => void)[] = [];
const collectFns: ((out: Record<string, unknown>) => void)[] = [];

function persisted(lsKey: string, serverKey: string, fallback: string): { value: string } {
	let value = $state(localStorage.getItem(lsKey) ?? fallback);
	applyFns.push((s) => {
		const sv = (s as unknown as Record<string, unknown>)[serverKey];
		if (typeof sv === 'string' && sv !== value) {
			value = sv;
			localStorage.setItem(lsKey, sv);
		}
	});
	collectFns.push((out) => (out[serverKey] = value));
	return {
		get value() {
			return value;
		},
		set value(v: string) {
			value = v;
			localStorage.setItem(lsKey, v);
			queue(serverKey, v);
		}
	};
}

export const prefDeck = persisted('tarot.deck', 'deck', '');
export const prefSpread = persisted('tarot.spread', 'spread', 'three-card');
export const prefReversals = persisted('tarot.reversals', 'reversals', 'true');
export const prefPersona = persisted('tarot.persona', 'persona', 'alice');
export const prefGuidedMode = persisted('tarot.guidedMode', 'guided_mode', 'isolated'); // isolated | cumulative
export const prefJournalLayout = persisted('tarot.journalLayout', 'journal_layout', 'grid');
// NOTE: auto-read audio was already a server setting; it stays on its own path.

function persistedList(lsKey: string, serverKey: string): { value: string[] } {
	let value = $state<string[]>(JSON.parse(localStorage.getItem(lsKey) ?? '[]'));
	applyFns.push((s) => {
		const sv = (s as unknown as Record<string, unknown>)[serverKey];
		if (Array.isArray(sv)) {
			value = sv as string[];
			localStorage.setItem(lsKey, JSON.stringify(sv));
		}
	});
	collectFns.push((out) => (out[serverKey] = value));
	return {
		get value() {
			return value;
		},
		set value(v: string[]) {
			value = v;
			localStorage.setItem(lsKey, JSON.stringify(v));
			queue(serverKey, v);
		}
	};
}

export const favDecks = persistedList('tarot.favDecks', 'fav_decks');
export const recentDecks = persistedList('tarot.recentDecks', 'recent_decks');

export function toggleFavDeck(slug: string): void {
	favDecks.value = favDecks.value.includes(slug)
		? favDecks.value.filter((s) => s !== slug)
		: [...favDecks.value, slug];
}

export function pushRecentDeck(slug: string): void {
	recentDecks.value = [slug, ...recentDecks.value.filter((s) => s !== slug)].slice(0, 5);
}

// Per-deck "include extras" — one server key per deck (extras.<slug>).
const extrasByDeck = $state<Record<string, boolean>>({});

export function extrasPref(deck: string): boolean {
	return extrasByDeck[deck] ?? localStorage.getItem(`tarot.extras.${deck}`) === 'true';
}

export function setExtrasPref(deck: string, include: boolean): void {
	extrasByDeck[deck] = include;
	localStorage.setItem(`tarot.extras.${deck}`, String(include));
	queue('extras', { [deck]: include });
}

function collectExtras(out: Record<string, unknown>): void {
	const extras: Record<string, boolean> = {};
	for (let i = 0; i < localStorage.length; i++) {
		const k = localStorage.key(i);
		if (k?.startsWith('tarot.extras.')) {
			extras[k.slice('tarot.extras.'.length)] = localStorage.getItem(k) === 'true';
		}
	}
	if (Object.keys(extras).length) out.extras = extras;
}

/**
 * Reconcile with the account profile (called once per app load, with the
 * settings that ride /api/me). Server wins for every key it has; a user
 * whose profile has never been written gets their current device prefs
 * imported once, so nobody loses their setup crossing to server-side prefs.
 */
export function syncPrefs(s: UserSettings): void {
	if (!s.has_profile) {
		const out: Record<string, unknown> = {};
		for (const fn of collectFns) fn(out);
		collectExtras(out);
		api.setMySettings(out as Partial<UserSettings>).catch(() => {});
		return;
	}
	for (const fn of applyFns) fn(s);
	if (s.extras) {
		for (const [deck, include] of Object.entries(s.extras)) {
			extrasByDeck[deck] = include;
			localStorage.setItem(`tarot.extras.${deck}`, String(include));
		}
	}
}

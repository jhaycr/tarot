// Reading preferences, persisted to localStorage.

function persisted(key: string, fallback: string): { value: string } {
	let value = $state(localStorage.getItem(key) ?? fallback);
	return {
		get value() {
			return value;
		},
		set value(v: string) {
			value = v;
			localStorage.setItem(key, v);
		}
	};
}

export const prefDeck = persisted('tarot.deck', '');
export const prefSpread = persisted('tarot.spread', 'three-card');
export const prefReversals = persisted('tarot.reversals', 'true');
export const prefPersona = persisted('tarot.persona', 'alice');
export const prefJournalLayout = persisted('tarot.journalLayout', 'grid');

function persistedList(key: string): { value: string[] } {
	let value = $state<string[]>(JSON.parse(localStorage.getItem(key) ?? '[]'));
	return {
		get value() {
			return value;
		},
		set value(v: string[]) {
			value = v;
			localStorage.setItem(key, JSON.stringify(v));
		}
	};
}

export const favDecks = persistedList('tarot.favDecks');
export const recentDecks = persistedList('tarot.recentDecks');

export function toggleFavDeck(slug: string): void {
	favDecks.value = favDecks.value.includes(slug)
		? favDecks.value.filter((s) => s !== slug)
		: [...favDecks.value, slug];
}

export function pushRecentDeck(slug: string): void {
	recentDecks.value = [slug, ...recentDecks.value.filter((s) => s !== slug)].slice(0, 5);
}

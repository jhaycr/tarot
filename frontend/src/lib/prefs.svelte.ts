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

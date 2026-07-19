// Current reading, survives refresh via sessionStorage.

import type { Reading } from '$lib/api';

const KEY = 'tarot.reading';

function load(): Reading | null {
	try {
		const raw = sessionStorage.getItem(KEY);
		return raw ? JSON.parse(raw) : null;
	} catch {
		return null;
	}
}

let current = $state<Reading | null>(load());

export const readingStore = {
	get current() {
		return current;
	},
	set(reading: Reading | null) {
		current = reading;
		if (reading) sessionStorage.setItem(KEY, JSON.stringify(reading));
		else sessionStorage.removeItem(KEY);
	}
};

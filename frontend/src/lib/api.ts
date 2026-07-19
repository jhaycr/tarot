export interface Card {
	index: number;
	name: string;
	arcana: 'major' | 'minor';
	suit: string | null;
	rank: string | null;
	number: number | null;
}

export interface DeckSummary {
	slug: string;
	name: string;
	source: string | null;
	attribution: string | null;
	license: string | null;
	count: number;
	complete: boolean;
	has_back: boolean;
}

export interface SpreadPosition {
	name: string;
	meaning: string;
	col: number;
	row: number;
	cross?: boolean;
}

export interface Spread {
	slug: string;
	name: string;
	description: string;
	positions: SpreadPosition[];
}

export interface DrawnCard {
	position: SpreadPosition;
	card: Card;
	reversed: boolean;
}

export interface Reading {
	deck: string;
	spread: string;
	question: string | null;
	cards: DrawnCard[];
}

async function get<T>(url: string): Promise<T> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`${url}: ${res.status}`);
	return res.json();
}

export const api = {
	cards: () => get<Card[]>('/api/cards'),
	decks: () => get<DeckSummary[]>('/api/decks'),
	spreads: () => get<Spread[]>('/api/spreads'),
	draw: async (deck: string, spread: string, reversals: boolean, question?: string): Promise<Reading> => {
		const res = await fetch('/api/draw', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ deck, spread, reversals, question: question || null })
		});
		if (!res.ok) throw new Error(`draw failed: ${res.status}`);
		return res.json();
	},
	cardImage: (deck: string, index: number) => `/api/decks/${deck}/cards/${index}`,
	backImage: (deck: string) => `/api/decks/${deck}/back`
};

export interface Card {
	index: number;
	name: string;
	arcana: 'major' | 'minor' | 'extra';
	suit: string | null;
	rank: string | null;
	number: number | null;
	upright?: string | null;
	reversed_meaning?: string | null;
	description?: string | null;
	pkt_upright?: string | null;
	pkt_reversed?: string | null;
}

export interface DeckExtra {
	index: number;
	name: string;
}

export interface DeckSummary {
	slug: string;
	name: string;
	source: string | null;
	attribution: string | null;
	license: string | null;
	count: number;
	complete: boolean;
	majors_only: boolean;
	extras: DeckExtra[];
	missing: number[];
	has_back: boolean;
	owner: string | null;
	shared: boolean;
	yours: boolean;
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

export interface Persona {
	slug: string;
	name: string;
	description: string;
}

export interface SavedReading extends Reading {
	id: number;
	owner: string;
	created_at: number;
	notes: string;
	shared: boolean;
	yours: boolean;
}

async function get<T>(url: string): Promise<T> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`${url}: ${res.status}`);
	return res.json();
}

async function send<T>(method: string, url: string, body?: unknown): Promise<T> {
	const res = await fetch(url, {
		method,
		headers: { 'content-type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!res.ok) throw new Error(`${method} ${url}: ${res.status}`);
	return res.json();
}

export const api = {
	me: () => get<{ user: string; interpretation: boolean; is_admin: boolean }>('/api/me'),
	uploadDeck: async (file: File, name: string) => {
		const form = new FormData();
		form.append('file', file);
		form.append('name', name);
		const res = await fetch('/api/decks/upload', { method: 'POST', body: form });
		if (!res.ok) throw new Error((await res.json()).detail ?? `upload failed: ${res.status}`);
		return res.json() as Promise<{ slug: string; count: number; majors_only: boolean }>;
	},
	startDeckDownload: (source: string, name?: string, slug?: string) =>
		send<{ job: string }>('POST', '/api/decks/download', {
			source,
			name: name || null,
			slug: slug || null
		}),
	deckDownloadStatus: (job: string) =>
		get<{
			source: string;
			slug: string | null;
			name: string | null;
			completed: number;
			failed: number[];
			done: boolean;
			error: string | null;
			total: number;
		}>(`/api/decks/download/${job}`),
	getReadingSettings: () =>
		get<{ reversal_chance: number; default: number }>('/api/settings/reading'),
	setReadingSettings: (s: { reversal_chance: number }) =>
		send<{ reversal_chance: number; default: number }>('PUT', '/api/settings/reading', s),
	getLlmSettings: () =>
		get<{ base_url: string; model: string; api_key_set: boolean; from_env: boolean }>(
			'/api/settings/llm'
		),
	setLlmSettings: (s: { base_url?: string; model?: string; api_key?: string }) =>
		send<{ base_url: string; model: string; api_key_set: boolean; from_env: boolean }>(
			'PUT',
			'/api/settings/llm',
			s
		),
	interpret: (question: string | null, spread: string, cards: DrawnCard[], persona?: string) =>
		send<{ interpretation: string }>('POST', '/api/interpret', {
			question,
			spread,
			cards,
			persona: persona || null
		}),
	personas: () =>
		get<{ personas: Persona[]; has_custom: boolean; default: string }>('/api/personas'),
	getPrompt: () => get<{ prompt: string; personas: Record<string, string> }>('/api/settings/prompt'),
	setPrompt: (prompt: string) =>
		send<{ prompt: string }>('PUT', '/api/settings/prompt', { prompt }),
	cards: () => get<Card[]>('/api/cards'),
	decks: () => get<DeckSummary[]>('/api/decks'),
	spreads: () => get<Spread[]>('/api/spreads'),
	draw: (deck: string, spread: string, reversals: boolean, question?: string, includeExtras = false) =>
		send<Reading>('POST', '/api/draw', {
			deck,
			spread,
			reversals,
			include_extras: includeExtras,
			question: question || null
		}),
	shareDeck: (slug: string, shared: boolean) =>
		send<{ slug: string; shared: boolean }>('POST', `/api/decks/${slug}/share`, { shared }),
	readings: () => get<SavedReading[]>('/api/readings'),
	reading: (id: number) => get<SavedReading>(`/api/readings/${id}`),
	saveReading: (r: Reading & { notes?: string }) => send<SavedReading>('POST', '/api/readings', r),
	updateReading: (id: number, patch: { notes?: string; shared?: boolean }) =>
		send<SavedReading>('PATCH', `/api/readings/${id}`, patch),
	deleteReading: (id: number) => send<{ deleted: number }>('DELETE', `/api/readings/${id}`),
	cardImage: (deck: string, index: number) => `/api/decks/${deck}/cards/${index}`,
	backImage: (deck: string) => `/api/decks/${deck}/back`
};

let cardsCache: Card[] | null = null;
export async function cardMeta(): Promise<Card[]> {
	if (!cardsCache) cardsCache = await api.cards();
	return cardsCache;
}

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
	suit_names: Record<string, string>;
	major_names: Record<string, string>;
	missing: number[];
	has_back: boolean;
	owner: string | null;
	tier: 'builtin' | 'library' | 'staging';
	published: boolean;
	published_by: string | null;
	yours: boolean;
	can_unpublish: boolean;
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

/** What the lightbox/infobox need: a card reference, its orientation, and —
 * when it was drawn into a spread — the position. DrawnCard satisfies this
 * structurally; deck galleries synthesize one with no position. */
export interface CardView {
	card: { index: number; name: string };
	reversed: boolean;
	position?: SpreadPosition;
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

export type Visibility = 'private' | 'specific' | 'everyone';

export type InterpretationMode = 'isolated' | 'cumulative' | 'single';
export type InterpretationStatus = 'none' | 'in_progress' | 'complete';

export interface ReadingInterpretation {
	mode: InterpretationMode | null;
	status: InterpretationStatus;
	/** Detail view only. Position ordinal (as string) -> focused reading text. */
	focused?: Record<string, string>;
	/** Detail view only. Whole-spread text, null until the final step completes. */
	comprehensive?: string | null;
	/** Detail view only. Card ordinals whose focused reading is done. */
	done_positions?: number[];
}

export interface SavedReading extends Reading {
	id: number;
	owner: string;
	created_at: number;
	notes: string;
	visibility: Visibility;
	/** Who it's shared with. Only ever populated for readings you own. */
	shared_with: string[];
	yours: boolean;
	interpretation: ReadingInterpretation;
}

export interface Person {
	username: string;
	display_name: string;
}

export interface GrantedShare {
	id: number;
	question: string | null;
	deck: string;
	spread: string;
	created_at: number;
	visibility: Visibility;
	shared_with: string[];
}

export interface ReceivedShare {
	id: number;
	owner: string;
	question: string | null;
	deck: string;
	spread: string;
	created_at: number;
	granted_at: number;
}

export interface Account {
	user: string;
	display_name: string;
	authenticated: boolean;
	is_admin: boolean;
	reading_count: number;
	shares_granted: GrantedShare[];
	shares_received: ReceivedShare[];
	published_decks: { slug: string; name: string }[];
}

/** Fields listed in `managed` come from the Ansible-managed config file and
 *  cannot be written from the UI. */
export interface ReadingSettings {
	reversal_chance: number;
	default: number;
	managed: string[];
	config_file: string | null;
}

export interface LlmSettings {
	base_url: string;
	model: string;
	api_key_set: boolean;
	from_env: boolean;
	managed: string[];
	config_file: string | null;
	config_error: string | null;
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

export type StreamEvent =
	| { type: 'token'; data: { text: string } }
	| { type: 'done'; data: { persona: string } }
	| { type: 'error'; data: { message: string } };

/** POST an SSE stream and yield its parsed events. Used for guided readings —
 * fetch()+ReadableStream rather than EventSource because we must POST a body.
 * abort the signal to stop the server-side LLM call. */
export async function* streamSSE(
	url: string,
	body: unknown,
	signal: AbortSignal
): AsyncGenerator<StreamEvent> {
	const res = await fetch(url, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body),
		signal
	});
	if (!res.ok || !res.body) throw new Error(`${url}: ${res.status}`);
	const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
	let buf = '';
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		buf += value;
		let i: number;
		while ((i = buf.indexOf('\n\n')) !== -1) {
			const frame = buf.slice(0, i);
			buf = buf.slice(i + 2);
			let ev = 'message';
			let data = '';
			for (const line of frame.split('\n')) {
				if (line.startsWith('event:')) ev = line.slice(6).trim();
				else if (line.startsWith('data:')) data += line.slice(5).trim();
			}
			if (data) yield { type: ev, data: JSON.parse(data) } as StreamEvent;
		}
	}
}

export const api = {
	me: () =>
		get<{
			user: string;
			display_name: string;
			interpretation: boolean;
			is_admin: boolean;
			authenticated: boolean;
			logout_url: string | null;
			version: string;
		}>('/api/me'),
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
	getReadingSettings: () => get<ReadingSettings>('/api/settings/reading'),
	setReadingSettings: (s: { reversal_chance: number }) =>
		send<ReadingSettings>('PUT', '/api/settings/reading', s),
	getLlmSettings: () => get<LlmSettings>('/api/settings/llm'),
	setLlmSettings: (s: { base_url?: string; model?: string; api_key?: string }) =>
		send<LlmSettings>('PUT', '/api/settings/llm', s),
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
	publishDeck: (slug: string) => send<DeckSummary>('POST', `/api/decks/${slug}/publish`),
	unpublishDeck: (slug: string) => send<DeckSummary>('POST', `/api/decks/${slug}/unpublish`),
	deleteDeck: (slug: string) => send<{ deleted: string }>('DELETE', `/api/decks/${slug}`),
	readings: () => get<SavedReading[]>('/api/readings'),
	reading: (id: number) => get<SavedReading>(`/api/readings/${id}`),
	createGuidedReading: (r: Reading & { mode: InterpretationMode; notes?: string }) =>
		send<SavedReading>('POST', '/api/readings/guided', r),
	streamFocused: (id: number, position: number, persona: string | null, signal: AbortSignal) =>
		streamSSE(`/api/readings/${id}/interpret/focused/${position}`, { persona }, signal),
	streamComprehensive: (id: number, persona: string | null, signal: AbortSignal) =>
		streamSSE(`/api/readings/${id}/interpret/comprehensive`, { persona }, signal),
	saveReading: (r: Reading & { notes?: string }) => send<SavedReading>('POST', '/api/readings', r),
	updateReading: (id: number, patch: { notes?: string }) =>
		send<SavedReading>('PATCH', `/api/readings/${id}`, patch),
	users: () => get<Person[]>('/api/users'),
	account: () => get<Account>('/api/account'),
	setSharing: (id: number, visibility: Visibility, grantees: string[] = []) =>
		send<SavedReading>('PUT', `/api/readings/${id}/sharing`, { visibility, grantees }),
	deleteReading: (id: number) => send<{ deleted: number }>('DELETE', `/api/readings/${id}`),
	cardImage: (deck: string, index: number) => `/api/decks/${deck}/cards/${index}`,
	backImage: (deck: string) => `/api/decks/${deck}/back`
};

let cardsCache: Card[] | null = null;
export async function cardMeta(): Promise<Card[]> {
	if (!cardsCache) cardsCache = await api.cards();
	return cardsCache;
}

export interface DeckRenames {
	suit_names?: Record<string, string>;
	major_names?: Record<string, string>;
}

/**
 * Apply a deck's renames: major arcana get a full replacement name
 * ("The Fool" -> "Spore"), minors get their suit swapped
 * ("Ace of Wands" -> "Ace of Vitality").
 */
export function deckCardName(name: string, deck?: DeckRenames): string {
	if (!deck) return name;
	const major = deck.major_names?.[name];
	if (major) return major;
	if (!deck.suit_names) return name;
	for (const [real, renamed] of Object.entries(deck.suit_names)) {
		if (name.endsWith(` of ${real}`)) return name.slice(0, -real.length) + renamed;
	}
	return name;
}

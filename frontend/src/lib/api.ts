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
	has_cover: boolean;
	owner: string | null;
	tier: 'builtin' | 'library' | 'staging';
	published: boolean;
	published_by: string | null;
	yours: boolean;
	can_unpublish: boolean;
	/** Deck-curated companion book slugs (only the deck's owner edits). */
	books: string[];
	/** Indices (canonical + extras) with DEDICATED reversed art — rendered
	 * upright instead of rotating the upright art. */
	reversed_indices: number[];
	/** Art cache-buster; rotates when any deck image changes. */
	art_version: number;
	/** Gallery tile shows the box cover instead of card 0. */
	tile_cover: boolean;
	can_edit_books: boolean;
	/** Title-match suggestions; only populated for the deck's controller. */
	suggested_books: string[];
}

export interface BookSummary {
	slug: string;
	name: string;
	author: string | null;
	tier: 'library' | 'staging';
	published: boolean;
	published_by: string | null;
	yours: boolean;
	can_unpublish: boolean;
	pages: number;
	cards_covered: number;
	chunk_count: number;
	llm_assisted: boolean;
	card_pages: Record<string, number>;
}

export interface BookImportJob {
	slug: string;
	name: string;
	stage: string;
	page: number;
	pages: number;
	cards_covered: number;
	llm_assisted: boolean;
	failed_pages: number[];
	done: boolean;
	error: string | null;
}

export interface BookPassage {
	heading: string | null;
	orientation: 'upright' | 'reversed' | null;
	pages: number[];
	sections: Record<string, string> | null;
	text: string;
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
	books: string[];
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

/** A persona's TTS voice: id + optional speed and style instructions
 * (instructions are honored by OpenAI, ignored by e.g. Kokoro). */
export interface VoiceBlock {
	voice?: string;
	speed?: number;
	instructions?: string;
}

/** Settings that follow the user across devices (unlike localStorage prefs). */
export interface UserSettings {
	auto_read_audio: boolean;
	/** Hide your own draft (unpublished) decks from the reading picker. */
	hide_draft_decks: boolean;
	default_books: string[];
}

export interface LimitGauge {
	used: number;
	limit: number | null;
}

/** Daily spend caps. `{enabled: false}` alone when no cap is configured. */
export interface LimitsStatus {
	enabled: boolean;
	exempt?: boolean;
	readings?: LimitGauge;
	tokens?: LimitGauge;
	minutes?: LimitGauge;
}

export interface LimitsSettings {
	readings_per_day: number | null;
	llm_tokens_per_day: number | null;
	tts_minutes_per_day: number | null;
	managed: string[];
	config_file: string | null;
	config_error: string | null;
}

export interface UsageRow {
	component: 'llm' | 'tts';
	model: string;
	calls: number;
	prompt_tokens: number;
	completion_tokens: number;
	characters: number;
	audio_bytes: number;
}

export interface UsageSummary {
	days: number;
	by_model: UsageRow[];
	daily: {
		day: string;
		calls: number;
		prompt_tokens: number;
		completion_tokens: number;
		tts_characters: number;
		audio_bytes: number;
	}[];
	by_user: {
		owner: string;
		component: 'llm' | 'tts';
		calls: number;
		prompt_tokens: number;
		completion_tokens: number;
		audio_bytes: number;
	}[];
}

export interface TtsSettings {
	base_url: string;
	model: string;
	api_key_set: boolean;
	voices: Record<string, Required<VoiceBlock>>;
	defaults: Record<string, Required<VoiceBlock>>;
	managed: string[];
	config_file: string | null;
	config_error: string | null;
}

/** The server's human-readable `detail` when there is one ("Daily reading
 * limit reached — resets at midnight."), else a terse status fallback. */
async function errorFrom(res: Response, fallback: string): Promise<Error> {
	try {
		const detail = (await res.json())?.detail;
		if (typeof detail === 'string' && detail) return new Error(detail);
	} catch {
		// non-JSON body — fall through
	}
	return new Error(fallback);
}

// Deck art versions, learned from any decks() fetch: extras are position-
// addressed, so art URLs must rotate when the deck's files change (see
// DeckSummary.art_version). URLs built before the fetch resolves simply omit
// the version — same behavior as before, corrected on the next render.
const deckArtVersions: Record<string, number> = {};
function artVersion(deck: string): string {
	const v = deckArtVersions[deck];
	return v ? `v=${v}` : '';
}

async function get<T>(url: string): Promise<T> {
	const res = await fetch(url);
	if (!res.ok) throw await errorFrom(res, `${url}: ${res.status}`);
	return res.json();
}

async function send<T>(method: string, url: string, body?: unknown): Promise<T> {
	const res = await fetch(url, {
		method,
		headers: { 'content-type': 'application/json' },
		body: body === undefined ? undefined : JSON.stringify(body)
	});
	if (!res.ok) throw await errorFrom(res, `${method} ${url}: ${res.status}`);
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
	if (!res.ok) throw await errorFrom(res, `${url}: ${res.status}`);
	if (!res.body) throw new Error(`${url}: empty response`);
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
			tts: boolean;
			settings: UserSettings;
			limits: LimitsStatus;
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
	books: () => get<BookSummary[]>('/api/books'),
	uploadBook: async (file: File, name: string) => {
		const form = new FormData();
		form.append('file', file);
		form.append('name', name);
		const res = await fetch('/api/books/upload', { method: 'POST', body: form });
		if (!res.ok) throw new Error((await res.json()).detail ?? `upload failed: ${res.status}`);
		return res.json() as Promise<{ job: string; slug: string }>;
	},
	bookImportStatus: (job: string) => get<BookImportJob>(`/api/books/import/${job}`),
	reextractBook: (slug: string) =>
		send<{ job: string; slug: string }>('POST', `/api/books/${slug}/reextract`),
	patchBook: (slug: string, patch: { name?: string; author?: string; license?: string }) =>
		send<BookSummary>('PATCH', `/api/books/${slug}`, patch),
	patchDeck: (slug: string, patch: { tile_cover?: boolean }) =>
		send<{ slug: string; tile_cover: boolean }>('PATCH', `/api/decks/${slug}`, patch),
	setDeckBooks: (slug: string, books: string[]) =>
		send<{ slug: string; books: string[] }>('PUT', `/api/decks/${slug}/books`, { books }),
	publishBook: (slug: string) => send<BookSummary>('POST', `/api/books/${slug}/publish`),
	unpublishBook: (slug: string) => send<BookSummary>('POST', `/api/books/${slug}/unpublish`),
	deleteBook: (slug: string) => send<{ deleted: string }>('DELETE', `/api/books/${slug}`),
	bookPassages: (index: number, books: string[]) =>
		get<{ books: { slug: string; name: string; passages: BookPassage[] }[] }>(
			`/api/books/passages/${index}?books=${encodeURIComponent(books.join(','))}`
		),
	bookPageUrl: (slug: string, n: number) => `/api/books/${slug}/pages/${n}`,
	getReadingSettings: () => get<ReadingSettings>('/api/settings/reading'),
	setReadingSettings: (s: { reversal_chance: number }) =>
		send<ReadingSettings>('PUT', '/api/settings/reading', s),
	getLlmSettings: () => get<LlmSettings>('/api/settings/llm'),
	setLlmSettings: (s: { base_url?: string; model?: string; api_key?: string }) =>
		send<LlmSettings>('PUT', '/api/settings/llm', s),
	interpret: (question: string | null, spread: string, cards: DrawnCard[], persona?: string, books: string[] = []) =>
		send<{ interpretation: string }>('POST', '/api/interpret', {
			question,
			spread,
			cards,
			persona: persona || null,
			books
		}),
	personas: () => get<{ personas: Persona[]; default: string }>('/api/personas'),
	getMySettings: () => get<UserSettings>('/api/settings/me'),
	getLimitsSettings: () => get<LimitsSettings>('/api/settings/limits'),
	setLimitsSettings: (s: {
		readings_per_day?: number;
		llm_tokens_per_day?: number;
		tts_minutes_per_day?: number;
	}) => send<LimitsSettings>('PUT', '/api/settings/limits', s),
	setMySettings: (s: Partial<UserSettings>) => send<UserSettings>('PUT', '/api/settings/me', s),
	adminUsage: (days: number) => get<UsageSummary>(`/api/admin/usage?days=${days}`),
	getTtsSettings: () => get<TtsSettings>('/api/settings/tts'),
	setTtsSettings: (s: {
		base_url?: string;
		model?: string;
		api_key?: string;
		voices?: Record<string, VoiceBlock>;
	}) => send<TtsSettings>('PUT', '/api/settings/tts', s),
	/** Spoken audio for a persisted interpretation piece (-1 = whole picture).
	 * Optional persona overrides the voice (text stays as written). */
	readingAudio: (id: number, position: number, persona?: string | null) =>
		`/api/readings/${id}/audio/${position}` +
		(persona ? `?persona=${encodeURIComponent(persona)}` : ''),
	/** Audio for ephemeral text (the quick reading). Returns an object URL. */
	speak: async (text: string, persona?: string | null): Promise<string> => {
		const res = await fetch('/api/tts', {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify({ text, persona: persona || null })
		});
		if (!res.ok) throw new Error(`tts: ${res.status}`);
		return URL.createObjectURL(await res.blob());
	},
	cards: () => get<Card[]>('/api/cards'),
	decks: async () => {
		const ds = await get<DeckSummary[]>('/api/decks');
		for (const d of ds) deckArtVersions[d.slug] = d.art_version;
		return ds;
	},
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
	streamFocused: (id: number, position: number, persona: string | null, signal: AbortSignal, books: string[] = []) =>
		streamSSE(`/api/readings/${id}/interpret/focused/${position}`, { persona, books }, signal),
	streamComprehensive: (id: number, persona: string | null, signal: AbortSignal, books: string[] = []) =>
		streamSSE(`/api/readings/${id}/interpret/comprehensive`, { persona, books }, signal),
	saveReading: (r: Reading & { notes?: string; books?: string[] }) => send<SavedReading>('POST', '/api/readings', r),
	updateReading: (id: number, patch: { notes?: string }) =>
		send<SavedReading>('PATCH', `/api/readings/${id}`, patch),
	users: () => get<Person[]>('/api/users'),
	account: () => get<Account>('/api/account'),
	setSharing: (id: number, visibility: Visibility, grantees: string[] = []) =>
		send<SavedReading>('PUT', `/api/readings/${id}/sharing`, { visibility, grantees }),
	deleteReading: (id: number) => send<{ deleted: number }>('DELETE', `/api/readings/${id}`),
	cardImage: (deck: string, index: number, reversed = false) => {
		const q = [reversed ? 'reversed=1' : '', artVersion(deck)].filter(Boolean).join('&');
		return `/api/decks/${deck}/cards/${index}${q ? `?${q}` : ''}`;
	},
	backImage: (deck: string) => {
		const v = artVersion(deck);
		return `/api/decks/${deck}/back${v ? `?${v}` : ''}`;
	},
	coverImage: (deck: string) => {
		const v = artVersion(deck);
		return `/api/decks/${deck}/cover${v ? `?${v}` : ''}`;
	}
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

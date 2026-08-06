<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		cardMeta,
		deckCardName,
		type BookSummary,
		type Card as CardType,
		type DeckSummary,
		type DrawnCard,
		type Persona,
		type SavedReading
	} from '$lib/api';
	import AudioButton from '$lib/AudioButton.svelte';
	import BookPicker from '$lib/BookPicker.svelte';
	import Card from '$lib/Card.svelte';
	import Lightbox from '$lib/Lightbox.svelte';
	import { toParagraphs } from '$lib/text';
	import { readingStore } from '$lib/reading.svelte';
	import { prefGuidedMode, prefPersona } from '$lib/prefs.svelte';

	// A guided reading is a persisted, resumable resource. We arrive either with a
	// fresh draw in the store (create it), or with ?id to resume a saved one.
	const resumeId = $derived(page.url.searchParams.get('id'));

	let reading = $state<SavedReading | null>(null);
	let decks = $state<DeckSummary[]>([]);
	// Derived, not set in a .then — api.decks() often resolves before `reading`
	// is assigned, which would strand deckInfo at null (deck renames/name/back).
	const deckInfo = $derived(decks.find((d) => d.slug === reading?.deck) ?? null);
	// Infobox excerpts: deck-curated companions always show, plus the picker's set.
	const infoboxBooks = $derived.by(() => {
		const visible = new Set(allBooks.map((b) => b.slug));
		const curated = (deckInfo?.books ?? []).filter((s) => visible.has(s));
		return [...new Set([...curated, ...books])];
	});
	let personas = $state<Persona[]>([]);
	let persona = $state<string | null>(null);
	// Guidebooks informing this reading: seeded from the reading's recorded set
	// (resume), else the deck's companion books, else the user's default set.
	let allBooks = $state<BookSummary[]>([]);
	let books = $state<string[]>([]);
	let defaultBooks: string[] = [];
	let booksLoaded = false, meLoaded = false, decksLoaded = false, booksSeeded = false;

	function seedBooks() {
		if (booksSeeded || !reading || !booksLoaded || !meLoaded || !decksLoaded) return;
		booksSeeded = true;
		const visible = new Set(allBooks.map((b) => b.slug));
		const recorded = (reading.books ?? []).filter((s) => visible.has(s));
		if (recorded.length) {
			books = recorded;
			return;
		}
		const deckBooks = decks.find((d) => d.slug === reading!.deck)?.books ?? [];
		const companions = deckBooks.filter((s) => visible.has(s));
		books = companions.length ? companions : defaultBooks.filter((s) => visible.has(s));
	}
	let error = $state('');

	// Per-card focused text + the comprehensive, streamed live and seeded from
	// the persisted reading on resume.
	let focused = $state<Record<number, string>>({});
	let comprehensive = $state('');
	let flipped = $state<boolean[]>([]);
	let streaming = $state<number | 'comprehensive' | null>(null);
	let zoomedIdx = $state<number | null>(null);
	const zoomed = $derived(zoomedIdx !== null && reading ? reading.cards[zoomedIdx] : null);
	let meta = $state<CardType[]>([]);
	let ctrl: AbortController | null = null;
	// Resolves when the init() metadata lookups have all landed; streams wait
	// on it so the first card never goes out with a null persona / empty books.
	let lookupsReady: Promise<void> = Promise.resolve();

	let ttsEnabled = $state(false);
	// bind:this refs so auto-read can start a piece the moment it finishes streaming
	let audioBtns = $state<(ReturnType<typeof AudioButton> | undefined)[]>([]);
	let compBtn = $state<ReturnType<typeof AudioButton> | undefined>(undefined);
	// per-user server-side setting (follows the account across devices)
	let autoRead = $state(false);

	async function setAutoRead(v: boolean) {
		autoRead = v;
		try {
			await api.setMySettings({ auto_read_audio: v });
		} catch {
			autoRead = !v; // revert on failure so the checkbox reflects reality
		}
	}

	const cards = $derived(reading?.cards ?? []);
	const allRevealed = $derived(cards.length > 0 && flipped.every(Boolean));
	const nextIdx = $derived(flipped.indexOf(false));
	const comprehensiveDone = $derived(!!comprehensive);

	// onMount, not $effect: init() reads readingStore.current and then clears it,
	// which under $effect would retrigger the effect and bounce back to home.
	onMount(() => {
		init();
		return () => ctrl?.abort();
	});

	async function init() {
		try {
			// Lookups run in parallel with the reading create/resume, but they're
			// gathered into one awaited promise: rejections land in this catch
			// (not as unhandled), and streamFocused gates on `lookupsReady` so the
			// first card can't stream before the persona and book set are known.
			lookupsReady = Promise.all([
				api.decks().then((d) => {
					decks = d;
					decksLoaded = true;
					seedBooks();
				}),
				api.me().then((m) => {
					ttsEnabled = m.tts;
					autoRead = m.settings.auto_read_audio;
					defaultBooks = m.settings.default_books;
					meLoaded = true;
					seedBooks();
				}),
				api.books().then((b) => {
					allBooks = b;
					booksLoaded = true;
					seedBooks();
				}),
				api.personas().then((p) => {
					personas = p.personas;
					if (!p.personas.some((x) => x.slug === prefPersona.value)) prefPersona.value = p.default;
					persona = prefPersona.value;
				}),
				cardMeta().then((m) => (meta = m))
			]).then(() => {});

			if (resumeId) {
				reading = await api.reading(Number(resumeId));
			} else if (readingStore.current) {
				const r = readingStore.current;
				reading = await api.createGuidedReading({
					deck: r.deck,
					spread: r.spread,
					question: r.question,
					cards: r.cards,
					mode: prefGuidedMode.value === 'cumulative' ? 'cumulative' : 'isolated'
				});
				readingStore.set(null); // it's persisted now; the store copy is redundant
				// Stamp the id into the URL so a refresh resumes instead of redirecting home.
				goto(`/reading/guided?id=${reading.id}`, { replaceState: true, noScroll: true });
			} else {
				goto('/');
				return;
			}
			seedFromPersisted();
			await lookupsReady;
			seedBooks();
		} catch (e) {
			error = errMsg(e);
		}
	}

	function seedFromPersisted() {
		if (!reading) return;
		const it = reading.interpretation;
		focused = {};
		for (const [pos, text] of Object.entries(it.focused ?? {})) focused[Number(pos)] = text;
		comprehensive = it.comprehensive ?? '';
		const done = new Set(it.done_positions ?? []);
		// A resumed reading shows already-read cards face-up; the rest face-down.
		flipped = reading.cards.map((_, i) => done.has(i));
	}

	function cardName(d: DrawnCard): string {
		return deckCardName(d.card.name, deckInfo ?? undefined);
	}

	async function flip(i: number) {
		// Reveal in order: only the next unflipped card is flippable, so
		// cumulative mode always has the prior cards' readings to build on.
		if (!reading || flipped[i] || streaming !== null || i !== nextIdx) return;
		flipped[i] = true;
		if (!focused[i]) await streamFocused(i);
	}

	async function streamFocused(i: number) {
		if (!reading || streaming !== null) return;
		// Claim the stream slot before waiting, so a second flip can't slip
		// past the guard while this one is parked on the lookups.
		streaming = i;
		// A rejection here already surfaced via init()'s catch — swallow it.
		await lookupsReady.catch(() => {});
		focused[i] = '';
		error = '';
		ctrl = new AbortController();
		let ok = false;
		try {
			for await (const ev of api.streamFocused(reading.id, i, persona, ctrl.signal, books)) {
				if (ev.type === 'token') focused[i] += ev.data.text;
				else if (ev.type === 'done') ok = true;
				else if (ev.type === 'error') error = ev.data.message;
			}
		} catch (e) {
			if ((e as Error).name !== 'AbortError') error = errMsg(e);
		} finally {
			streaming = null;
			// Failed/aborted mid-stream: drop the un-persisted partial so the
			// "Read this card" retry button shows instead of stranding it.
			if (!ok) focused[i] = '';
		}
		if (ok && autoRead) {
			await tick(); // the button mounts on the same state change
			audioBtns[i]?.play();
		}
	}

	async function revealWholePicture() {
		if (!reading || streaming !== null) return;
		streaming = 'comprehensive';
		await lookupsReady.catch(() => {});
		comprehensive = '';
		error = '';
		ctrl = new AbortController();
		let ok = false;
		try {
			for await (const ev of api.streamComprehensive(reading.id, persona, ctrl.signal, books)) {
				if (ev.type === 'token') comprehensive += ev.data.text;
				else if (ev.type === 'done') ok = true;
				else if (ev.type === 'error') error = ev.data.message;
			}
		} catch (e) {
			if ((e as Error).name !== 'AbortError') error = errMsg(e);
		} finally {
			streaming = null;
			if (!ok) comprehensive = ''; // failed: show the Reveal button again to retry
		}
		if (ok && autoRead) {
			await tick();
			compBtn?.play();
		}
	}

	function retryFocused(i: number) {
		if (streaming !== null) return; // same guard as flip: never two streams at once
		error = '';
		streamFocused(i);
	}

	// 429 limit messages (and any API detail) must read verbatim, not "Error: …"
	function errMsg(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	function nav(dir: -1 | 1) {
		// arrow keys browse the revealed cards only
		if (zoomedIdx === null || !reading) return;
		const n = reading.cards.length;
		let j = zoomedIdx;
		do {
			j = (j + dir + n) % n;
		} while (!flipped[j] && j !== zoomedIdx);
		zoomedIdx = j;
	}

	let discarding = $state(false);
	async function discard() {
		if (!reading || discarding) return;
		const done = reading.interpretation.status === 'complete';
		if (!confirm(done ? 'Delete this reading from your journal?' : 'Discard this unfinished reading?'))
			return;
		discarding = true;
		ctrl?.abort(); // stop any in-flight stream before deleting
		try {
			await api.deleteReading(reading.id);
			readingStore.set(null);
			goto('/');
		} catch (e) {
			error = errMsg(e);
			discarding = false;
		}
	}
</script>

{#if error && !reading}
	<p class="error">{error}</p>
	<button onclick={() => goto('/')}>New reading</button>
{:else if reading}
	<section class="guided">
		<header class="head">
			<div>
				{#if reading.question}<h1>“{reading.question}”</h1>{/if}
				<p class="dim">
					{deckInfo?.name ?? reading.deck} · a guided walkthrough — reveal each card to hear it
				</p>
			</div>
			<div class="actions">
				<!-- Mid-reading switches apply from the next card on; already-read
				     cards keep the persona (and voice) that read them. -->
				<BookPicker available={allBooks} bind:selected={books} />
				<select
					class="reader"
					bind:value={persona}
					onchange={() => { if (persona) prefPersona.value = persona; }}
					aria-label="Reader persona"
				>
					{#each personas as p (p.slug)}
						<option value={p.slug} title={p.description}>{p.name}</option>
					{/each}
				</select>
				{#if ttsEnabled}
					<label class="autoread" title="Speak each reading aloud as it completes (saved to your account)">
						<input
							type="checkbox"
							checked={autoRead}
							onchange={(e) => setAutoRead(e.currentTarget.checked)}
						/>
						🔊 Read aloud
					</label>
				{/if}
				<a class="link" href="/journal/{reading.id}">Saved to journal ✓</a>
				<button onclick={() => { readingStore.set(null); goto('/'); }}>New reading</button>
				<button class="danger" onclick={discard} disabled={discarding}>
					{discarding ? 'Discarding…' : 'Discard'}
				</button>
			</div>
		</header>

		<ol class="cards">
			{#each cards as drawn, i (i)}
				<li class:isnext={i === nextIdx && streaming === null}>
					<!-- Card stops propagation on a face-down click (which flips it), so a
					     click that reaches here is a face-up card -> show full-size art. -->
					<div
						class="cardcol"
						role="presentation"
						onclick={() => { if (flipped[i]) zoomedIdx = i; }}
					>
						<Card
							{drawn}
							deck={reading.deck}
							displayName={cardName(drawn)}
							hasBack={deckInfo?.has_back ?? false}
							reversedArt={deckInfo?.reversed_indices.includes(drawn.card.index) ?? false}
							next={i === nextIdx && streaming === null}
							showTip={false}
							bind:flipped={() => flipped[i], (v) => { if (v) flip(i); }}
						/>
						<span class="pos">{drawn.position.name}</span>
					</div>
					<div class="reading">
						{#if flipped[i]}
							<h3>
								<button class="namelink" onclick={() => (zoomedIdx = i)}>
									{cardName(drawn)}{drawn.reversed ? ' (reversed)' : ''}
								</button>
								{#if ttsEnabled && focused[i] && streaming !== i}
									{#key persona}
										<AudioButton
											bind:this={audioBtns[i]}
											src={api.readingAudio(reading.id, i, persona)}
											label="Read this card aloud"
										/>
									{/key}
								{/if}
							</h3>
							{#if focused[i]}
								{@const paras = toParagraphs(focused[i])}
								{#each paras as para, p (p)}
									<p>{para}{#if streaming === i && p === paras.length - 1}<span class="caret">▋</span>{/if}</p>
								{/each}
							{:else if streaming === i}
								<p class="dim">consulting the cards…</p>
							{:else}
								<button class="retry" onclick={() => retryFocused(i)}>Read this card</button>
							{/if}
						{:else}
							<p class="dim tap">{i === nextIdx ? 'Tap the card to reveal it' : 'Reveal the cards in order'}</p>
						{/if}
					</div>
				</li>
			{/each}
		</ol>

		<!-- A single-card reading IS its own whole picture — no synthesis step. -->
		{#if allRevealed && cards.length > 1}
			<section class="comprehensive">
				<h2>
					The whole picture
					{#if ttsEnabled && comprehensive && streaming !== 'comprehensive'}
						{#key persona}
							<AudioButton
								bind:this={compBtn}
								src={api.readingAudio(reading.id, -1, persona)}
								label="Read the whole picture aloud"
							/>
						{/key}
					{/if}
				</h2>
				{#if comprehensive}
					{@const cparas = toParagraphs(comprehensive)}
					{#each cparas as para, i (i)}
						<p>{para}{#if streaming === 'comprehensive' && i === cparas.length - 1}<span class="caret">▋</span>{/if}</p>
					{/each}
				{:else if streaming === 'comprehensive'}
					<p class="dim">drawing the threads together…</p>
				{:else}
					<button class="reveal" onclick={revealWholePicture}>✶ Reveal the whole picture</button>
				{/if}
			</section>
		{/if}

		{#if error}<p class="error">{error}</p>{/if}
	</section>

	{#if zoomed}
		{#key zoomedIdx}
			<Lightbox
				deck={reading.deck}
				view={zoomed}
				{meta}
				renames={deckInfo ?? undefined}
				onclose={() => (zoomedIdx = null)}
				onnav={nav}
				books={infoboxBooks}
			/>
		{/key}
	{/if}
{/if}

<style>
	.cardcol {
		cursor: pointer;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
		margin-bottom: 1.5rem;
	}
	.head h1 {
		margin: 0;
	}
	.actions {
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}
	.link {
		color: var(--accent);
	}
	.reader {
		width: auto;
	}
	.autoread {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--text-dim);
		font-size: 0.9rem;
		cursor: pointer;
	}
	.autoread input {
		accent-color: var(--gold);
	}
	.danger {
		border-color: var(--danger);
	}
	.cards {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 1.4rem;
	}
	.cards li {
		display: grid;
		grid-template-columns: minmax(7rem, 9rem) 1fr;
		gap: 1.2rem;
		align-items: start;
	}
	.cardcol {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.35rem;
	}
	.pos {
		font-size: 0.85rem;
		color: var(--text-dim);
		text-align: center;
	}
	.reading {
		padding-top: 0.2rem;
		min-height: 3rem;
	}
	.reading h3 {
		margin: 0 0 0.4rem;
		font-size: 1rem;
	}
	.namelink {
		all: unset;
		cursor: pointer;
	}
	.namelink:hover {
		color: var(--gold);
	}
	.reading p {
		margin: 0 0 0.6rem;
		line-height: 1.6;
	}
	.tap {
		font-style: italic;
	}
	.caret {
		animation: blink 1s steps(2) infinite;
	}
	@keyframes blink {
		0%,
		50% {
			opacity: 1;
		}
		50.01%,
		100% {
			opacity: 0;
		}
	}
	.comprehensive {
		margin-top: 2rem;
		padding-top: 1.2rem;
		border-top: 1px solid var(--border);
	}
	.comprehensive p {
		line-height: 1.7;
	}
	.reveal,
	.retry {
		font-size: 0.95rem;
	}
	.retry {
		font-size: 0.8rem;
	}
	.error {
		color: var(--danger, #e57373);
	}
	@media (max-width: 560px) {
		.cards li {
			grid-template-columns: 1fr;
		}
	}
</style>

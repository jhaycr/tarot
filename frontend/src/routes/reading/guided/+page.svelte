<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		cardMeta,
		deckCardName,
		type Card as CardType,
		type DeckSummary,
		type DrawnCard,
		type Persona,
		type SavedReading
	} from '$lib/api';
	import Card from '$lib/Card.svelte';
	import CardDetail from '$lib/CardDetail.svelte';
	import { toParagraphs } from '$lib/text';
	import { readingStore } from '$lib/reading.svelte';
	import { prefPersona, prefGuidedMode } from '$lib/prefs.svelte';

	// A guided reading is a persisted, resumable resource. We arrive either with a
	// fresh draw in the store (create it), or with ?id to resume a saved one.
	const resumeId = $derived(page.url.searchParams.get('id'));

	let reading = $state<SavedReading | null>(null);
	let decks = $state<DeckSummary[]>([]);
	// Derived, not set in a .then — api.decks() often resolves before `reading`
	// is assigned, which would strand deckInfo at null (deck renames/name/back).
	const deckInfo = $derived(decks.find((d) => d.slug === reading?.deck) ?? null);
	let personas = $state<Persona[]>([]);
	let persona = $state<string | null>(null);
	let error = $state('');

	// Per-card focused text + the comprehensive, streamed live and seeded from
	// the persisted reading on resume.
	let focused = $state<Record<number, string>>({});
	let comprehensive = $state('');
	let flipped = $state<boolean[]>([]);
	let streaming = $state<number | 'comprehensive' | null>(null);
	let zoomed = $state<DrawnCard | null>(null);
	let meta = $state<CardType[]>([]);
	let ctrl: AbortController | null = null;

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
			api.decks().then((d) => (decks = d));
			api.personas().then((p) => {
				personas = p.personas;
				persona = prefPersona.value;
			});
			cardMeta().then((m) => (meta = m));

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
		} catch (e) {
			error = String(e);
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
		if (!reading) return;
		streaming = i;
		focused[i] = '';
		error = '';
		ctrl = new AbortController();
		let ok = false;
		try {
			for await (const ev of api.streamFocused(reading.id, i, persona, ctrl.signal)) {
				if (ev.type === 'token') focused[i] += ev.data.text;
				else if (ev.type === 'done') ok = true;
				else if (ev.type === 'error') error = ev.data.message;
			}
		} catch (e) {
			if ((e as Error).name !== 'AbortError') error = String(e);
		} finally {
			streaming = null;
			// Failed/aborted mid-stream: drop the un-persisted partial so the
			// "Read this card" retry button shows instead of stranding it.
			if (!ok) focused[i] = '';
		}
	}

	async function revealWholePicture() {
		if (!reading || streaming !== null) return;
		streaming = 'comprehensive';
		comprehensive = '';
		error = '';
		ctrl = new AbortController();
		let ok = false;
		try {
			for await (const ev of api.streamComprehensive(reading.id, persona, ctrl.signal)) {
				if (ev.type === 'token') comprehensive += ev.data.text;
				else if (ev.type === 'done') ok = true;
				else if (ev.type === 'error') error = ev.data.message;
			}
		} catch (e) {
			if ((e as Error).name !== 'AbortError') error = String(e);
		} finally {
			streaming = null;
			if (!ok) comprehensive = ''; // failed: show the Reveal button again to retry
		}
	}

	function retryFocused(i: number) {
		error = '';
		streamFocused(i);
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
			error = String(e);
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
						onclick={() => { if (flipped[i]) zoomed = drawn; }}
					>
						<Card
							{drawn}
							deck={reading.deck}
							displayName={cardName(drawn)}
							hasBack={deckInfo?.has_back ?? false}
							next={i === nextIdx && streaming === null}
							showTip={false}
							bind:flipped={() => flipped[i], (v) => { if (v) flip(i); }}
						/>
						<span class="pos">{drawn.position.name}</span>
					</div>
					<div class="reading">
						{#if flipped[i]}
							<h3>{cardName(drawn)}{drawn.reversed ? ' (reversed)' : ''}</h3>
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

		{#if allRevealed}
			<section class="comprehensive">
				<h2>The whole picture</h2>
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
		<div class="lightbox" role="presentation" onclick={() => (zoomed = null)}>
			<div class="zoomview">
				<figure role="presentation" onclick={(e) => e.stopPropagation()}>
					<img src={api.cardImage(reading.deck, zoomed.card.index)} alt={zoomed.card.name} />
					<figcaption>
						{cardName(zoomed)}{zoomed.reversed ? ' (reversed)' : ''} — {zoomed.position.name}
					</figcaption>
				</figure>
				<div class="zoominfo" role="presentation" onclick={(e) => e.stopPropagation()}>
					<CardDetail drawn={zoomed} {meta} renames={deckInfo ?? undefined} />
				</div>
				<button class="zoomclose" onclick={() => (zoomed = null)} aria-label="Close">✕</button>
			</div>
		</div>
	{/if}
{/if}

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') zoomed = null; }} />

<style>
	.cardcol {
		cursor: pointer;
	}
	.lightbox {
		position: fixed;
		inset: 0;
		background: rgba(10, 8, 20, 0.88);
		display: grid;
		place-items: center;
		z-index: 20;
		cursor: zoom-out;
		padding: 1.5rem;
	}
	.zoomview {
		position: relative;
		display: flex;
		gap: 1.5rem;
		align-items: flex-start;
		max-width: min(64rem, 96vw);
		max-height: 90dvh;
		cursor: default;
	}
	.zoomview figure {
		margin: 0;
		text-align: center;
		flex: 0 0 auto;
	}
	.zoomview img {
		max-height: 80dvh;
		max-width: min(48vw, 26rem);
		border-radius: 10px;
	}
	.zoomview figcaption {
		margin-top: 0.6rem;
		color: var(--gold-bright);
	}
	.zoominfo {
		flex: 1 1 22rem;
		max-width: 26rem;
		max-height: 80dvh;
		overflow-y: auto;
	}
	.zoominfo :global(.detail) {
		margin: 0;
	}
	.zoomclose {
		position: absolute;
		top: -0.6rem;
		right: -0.6rem;
		border-radius: 999px;
		width: 2rem;
		height: 2rem;
		padding: 0;
		line-height: 1;
	}
	@media (max-width: 640px) {
		.zoomview {
			flex-direction: column;
			align-items: center;
			overflow-y: auto;
		}
		.zoomview img {
			max-width: 80vw;
			max-height: 55dvh;
		}
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

<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import {
		api,
		deckCardName,
		type DeckSummary,
		type DrawnCard,
		type Persona,
		type SavedReading
	} from '$lib/api';
	import Card from '$lib/Card.svelte';
	import { toParagraphs } from '$lib/text';
	import { readingStore } from '$lib/reading.svelte';
	import { prefPersona, prefGuidedMode } from '$lib/prefs.svelte';

	// A guided reading is a persisted, resumable resource. We arrive either with a
	// fresh draw in the store (create it), or with ?id to resume a saved one.
	const resumeId = $derived(page.url.searchParams.get('id'));

	let reading = $state<SavedReading | null>(null);
	let deckInfo = $state<DeckSummary | null>(null);
	let personas = $state<Persona[]>([]);
	let persona = $state<string | null>(null);
	let error = $state('');

	// Per-card focused text + the comprehensive, streamed live and seeded from
	// the persisted reading on resume.
	let focused = $state<Record<number, string>>({});
	let comprehensive = $state('');
	let flipped = $state<boolean[]>([]);
	let streaming = $state<number | 'comprehensive' | null>(null);
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
			api.decks().then((d) => {
				if (reading) deckInfo = d.find((x) => x.slug === reading!.deck) ?? null;
			});
			api.personas().then((p) => {
				personas = p.personas;
				persona = prefPersona.value;
			});

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
		if (!reading || flipped[i] || streaming !== null) return;
		flipped[i] = true;
		if (!focused[i]) await streamFocused(i);
	}

	async function streamFocused(i: number) {
		if (!reading) return;
		streaming = i;
		focused[i] = '';
		ctrl = new AbortController();
		try {
			for await (const ev of api.streamFocused(reading.id, i, persona, ctrl.signal)) {
				if (ev.type === 'token') focused[i] += ev.data.text;
				else if (ev.type === 'error') error = ev.data.message;
			}
		} catch (e) {
			if ((e as Error).name !== 'AbortError') error = String(e);
		} finally {
			streaming = null;
		}
	}

	async function revealWholePicture() {
		if (!reading || streaming !== null) return;
		streaming = 'comprehensive';
		comprehensive = '';
		error = '';
		ctrl = new AbortController();
		try {
			for await (const ev of api.streamComprehensive(reading.id, persona, ctrl.signal)) {
				if (ev.type === 'token') comprehensive += ev.data.text;
				else if (ev.type === 'error') error = ev.data.message;
			}
		} catch (e) {
			if ((e as Error).name !== 'AbortError') error = String(e);
		} finally {
			streaming = null;
		}
	}

	function retryFocused(i: number) {
		error = '';
		streamFocused(i);
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
			</div>
		</header>

		<ol class="cards">
			{#each cards as drawn, i (i)}
				<li class:isnext={i === nextIdx && streaming === null}>
					<div class="cardcol">
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
{/if}

<style>
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

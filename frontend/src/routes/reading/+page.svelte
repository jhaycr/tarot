<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, cardMeta, type Card as CardType, type DeckSummary, type DrawnCard } from '$lib/api';
	import Card from '$lib/Card.svelte';
	import { readingStore } from '$lib/reading.svelte';

	const reading = readingStore.current;

	let decks = $state<DeckSummary[]>([]);
	let meta = $state<CardType[]>([]);
	let flips = $state<boolean[]>(reading ? reading.cards.map(() => false) : []);
	let selected = $state<number | null>(null);
	let savedId = $state<number | null>(null);
	let saving = $state(false);
	let llmEnabled = $state(false);
	let interpretation = $state('');
	let interpreting = $state(false);
	let interpretError = $state('');

	$effect(() => {
		if (!reading) goto('/');
		else {
			api.decks().then((d) => (decks = d));
			cardMeta().then((c) => (meta = c));
			api.me().then((m) => (llmEnabled = m.interpretation));
		}
	});

	const deckInfo = $derived(decks.find((d) => d.slug === reading?.deck));
	const allFlipped = $derived(flips.every(Boolean));
	const cols = $derived(reading ? Math.max(...reading.cards.map((c) => c.position.col)) : 1);
	const rows = $derived(reading ? Math.max(...reading.cards.map((c) => c.position.row)) : 1);

	function cellCards(col: number, row: number): { drawn: DrawnCard; i: number }[] {
		return (reading?.cards ?? [])
			.map((drawn, i) => ({ drawn, i }))
			.filter(({ drawn }) => drawn.position.col === col && drawn.position.row === row);
	}

	function meaning(drawn: DrawnCard): string | null {
		const m = meta.find((c) => c.index === drawn.card.index);
		if (!m) return null;
		return (drawn.reversed ? m.reversed_meaning : m.upright) ?? null;
	}

	function revealAll() {
		flips = flips.map(() => true);
	}

	async function save() {
		if (!reading || savedId) return;
		saving = true;
		try {
			const notes = interpretation ? `AI interpretation:\n${interpretation}` : '';
			const saved = await api.saveReading({ ...reading, notes });
			savedId = saved.id;
		} finally {
			saving = false;
		}
	}

	async function interpret() {
		if (!reading || interpreting) return;
		interpreting = true;
		interpretError = '';
		try {
			const res = await api.interpret(reading.question, reading.spread, reading.cards);
			interpretation = res.interpretation;
		} catch (e) {
			interpretError = String(e);
		} finally {
			interpreting = false;
		}
	}
</script>

{#if reading}
	<section class="reading">
		<header class="head">
			<div>
				{#if reading.question}<h1>“{reading.question}”</h1>{/if}
				<p class="dim">{deckInfo?.name ?? reading.deck} · tap a card to reveal it</p>
			</div>
			<div class="actions">
				{#if !allFlipped}
					<button onclick={revealAll}>Reveal all</button>
				{:else if savedId}
					<a class="saved" href="/journal/{savedId}">Saved ✓</a>
				{:else}
					<button onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save to journal'}</button>
				{/if}
				<button onclick={() => { readingStore.set(null); goto('/'); }}>New reading</button>
			</div>
		</header>

		<div class="table" style="--cols: {cols}; --rows: {rows};">
			{#each Array(rows) as _, r (r)}
				{#each Array(cols) as _, c (c)}
					{@const cell = cellCards(c + 1, r + 1)}
					{#if cell.length}
						<div class="cell" style="grid-column: {c + 1}; grid-row: {r + 1};">
							{#each cell as { drawn, i } (i)}
								<div
									class="slot"
									class:overlay={drawn.position.cross}
									class:selected={selected === i}
									role="presentation"
									onclick={() => { if (flips[i]) selected = i; }}
								>
									<Card
										{drawn}
										deck={reading.deck}
										hasBack={deckInfo?.has_back ?? false}
										cross={drawn.position.cross ?? false}
										bind:flipped={
											() => flips[i],
											(v) => { flips[i] = v; if (v) selected = i; }
										}
									/>
									<span class="pos">{drawn.position.name}</span>
								</div>
							{/each}
						</div>
					{/if}
				{/each}
			{/each}
		</div>

		{#if selected !== null && flips[selected]}
			{@const drawn = reading.cards[selected]}
			<aside class="detail">
				<h2>
					{drawn.card.name}
					{#if drawn.reversed}<span class="rev">reversed</span>{/if}
				</h2>
				<p class="dim">{drawn.position.name} — {drawn.position.meaning}</p>
				{#if meaning(drawn)}
					<p class="meaning">{meaning(drawn)}</p>
				{/if}
			</aside>
		{/if}

		{#if llmEnabled && allFlipped}
			<aside class="interpretation">
				{#if interpretation}
					<h2>Interpretation</h2>
					{#each interpretation.split('\n\n') as para, i (i)}
						<p>{para}</p>
					{/each}
				{:else}
					<button onclick={interpret} disabled={interpreting}>
						{interpreting ? 'Consulting the cards…' : '✶ Interpret this reading'}
					</button>
					{#if interpretError}<p class="error">{interpretError}</p>{/if}
				{/if}
			</aside>
		{/if}
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
		font-size: 1.3rem;
	}

	.actions {
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}

	.saved {
		color: var(--gold);
	}

	.table {
		display: grid;
		grid-template-columns: repeat(var(--cols), minmax(0, 10rem));
		gap: 1.2rem;
		justify-content: center;
	}

	.cell {
		position: relative;
	}

	.slot {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		align-items: center;
	}

	.slot.overlay {
		position: absolute;
		inset: 0 0 auto 0;
		z-index: 2;
	}

	.slot.overlay .pos {
		display: none;
	}

	.slot.selected .pos {
		color: var(--gold);
	}

	.pos {
		font-size: 0.8rem;
		color: var(--text-dim);
		text-align: center;
	}

	.detail {
		margin: 2rem auto 0;
		max-width: 40rem;
		background: var(--bg-raised);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1.2rem 1.5rem;
	}

	.meaning {
		color: var(--gold-bright);
	}

	.rev {
		font-size: 0.8rem;
		color: var(--danger);
		margin-left: 0.5rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.dim {
		color: var(--text-dim);
	}

	.interpretation {
		margin: 2rem auto 0;
		max-width: 40rem;
		text-align: center;
	}

	.interpretation h2 {
		text-align: left;
	}

	.interpretation p {
		text-align: left;
	}

	.error {
		color: var(--danger);
	}

	@media (max-width: 640px) {
		.table {
			grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
			gap: 0.6rem;
		}
	}
</style>

<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type DeckSummary, type DrawnCard } from '$lib/api';
	import Card from '$lib/Card.svelte';
	import { readingStore } from '$lib/reading.svelte';

	const reading = readingStore.current;

	let decks = $state<DeckSummary[]>([]);
	let flips = $state<boolean[]>(reading ? reading.cards.map(() => false) : []);
	let selected = $state<number | null>(null);

	$effect(() => {
		if (!reading) goto('/');
		else api.decks().then((d) => (decks = d));
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

	function revealAll() {
		flips = flips.map(() => true);
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
				<p class="dim">
					{drawn.position.name} — {drawn.position.meaning}
				</p>
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

	@media (max-width: 640px) {
		.table {
			grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
			gap: 0.6rem;
		}
	}
</style>

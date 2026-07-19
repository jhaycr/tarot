<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, cardMeta, type Card as CardType, type DeckSummary, type DrawnCard, type Persona } from '$lib/api';
	import { prefPersona } from '$lib/prefs.svelte';
	import Card from '$lib/Card.svelte';
	import CardDetail from '$lib/CardDetail.svelte';
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
	let personas = $state<Persona[]>([]);
	let hasCustom = $state(false);

	$effect(() => {
		if (!reading) goto('/');
		else {
			api.decks().then((d) => (decks = d));
			cardMeta().then((c) => (meta = c));
			api.me().then((m) => {
				llmEnabled = m.interpretation;
				if (m.interpretation) {
					api.personas().then((p) => {
						personas = p.personas;
						hasCustom = p.has_custom;
						const valid = [...p.personas.map((x) => x.slug), ...(p.has_custom ? ['custom'] : [])];
						if (!valid.includes(prefPersona.value)) prefPersona.value = p.default;
					});
				}
			});
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
			const res = await api.interpret(reading.question, reading.spread, reading.cards, prefPersona.value);
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
			<CardDetail drawn={reading.cards[selected]} {meta} />
		{/if}

		{#if llmEnabled && allFlipped}
			<aside class="interpretation">
				{#if interpretation}
					<h2>Interpretation</h2>
					{#each interpretation.split('\n\n') as para, i (i)}
						<p>{para}</p>
					{/each}
				{:else}
					<div class="ask">
						<select bind:value={prefPersona.value} aria-label="Reader persona">
							{#each personas as p (p.slug)}
								<option value={p.slug} title={p.description}>{p.name}</option>
							{/each}
							{#if hasCustom}<option value="custom">Custom</option>{/if}
						</select>
						<button onclick={interpret} disabled={interpreting}>
							{interpreting ? 'Consulting the cards…' : '✶ Interpret this reading'}
						</button>
					</div>
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

	.ask {
		display: flex;
		gap: 0.6rem;
		justify-content: center;
	}

	.ask select {
		width: auto;
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

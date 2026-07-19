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
	let zoomed = $state<DrawnCard | null>(null);
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
	const nextIdx = $derived(flips.indexOf(false));
	const cols = $derived(reading ? Math.max(...reading.cards.map((c) => c.position.col)) : 1);
	const rows = $derived(reading ? Math.max(...reading.cards.map((c) => c.position.row)) : 1);

	function cellCards(col: number, row: number): { drawn: DrawnCard; i: number }[] {
		return (reading?.cards ?? [])
			.map((drawn, i) => ({ drawn, i }))
			.filter(({ drawn }) => drawn.position.col === col && drawn.position.row === row);
	}

	function keywordsFor(drawn: DrawnCard): string | null {
		const m = meta.find((c) => c.index === drawn.card.index);
		return (drawn.reversed ? m?.reversed_meaning : m?.upright) ?? null;
	}

	function slotClick(i: number) {
		if (!flips[i]) return;
		selected = selected === i ? null : i;
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

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') {
			if (zoomed) zoomed = null;
			else selected = null;
		}
	}}
/>

{#if reading}
	<section class="reading">
		<header class="head">
			<div>
				{#if reading.question}<h1>“{reading.question}”</h1>{/if}
				<p class="dim">
					{deckInfo?.name ?? reading.deck} · tap the glowing card to continue · hover a revealed
					card for the gist, tap it for the full meaning
				</p>
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
									onclick={() => slotClick(i)}
								>
									<Card
										{drawn}
										deck={reading.deck}
										hasBack={deckInfo?.has_back ?? false}
										cross={drawn.position.cross ?? false}
										next={i === nextIdx}
										keywords={keywordsFor(drawn)}
										showTip={selected !== i}
										bind:flipped={
											() => flips[i],
											(v) => { flips[i] = v; }
										}
									/>
									<span class="pos" class:nextpos={i === nextIdx && !flips[i]}>{drawn.position.name}</span>

									{#if selected === i && flips[i]}
										<div
											class="popover"
											class:flip-left={drawn.position.col > cols / 2}
											role="presentation"
											onclick={(e) => e.stopPropagation()}
										>
											<button class="close" onclick={() => (selected = null)} aria-label="Close">✕</button>
											<CardDetail {drawn} {meta} onZoom={() => (zoomed = drawn)} />
										</div>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				{/each}
			{/each}
		</div>

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

	{#if zoomed}
		<div class="lightbox" role="presentation" onclick={() => (zoomed = null)}>
			<figure>
				<img src={api.cardImage(reading.deck, zoomed.card.index)} alt={zoomed.card.name} />
				<figcaption>
					{zoomed.card.name}{zoomed.reversed ? ' (reversed)' : ''} — {zoomed.position.name}
				</figcaption>
			</figure>
		</div>
	{/if}
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
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		align-items: center;
	}

	.slot.overlay {
		position: absolute;
		inset: 0 0 auto 0;
		z-index: 2;
		/* only the rotated card itself catches clicks — the base card under the
		   cross stays reachable at its top and bottom */
		pointer-events: none;
	}

	.slot.overlay :global(.card),
	.slot.overlay .popover {
		pointer-events: auto;
	}

	.slot.overlay .pos {
		display: none;
	}

	.slot.selected {
		z-index: 12;
	}

	.slot.selected .pos {
		color: var(--gold);
	}

	.pos {
		font-size: 0.8rem;
		color: var(--text-dim);
		text-align: center;
	}

	.pos.nextpos {
		color: var(--gold);
	}

	.popover {
		position: absolute;
		top: -0.4rem;
		left: calc(100% + 0.7rem);
		width: 18rem;
		z-index: 12;
		background: var(--bg-raised);
		border: 1px solid var(--gold);
		border-radius: var(--radius);
		box-shadow: 0 12px 34px rgba(0, 0, 0, 0.55);
		cursor: default;
	}

	.popover.flip-left {
		left: auto;
		right: calc(100% + 0.7rem);
	}

	.popover :global(.detail) {
		margin: 0;
		max-width: none;
		background: none;
		border: none;
		padding: 0.9rem 2rem 0.4rem 1rem;
	}

	.popover .close {
		position: absolute;
		top: 0.4rem;
		right: 0.4rem;
		padding: 0.15rem 0.45rem;
		font-size: 0.8rem;
		border-radius: 6px;
	}

	.popover :global(.detail .zoom) {
		margin: 0 0 0.5rem;
	}

	@media (max-width: 700px) {
		.popover,
		.popover.flip-left {
			position: fixed;
			inset: auto 0 0 0;
			width: auto;
			max-height: 65dvh;
			overflow-y: auto;
			border-radius: var(--radius) var(--radius) 0 0;
			border-bottom: none;
		}
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

	.lightbox {
		position: fixed;
		inset: 0;
		background: rgba(10, 8, 20, 0.88);
		display: grid;
		place-items: center;
		z-index: 20;
		cursor: zoom-out;
	}

	.lightbox figure {
		margin: 0;
		text-align: center;
	}

	.lightbox img {
		max-height: 84dvh;
		max-width: 92vw;
		border-radius: 10px;
	}

	.lightbox figcaption {
		margin-top: 0.6rem;
		color: var(--gold-bright);
	}

	@media (max-width: 640px) {
		.table {
			grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
			gap: 0.6rem;
		}
	}
</style>

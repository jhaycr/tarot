<script lang="ts">
	import { page } from '$app/state';
	import { api, deckCardName, type Card, type DeckSummary } from '$lib/api';

	const slug = $derived(page.params.slug!);

	let cards = $state<Card[]>([]);
	let deck = $state<DeckSummary | undefined>(undefined);
	let zoomed = $state<{ index: number; name: string } | null>(null);

	$effect(() => {
		api.cards().then((c) => (cards = c));
		api.decks().then((d) => (deck = d.find((x) => x.slug === slug)));
	});

	const ROMAN = ['0', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII',
		'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX', 'XXI'];

	function displayName(card: Card): string {
		const renamed = deckCardName(card.name, deck);
		return renamed === card.name ? card.name : `${renamed} (${card.name})`;
	}

	function numeral(card: Card): string {
		if (card.arcana === 'major') return ROMAN[card.index];
		if (card.number == null) return '';
		if (card.number === 1) return 'A';
		if (card.number <= 10) return String(card.number);
		return ['P', 'Kn', 'Q', 'K'][card.number - 11];
	}

	const has = $derived((i: number) =>
		deck ? !deck.missing.includes(i) && (!deck.majors_only || i < 22) : true
	);

	const sections = $derived.by(() => {
		const secs: { id: string; title: string; cards: { index: number; name: string; numeral: string }[] }[] = [];
		const majors = cards.filter((c) => c.arcana === 'major' && has(c.index));
		if (majors.length)
			secs.push({
				id: 'majors',
				title: 'Major Arcana',
				cards: majors.map((c) => ({ index: c.index, name: displayName(c), numeral: numeral(c) }))
			});
		for (const suit of ['Wands', 'Cups', 'Swords', 'Pentacles']) {
			const suited = cards.filter((c) => c.suit === suit && has(c.index));
			const renamed = deck?.suit_names?.[suit];
			if (suited.length)
				secs.push({
					id: suit.toLowerCase(),
					title: renamed ? `${renamed} (${suit})` : suit,
					cards: suited.map((c) => ({
						index: c.index,
						name: deckCardName(c.name, deck),
						numeral: numeral(c)
					}))
				});
		}
		if (deck?.extras.length)
			secs.push({
				id: 'extras',
				title: 'Extras',
				cards: deck.extras.map((e, i) => ({ index: e.index, name: e.name, numeral: `+${i + 1}` }))
			});
		return secs;
	});
</script>

<header class="top">
	<div>
		<h1>{deck?.name ?? slug}</h1>
		{#if deck?.attribution || deck?.source}
			<p class="dim">
				{deck?.attribution ?? ''}
				{#if deck?.source}
					· <a href={deck.source} target="_blank" rel="noreferrer">source</a>
				{/if}
			</p>
		{/if}
	</div>
	<a class="export" href="/api/decks/{slug}/export" download="{slug}.zip">⇩ Export zip</a>
</header>

{#if sections.length > 1}
	<nav class="secnav">
		{#each sections as sec (sec.id)}
			<a href="#{sec.id}">{sec.title}</a>
		{/each}
	</nav>
{/if}

{#each sections as sec (sec.id)}
	<section id={sec.id}>
		<h2>{sec.title} <small class="dim">{sec.cards.length}</small></h2>
		<div class="grid">
			{#each sec.cards as card (card.index)}
				<button class="tile" onclick={() => (zoomed = card)}>
					<img src={api.cardImage(slug, card.index)} alt={card.name} loading="lazy" />
					<small>
						{#if card.numeral}<span class="num">{card.numeral}</span>{/if}
						{card.name}
					</small>
				</button>
			{/each}
		</div>
	</section>
{/each}

{#if zoomed}
	<div class="lightbox" role="presentation" onclick={() => (zoomed = null)}>
		<figure>
			<img src={api.cardImage(slug, zoomed.index)} alt={zoomed.name} />
			<figcaption>{zoomed.name}</figcaption>
		</figure>
	</div>
{/if}

<style>
	.top {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.export {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 0.45rem 0.9rem;
		color: var(--text);
	}

	.export:hover {
		border-color: var(--gold);
	}

	.secnav {
		position: sticky;
		top: 0;
		z-index: 5;
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
		padding: 0.6rem 0;
		margin: 0.4rem 0 0.6rem;
		background: linear-gradient(var(--bg) 85%, transparent);
	}

	.secnav a {
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.25rem 0.85rem;
		color: var(--text-dim);
		font-size: 0.85rem;
	}

	.secnav a:hover {
		border-color: var(--gold);
		color: var(--gold);
	}

	section {
		scroll-margin-top: 3.2rem;
		margin-bottom: 1.6rem;
	}

	section h2 {
		font-size: 1.05rem;
		border-bottom: 1px solid var(--border);
		padding-bottom: 0.3rem;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(7.5rem, 1fr));
		gap: 0.9rem;
		margin-top: 0.8rem;
	}

	.tile {
		all: unset;
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.tile img {
		width: 100%;
		aspect-ratio: var(--card-ratio);
		object-fit: cover;
		border-radius: 6px;
		border: 1px solid var(--border);
	}

	.tile:hover img {
		border-color: var(--gold);
	}

	.tile small {
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.num {
		display: inline-block;
		min-width: 1.3em;
		color: var(--gold);
		font-variant: small-caps;
	}

	.lightbox {
		position: fixed;
		inset: 0;
		background: rgba(10, 8, 20, 0.85);
		display: grid;
		place-items: center;
		z-index: 10;
		cursor: zoom-out;
	}

	.lightbox figure {
		margin: 0;
		text-align: center;
	}

	.lightbox img {
		max-height: 82dvh;
		max-width: 92vw;
		border-radius: 10px;
	}

	.lightbox figcaption {
		margin-top: 0.6rem;
		color: var(--gold-bright);
	}

	.dim {
		color: var(--text-dim);
	}
</style>

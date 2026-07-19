<script lang="ts">
	import { page } from '$app/state';
	import { api, type Card, type DeckSummary } from '$lib/api';

	const slug = $derived(page.params.slug!);

	let cards = $state<Card[]>([]);
	let deck = $state<DeckSummary | undefined>(undefined);
	let zoomed = $state<Card | null>(null);

	$effect(() => {
		api.cards().then((c) => (cards = c));
		api.decks().then((d) => (deck = d.find((x) => x.slug === slug)));
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

<div class="grid">
	{#each cards as card (card.index)}
		<button class="tile" onclick={() => (zoomed = card)}>
			<img src={api.cardImage(slug, card.index)} alt={card.name} loading="lazy" />
			<small>{card.name}</small>
		</button>
	{/each}
</div>

{#if zoomed}
	<div class="lightbox" role="presentation" onclick={() => (zoomed = null)}>
		<figure>
			<img src={api.cardImage(slug, zoomed.index)} alt={zoomed.name} />
			<figcaption>{zoomed.name}</figcaption>
		</figure>
	</div>
{/if}

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(7.5rem, 1fr));
		gap: 0.9rem;
		margin-top: 1rem;
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
</style>

<script lang="ts">
	import { api, type DeckSummary } from '$lib/api';

	let decks = $state<DeckSummary[]>([]);
	let loaded = $state(false);

	$effect(() => {
		api.decks().then((d) => {
			decks = d;
			loaded = true;
		});
	});
</script>

<h1>Decks</h1>

{#if loaded && decks.length === 0}
	<p>
		No decks installed yet. On the server, run
		<code>tarot-dl &lt;source-url&gt;</code> to download a deck into the decks folder,
		then reload this page.
	</p>
{/if}

<div class="grid">
	{#each decks as deck (deck.slug)}
		<a class="deck" href="/decks/{deck.slug}">
			<img src={api.cardImage(deck.slug, 0)} alt="{deck.name} — The Fool" loading="lazy" />
			<strong>{deck.name}</strong>
			<small>{deck.complete ? '78 cards' : `${deck.count}/78 cards`}</small>
		</a>
	{/each}
</div>

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
		gap: 1.2rem;
	}

	.deck {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		color: var(--text);
	}

	.deck img {
		width: 100%;
		aspect-ratio: var(--card-ratio);
		object-fit: cover;
		border-radius: 8px;
		border: 1px solid var(--border);
		transition: transform 0.15s;
	}

	.deck:hover img {
		transform: translateY(-3px);
	}

	.deck small {
		color: var(--text-dim);
	}

	code {
		background: var(--bg-raised);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
	}
</style>

<script lang="ts">
	import { api, deckCardName, type BookPassage, type Card, type CardView, type DeckRenames } from '$lib/api';

	let {
		drawn,
		meta,
		renames = undefined,
		books = []
	}: {
		drawn: CardView;
		meta: Card[];
		renames?: DeckRenames;
		/** Guidebook slugs whose excerpts to show (the reading's selected set). */
		books?: string[];
	} = $props();

	const card = $derived(meta.find((c) => c.index === drawn.card.index));
	const display = $derived(deckCardName(drawn.card.name, renames));
	const keywords = $derived(
		drawn.reversed ? card?.reversed_meaning : card?.upright
	);
	const pkt = $derived(drawn.reversed ? card?.pkt_reversed : card?.pkt_upright);

	let excerpts = $state<{ slug: string; name: string; passages: BookPassage[] }[]>([]);
	$effect(() => {
		const index = drawn.card.index;
		const wanted = books;
		if (!wanted.length || index > 77) {
			excerpts = [];
			return;
		}
		let stale = false;
		api.bookPassages(index, wanted).then((r) => {
			if (!stale) excerpts = r.books;
		}).catch(() => {
			if (!stale) excerpts = [];
		});
		return () => { stale = true; };
	});

	// Orientation-matching passages first; unoriented prose next; other side last.
	function ordered(passages: BookPassage[]): BookPassage[] {
		const want = drawn.reversed ? 'reversed' : 'upright';
		const rank = (p: BookPassage) => (p.orientation === want ? 0 : p.orientation === null ? 1 : 2);
		return [...passages].sort((a, b) => rank(a) - rank(b));
	}
</script>

<aside class="detail">
	<h2>
		{display}
		{#if display !== drawn.card.name}<span class="real">({drawn.card.name})</span>{/if}
		{#if drawn.reversed}<span class="rev">reversed</span>{/if}
	</h2>
	{#if drawn.position}
		<p class="dim">{drawn.position.name} — {drawn.position.meaning}</p>
	{/if}
	{#if keywords}
		<p class="meaning">{keywords}</p>
	{/if}
	{#if card?.description || pkt}
		<details>
			<summary>From Waite's <em>Pictorial Key to the Tarot</em> (1911)</summary>
			{#if card?.description}
				<p class="desc">{card.description}</p>
			{/if}
			{#if pkt}
				<p>{pkt}</p>
			{:else if drawn.reversed && card?.pkt_upright}
				<p class="dim">Waite gives no reversed meaning for this card; upright: {card.pkt_upright}</p>
			{/if}
		</details>
	{/if}
	{#each excerpts as book (book.slug)}
		<details>
			<summary>From <em>{book.name}</em></summary>
			{#each ordered(book.passages) as p, i (i)}
				{#if p.orientation}<p class="orient">{p.orientation}</p>{/if}
				<p>{p.text}</p>
			{/each}
			<a class="viewin" href="/books/{book.slug}?page={(ordered(book.passages)[0]?.pages?.[0] ?? 0) + 1}">
				view in book →
			</a>
		</details>
	{/each}
</aside>

<style>
	.detail {
		margin: 1.5rem auto 0;
		max-width: 40rem;
		background: var(--bg-raised);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1.2rem 1.5rem;
	}

	.meaning {
		color: var(--gold-bright);
	}

	.real {
		font-size: 0.85rem;
		color: var(--text-dim);
		font-weight: normal;
		margin-left: 0.3rem;
	}

	.rev {
		font-size: 0.8rem;
		color: var(--danger);
		margin-left: 0.5rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	details {
		margin-top: 0.8rem;
		border-top: 1px solid var(--border);
		padding-top: 0.8rem;
	}

	summary {
		cursor: pointer;
		color: var(--accent);
		font-size: 0.9rem;
	}

	.desc {
		font-style: italic;
		color: var(--text-dim);
	}

	.dim {
		color: var(--text-dim);
	}

	.orient {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--text-dim);
		margin-bottom: 0.1rem;
	}

	.viewin {
		font-size: 0.8rem;
		color: var(--accent);
	}
</style>

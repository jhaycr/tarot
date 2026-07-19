<script lang="ts">
	import type { Card, DrawnCard } from '$lib/api';

	let {
		drawn,
		meta,
		onZoom = null
	}: { drawn: DrawnCard; meta: Card[]; onZoom?: (() => void) | null } = $props();

	const card = $derived(meta.find((c) => c.index === drawn.card.index));
	const keywords = $derived(
		drawn.reversed ? card?.reversed_meaning : card?.upright
	);
	const pkt = $derived(drawn.reversed ? card?.pkt_reversed : card?.pkt_upright);
</script>

<aside class="detail">
	<h2>
		{drawn.card.name}
		{#if drawn.reversed}<span class="rev">reversed</span>{/if}
	</h2>
	<p class="dim">{drawn.position.name} — {drawn.position.meaning}</p>
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
	{#if onZoom}
		<button class="zoom" onclick={onZoom}>⤢ View full art</button>
	{/if}
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

	.zoom {
		margin-top: 0.8rem;
		font-size: 0.85rem;
		padding: 0.35rem 0.8rem;
	}
</style>

<script lang="ts">
	import { api, deckCardName, type Card, type CardView, type DeckRenames } from '$lib/api';
	import CardDetail from '$lib/CardDetail.svelte';

	let {
		deck,
		view,
		meta,
		renames = undefined,
		onclose
	}: {
		/** Deck slug the art is resolved against. */
		deck: string;
		view: CardView;
		meta: Card[];
		renames?: DeckRenames;
		onclose: () => void;
	} = $props();

	// Visual orientation only: starts as drawn, and the flip button turns the
	// art freely without changing the reading's recorded orientation.
	let flips = $state(0);
	const showReversed = $derived(view.reversed !== (flips % 2 === 1));

	const display = $derived(deckCardName(view.card.name, renames));
</script>

<svelte:window onkeydown={(e) => { if (e.key === 'Escape') onclose(); }} />

<div class="lightbox" role="presentation" onclick={onclose}>
	<div class="zoomview">
		<figure role="presentation" onclick={(e) => e.stopPropagation()}>
			<img
				class:reversed={showReversed}
				src={api.cardImage(deck, view.card.index)}
				alt={view.card.name}
			/>
			<figcaption>
				{display}{view.reversed ? ' (reversed)' : ''}{view.position ? ` — ${view.position.name}` : ''}
			</figcaption>
		</figure>
		<div class="zoominfo" role="presentation" onclick={(e) => e.stopPropagation()}>
			<!-- The infobox follows the visual flip, so its meanings match the art;
			     the figcaption stays the record of how the card was drawn. -->
			<CardDetail drawn={{ ...view, reversed: showReversed }} {meta} {renames} />
			<button class="flip" onclick={() => (flips += 1)}>⟳ Flip</button>
		</div>
		<button class="zoomclose" onclick={onclose} aria-label="Close">✕</button>
	</div>
</div>

<style>
	.lightbox {
		position: fixed;
		inset: 0;
		background: rgba(10, 8, 20, 0.88);
		display: grid;
		place-items: center;
		z-index: 20;
		cursor: zoom-out;
		padding: 1.5rem;
	}

	.zoomview {
		position: relative;
		display: flex;
		gap: 1.5rem;
		align-items: flex-start;
		max-width: min(64rem, 96vw);
		max-height: 90dvh;
		cursor: default;
	}

	.zoomview figure {
		margin: 0;
		text-align: center;
		flex: 0 0 auto;
	}

	.zoomview img {
		max-height: 76dvh;
		max-width: min(48vw, 26rem);
		border-radius: 10px;
		transition: transform 0.4s;
	}

	.zoomview img.reversed {
		transform: rotate(180deg);
	}

	.zoomview figcaption {
		margin-top: 0.6rem;
		color: var(--gold-bright);
	}

	.flip {
		margin-top: 0.8rem;
		font-size: 0.8rem;
		padding: 0.3rem 0.8rem;
	}

	.zoominfo {
		flex: 1 1 22rem;
		max-width: 26rem;
		max-height: 80dvh;
		overflow-y: auto;
	}

	.zoominfo :global(.detail) {
		margin: 0;
	}

	.zoomclose {
		position: absolute;
		top: -0.6rem;
		right: -0.6rem;
		border-radius: 999px;
		width: 2rem;
		height: 2rem;
		padding: 0;
		line-height: 1;
	}

	@media (max-width: 640px) {
		.zoomview {
			flex-direction: column;
			align-items: center;
			overflow-y: auto;
		}
		.zoomview img {
			max-width: 80vw;
			max-height: 55dvh;
		}
	}
</style>

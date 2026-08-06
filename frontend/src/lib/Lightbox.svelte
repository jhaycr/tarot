<script module lang="ts">
	// One card ratio per deck, measured from the first image that loads and
	// kept for the session: every card then renders in an identically-sized
	// stage, so the infobox never shifts while flipping (even to replacement
	// art of different dimensions) and arrow-navigation doesn't make the
	// layout jump between cards of slightly different native sizes.
	const deckRatios: Record<string, number> = {};
</script>

<script lang="ts">
	import { api, deckCardName, type Card, type CardView, type DeckRenames } from '$lib/api';
	import CardDetail from '$lib/CardDetail.svelte';

	let {
		deck,
		view,
		meta,
		renames = undefined,
		onclose,
		onnav = undefined,
		src = undefined,
		books = [],
		reversedIndices = []
	}: {
		/** Deck slug the art is resolved against. */
		deck: string;
		view: CardView;
		meta: Card[];
		renames?: DeckRenames;
		onclose: () => void;
		/** Arrow-key navigation: called with -1/+1 to move to the prev/next card. */
		onnav?: (dir: -1 | 1) => void;
		/** Art URL override for non-card images (e.g. the deck's back). */
		src?: string;
		/** Guidebook slugs whose excerpts show in the infobox. */
		books?: string[];
		/** Indices with dedicated reversed art (deck summary's reversed_indices). */
		reversedIndices?: number[];
	} = $props();

	// Visual orientation only: starts as drawn, and the flip button turns the
	// art freely without changing the reading's recorded orientation.
	let flips = $state(0);
	const showReversed = $derived(view.reversed !== (flips % 2 === 1));
	// Dedicated reversed art: swap artwork instead of rotating
	const dedicated = $derived(reversedIndices.includes(view.card.index));
	// The flip always rotates FORWARD: the angle accumulates (0 -> 180 -> 360
	// -> ...) instead of unwinding, so flipping back completes the rotation.
	// Dedicated-art cards don't rotate (the artwork itself swaps).
	const spin = $derived(dedicated ? 0 : (view.reversed ? 180 : 0) + flips * 180);
	// Extras (index 78+) have no reversed meanings, so rotating them is
	// meaningless: flip only exists for an extra when it has dedicated
	// reversed art to swap to. Canonical cards keep rotate-or-swap.
	const isExtra = $derived(view.card.index >= 78);
	const canFlip = $derived(!isExtra || dedicated);

	const display = $derived(deckCardName(view.card.name, renames));

	let measured = $state(0); // bumped when a deck ratio lands in the cache
	const ratio = $derived.by(() => {
		void measured;
		return deckRatios[deck] ?? 0.58; // typical tarot ratio until measured
	});
	function measure(img: HTMLImageElement) {
		const set = () => {
			if (src) return; // back/cover overrides must not define the card ratio
			if (!(deck in deckRatios) && img.naturalWidth && img.naturalHeight) {
				deckRatios[deck] = img.naturalWidth / img.naturalHeight;
				measured += 1;
			}
		};
		if (img.complete) set();
		else img.addEventListener('load', set, { once: true });
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') onclose();
		else if (e.key === 'ArrowLeft') onnav?.(-1);
		else if (e.key === 'ArrowRight') onnav?.(1);
	}}
/>

<div class="lightbox" role="presentation" onclick={onclose}>
	<div class="zoomview">
		<figure role="presentation" onclick={(e) => e.stopPropagation()}>
			<div class="stage" style:aspect-ratio={ratio}>
				<img
					use:measure
					style:transform={`rotate(${spin}deg)`}
					src={src ?? api.cardImage(deck, view.card.index, showReversed && dedicated)}
					alt={view.card.name}
				/>
			</div>
			<figcaption>
				{display}{view.reversed ? ' (reversed)' : ''}{view.position ? ` — ${view.position.name}` : ''}
			</figcaption>
		</figure>
		<div class="zoominfo" role="presentation" onclick={(e) => e.stopPropagation()}>
			<!-- The infobox follows the visual flip, so its meanings match the art;
			     the figcaption stays the record of how the card was drawn. -->
			<CardDetail drawn={{ ...view, reversed: showReversed }} {meta} {renames} {books} />
			{#if canFlip}
				<button class="flip" onclick={() => (flips += 1)}>⟳ Flip</button>
			{/if}
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

	/* The stage is the constant frame: sized by the DECK's card ratio, not the
	   current image, so nothing reflows on flip or arrow navigation. */
	.zoomview .stage {
		height: 76dvh;
		max-width: min(48vw, 26rem);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.zoomview img {
		max-width: 100%;
		max-height: 100%;
		border-radius: 10px;
		transition: transform 0.4s;
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
		/* FIXED width: the infobox must not resize with its content (a
		   meaning-rich canonical card vs a bare extra), or the centered row
		   re-centers and the card image slides sideways while navigating. */
		flex: 0 0 min(26rem, 42vw);
		width: min(26rem, 42vw);
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

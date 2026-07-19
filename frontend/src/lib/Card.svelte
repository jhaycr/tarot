<script lang="ts">
	import { api, type DrawnCard } from '$lib/api';

	let {
		drawn,
		deck,
		hasBack,
		flipped = $bindable(false),
		cross = false
	}: {
		drawn: DrawnCard;
		deck: string;
		hasBack: boolean;
		flipped?: boolean;
		cross?: boolean;
	} = $props();
</script>

<button
	class="card"
	class:flipped
	class:cross
	class:reversed={drawn.reversed}
	onclick={() => (flipped = true)}
	title={flipped ? drawn.card.name : drawn.position.name}
	aria-label={flipped ? drawn.card.name : `Reveal ${drawn.position.name}`}
>
	<div class="inner">
		<div class="face back">
			{#if hasBack}
				<img src={api.backImage(deck)} alt="card back" loading="lazy" />
			{:else}
				<div class="pattern"><span>✶</span></div>
			{/if}
		</div>
		<div class="face front">
			<img src={api.cardImage(deck, drawn.card.index)} alt={drawn.card.name} loading="lazy" />
		</div>
	</div>
</button>

<style>
	.card {
		all: unset;
		cursor: pointer;
		display: block;
		aspect-ratio: var(--card-ratio);
		width: 100%;
		perspective: 1200px;
	}

	.card.cross {
		transform: rotate(90deg) scale(0.85);
	}

	.inner {
		position: relative;
		width: 100%;
		height: 100%;
		transform-style: preserve-3d;
		transition: transform 0.7s cubic-bezier(0.3, 0.9, 0.4, 1);
	}

	.card.flipped .inner {
		transform: rotateY(180deg);
	}

	.face {
		position: absolute;
		inset: 0;
		backface-visibility: hidden;
		border-radius: 8px;
		overflow: hidden;
		border: 1px solid var(--border);
		box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
	}

	.face img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.front {
		transform: rotateY(180deg);
	}

	.card.reversed .front img {
		transform: rotate(180deg);
	}

	.pattern {
		width: 100%;
		height: 100%;
		display: grid;
		place-items: center;
		background:
			repeating-linear-gradient(45deg, #2a2450 0 8px, #241f42 8px 16px);
		color: var(--gold);
		font-size: 2rem;
	}
</style>

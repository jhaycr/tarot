<script lang="ts">
	import { api, type DrawnCard } from '$lib/api';

	let {
		drawn,
		deck,
		hasBack,
		flipped = $bindable(false),
		cross = false,
		next = false,
		keywords = null,
		showTip = true
	}: {
		drawn: DrawnCard;
		deck: string;
		hasBack: boolean;
		flipped?: boolean;
		cross?: boolean;
		next?: boolean;
		keywords?: string | null;
		showTip?: boolean;
	} = $props();
</script>

<button
	class="card"
	class:flipped
	class:cross
	class:next={next && !flipped}
	class:reversed={drawn.reversed}
	onclick={() => (flipped = true)}
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
	{#if !flipped}
		<span class="tip" role="tooltip">
			<strong>{drawn.position.name}</strong> — {drawn.position.meaning}
			{#if next}<em>· flip next</em>{/if}
		</span>
	{:else if showTip}
		<span class="tip" role="tooltip">
			<strong>{drawn.position.name}</strong> — {drawn.position.meaning}
			{#if keywords}<span class="kw">{keywords}</span>{/if}
		</span>
	{/if}
</button>

<style>
	.card {
		all: unset;
		cursor: pointer;
		display: block;
		position: relative;
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

	.card.next .face.back {
		animation: beckon 1.8s ease-in-out infinite;
		border-color: var(--gold);
	}

	@keyframes beckon {
		0%,
		100% {
			box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45), 0 0 0 0 rgba(212, 175, 106, 0.55);
		}
		50% {
			box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45), 0 0 14px 4px rgba(212, 175, 106, 0.55);
		}
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
		background: repeating-linear-gradient(45deg, #2a2450 0 8px, #241f42 8px 16px);
		color: var(--gold);
		font-size: 2rem;
	}

	.tip {
		position: absolute;
		bottom: calc(100% + 0.45rem);
		left: 50%;
		transform: translateX(-50%);
		width: max-content;
		max-width: 15rem;
		background: var(--bg-raised);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 0.45rem 0.7rem;
		font-size: 0.8rem;
		line-height: 1.35;
		color: var(--text-dim);
		opacity: 0;
		pointer-events: none;
		transition: opacity 0.15s;
		z-index: 8;
	}

	.tip strong {
		color: var(--gold-bright);
	}

	.tip em {
		color: var(--gold);
		font-style: normal;
	}

	.tip .kw {
		display: block;
		margin-top: 0.25rem;
		color: var(--gold-bright);
	}

	.card:hover .tip,
	.card:focus-visible .tip {
		opacity: 1;
	}

	/* the rotated cross card would show a rotated tooltip — counter-rotate it */
	.card.cross .tip {
		transform: translateX(-50%) rotate(-90deg);
	}
</style>

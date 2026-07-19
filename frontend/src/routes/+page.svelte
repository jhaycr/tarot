<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type DeckSummary, type Spread } from '$lib/api';
	import {
		prefDeck,
		prefSpread,
		prefReversals,
		favDecks,
		recentDecks,
		toggleFavDeck,
		pushRecentDeck
	} from '$lib/prefs.svelte';
	import { readingStore } from '$lib/reading.svelte';

	let decks = $state<DeckSummary[]>([]);
	let spreads = $state<Spread[]>([]);
	let question = $state('');
	let error = $state('');
	let drawing = $state(false);
	let showAllDecks = $state(false);

	function deckRank(d: DeckSummary): number {
		if (favDecks.value.includes(d.slug)) return 0;
		const r = recentDecks.value.indexOf(d.slug);
		return r >= 0 ? 1 + r : 100;
	}

	const orderedDecks = $derived(
		[...decks].sort((a, b) => deckRank(a) - deckRank(b) || a.name.localeCompare(b.name))
	);
	const visibleDecks = $derived.by(() => {
		if (showAllDecks) return orderedDecks;
		const pinned = orderedDecks.filter(
			(d) =>
				favDecks.value.includes(d.slug) ||
				recentDecks.value.includes(d.slug) ||
				d.slug === prefDeck.value
		);
		return pinned.length ? pinned : orderedDecks.slice(0, 3);
	});
	const hiddenDeckCount = $derived(decks.length - visibleDecks.length);

	$effect(() => {
		Promise.all([api.decks(), api.spreads()])
			.then(([d, s]) => {
				decks = d;
				spreads = s;
				if (!decks.find((x) => x.slug === prefDeck.value) && decks.length) {
					prefDeck.value = decks[0].slug;
				}
			})
			.catch((e) => (error = String(e)));
	});

	async function draw() {
		drawing = true;
		error = '';
		try {
			const reading = await api.draw(
				prefDeck.value,
				prefSpread.value,
				prefReversals.value === 'true',
				question.trim() || undefined
			);
			pushRecentDeck(prefDeck.value);
			readingStore.set(reading);
			goto('/reading');
		} catch (e) {
			error = String(e);
		} finally {
			drawing = false;
		}
	}
</script>

<section class="setup">
	<h1>New Reading</h1>

	{#if decks.length === 0 && !error}
		<p class="dim">
			No decks found. Add one with <code>tarot-dl</code> — see the Decks page for details.
		</p>
	{/if}

	<label class="field">
		<span>Question <em>(optional)</em></span>
		<input type="text" bind:value={question} placeholder="What should I focus on today?" maxlength="500" />
	</label>

	<div class="field">
		<span>Spread</span>
		<div class="choices">
			{#each spreads as spread (spread.slug)}
				{@const deckCount = decks.find((d) => d.slug === prefDeck.value)?.count ?? 78}
				{@const tooBig = spread.positions.length > deckCount}
				<button
					class="choice"
					class:selected={prefSpread.value === spread.slug}
					disabled={tooBig}
					title={tooBig ? 'This deck has too few cards for this spread' : undefined}
					onclick={() => (prefSpread.value = spread.slug)}
				>
					<strong>{spread.name}</strong>
					<small>{spread.positions.length} {spread.positions.length === 1 ? 'card' : 'cards'} — {spread.description}</small>
				</button>
			{/each}
		</div>
	</div>

	<div class="field">
		<span>Deck</span>
		<div class="choices">
			{#each visibleDecks as deck (deck.slug)}
				<div class="deckrow">
					<button
						class="choice deck"
						class:selected={prefDeck.value === deck.slug}
						onclick={() => (prefDeck.value = deck.slug)}
					>
						<img src={api.cardImage(deck.slug, 0)} alt="" loading="lazy" />
						<span>
							<strong>{deck.name}</strong>
							{#if deck.majors_only}<small class="dim">majors only</small>
							{:else if !deck.complete}<small class="warn">{deck.count}/78 cards</small>{/if}
						</span>
					</button>
					<button
						class="star"
						class:faved={favDecks.value.includes(deck.slug)}
						onclick={() => toggleFavDeck(deck.slug)}
						aria-label={favDecks.value.includes(deck.slug) ? 'Unfavorite' : 'Favorite'}
						title={favDecks.value.includes(deck.slug) ? 'Unfavorite' : 'Favorite'}
					>
						{favDecks.value.includes(deck.slug) ? '★' : '☆'}
					</button>
				</div>
			{/each}
			{#if hiddenDeckCount > 0}
				<button class="more" onclick={() => (showAllDecks = true)}>
					Show all decks ({hiddenDeckCount} more)
				</button>
			{:else if showAllDecks}
				<button class="more" onclick={() => (showAllDecks = false)}>Show fewer</button>
			{/if}
		</div>
	</div>

	<label class="field row">
		<input type="checkbox" checked={prefReversals.value === 'true'} onchange={(e) => (prefReversals.value = String(e.currentTarget.checked))} />
		<span>Allow reversed cards</span>
	</label>

	{#if error}<p class="error">{error}</p>{/if}

	<button class="primary" onclick={draw} disabled={drawing || !prefDeck.value}>
		{drawing ? 'Shuffling…' : 'Draw the Cards'}
	</button>
</section>

<style>
	.setup {
		max-width: 40rem;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 1.4rem;
	}

	.field > span {
		display: block;
		margin-bottom: 0.5rem;
		color: var(--text-dim);
	}

	.field.row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.field.row span {
		margin: 0;
	}

	.choices {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.choice {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		text-align: left;
		gap: 0.15rem;
	}

	.choice small {
		color: var(--text-dim);
	}

	.choice.selected {
		border-color: var(--gold);
		background: var(--bg-card);
	}

	.choice.deck {
		flex-direction: row;
		align-items: center;
		gap: 0.9rem;
	}

	.deckrow {
		display: flex;
		gap: 0.5rem;
		align-items: stretch;
	}

	.deckrow .choice {
		flex: 1;
	}

	.star {
		padding: 0 0.7rem;
		font-size: 1.1rem;
		color: var(--text-dim);
	}

	.star.faved {
		color: var(--gold);
		border-color: var(--gold);
	}

	.more {
		color: var(--accent);
		border-style: dashed;
	}

	.choice.deck img {
		width: 3rem;
		aspect-ratio: var(--card-ratio);
		object-fit: cover;
		border-radius: 4px;
	}

	.warn {
		color: var(--danger);
	}

	.error {
		color: var(--danger);
	}

	.dim {
		color: var(--text-dim);
	}

	code {
		background: var(--bg-raised);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
	}
</style>

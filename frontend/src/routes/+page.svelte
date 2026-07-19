<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type DeckSummary, type Spread } from '$lib/api';
	import { prefDeck, prefSpread, prefReversals } from '$lib/prefs.svelte';
	import { readingStore } from '$lib/reading.svelte';

	let decks = $state<DeckSummary[]>([]);
	let spreads = $state<Spread[]>([]);
	let question = $state('');
	let error = $state('');
	let drawing = $state(false);

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
				<button
					class="choice"
					class:selected={prefSpread.value === spread.slug}
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
			{#each decks as deck (deck.slug)}
				<button
					class="choice deck"
					class:selected={prefDeck.value === deck.slug}
					onclick={() => (prefDeck.value = deck.slug)}
				>
					<img src={api.cardImage(deck.slug, 0)} alt="" loading="lazy" />
					<span>
						<strong>{deck.name}</strong>
						{#if !deck.complete}<small class="warn">{deck.count}/78 cards</small>{/if}
					</span>
				</button>
			{/each}
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

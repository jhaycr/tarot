<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, cardMeta, type Card as CardType, type DrawnCard, type SavedReading } from '$lib/api';

	const id = $derived(Number(page.params.id));

	let reading = $state<SavedReading | null>(null);
	let meta = $state<CardType[]>([]);
	let notes = $state('');
	let notesSaved = $state(true);
	let selected = $state<number | null>(null);

	$effect(() => {
		api.reading(id)
			.then((r) => {
				reading = r;
				notes = r.notes;
			})
			.catch(() => goto('/journal'));
		cardMeta().then((c) => (meta = c));
	});

	function meaning(drawn: DrawnCard): string | null {
		const m = meta.find((c) => c.index === drawn.card.index);
		return (drawn.reversed ? m?.reversed_meaning : m?.upright) ?? null;
	}

	async function saveNotes() {
		if (!reading) return;
		reading = await api.updateReading(reading.id, { notes });
		notesSaved = true;
	}

	async function toggleShared() {
		if (!reading) return;
		reading = await api.updateReading(reading.id, { shared: !reading.shared });
	}

	async function remove() {
		if (!reading || !confirm('Delete this reading?')) return;
		await api.deleteReading(reading.id);
		goto('/journal');
	}

	function fmtDate(ts: number): string {
		return new Date(ts * 1000).toLocaleString(undefined, {
			dateStyle: 'full',
			timeStyle: 'short'
		});
	}
</script>

{#if reading}
	<header class="head">
		<div>
			<h1>{reading.question || 'Reading'}</h1>
			<p class="dim">
				{fmtDate(reading.created_at)}
				{#if !reading.yours}· by <span class="badge">{reading.owner}</span>{/if}
			</p>
		</div>
		{#if reading.yours}
			<div class="actions">
				<button onclick={toggleShared}>{reading.shared ? 'Unshare' : 'Share with instance'}</button>
				<button class="danger" onclick={remove}>Delete</button>
			</div>
		{/if}
	</header>

	<div class="cards">
		{#each reading.cards as drawn, i (i)}
			<button class="drawn" class:selected={selected === i} onclick={() => (selected = i)}>
				<img
					src={api.cardImage(reading.deck, drawn.card.index)}
					alt={drawn.card.name}
					class:flipped-img={drawn.reversed}
					loading="lazy"
				/>
				<small class="pos">{drawn.position.name}</small>
				<small>{drawn.card.name}{drawn.reversed ? ' (rev)' : ''}</small>
			</button>
		{/each}
	</div>

	{#if selected !== null}
		{@const drawn = reading.cards[selected]}
		<aside class="detail">
			<h2>
				{drawn.card.name}
				{#if drawn.reversed}<span class="rev">reversed</span>{/if}
			</h2>
			<p class="dim">{drawn.position.name} — {drawn.position.meaning}</p>
			{#if meaning(drawn)}<p class="meaning">{meaning(drawn)}</p>{/if}
		</aside>
	{/if}

	{#if reading.yours}
		<section class="notes">
			<h2>Notes</h2>
			<textarea
				rows="5"
				bind:value={notes}
				oninput={() => (notesSaved = false)}
				placeholder="What resonated? What happened afterwards?"
			></textarea>
			<button onclick={saveNotes} disabled={notesSaved}>{notesSaved ? 'Notes saved' : 'Save notes'}</button>
		</section>
	{:else if reading.notes}
		<section class="notes">
			<h2>Notes</h2>
			<p>{reading.notes}</p>
		</section>
	{/if}
{/if}

<style>
	.head {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.head h1 {
		font-size: 1.3rem;
	}

	.actions {
		display: flex;
		gap: 0.6rem;
	}

	.danger {
		border-color: var(--danger);
	}

	.badge {
		color: var(--accent);
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
		gap: 1rem;
		margin-top: 1.5rem;
	}

	.drawn {
		all: unset;
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		text-align: center;
	}

	.drawn img {
		width: 100%;
		aspect-ratio: var(--card-ratio);
		object-fit: cover;
		border-radius: 8px;
		border: 1px solid var(--border);
	}

	.drawn.selected img {
		border-color: var(--gold);
	}

	.flipped-img {
		transform: rotate(180deg);
	}

	.pos {
		color: var(--text-dim);
	}

	.detail {
		margin-top: 1.5rem;
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

	.notes {
		margin-top: 2rem;
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		align-items: flex-start;
	}

	.notes textarea {
		width: 100%;
	}

	.dim {
		color: var(--text-dim);
	}
</style>

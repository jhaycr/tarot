<script lang="ts">
	import { api, type SavedReading, type Spread } from '$lib/api';

	let readings = $state<SavedReading[]>([]);
	let spreads = $state<Spread[]>([]);
	let loaded = $state(false);

	$effect(() => {
		Promise.all([api.readings(), api.spreads()]).then(([r, s]) => {
			readings = r;
			spreads = s;
			loaded = true;
		});
	});

	function spreadName(slug: string): string {
		return spreads.find((s) => s.slug === slug)?.name ?? slug;
	}

	function fmtDate(ts: number): string {
		return new Date(ts * 1000).toLocaleString(undefined, {
			dateStyle: 'medium',
			timeStyle: 'short'
		});
	}
</script>

<h1>Journal</h1>

{#if loaded && readings.length === 0}
	<p class="dim">No saved readings yet — draw some cards and save the reading.</p>
{/if}

<ul class="list">
	{#each readings as r (r.id)}
		<li>
			<a href="/journal/{r.id}">
				<div class="thumbs">
					{#each r.cards.slice(0, 3) as c (c.position.name)}
						<img src={api.cardImage(r.deck, c.card.index)} alt={c.card.name} loading="lazy" />
					{/each}
				</div>
				<div class="info">
					<strong>{r.question || spreadName(r.spread)}</strong>
					<small class="dim">
						{fmtDate(r.created_at)} · {spreadName(r.spread)}
						{#if !r.yours} · <span class="badge">{r.owner}</span>{/if}
						{#if r.yours && r.shared} · <span class="badge shared">shared</span>{/if}
					</small>
					{#if r.notes}<small class="notes">{r.notes.slice(0, 120)}</small>{/if}
				</div>
			</a>
		</li>
	{/each}
</ul>

<style>
	.list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
	}

	.list a {
		display: flex;
		gap: 1rem;
		align-items: center;
		background: var(--bg-raised);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 0.8rem 1rem;
		color: var(--text);
	}

	.list a:hover {
		border-color: var(--gold);
	}

	.thumbs {
		display: flex;
		gap: 0.25rem;
		flex-shrink: 0;
	}

	.thumbs img {
		width: 2.2rem;
		aspect-ratio: var(--card-ratio);
		object-fit: cover;
		border-radius: 3px;
	}

	.info {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
	}

	.badge {
		color: var(--accent);
	}

	.badge.shared {
		color: var(--gold);
	}

	.notes {
		color: var(--text-dim);
		font-style: italic;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dim {
		color: var(--text-dim);
	}
</style>

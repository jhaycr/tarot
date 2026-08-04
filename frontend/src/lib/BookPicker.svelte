<script lang="ts">
	import type { BookSummary } from '$lib/api';

	// Compact multi-select for the guidebooks informing a reading. Sits beside
	// the persona picker; closed it reads like a select ("📖 2 books").
	let {
		available,
		selected = $bindable()
	}: { available: BookSummary[]; selected: string[] } = $props();

	function toggle(slug: string) {
		selected = selected.includes(slug)
			? selected.filter((s) => s !== slug)
			: [...selected, slug];
	}

	const label = $derived(
		selected.length === 0
			? '📖 No books'
			: selected.length === 1
				? `📖 ${available.find((b) => b.slug === selected[0])?.name ?? '1 book'}`
				: `📖 ${selected.length} books`
	);
</script>

{#if available.length}
	<details class="picker">
		<summary title="Guidebooks whose passages inform this reading">{label}</summary>
		<div class="menu">
			{#each available as book (book.slug)}
				<label>
					<input
						type="checkbox"
						checked={selected.includes(book.slug)}
						onchange={() => toggle(book.slug)}
					/>
					<span>{book.name}</span>
					<small>{book.cards_covered}/78</small>
				</label>
			{/each}
			{#if selected.length}
				<button class="clear" onclick={() => (selected = [])}>None</button>
			{/if}
		</div>
	</details>
{/if}

<style>
	.picker {
		position: relative;
		display: inline-block;
	}

	summary {
		cursor: pointer;
		list-style: none;
		padding: 0.35rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 0.85rem;
		white-space: nowrap;
		max-width: 14rem;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	summary::-webkit-details-marker {
		display: none;
	}

	.menu {
		position: absolute;
		right: 0;
		z-index: 30;
		margin-top: 0.3rem;
		padding: 0.5rem 0.7rem;
		background: var(--bg, #1a1a24);
		border: 1px solid var(--border);
		border-radius: 8px;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		min-width: 13rem;
		box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35);
	}

	.menu label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.85rem;
		cursor: pointer;
	}

	.menu label span {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.menu small {
		color: var(--text-dim);
	}

	.clear {
		font-size: 0.75rem;
		padding: 0.25rem 0.5rem;
		align-self: flex-start;
	}
</style>

<script lang="ts">
	import { page } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { api, cardMeta, type BookSummary, type Card } from '$lib/api';

	const slug = $derived(page.params.slug);

	let book = $state<BookSummary | null>(null);
	let meta = $state<Card[]>([]);
	let current = $state(0); // 0-based page
	let missing = $state(false);

	$effect(() => {
		cardMeta().then((m) => (meta = m));
		api.books().then((all) => {
			book = all.find((b) => b.slug === slug) ?? null;
			missing = book === null;
			const q = Number(page.url.searchParams.get('page'));
			if (book && q >= 1 && q <= book.pages) current = q - 1;
		});
	});

	function go(n: number) {
		if (!book) return;
		current = Math.min(Math.max(n, 0), book.pages - 1);
		// keep the URL shareable/refreshable without polluting history
		replaceState(`/books/${slug}?page=${current + 1}`, {});
	}

	let zoomed = $state(false);

	function onkey(e: KeyboardEvent) {
		if (e.key === 'ArrowLeft') go(current - 1);
		else if (e.key === 'ArrowRight') go(current + 1);
		else if (e.key === 'Escape') zoomed = false;
	}

	// Section nav: majors / suits / essays, from the per-card first-page map.
	const sections = $derived.by(() => {
		if (!book) return [];
		const entries = Object.entries(book.card_pages).map(([k, v]) => ({
			index: Number(k),
			page: v
		}));
		if (!entries.length) return [];
		const first = (lo: number, hi: number) => {
			const pages = entries.filter((e) => e.index >= lo && e.index <= hi).map((e) => e.page);
			return pages.length ? Math.min(...pages) : null;
		};
		return [
			{ label: 'Majors', page: first(0, 21) },
			{ label: 'Wands', page: first(22, 35) },
			{ label: 'Cups', page: first(36, 49) },
			{ label: 'Swords', page: first(50, 63) },
			{ label: 'Pentacles', page: first(64, 77) }
		].filter((s) => s.page !== null) as { label: string; page: number }[];
	});

	const cardJump = $derived.by(() => {
		if (!book || !meta.length) return [];
		return Object.entries(book.card_pages)
			.map(([k, v]) => ({
				index: Number(k),
				page: v,
				name: meta.find((c) => c.index === Number(k))?.name ?? `Card ${k}`
			}))
			.sort((a, b) => a.index - b.index);
	});
</script>

<svelte:window onkeydown={onkey} />

{#if missing}
	<p class="error">No book “{slug}”.</p>
	<a href="/books">← Books</a>
{:else if book}
	<header class="head">
		<div>
			<h1>{book.name}</h1>
			<p class="dim">
				{#if book.author}{book.author} · {/if}{book.pages} pages ·
				{book.cards_covered}/78 cards
				<a class="back" href="/books">← all books</a>
			</p>
		</div>
		<div class="nav">
			{#each sections as s (s.label)}
				<button class="sec" onclick={() => go(s.page)}>{s.label}</button>
			{/each}
			{#if cardJump.length}
				<select
					aria-label="Jump to card"
					onchange={(e) => {
						const v = Number(e.currentTarget.value);
						if (!Number.isNaN(v)) go(v);
						e.currentTarget.value = '';
					}}
				>
					<option value="">Jump to card…</option>
					{#each cardJump as c (c.index)}
						<option value={c.page}>{c.name}</option>
					{/each}
				</select>
			{/if}
		</div>
	</header>

	<div class="pager">
		<button class="arrow" onclick={() => go(current - 1)} disabled={current === 0} aria-label="Previous page">
			‹
		</button>
		<div class="stage" class:zoomed>
			<button
				class="pagebtn"
				onclick={() => (zoomed = !zoomed)}
				aria-label={zoomed ? 'Zoom out' : 'Zoom in'}
			>
				<img src={api.bookPageUrl(book.slug, current)} alt="{book.name}, page {current + 1}" />
			</button>
		</div>
		<button
			class="arrow"
			onclick={() => go(current + 1)}
			disabled={current >= book.pages - 1}
			aria-label="Next page"
		>
			›
		</button>
	</div>
	<p class="pageno dim">
		page {current + 1} / {book.pages} — arrow keys turn pages · click the page to
		{zoomed ? 'zoom out' : 'zoom in'}
	</p>
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
		margin-bottom: 0.2rem;
	}

	.back {
		margin-left: 0.6rem;
		color: var(--accent);
		font-size: 0.85rem;
	}

	.nav {
		display: flex;
		gap: 0.4rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.sec {
		font-size: 0.8rem;
		padding: 0.3rem 0.6rem;
	}

	.pager {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.8rem;
		margin-top: 1rem;
	}

	.pagebtn {
		background: none;
		border: none;
		padding: 0;
		cursor: zoom-in;
		display: block;
	}

	.pager img {
		max-width: min(92vw, 34rem);
		max-height: 78vh;
		border-radius: 8px;
		border: 1px solid var(--border);
		background: var(--bg-raised);
		display: block;
	}

	/* Zoomed: the rendered page at its full 2x resolution, panned by scrolling
	   inside the stage so the surrounding layout never scrolls sideways. */
	.stage.zoomed {
		overflow: auto;
		max-height: 82vh;
		max-width: 92vw;
		border-radius: 8px;
	}

	.stage.zoomed .pagebtn {
		cursor: zoom-out;
	}

	.stage.zoomed img {
		max-width: none;
		max-height: none;
	}

	.arrow {
		font-size: 1.6rem;
		padding: 0.4rem 0.8rem;
	}

	.pageno {
		text-align: center;
		margin-top: 0.5rem;
	}

	.dim {
		color: var(--text-dim);
		font-size: 0.9rem;
	}

	.error {
		color: var(--danger, #d66);
	}
</style>

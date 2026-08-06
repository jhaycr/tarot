<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, deckCardName, type BookSummary, type Card, type DeckSummary } from '$lib/api';
	import Lightbox from '$lib/Lightbox.svelte';

	const slug = $derived(page.params.slug!);

	let cards = $state<Card[]>([]);
	let deck = $state<DeckSummary | undefined>(undefined);
	// canonical is the real card name (index <78) that keys meanings + renames;
	// extras just carry their display name.
	let zoomed = $state<{ index: number; canonical: string } | null>(null);
	let deleting = $state(false);
	let unpublishing = $state(false);
	let deleteError = $state('');

	let allBooks = $state<BookSummary[]>([]);
	const companionBooks = $derived(
		(deck?.books ?? [])
			.map((s) => allBooks.find((b) => b.slug === s))
			.filter((b): b is BookSummary => !!b)
	);
	const companionSlugs = $derived(companionBooks.map((b) => b.slug));

	$effect(() => {
		api.cards().then((c) => (cards = c));
		api.books().then((b) => (allBooks = b));
		refreshDeck();
	});

	let bookError = $state('');

	async function setBooks(next: string[]) {
		if (!deck) return;
		bookError = '';
		try {
			await api.setDeckBooks(slug, next);
			await refreshDeck();
		} catch (e) {
			bookError = e instanceof Error ? e.message : 'Could not update companion books.';
		}
	}

	function toggleBook(bookSlug: string) {
		if (!deck) return;
		const next = deck.books.includes(bookSlug)
			? deck.books.filter((s) => s !== bookSlug)
			: [...deck.books, bookSlug];
		setBooks(next);
	}

	async function refreshDeck() {
		const d = await api.decks();
		deck = d.find((x) => x.slug === slug);
	}

	async function unpublish() {
		if (!deck || unpublishing) return;
		if (
			!confirm(
				`Remove “${deck.name}” from the shared library? It returns to ${deck.published_by ?? 'the publisher'}'s private drafts — nobody else will see it.`
			)
		)
			return;
		unpublishing = true;
		deleteError = '';
		try {
			await api.unpublishDeck(slug);
			await refreshDeck(); // now a draft — the Delete button takes over
		} catch {
			deleteError = 'Could not unpublish the deck.';
		} finally {
			unpublishing = false;
		}
	}

	async function remove() {
		if (!deck || deleting) return;
		if (!confirm(`Delete the deck “${deck.name}” and its images? This cannot be undone.`)) return;
		deleting = true;
		deleteError = '';
		try {
			await api.deleteDeck(slug);
			goto('/decks');
		} catch {
			deleteError = 'Could not delete the deck.';
			deleting = false;
		}
	}

	const ROMAN = ['0', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII',
		'XIII', 'XIV', 'XV', 'XVI', 'XVII', 'XVIII', 'XIX', 'XX', 'XXI'];

	function displayName(card: Card): string {
		const renamed = deckCardName(card.name, deck);
		return renamed === card.name ? card.name : `${renamed} (${card.name})`;
	}

	function numeral(card: Card): string {
		if (card.arcana === 'major') return ROMAN[card.index];
		if (card.number == null) return '';
		if (card.number === 1) return 'A';
		if (card.number <= 10) return String(card.number);
		return ['P', 'Kn', 'Q', 'K'][card.number - 11];
	}

	const has = $derived((i: number) =>
		deck ? !deck.missing.includes(i) && (!deck.majors_only || i < 22) : true
	);

	const sections = $derived.by(() => {
		const secs: {
			id: string;
			title: string;
			cards: { index: number; name: string; canonical: string; numeral: string }[];
		}[] = [];
		const majors = cards.filter((c) => c.arcana === 'major' && has(c.index));
		if (majors.length)
			secs.push({
				id: 'majors',
				title: 'Major Arcana',
				cards: majors.map((c) => ({
					index: c.index,
					name: displayName(c),
					canonical: c.name,
					numeral: numeral(c)
				}))
			});
		for (const suit of ['Wands', 'Cups', 'Swords', 'Pentacles']) {
			const suited = cards.filter((c) => c.suit === suit && has(c.index));
			const renamed = deck?.suit_names?.[suit];
			if (suited.length)
				secs.push({
					id: suit.toLowerCase(),
					title: renamed ? `${renamed} (${suit})` : suit,
					cards: suited.map((c) => ({
						index: c.index,
						name: deckCardName(c.name, deck),
						canonical: c.name,
						numeral: numeral(c)
					}))
				});
		}
		if (deck?.extras.length)
			secs.push({
				id: 'extras',
				title: 'Extras',
				cards: deck.extras.map((e, i) => ({
					index: e.index,
					name: e.name,
					canonical: e.name,
					numeral: `+${i + 1}`
				}))
			});
		// indexes -1/-2 = the deck's back/cover images (each has its own endpoint)
		if (deck?.has_cover)
			secs.push({
				id: 'cover',
				title: 'Cover',
				cards: [{ index: -2, name: 'Cover', canonical: 'Cover', numeral: '' }]
			});
		if (deck?.has_back)
			secs.push({
				id: 'back',
				title: 'Back',
				cards: [{ index: -1, name: 'Back', canonical: 'Back', numeral: '' }]
			});
		return secs;
	});

	function tileSrc(index: number): string {
		if (index === -1) return api.backImage(slug);
		if (index === -2) return api.coverImage(slug);
		return api.cardImage(slug, index);
	}

	const flatCards = $derived(sections.flatMap((s) => s.cards));

	// Decks vary in native card proportions (Marseille and game decks run taller
	// than RWS). Size the gallery tiles to this deck's own ratio — measured from
	// the first card image that loads — so frames aren't cropped; object-fit:
	// contain guards any outlier cards. Tiles stay uniform within the deck.
	let tileRatio = $state<number | null>(null);
	function measure(img: HTMLImageElement) {
		const set = () => {
			if (tileRatio === null && img.naturalWidth && img.naturalHeight)
				tileRatio = img.naturalWidth / img.naturalHeight;
		};
		if (img.complete) set();
		else img.addEventListener('load', set, { once: true });
	}

	function nav(dir: -1 | 1) {
		if (!zoomed || !flatCards.length) return;
		const pos = flatCards.findIndex((c) => c.index === zoomed!.index);
		if (pos === -1) return;
		zoomed = flatCards[(pos + dir + flatCards.length) % flatCards.length];
	}
</script>

<header class="top">
	<div>
		<h1>{deck?.name ?? slug}</h1>
		{#if deck?.attribution || deck?.source}
			<p class="dim">
				{deck?.attribution ?? ''}
				{#if deck?.source}
					· <a href={deck.source} target="_blank" rel="noreferrer">source</a>
				{/if}
			</p>
		{/if}
		{#if companionBooks.length}
			<p class="dim companions">
				📖 Companion {companionBooks.length === 1 ? 'book' : 'books'}:
				{#each companionBooks as b, i (b.slug)}
					{#if i > 0}·{/if}
					<a href="/books/{b.slug}">{b.name}</a>
				{/each}
			</p>
		{/if}
		{#if deck?.can_edit_books && deck?.has_cover}
			<label class="tilecover dim">
				<input
					type="checkbox"
					checked={deck.tile_cover}
					onchange={async (e) => {
						try {
							await api.patchDeck(slug, { tile_cover: e.currentTarget.checked });
							await refreshDeck();
						} catch {
							bookError = 'Could not update the tile setting.';
						}
					}}
				/>
				Show the box cover as this deck's tile on the Decks page
			</label>
		{/if}
		{#if deck?.can_edit_books}
			<details class="curate">
				<summary>Curate companion books</summary>
				<div class="curatebody">
					{#if deck.suggested_books.length}
						<div class="suggest">
							<span class="dim">Suggested:</span>
							{#each deck.suggested_books as s (s)}
								<button class="chip" onclick={() => toggleBook(s)}>
									+ {allBooks.find((b) => b.slug === s)?.name ?? s}
								</button>
							{/each}
						</div>
					{/if}
					{#each allBooks as b (b.slug)}
						<label>
							<input
								type="checkbox"
								checked={deck.books.includes(b.slug)}
								onchange={() => toggleBook(b.slug)}
							/>
							{b.name}
							<small class="dim">{b.cards_covered}/78</small>
						</label>
					{:else}
						<span class="dim">No books imported yet — add one on the Books page.</span>
					{/each}
					{#if bookError}<p class="error">{bookError}</p>{/if}
				</div>
			</details>
		{/if}
	</div>
	<div class="topactions">
		<a class="export" href="/api/decks/{slug}/export" download="{slug}.zip">⇩ Export zip</a>
		{#if deck?.can_unpublish}
			<button onclick={unpublish} disabled={unpublishing}>
				{unpublishing ? 'Unpublishing…' : 'Unpublish'}
			</button>
		{/if}
		{#if deck?.yours}
			<button class="danger" onclick={remove} disabled={deleting}>
				{deleting ? 'Deleting…' : 'Delete deck'}
			</button>
		{/if}
	</div>
</header>

{#if deleteError}<p class="error">{deleteError}</p>{/if}

{#if sections.length > 1}
	<nav class="secnav">
		{#each sections as sec (sec.id)}
			<a href="#{sec.id}">{sec.title}</a>
		{/each}
	</nav>
{/if}

{#each sections as sec (sec.id)}
	<section id={sec.id}>
		<h2>{sec.title} <small class="dim">{sec.cards.length}</small></h2>
		<div class="grid" style={tileRatio ? `--tile-ratio: ${tileRatio}` : ''}>
			{#each sec.cards as card (card.index)}
				<button class="tile" onclick={() => (zoomed = card)}>
					<img use:measure src={tileSrc(card.index)} alt={card.name} loading="lazy" />
					<small>
						{#if card.numeral}<span class="num">{card.numeral}</span>{/if}
						{card.name}
						{#if deck?.reversed_indices.includes(card.index)}<span
								class="revart"
								title="Has dedicated reversed art — flip it in the lightbox">⇅</span>{/if}
					</small>
				</button>
			{/each}
		</div>
	</section>
{/each}

{#if zoomed}
	{#key zoomed.index}
		<Lightbox
			deck={slug}
			view={{ card: { index: zoomed.index, name: zoomed.canonical }, reversed: false }}
			meta={cards}
			renames={deck}
			src={zoomed.index < 0 ? tileSrc(zoomed.index) : undefined}
			onclose={() => (zoomed = null)}
			onnav={nav}
			books={companionSlugs}
			reversedIndices={deck?.reversed_indices ?? []}
		/>
	{/key}
{/if}

<style>
	.revart {
		color: var(--accent);
		margin-left: 0.15rem;
	}

	.tilecover {
		display: flex;
		gap: 0.4rem;
		align-items: center;
		font-size: 0.85rem;
		margin-top: 0.3rem;
	}

	.curate {
		margin-top: 0.4rem;
	}

	.curate summary {
		cursor: pointer;
		font-size: 0.85rem;
		color: var(--accent);
	}

	.curatebody {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		padding: 0.5rem 0;
		font-size: 0.85rem;
	}

	.curatebody label {
		display: flex;
		gap: 0.4rem;
		align-items: center;
	}

	.suggest {
		display: flex;
		gap: 0.35rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.chip {
		font-size: 0.75rem;
		padding: 0.2rem 0.55rem;
		border-radius: 999px;
		border: 1px solid var(--accent);
		color: var(--accent);
		background: none;
		cursor: pointer;
	}

	.top {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.export {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 0.45rem 0.9rem;
		color: var(--text);
	}

	.export:hover {
		border-color: var(--gold);
	}

	.topactions {
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}

	.danger {
		border-color: var(--danger);
	}

	.error {
		color: var(--danger);
	}

	.secnav {
		position: sticky;
		top: 0;
		z-index: 5;
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
		padding: 0.6rem 0;
		margin: 0.4rem 0 0.6rem;
		background: linear-gradient(var(--bg) 85%, transparent);
	}

	.secnav a {
		border: 1px solid var(--border);
		border-radius: 999px;
		padding: 0.25rem 0.85rem;
		color: var(--text-dim);
		font-size: 0.85rem;
	}

	.secnav a:hover {
		border-color: var(--gold);
		color: var(--gold);
	}

	section {
		scroll-margin-top: 3.2rem;
		margin-bottom: 1.6rem;
	}

	section h2 {
		font-size: 1.05rem;
		border-bottom: 1px solid var(--border);
		padding-bottom: 0.3rem;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(7.5rem, 1fr));
		gap: 0.9rem;
		margin-top: 0.8rem;
	}

	.tile {
		all: unset;
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.tile img {
		width: 100%;
		aspect-ratio: var(--tile-ratio, var(--card-ratio));
		object-fit: contain;
		background: var(--bg-raised);
		border-radius: 6px;
		border: 1px solid var(--border);
	}

	.tile:hover img {
		border-color: var(--gold);
	}

	.tile small {
		color: var(--text-dim);
		font-size: 0.75rem;
	}

	.num {
		display: inline-block;
		min-width: 1.3em;
		color: var(--gold);
		font-variant: small-caps;
	}

	.dim {
		color: var(--text-dim);
	}
</style>

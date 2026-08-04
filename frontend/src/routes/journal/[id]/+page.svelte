<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, cardMeta, deckCardName, type BookSummary, type Card as CardType, type DeckSummary, type DrawnCard, type SavedReading } from '$lib/api';
	import AudioButton from '$lib/AudioButton.svelte';
	import Lightbox from '$lib/Lightbox.svelte';
	import VisibilitySelect from '$lib/VisibilitySelect.svelte';
	import { toParagraphs } from '$lib/text';
	import { prefJournalLayout } from '$lib/prefs.svelte';

	const id = $derived(Number(page.params.id));

	let reading = $state<SavedReading | null>(null);
	let allBooks = $state<BookSummary[]>([]);
	// The recorded provenance set, restricted to books this viewer can see.
	const readingBooks = $derived(
		(reading?.books ?? []).filter((slug) => allBooks.some((b) => b.slug === slug))
	);
	// Infobox: the VIEWING deck's curated companions plus the recorded set.
	const infoboxBooks = $derived.by(() => {
		const visible = new Set(allBooks.map((b) => b.slug));
		const curated = (viewDeckInfo?.books ?? []).filter((s) => visible.has(s));
		return [...new Set([...curated, ...readingBooks])];
	});
	const bookNames = $derived(
		(reading?.books ?? []).map(
			(slug) => allBooks.find((b) => b.slug === slug)?.name ?? slug
		)
	);
	let decks = $state<DeckSummary[]>([]);
	let viewDeck = $state('');
	let meta = $state<CardType[]>([]);
	let notes = $state('');
	let notesSaved = $state(true);
	let zoomedIdx = $state<number | null>(null);
	const zoomed = $derived(zoomedIdx !== null && reading ? reading.cards[zoomedIdx] : null);
	let ttsEnabled = $state(false);

	function nav(dir: -1 | 1) {
		if (zoomedIdx === null || !reading) return;
		const n = reading.cards.length;
		zoomedIdx = (zoomedIdx + dir + n) % n;
	}

	$effect(() => {
		api.books().then((b) => (allBooks = b));
		api.reading(id)
			.then((r) => {
				reading = r;
				notes = r.notes;
				viewDeck = r.deck;
			})
			.catch(() => goto('/journal'));
		api.decks().then((d) => (decks = d));
		cardMeta().then((c) => (meta = c));
		api.me().then((m) => (ttsEnabled = m.tts));
	});

	const viewDeckInfo = $derived(decks.find((d) => d.slug === viewDeck));

	const compatibleDecks = $derived.by(() => {
		if (!reading) return [];
		// readings containing deck-specific extra cards can't be re-skinned
		if (reading.cards.some((c) => c.card.index >= 78)) {
			return decks.filter((d) => d.slug === reading!.deck);
		}
		const majorsFine = reading.cards.every((c) => c.card.index < 22);
		return decks.filter(
			(d) => d.slug === reading!.deck || d.complete || (d.majors_only && majorsFine)
		);
	});

	const spreadMode = $derived(prefJournalLayout.value === 'spread');
	const cols = $derived(reading ? Math.max(...reading.cards.map((c) => c.position.col ?? 1)) : 1);
	const rows = $derived(reading ? Math.max(...reading.cards.map((c) => c.position.row ?? 1)) : 1);
	const hasLayout = $derived(reading ? reading.cards.every((c) => c.position.col && c.position.row) : false);

	function cellCards(col: number, row: number): { drawn: DrawnCard; i: number }[] {
		return (reading?.cards ?? [])
			.map((drawn, i) => ({ drawn, i }))
			.filter(({ drawn }) => drawn.position.col === col && drawn.position.row === row);
	}

	async function saveNotes() {
		if (!reading) return;
		reading = await api.updateReading(reading.id, { notes });
		notesSaved = true;
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
				{#if bookNames.length}· books consulted: {bookNames.join(', ')}{/if}
			</p>
		</div>
		{#if reading.yours}
			<div class="actions">
				<VisibilitySelect bind:reading />
				<button class="danger" onclick={remove}>Delete</button>
			</div>
		{/if}
	</header>

	<div class="viewbar">
		{#if compatibleDecks.length > 1}
			<label>
				<span class="dim">View with deck</span>
				<select bind:value={viewDeck}>
					{#each compatibleDecks as d (d.slug)}
						<option value={d.slug}>{d.name}{d.slug === reading.deck ? ' (original)' : ''}</option>
					{/each}
				</select>
			</label>
		{/if}
		{#if hasLayout}
			<div class="modes">
				<button class:active={!spreadMode} onclick={() => (prefJournalLayout.value = 'grid')}>Grid</button>
				<button class:active={spreadMode} onclick={() => (prefJournalLayout.value = 'spread')}>Spread</button>
			</div>
		{/if}
	</div>

	{#if spreadMode && hasLayout}
		<div class="table" style="--cols: {cols}; --rows: {rows};">
			{#each Array(rows) as _, r (r)}
				{#each Array(cols) as _, c (c)}
					{@const cell = cellCards(c + 1, r + 1)}
					{#if cell.length}
						<div class="cell" style="grid-column: {c + 1}; grid-row: {r + 1};">
							{#each cell as { drawn, i } (i)}
								<div class="slot" class:overlay={drawn.position.cross}>
									<button
										class="faceup"
										class:cross={drawn.position.cross}
										onclick={() => (zoomedIdx = i)}
									>
										<img
											src={api.cardImage(viewDeck, drawn.card.index)}
											class:reversed={drawn.reversed}
											alt={drawn.card.name}
											loading="lazy"
										/>
									</button>
									{#if !drawn.position.cross}
										<small class="pos">{drawn.position.name}</small>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				{/each}
			{/each}
		</div>
	{:else}
		<div class="cards">
			{#each reading.cards as drawn, i (i)}
				<button class="drawn" onclick={() => (zoomedIdx = i)}>
					<img
						src={api.cardImage(viewDeck, drawn.card.index)}
						alt={drawn.card.name}
						class:reversed={drawn.reversed}
						loading="lazy"
					/>
					<small class="pos">{drawn.position.name}</small>
					<small>{deckCardName(drawn.card.name, viewDeckInfo)}{drawn.reversed ? ' (rev)' : ''}</small>
				</button>
			{/each}
		</div>
	{/if}

	{#if reading.interpretation?.mode}
		{@const it = reading.interpretation}
		<section class="guided-readings">
			<h2>Guided reading</h2>
			{#if it.status === 'in_progress' && reading.yours}
				<div class="unfinished">
					<span class="dim">This reading is unfinished.</span>
					<a class="continue" href="/reading/guided?id={reading.id}">Continue reading →</a>
				</div>
			{/if}
			{#each reading.cards as drawn, i (i)}
				{#if it.focused?.[String(i)]}
					<div class="fr">
						<h3>{deckCardName(drawn.card.name, viewDeckInfo)}{drawn.reversed ? ' (reversed)' : ''}
							<span class="dim">· {drawn.position.name}</span>
							{#if ttsEnabled}
								<AudioButton src={api.readingAudio(reading.id, i)} label="Read this card aloud" />
							{/if}</h3>
						{#each toParagraphs(it.focused[String(i)]) as para, p (p)}<p>{para}</p>{/each}
					</div>
				{/if}
			{/each}
			{#if it.comprehensive}
				<div class="fr whole">
					<h3>The whole picture
						{#if ttsEnabled}
							<AudioButton src={api.readingAudio(reading.id, -1)} label="Read the whole picture aloud" />
						{/if}</h3>
					{#each toParagraphs(it.comprehensive) as para, i (i)}<p>{para}</p>{/each}
				</div>
			{/if}
		</section>
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

	{#if zoomed}
		{#key zoomedIdx}
			<Lightbox
				deck={viewDeck}
				view={zoomed}
				{meta}
				renames={viewDeckInfo}
				onclose={() => (zoomedIdx = null)}
				onnav={nav}
				books={infoboxBooks}
			/>
		{/key}
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

	.viewbar {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		margin: 1rem 0;
	}

	.viewbar label {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.viewbar select {
		width: auto;
	}

	.modes {
		display: flex;
		gap: 0;
	}

	.modes button {
		border-radius: 0;
	}

	.modes button:first-child {
		border-radius: var(--radius) 0 0 var(--radius);
	}

	.modes button:last-child {
		border-radius: 0 var(--radius) var(--radius) 0;
	}

	.modes button.active {
		border-color: var(--gold);
		color: var(--gold);
	}

	.table {
		display: grid;
		grid-template-columns: repeat(var(--cols), minmax(0, 9rem));
		gap: 1.1rem;
		justify-content: center;
		margin-top: 0.5rem;
	}

	.cell {
		position: relative;
	}

	.slot {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		align-items: center;
	}

	.slot.overlay {
		position: absolute;
		inset: 0 0 auto 0;
		z-index: 2;
	}

	.faceup {
		all: unset;
		cursor: pointer;
		display: block;
		width: 100%;
		aspect-ratio: var(--card-ratio);
	}

	.faceup.cross {
		transform: rotate(90deg) scale(0.85);
	}

	.faceup img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		border-radius: 8px;
		border: 1px solid var(--border);
		box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
	}

	.faceup:hover img {
		border-color: var(--gold);
	}

	img.reversed {
		transform: rotate(180deg);
	}

	.faceup.cross img.reversed {
		transform: rotate(180deg);
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
		gap: 1rem;
		margin-top: 0.5rem;
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

	.drawn:hover img {
		border-color: var(--gold);
	}

	.pos {
		color: var(--text-dim);
		font-size: 0.75rem;
		text-align: center;
	}

	.guided-readings {
		margin-top: 2rem;
	}
	.unfinished {
		display: flex;
		align-items: center;
		gap: 0.8rem;
		flex-wrap: wrap;
		margin-bottom: 1rem;
		padding: 0.6rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
	}
	.continue {
		color: var(--accent);
		font-weight: 600;
	}
	.guided-readings .fr {
		margin-bottom: 1.2rem;
	}
	.guided-readings h3 {
		margin: 0 0 0.3rem;
		font-size: 1rem;
	}
	.guided-readings p {
		margin: 0 0 0.5rem;
		line-height: 1.6;
	}
	.guided-readings .whole {
		padding-top: 1rem;
		border-top: 1px solid var(--border);
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

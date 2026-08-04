<script lang="ts">
	import { api, type BookSummary, type DeckSummary } from '$lib/api';

	let books = $state<BookSummary[]>([]);
	let decks = $state<DeckSummary[]>([]);
	let loaded = $state(false);

	let defaults = $state<string[]>([]);

	$effect(() => {
		refresh();
		api.decks().then((d) => (decks = d));
		api.getMySettings().then((s) => (defaults = s.default_books));
	});

	async function refresh() {
		books = await api.books();
		loaded = true;
	}

	async function toggleDefault(book: BookSummary) {
		const next = defaults.includes(book.slug)
			? defaults.filter((s) => s !== book.slug)
			: [...defaults, book.slug];
		try {
			const s = await api.setMySettings({ default_books: next });
			defaults = s.default_books;
		} catch {
			bookError = 'Could not update your default books.';
		}
	}

	let myDrafts = $derived(books.filter((b) => b.tier === 'staging'));
	let library = $derived(books.filter((b) => b.tier !== 'staging'));

	// --- upload + import job -------------------------------------------------
	let uploadName = $state('');
	let uploadFile = $state<File | null>(null);
	let uploading = $state(false);
	let uploadError = $state('');
	let job = $state<string | null>(null);
	let jobState = $state({ stage: '', page: 0, pages: 0 });
	let jobDoneMsg = $state('');

	async function upload() {
		if (!uploadFile || !uploadName.trim()) return;
		uploading = true;
		uploadError = '';
		jobDoneMsg = '';
		try {
			const res = await api.uploadBook(uploadFile, uploadName.trim());
			uploadName = '';
			uploadFile = null;
			job = res.job;
			poll(res.job);
		} catch (e) {
			uploadError = e instanceof Error ? e.message : String(e);
		} finally {
			uploading = false;
		}
	}

	async function poll(id: string) {
		try {
			const s = await api.bookImportStatus(id);
			jobState = { stage: s.stage, page: s.page, pages: s.pages };
			if (s.done) {
				job = null;
				if (s.error) {
					uploadError = s.error;
				} else {
					jobDoneMsg =
						`“${s.name}” imported: ${s.cards_covered}/78 cards across ${s.pages} pages` +
						(s.failed_pages.length ? ` (${s.failed_pages.length} pages unreadable — re-extract to retry)` : '') +
						'.';
				}
				await refresh();
			} else {
				setTimeout(() => poll(id), 1500);
			}
		} catch {
			setTimeout(() => poll(id), 3000);
		}
	}

	// --- per-book actions ----------------------------------------------------
	let bookError = $state('');

	async function act(fn: () => Promise<unknown>, failMsg: string) {
		bookError = '';
		try {
			await fn();
		} catch (e) {
			bookError = e instanceof Error ? e.message : failMsg;
		}
		await refresh();
	}

	function reextract(book: BookSummary) {
		act(async () => {
			const res = await api.reextractBook(book.slug);
			job = res.job;
			jobDoneMsg = '';
			poll(res.job);
		}, 'Could not start re-extraction.');
	}

	function remove(book: BookSummary) {
		if (!confirm(`Delete the draft book “${book.name}”? This removes its extracted text.`)) return;
		act(() => api.deleteBook(book.slug), 'Could not delete the book.');
	}

	// which decks curate this book as a companion (deck-side links, read-only here)
	function companionOf(book: BookSummary): string[] {
		return decks.filter((d) => d.books.includes(book.slug)).map((d) => d.name);
	}

	function coverage(book: BookSummary): string {
		const cards = `${book.cards_covered}/78 cards`;
		return `${book.pages} pages · ${cards}`;
	}
</script>

<h1>Books</h1>
<p class="dim">
	Guidebooks live alongside your decks: upload the PDF that came with a deck (or any tarot
	book you own), and its card meanings appear in card details and can inform readings.
	Books stay private until you publish them to the shared library.
</p>

{#if loaded && books.length === 0}
	<p>No books yet — upload a guidebook PDF below.</p>
{/if}

<section class="upload">
	<h2>Upload a guidebook</h2>
	<p class="dim">
		PDF only, for personal use. Image-only PDFs (most Etsy guidebooks) are read with the
		configured vision model — a one-time AI pass per book.
	</p>
	<div class="row">
		<input type="text" placeholder="Book name" bind:value={uploadName} />
		<input
			type="file"
			accept=".pdf,application/pdf"
			onchange={(e) => (uploadFile = e.currentTarget.files?.[0] ?? null)}
		/>
		<button onclick={upload} disabled={uploading || job !== null || !uploadFile || !uploadName.trim()}>
			{uploading || job ? 'Importing…' : 'Upload'}
		</button>
	</div>
	{#if job}
		<div class="progress">
			<div
				class="bar"
				style="width: {jobState.pages ? (jobState.page / jobState.pages) * 100 : 0}%"
			></div>
		</div>
		<p class="dim">
			{jobState.stage === 'transcribe' ? 'Reading pages' : 'Rendering pages'}
			{jobState.page}/{jobState.pages || '…'}
		</p>
	{/if}
	{#if jobDoneMsg}<p class="ok">{jobDoneMsg}</p>{/if}
	{#if uploadError}<p class="error">{uploadError}</p>{/if}
</section>

{#if bookError}<p class="error">{bookError}</p>{/if}

{#snippet bookCard(book: BookSummary)}
	<div class="book">
		<a class="cover" href="/books/{book.slug}">
			<img src={api.bookPageUrl(book.slug, 0)} alt="{book.name} — first page" loading="lazy" />
		</a>
		<strong>
			<a href="/books/{book.slug}">{book.name}</a>
			<button
				class="star"
				class:on={defaults.includes(book.slug)}
				title="Default book — informs your readings when the deck has no companion"
				onclick={() => toggleDefault(book)}
			>
				{defaults.includes(book.slug) ? '★' : '☆'}
			</button>
		</strong>
		<small>
			{coverage(book)}
			{#if book.published && book.published_by}· <span class="badge">by {book.published_by}</span>{/if}
		</small>
		{#if companionOf(book).length}
			<small class="dim">companion to {companionOf(book).join(', ')}</small>
		{/if}
		{#if book.yours || book.can_unpublish}
			<details>
				<summary>Manage</summary>
				<div class="manage">
					<span class="dim">Companion links are curated from each deck's page (deck owners only).</span>
					<div class="actions">
						{#if book.yours}
							<button onclick={() => act(() => api.publishBook(book.slug), 'Could not publish.')}>
								Publish to library
							</button>
							{#if book.cards_covered < 78}
								<button onclick={() => reextract(book)}>Re-extract</button>
							{/if}
							<button class="danger" onclick={() => remove(book)}>Delete</button>
						{:else if book.can_unpublish}
							<button onclick={() => act(() => api.unpublishBook(book.slug), 'Could not unpublish.')}>
								Unpublish
							</button>
						{/if}
					</div>
				</div>
			</details>
		{/if}
	</div>
{/snippet}

{#if myDrafts.length}
	<h2 class="section">Drafts <span class="dim">· private until you publish</span></h2>
	<div class="grid">
		{#each myDrafts as book (book.slug)}{@render bookCard(book)}{/each}
	</div>
{/if}

{#if library.length}
	<h2 class="section">Shared</h2>
	<div class="grid">
		{#each library as book (book.slug)}{@render bookCard(book)}{/each}
	</div>
{/if}

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
		gap: 1.2rem;
	}

	.book {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		color: var(--text);
	}

	.book .cover img {
		width: 100%;
		border-radius: 8px;
		border: 1px solid var(--border);
		transition: transform 0.15s;
	}

	.book:hover .cover img {
		transform: translateY(-3px);
	}

	.book small {
		color: var(--text-dim);
	}

	.badge {
		color: var(--accent);
	}

	.section {
		font-size: 1.05rem;
		margin: 1.6rem 0 0.8rem;
	}

	.section .dim {
		font-weight: normal;
		font-size: 0.85rem;
	}

	details summary {
		cursor: pointer;
		font-size: 0.8rem;
		color: var(--text-dim);
	}

	.manage {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		font-size: 0.8rem;
		padding: 0.4rem 0;
	}

	.actions {
		display: flex;
		gap: 0.4rem;
		margin-top: 0.3rem;
		flex-wrap: wrap;
	}

	.actions button {
		font-size: 0.75rem;
		padding: 0.3rem 0.6rem;
	}

	.danger {
		color: var(--error, #d66);
	}

	.star {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 0.95rem;
		color: var(--text-dim);
		padding: 0 0.2rem;
	}

	.star.on {
		color: var(--accent);
	}

	.upload {
		margin: 1.2rem 0;
	}

	.row {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
		align-items: center;
	}

	.progress {
		height: 6px;
		background: var(--border);
		border-radius: 3px;
		margin-top: 0.6rem;
		overflow: hidden;
	}

	.bar {
		height: 100%;
		background: var(--accent);
		transition: width 0.4s;
	}

	.ok {
		color: var(--accent);
	}

	.error {
		color: var(--error, #d66);
	}

	.dim {
		color: var(--text-dim);
		font-size: 0.9rem;
	}
</style>

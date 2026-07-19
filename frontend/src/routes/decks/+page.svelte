<script lang="ts">
	import { api, type DeckSummary } from '$lib/api';

	let decks = $state<DeckSummary[]>([]);
	let loaded = $state(false);
	let uploadName = $state('');
	let uploadFile = $state<File | null>(null);
	let uploading = $state(false);
	let uploadError = $state('');

	$effect(() => {
		refresh();
	});

	async function refresh() {
		decks = await api.decks();
		loaded = true;
	}

	async function toggleShare(deck: DeckSummary, e: Event) {
		e.preventDefault();
		e.stopPropagation();
		await api.shareDeck(deck.slug, !deck.shared);
		await refresh();
	}

	let dlSource = $state('');
	let dlName = $state('');
	let dlJob = $state<string | null>(null);
	let dlProgress = $state({ completed: 0, total: 78, failed: 0 });
	let dlError = $state('');
	let dlDoneMsg = $state('');

	async function startDownload() {
		if (!dlSource.trim()) return;
		dlError = '';
		dlDoneMsg = '';
		try {
			const { job } = await api.startDeckDownload(dlSource.trim(), dlName.trim() || undefined);
			dlJob = job;
			poll(job);
		} catch (e) {
			dlError = e instanceof Error ? e.message : String(e);
		}
	}

	async function poll(job: string) {
		try {
			const s = await api.deckDownloadStatus(job);
			dlProgress = { completed: s.completed, total: s.total, failed: s.failed.length };
			if (s.done) {
				dlJob = null;
				if (s.error) {
					dlError = s.error;
				} else {
					dlDoneMsg =
						s.failed.length === 0
							? `“${s.name ?? s.slug}” downloaded (${s.completed}/${s.total}).`
							: `“${s.name ?? s.slug}”: ${s.completed}/${s.total} cards — run the same download again to retry the ${s.failed.length} missing.`;
					dlSource = '';
					dlName = '';
				}
				await refresh();
			} else {
				setTimeout(() => poll(job), 1500);
			}
		} catch {
			setTimeout(() => poll(job), 3000);
		}
	}

	async function upload() {
		if (!uploadFile || !uploadName.trim()) return;
		uploading = true;
		uploadError = '';
		try {
			await api.uploadDeck(uploadFile, uploadName.trim());
			uploadName = '';
			uploadFile = null;
			await refresh();
		} catch (e) {
			uploadError = e instanceof Error ? e.message : String(e);
		} finally {
			uploading = false;
		}
	}

	function deckLabel(deck: DeckSummary): string {
		if (deck.complete) return '78 cards';
		if (deck.majors_only) return '22 cards · majors only';
		return `${deck.count}/78 cards`;
	}
</script>

<h1>Decks</h1>

{#if loaded && decks.length === 0}
	<p>
		No decks installed yet. Upload one below, or run
		<code>tarot-dl &lt;source-url&gt;</code> on the server.
	</p>
{/if}

<section class="upload">
	<h2>Download a deck</h2>
	<p class="dim">
		Paste a deck page URL from a supported site, type <code>rws</code> for the classic
		Rider–Waite–Smith, or use a URL template with <code>{'{n}'}</code>. Downloads into
		your personal collection — for personal use only.
	</p>
	<div class="row">
		<input type="text" placeholder="https://… or rws" bind:value={dlSource} disabled={dlJob !== null} />
		<input type="text" placeholder="Name (optional)" bind:value={dlName} disabled={dlJob !== null} />
		<button onclick={startDownload} disabled={dlJob !== null || !dlSource.trim()}>
			{dlJob ? 'Downloading…' : 'Download'}
		</button>
	</div>
	{#if dlJob}
		<div class="progress">
			<div class="bar" style="width: {(dlProgress.completed / dlProgress.total) * 100}%"></div>
		</div>
		<p class="dim">
			{dlProgress.completed}/{dlProgress.total} cards
			{#if dlProgress.failed}· {dlProgress.failed} failed{/if}
		</p>
	{/if}
	{#if dlDoneMsg}<p class="ok">{dlDoneMsg}</p>{/if}
	{#if dlError}<p class="error">{dlError}</p>{/if}
</section>

<section class="upload">
	<h2>Upload a deck</h2>
	<p class="dim">
		Zip of card images: 78 for a full deck, 22 for majors-only — or number the
		files <code>00</code>–<code>77</code> to map them explicitly (majors 0–21, then
		wands, cups, swords, pentacles: ace, 2–10, page, knight, queen, king). Include
		<code>back.jpg</code> for a card back. Goes into your personal collection.
	</p>
	<div class="row">
		<input type="text" placeholder="Deck name" bind:value={uploadName} />
		<input
			type="file"
			accept=".zip"
			onchange={(e) => (uploadFile = e.currentTarget.files?.[0] ?? null)}
		/>
		<button onclick={upload} disabled={uploading || !uploadFile || !uploadName.trim()}>
			{uploading ? 'Uploading…' : 'Upload'}
		</button>
	</div>
	{#if uploadError}<p class="error">{uploadError}</p>{/if}
</section>

<div class="grid">
	{#each decks as deck (deck.slug)}
		<a class="deck" href="/decks/{deck.slug}">
			<img src={api.cardImage(deck.slug, 0)} alt="{deck.name} — The Fool" loading="lazy" />
			<strong>{deck.name}</strong>
			<small>
				{deckLabel(deck)}
				{#if deck.owner && !deck.yours}· <span class="badge">{deck.owner}</span>{/if}
			</small>
			{#if deck.yours}
				<button class="share" onclick={(e) => toggleShare(deck, e)}>
					{deck.shared ? 'Shared ✓ (click to unshare)' : 'Share with instance'}
				</button>
			{/if}
		</a>
	{/each}
</div>

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
		gap: 1.2rem;
	}

	.deck {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		color: var(--text);
	}

	.deck img {
		width: 100%;
		aspect-ratio: var(--card-ratio);
		object-fit: cover;
		border-radius: 8px;
		border: 1px solid var(--border);
		transition: transform 0.15s;
	}

	.deck:hover img {
		transform: translateY(-3px);
	}

	.deck small {
		color: var(--text-dim);
	}

	.badge {
		color: var(--accent);
	}

	.share {
		font-size: 0.75rem;
		padding: 0.3rem 0.6rem;
		margin-top: 0.2rem;
	}

	code {
		background: var(--bg-raised);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
	}

	.upload {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 1rem 1.2rem;
		margin-bottom: 1.6rem;
	}

	.upload h2 {
		font-size: 1.05rem;
	}

	.upload .row {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
		align-items: center;
	}

	.upload input[type='text'] {
		max-width: 16rem;
	}

	.upload input[type='file'] {
		color: var(--text-dim);
	}

	.dim {
		color: var(--text-dim);
	}

	.error {
		color: var(--danger);
	}

	.ok {
		color: var(--gold);
	}

	.progress {
		height: 6px;
		background: var(--bg-raised);
		border-radius: 3px;
		overflow: hidden;
		margin-top: 0.8rem;
	}

	.progress .bar {
		height: 100%;
		background: linear-gradient(90deg, var(--accent), var(--gold));
		transition: width 0.6s;
	}
</style>

<script lang="ts">
	import { api, type Account, type GrantedShare } from '$lib/api';

	let account = $state<Account | null>(null);
	let busy = $state('');

	$effect(() => {
		load();
	});

	async function load() {
		account = await api.account();
	}

	function fmtDate(ts: number): string {
		return new Date(ts * 1000).toLocaleDateString(undefined, { dateStyle: 'medium' });
	}

	function title(s: { question: string | null; spread: string }): string {
		return s.question || s.spread.replace(/-/g, ' ');
	}

	// Revoke one grantee by re-setting the share without them; drop to private
	// when they were the last one.
	async function revoke(share: GrantedShare, grantee: string) {
		busy = `${share.id}:${grantee}`;
		const remaining = share.shared_with.filter((g) => g !== grantee);
		await api.setSharing(share.id, remaining.length ? 'specific' : 'private', remaining);
		await load();
		busy = '';
	}

	async function makePrivate(share: GrantedShare) {
		busy = `${share.id}:all`;
		await api.setSharing(share.id, 'private', []);
		await load();
		busy = '';
	}
</script>

<h1>Account</h1>

{#if account}
	<section class="identity">
		<div class="who">
			<span class="name">☾ {account.display_name}</span>
			{#if account.is_admin}<span class="tag">admin</span>{/if}
			{#if !account.authenticated}<span class="tag warn">local / LAN</span>{/if}
		</div>
		<p class="dim">
			Saved under <code>{account.user}</code> · {account.reading_count} reading{account.reading_count ===
			1
				? ''
				: 's'}
			· {account.published_decks.length} published deck{account.published_decks.length === 1
				? ''
				: 's'}
		</p>
	</section>

	<section>
		<h2>Readings you've shared</h2>
		{#if account.shares_granted.length === 0}
			<p class="dim">You haven't shared any readings.</p>
		{:else}
			<ul class="shares">
				{#each account.shares_granted as s (s.id)}
					<li>
						<a href="/journal/{s.id}" class="rlink">{title(s)}</a>
						<span class="dim">· {fmtDate(s.created_at)}</span>
						{#if s.visibility === 'everyone'}
							<div class="row">
								<span class="tag">Everyone</span>
								<button disabled={busy === `${s.id}:all`} onclick={() => makePrivate(s)}>
									Make private
								</button>
							</div>
						{:else}
							<div class="grantees">
								{#each s.shared_with as g (g)}
									<span class="chip">
										{g}
										<button
											class="x"
											title="Revoke {g}"
											disabled={busy === `${s.id}:${g}`}
											onclick={() => revoke(s, g)}>×</button
										>
									</span>
								{/each}
							</div>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section>
		<h2>Shared with you</h2>
		{#if account.shares_received.length === 0}
			<p class="dim">No one has shared a reading with you.</p>
		{:else}
			<ul class="shares">
				{#each account.shares_received as s (s.id)}
					<li>
						<a href="/journal/{s.id}" class="rlink">{title(s)}</a>
						<span class="dim">· from {s.owner} · {fmtDate(s.granted_at)}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<section>
		<h2>Decks you've published</h2>
		{#if account.published_decks.length === 0}
			<p class="dim">You haven't published any decks to the shared library.</p>
		{:else}
			<ul class="shares">
				{#each account.published_decks as d (d.slug)}
					<li><a href="/decks/{d.slug}" class="rlink">{d.name}</a></li>
				{/each}
			</ul>
		{/if}
	</section>
{:else}
	<p class="dim">Loading…</p>
{/if}

<style>
	.identity {
		margin-bottom: 1.5rem;
	}
	.who {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.name {
		font-size: 1.2rem;
		font-weight: 600;
	}
	section {
		margin-bottom: 1.8rem;
	}
	h2 {
		font-size: 1.05rem;
		margin-bottom: 0.6rem;
	}
	.shares {
		list-style: none;
		padding: 0;
		display: grid;
		gap: 0.7rem;
	}
	.shares li {
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
	}
	.rlink {
		font-weight: 600;
		color: var(--text);
	}
	.row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: 0.4rem;
	}
	.grantees {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 0.4rem;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.15rem 0.2rem 0.15rem 0.5rem;
		background: var(--bg-raised);
		border-radius: 999px;
		font-size: 0.85rem;
	}
	.chip .x {
		border: 0;
		background: transparent;
		cursor: pointer;
		font-size: 1rem;
		line-height: 1;
		padding: 0 0.3rem;
		color: var(--accent);
	}
	.tag {
		font-size: 0.75rem;
		padding: 0.1rem 0.45rem;
		border-radius: 999px;
		background: var(--bg-raised);
		color: var(--accent);
	}
	.tag.warn {
		color: #e0a030;
	}
	code {
		background: var(--bg-raised);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
	}
</style>

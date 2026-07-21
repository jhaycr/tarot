<script lang="ts">
	import '../app.css';
	import favicon from '$lib/assets/favicon.svg';
	import { page } from '$app/state';

	import { api } from '$lib/api';

	let { children } = $props();

	let user = $state('');
	let logoutUrl = $state<string | null>(null);
	$effect(() => {
		api.me().then((m) => {
			user = m.display_name;
			logoutUrl = m.logout_url;
		});
	});

	const links = [
		{ href: '/', label: 'Reading' },
		{ href: '/decks', label: 'Decks' },
		{ href: '/journal', label: 'Journal' },
		{ href: '/settings', label: 'Settings' }
	];

	function isActive(href: string): boolean {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="shell">
	<header>
		<a class="brand" href="/">✦ Tarotarium</a>
		<nav>
			{#each links as link (link.href)}
				<a href={link.href} class:active={isActive(link.href)}>{link.label}</a>
			{/each}
		</nav>
		{#if user}
			<span class="account">
				<span class="user" title="Readings and decks are saved under this name">☾ {user}</span>
				{#if logoutUrl}
					<a class="logout" href={logoutUrl} data-sveltekit-reload title="Sign out">Log out</a>
				{/if}
			</span>
		{/if}
	</header>
	<main>
		{@render children()}
	</main>
</div>

<style>
	.shell {
		max-width: 72rem;
		margin: 0 auto;
		padding: 0 1rem 4rem;
	}

	header {
		display: flex;
		align-items: baseline;
		gap: 2rem;
		padding: 1.2rem 0.2rem;
		border-bottom: 1px solid var(--border);
		margin-bottom: 1.5rem;
	}

	.brand {
		font-size: 1.3rem;
		color: var(--gold-bright);
		letter-spacing: 0.06em;
	}

	nav {
		display: flex;
		gap: 1.2rem;
	}

	nav a {
		color: var(--text-dim);
		padding-bottom: 0.2rem;
	}

	nav a.active {
		color: var(--gold);
		border-bottom: 1px solid var(--gold);
	}

	.account {
		margin-left: auto;
		display: flex;
		align-items: baseline;
		gap: 0.9rem;
	}

	.user {
		color: var(--text-dim);
		font-size: 0.85rem;
	}

	.logout {
		color: var(--text-dim);
		font-size: 0.85rem;
		border-bottom: 1px solid transparent;
	}

	.logout:hover {
		color: var(--gold);
		border-bottom-color: var(--gold);
	}

	@media (max-width: 480px) {
		header {
			gap: 1rem;
			flex-wrap: wrap;
		}
	}
</style>

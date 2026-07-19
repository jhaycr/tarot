<script lang="ts">
	import { api } from '$lib/api';

	let prompt = $state('');
	let personas = $state<Record<string, string>>({});
	let saved = $state(true);
	let expanded = $state<string | null>(null);

	$effect(() => {
		api.getPrompt().then((r) => {
			prompt = r.prompt;
			personas = r.personas;
		});
	});

	async function save() {
		const r = await api.setPrompt(prompt);
		prompt = r.prompt;
		saved = true;
	}

	async function clear() {
		prompt = '';
		await save();
	}
</script>

<h1>Settings</h1>

<section>
	<h2>Custom reader persona</h2>
	<p class="dim">
		Your own system prompt for AI interpretations. Leave empty to use the built-in
		personas. When saved, it becomes the “Custom” option on the reading page and
		your default reader.
	</p>
	<textarea
		rows="12"
		bind:value={prompt}
		oninput={() => (saved = false)}
		placeholder="You are …, a tarot reader who …"
	></textarea>
	<div class="row">
		<button onclick={save} disabled={saved}>{saved ? 'Saved' : 'Save persona'}</button>
		{#if prompt}
			<button onclick={clear}>Clear (use built-in)</button>
		{/if}
	</div>
</section>

<section>
	<h2>Built-in personas</h2>
	{#each Object.entries(personas) as [slug, text] (slug)}
		<details open={expanded === slug} ontoggle={(e) => { if (e.currentTarget.open) expanded = slug; }}>
			<summary>{slug}</summary>
			<pre>{text}</pre>
		</details>
	{/each}
	<p class="dim">
		Tip: copy a built-in persona into the box above as a starting point for your own.
	</p>
</section>

<style>
	section {
		max-width: 46rem;
		margin-bottom: 2.5rem;
	}

	textarea {
		width: 100%;
		font-size: 0.9rem;
		line-height: 1.5;
	}

	.row {
		display: flex;
		gap: 0.6rem;
		margin-top: 0.6rem;
	}

	details {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		margin-bottom: 0.6rem;
		padding: 0.5rem 0.9rem;
	}

	summary {
		cursor: pointer;
		color: var(--gold);
		text-transform: capitalize;
	}

	pre {
		white-space: pre-wrap;
		font-family: inherit;
		font-size: 0.85rem;
		color: var(--text-dim);
	}

	.dim {
		color: var(--text-dim);
	}
</style>

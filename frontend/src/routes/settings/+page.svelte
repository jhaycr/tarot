<script lang="ts">
	import { api } from '$lib/api';

	let prompt = $state('');
	let personas = $state<Record<string, string>>({});
	let saved = $state(true);
	let expanded = $state<string | null>(null);

	let isAdmin = $state(false);
	let llmBaseUrl = $state('');
	let llmModel = $state('');
	let llmApiKey = $state('');
	let llmKeySet = $state(false);
	let llmFromEnv = $state(false);
	let llmSaved = $state(true);
	let llmError = $state('');

	$effect(() => {
		api.getPrompt().then((r) => {
			prompt = r.prompt;
			personas = r.personas;
		});
		api.me().then((m) => {
			isAdmin = m.is_admin;
			if (m.is_admin) refreshLlm();
		});
	});

	async function refreshLlm() {
		const s = await api.getLlmSettings();
		llmBaseUrl = s.base_url;
		llmModel = s.model;
		llmKeySet = s.api_key_set;
		llmFromEnv = s.from_env;
	}

	async function saveLlm() {
		llmError = '';
		try {
			const s = await api.setLlmSettings({
				base_url: llmBaseUrl,
				model: llmModel,
				...(llmApiKey ? { api_key: llmApiKey } : {})
			});
			llmApiKey = '';
			llmKeySet = s.api_key_set;
			llmFromEnv = s.from_env;
			llmSaved = true;
		} catch (e) {
			llmError = String(e);
		}
	}

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

{#if isAdmin}
	<section>
		<h2>AI connection <small class="dim">(admin)</small></h2>
		<p class="dim">
			Any OpenAI-compatible endpoint. Examples — OpenRouter:
			<code>https://openrouter.ai/api/v1</code> with model <code>minimax/minimax-m2</code>;
			Anthropic: <code>https://api.anthropic.com/v1</code> with model
			<code>claude-haiku-4-5</code>; OpenAI: <code>https://api.openai.com/v1</code> with
			model <code>gpt-4o-mini</code>; local Ollama: <code>http://ollama:11434/v1</code> with
			model <code>llama3.1</code>. The API key is encrypted at rest and never shown again
			after saving.
		</p>
		<label class="fld">
			<span>Base URL</span>
			<input type="text" bind:value={llmBaseUrl} oninput={() => (llmSaved = false)} placeholder="https://openrouter.ai/api/v1" />
		</label>
		<label class="fld">
			<span>Model</span>
			<input type="text" bind:value={llmModel} oninput={() => (llmSaved = false)} placeholder="minimax/minimax-m2" />
		</label>
		<label class="fld">
			<span>API key {#if llmKeySet}<em class="dim">(saved — leave blank to keep)</em>{/if}</span>
			<input type="password" bind:value={llmApiKey} oninput={() => (llmSaved = false)} placeholder={llmKeySet ? '••••••••' : 'sk-…'} autocomplete="off" />
		</label>
		{#if llmFromEnv}<p class="dim">Currently configured from environment variables; saving here overrides them.</p>{/if}
		{#if llmError}<p class="error">{llmError}</p>{/if}
		<button onclick={saveLlm} disabled={llmSaved}>{llmSaved ? 'Saved' : 'Save connection'}</button>
	</section>
{/if}

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

	.fld {
		display: block;
		margin-bottom: 0.8rem;
	}

	.fld > span {
		display: block;
		color: var(--text-dim);
		margin-bottom: 0.25rem;
	}

	.error {
		color: var(--danger);
	}

	code {
		background: var(--bg-raised);
		padding: 0.1rem 0.3rem;
		border-radius: 4px;
	}
</style>

<script lang="ts">
	import { api, type VoiceBlock } from '$lib/api';

	let prompt = $state('');
	let personas = $state<Record<string, string>>({});
	let saved = $state(true);
	let expanded = $state<string | null>(null);
	let customVoice = $state('');
	let customSpeed = $state('');
	let customInstructions = $state('');

	let isAdmin = $state(false);
	let llmBaseUrl = $state('');
	let llmModel = $state('');
	let llmApiKey = $state('');
	let llmKeySet = $state(false);
	let llmFromEnv = $state(false);
	let llmSaved = $state(true);
	let llmError = $state('');
	let llmManaged = $state<string[]>([]);
	let configFile = $state<string | null>(null);
	let configError = $state<string | null>(null);

	let reversalChance = $state(25);
	let reversalSaved = $state(true);
	let reversalManaged = $state(false);

	let ttsEnabled = $state(false);
	let ttsBaseUrl = $state('');
	let ttsModel = $state('');
	let ttsApiKey = $state('');
	let ttsKeySet = $state(false);
	let ttsSaved = $state(true);
	let ttsError = $state('');
	let ttsManaged = $state<string[]>([]);
	// editable copies of the alice/selene voice blocks
	let voices = $state<Record<string, { voice: string; speed: number; instructions: string }>>({});

	const managed = (f: string) => llmManaged.includes(f);
	const tmanaged = (f: string) => ttsManaged.includes(f);

	$effect(() => {
		api.getPrompt().then((r) => {
			prompt = r.prompt;
			personas = r.personas;
			customVoice = r.voice?.voice ?? '';
			customSpeed = r.voice?.speed != null ? String(r.voice.speed) : '';
			customInstructions = r.voice?.instructions ?? '';
		});
		api.me().then((m) => {
			isAdmin = m.is_admin;
			ttsEnabled = m.tts;
			if (m.is_admin) {
				refreshLlm();
				refreshTts();
				api.getReadingSettings().then((s) => {
					reversalChance = s.reversal_chance;
					reversalManaged = s.managed.includes('reversal_chance');
				});
			}
		});
	});

	async function refreshTts() {
		const s = await api.getTtsSettings();
		ttsBaseUrl = s.base_url;
		ttsModel = s.model;
		ttsKeySet = s.api_key_set;
		ttsManaged = s.managed;
		voices = Object.fromEntries(
			Object.entries(s.voices).map(([p, v]) => [
				p,
				{ voice: v.voice ?? '', speed: v.speed ?? 1, instructions: v.instructions ?? '' }
			])
		);
		configFile = s.config_file;
		configError = configError || s.config_error;
	}

	async function saveTts() {
		ttsError = '';
		try {
			const editable = Object.entries(voices).filter(([p]) => !tmanaged(`voice_${p}`));
			await api.setTtsSettings({
				...(tmanaged('base_url') ? {} : { base_url: ttsBaseUrl }),
				...(tmanaged('model') ? {} : { model: ttsModel }),
				...(ttsApiKey && !tmanaged('api_key') ? { api_key: ttsApiKey } : {}),
				voices: Object.fromEntries(
					editable.map(([p, v]) => [
						p,
						{ voice: v.voice, speed: v.speed, instructions: v.instructions }
					])
				)
			});
			ttsApiKey = '';
			await refreshTts();
			ttsSaved = true;
		} catch (e) {
			ttsError = String(e);
		}
	}

	async function saveReversal() {
		const s = await api.setReadingSettings({ reversal_chance: reversalChance });
		reversalChance = s.reversal_chance;
		reversalSaved = true;
	}

	async function refreshLlm() {
		const s = await api.getLlmSettings();
		llmBaseUrl = s.base_url;
		llmModel = s.model;
		llmKeySet = s.api_key_set;
		llmFromEnv = s.from_env;
		llmManaged = s.managed;
		configFile = s.config_file;
		configError = s.config_error;
	}

	async function saveLlm() {
		llmError = '';
		try {
			// Don't send fields the config file owns; the API rejects them.
			const s = await api.setLlmSettings({
				...(managed('base_url') ? {} : { base_url: llmBaseUrl }),
				...(managed('model') ? {} : { model: llmModel }),
				...(llmApiKey && !managed('api_key') ? { api_key: llmApiKey } : {})
			});
			llmApiKey = '';
			llmKeySet = s.api_key_set;
			llmFromEnv = s.from_env;
			llmManaged = s.managed;
			llmSaved = true;
		} catch (e) {
			llmError = String(e);
		}
	}

	async function save() {
		const voice: VoiceBlock = {
			...(customVoice.trim() ? { voice: customVoice.trim() } : {}),
			...(customSpeed.trim() ? { speed: Number(customSpeed) } : {}),
			...(customInstructions.trim() ? { instructions: customInstructions.trim() } : {})
		};
		const r = await api.setPrompt(prompt, Object.keys(voice).length ? voice : null);
		prompt = r.prompt;
		saved = true;
	}

	async function clear() {
		prompt = '';
		customVoice = customSpeed = customInstructions = '';
		await save();
	}
</script>

<h1>Settings</h1>

{#if isAdmin}
	<section>
		<h2>Readings <small class="dim">(admin)</small></h2>
		<label class="fld">
			<span>Reversal chance — how often a drawn card lands reversed (when the querent allows
				reversals). Physical decks rarely exceed ~25%; 50% is a fully scrambled deck.</span>
			<span class="range">
				<input
					type="range"
					min="0"
					max="100"
					step="5"
					bind:value={reversalChance}
					oninput={() => (reversalSaved = false)}
					disabled={reversalManaged}
				/>
				<strong>{reversalChance}%</strong>
			</span>
		</label>
		{#if reversalManaged}
			<p class="managed">Managed by <code>{configFile}</code> — edit the config file.</p>
		{:else}
			<button onclick={saveReversal} disabled={reversalSaved}>
				{reversalSaved ? 'Saved' : 'Save'}
			</button>
		{/if}
	</section>

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
		{#if configError}
			<p class="error">Config file problem — {configError}</p>
		{/if}
		<label class="fld">
			<span>Base URL {#if managed('base_url')}<em class="dim">(managed)</em>{/if}</span>
			<input type="text" bind:value={llmBaseUrl} oninput={() => (llmSaved = false)} disabled={managed('base_url')} placeholder="https://openrouter.ai/api/v1" />
		</label>
		<label class="fld">
			<span>Model {#if managed('model')}<em class="dim">(managed)</em>{/if}</span>
			<input type="text" bind:value={llmModel} oninput={() => (llmSaved = false)} disabled={managed('model')} placeholder="minimax/minimax-m2" />
		</label>
		<label class="fld">
			<span>API key
				{#if managed('api_key')}<em class="dim">(managed)</em>
				{:else if llmKeySet}<em class="dim">(saved — leave blank to keep)</em>{/if}</span>
			<input type="password" bind:value={llmApiKey} oninput={() => (llmSaved = false)} disabled={managed('api_key')} placeholder={llmKeySet ? '••••••••' : 'sk-…'} autocomplete="off" />
		</label>
		{#if llmManaged.length}
			<p class="managed">
				{llmManaged.length === 3 ? 'Managed' : 'Partly managed'} by <code>{configFile}</code> —
				edit the config file rather than this page.
			</p>
		{:else if llmFromEnv}
			<p class="dim">Currently configured from environment variables; saving here overrides them.</p>
		{/if}
		{#if llmError}<p class="error">{llmError}</p>{/if}
		{#if llmManaged.length < 3}
			<button onclick={saveLlm} disabled={llmSaved}>{llmSaved ? 'Saved' : 'Save connection'}</button>
		{/if}
	</section>

	<section>
		<h2>Voice (text-to-speech) <small class="dim">(admin)</small></h2>
		<p class="dim">
			Any OpenAI-compatible <code>/audio/speech</code> endpoint. OpenAI:
			<code>https://api.openai.com/v1</code> with model <code>gpt-4o-mini-tts</code>
			(supports style instructions); self-hosted Kokoro (kokoro-fastapi):
			<code>http://kokoro:8880/v1</code> with model <code>kokoro</code> (pick a voice like
			<code>af_heart</code>; instructions are ignored). Leave the Base URL empty to turn the
			feature off — audio buttons only appear when it's configured.
		</p>
		<label class="fld">
			<span>Base URL {#if tmanaged('base_url')}<em class="dim">(managed)</em>{/if}</span>
			<input type="text" bind:value={ttsBaseUrl} oninput={() => (ttsSaved = false)} disabled={tmanaged('base_url')} placeholder="https://api.openai.com/v1" />
		</label>
		<label class="fld">
			<span>Model {#if tmanaged('model')}<em class="dim">(managed)</em>{/if}</span>
			<input type="text" bind:value={ttsModel} oninput={() => (ttsSaved = false)} disabled={tmanaged('model')} placeholder="gpt-4o-mini-tts" />
		</label>
		<label class="fld">
			<span>API key
				{#if tmanaged('api_key')}<em class="dim">(managed)</em>
				{:else if ttsKeySet}<em class="dim">(saved — leave blank to keep)</em>{/if}</span>
			<input type="password" bind:value={ttsApiKey} oninput={() => (ttsSaved = false)} disabled={tmanaged('api_key')} placeholder={ttsKeySet ? '••••••••' : 'sk-…'} autocomplete="off" />
		</label>
		{#each Object.entries(voices) as [p, v] (p)}
			<fieldset class="voice">
				<legend>{p} {#if tmanaged(`voice_${p}`)}<em class="dim">(managed)</em>{/if}</legend>
				<div class="voicerow">
					<label class="fld">
						<span>Voice</span>
						<input type="text" bind:value={v.voice} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)} />
					</label>
					<label class="fld">
						<span>Speed</span>
						<input type="number" min="0.25" max="4" step="0.05" bind:value={v.speed} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)} />
					</label>
				</div>
				<label class="fld">
					<span>Style instructions (OpenAI only)</span>
					<textarea rows="2" bind:value={v.instructions} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)}></textarea>
				</label>
			</fieldset>
		{/each}
		{#if ttsManaged.length}
			<p class="managed">Partly managed by <code>{configFile}</code> — edit the config file rather than this page.</p>
		{/if}
		{#if ttsError}<p class="error">{ttsError}</p>{/if}
		<button onclick={saveTts} disabled={ttsSaved}>{ttsSaved ? 'Saved' : 'Save voice settings'}</button>
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
	{#if ttsEnabled && prompt}
		<div class="customvoice">
			<p class="dim">Your persona's voice (optional — defaults to the instance default):</p>
			<div class="voicerow">
				<label class="fld">
					<span>Voice</span>
					<input type="text" bind:value={customVoice} oninput={() => (saved = false)} placeholder="e.g. onyx" />
				</label>
				<label class="fld">
					<span>Speed</span>
					<input type="text" inputmode="decimal" bind:value={customSpeed} oninput={() => (saved = false)} placeholder="1.0" />
				</label>
			</div>
			<label class="fld">
				<span>Style instructions (OpenAI only)</span>
				<textarea rows="2" bind:value={customInstructions} oninput={() => (saved = false)} placeholder="How should your reader sound?"></textarea>
			</label>
		</div>
	{/if}
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

	.managed {
		color: var(--text-dim);
		border-left: 2px solid var(--line, #3a3a4a);
		padding-left: 0.6rem;
		font-size: 0.92em;
	}

	.fld {
		display: block;
		margin-bottom: 0.8rem;
	}

	.fld input:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.fld > span {
		display: block;
		color: var(--text-dim);
		margin-bottom: 0.25rem;
	}

	.error {
		color: var(--danger);
	}

	.range {
		display: flex;
		align-items: center;
		gap: 0.8rem;
	}

	.range input {
		flex: 1;
		accent-color: var(--gold);
	}

	.range strong {
		color: var(--gold-bright);
		min-width: 3rem;
		text-align: right;
	}

	code {
		background: var(--bg-raised);
		padding: 0.1rem 0.3rem;
		border-radius: 4px;
	}

	.voice {
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 0.6rem 0.9rem;
		margin-bottom: 0.8rem;
	}

	.voice legend {
		text-transform: capitalize;
		color: var(--gold);
		padding: 0 0.4rem;
	}

	.voicerow {
		display: flex;
		gap: 0.8rem;
	}

	.voicerow .fld {
		flex: 1;
	}

	.voicerow .fld:last-child {
		max-width: 8rem;
	}

	.customvoice {
		margin-top: 0.8rem;
	}
</style>

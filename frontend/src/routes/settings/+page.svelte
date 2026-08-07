<script lang="ts">
	import { api, type UsageSummary } from '$lib/api';


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

	let limReadings = $state('');
	let limTokens = $state('');
	let limMinutes = $state('');
	let limManaged = $state<string[]>([]);
	let limSaved = $state(true);
	let limError = $state('');
	const lmanaged = (f: string) => limManaged.includes(f);

	async function refreshLimits() {
		const s = await api.getLimitsSettings();
		limReadings = s.readings_per_day != null ? String(s.readings_per_day) : '';
		limTokens = s.llm_tokens_per_day != null ? String(s.llm_tokens_per_day) : '';
		limMinutes = s.tts_minutes_per_day != null ? String(s.tts_minutes_per_day) : '';
		limManaged = s.managed;
		configFile = s.config_file;
		configError = configError || s.config_error;
	}

	async function saveLimits() {
		limError = '';
		try {
			// blank = disabled (sent as 0, stored as unset); managed fields not sent
			const num = (v: string) => (v.trim() === '' ? 0 : Number(v));
			await api.setLimitsSettings({
				...(lmanaged('readings_per_day') ? {} : { readings_per_day: num(limReadings) }),
				...(lmanaged('llm_tokens_per_day') ? {} : { llm_tokens_per_day: num(limTokens) }),
				...(lmanaged('tts_minutes_per_day') ? {} : { tts_minutes_per_day: num(limMinutes) })
			});
			await refreshLimits();
			limSaved = true;
		} catch (e) {
			limError = String(e);
		}
	}

	let usage = $state<UsageSummary | null>(null);
	let usageDays = $state(30);

	async function loadUsage() {
		usage = await api.adminUsage(usageDays);
	}

	const fmt = (n: number) => n.toLocaleString();
	// OpenAI TTS returns ~128 kbps MP3 -> ~0.94 MB per audio-minute
	const audioMinutes = (bytes: number) => (bytes / 983040).toFixed(1);

	let autoRead = $state(false);
	let autoReadError = $state('');
	let hideDrafts = $state(false);
	let hideDraftsError = $state('');
	let displayName = $state('');
	let displayNameSaved = $state(true);
	let displayNameError = $state('');

	async function saveDisplayName() {
		displayNameError = '';
		try {
			const r = await api.patchMe({ display_name: displayName.trim() });
			displayName = r.display_name;
			displayNameSaved = true;
		} catch {
			displayNameError = 'Could not save — try again.';
		}
	}

	async function setHideDrafts(v: boolean) {
		hideDrafts = v;
		hideDraftsError = '';
		try {
			await api.setMySettings({ hide_draft_decks: v });
		} catch {
			hideDrafts = !v;
			hideDraftsError = 'Could not save — try again.';
		}
	}

	async function setAutoRead(v: boolean) {
		autoRead = v;
		autoReadError = '';
		try {
			await api.setMySettings({ auto_read_audio: v });
		} catch {
			autoRead = !v;
			autoReadError = 'Could not save — try again.';
		}
	}

	$effect(() => {
		api.me().then((m) => {
			isAdmin = m.is_admin;
			ttsEnabled = m.tts;
			autoRead = m.settings.auto_read_audio;
			hideDrafts = m.settings.hide_draft_decks;
			displayName = m.display_name;
			if (m.is_admin) {
				refreshLlm();
				refreshTts();
				refreshLimits();
				loadUsage();
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

</script>

<h1>Settings</h1>

<section>
	<h2>Display name</h2>
	<label class="fld">
		<span>How your name appears in shares and the journal. Clearing it goes back to the
			name from your sign-in.</span>
		<input
			type="text"
			bind:value={displayName}
			maxlength="64"
			oninput={() => (displayNameSaved = false)}
			onkeydown={(e) => e.key === 'Enter' && saveDisplayName()}
		/>
	</label>
	{#if !displayNameSaved}
		<button onclick={saveDisplayName}>Save name</button>
	{/if}
	{#if displayNameError}<p class="error">{displayNameError}</p>{/if}
</section>

{#if ttsEnabled}
	<section>
		<h2>Reading audio</h2>
		<label class="fld checkline">
			<input type="checkbox" checked={autoRead} onchange={(e) => setAutoRead(e.currentTarget.checked)} />
			<span>Read readings aloud automatically — each card's reading (and the whole picture)
				starts speaking as it appears. Saved to your account, so it applies on every device.
				You can also toggle this during a guided reading.</span>
		</label>
		{#if autoReadError}<p class="error">{autoReadError}</p>{/if}
	</section>
{/if}

<section>
	<h2>Reading decks</h2>
	<label class="fld checkline">
		<input type="checkbox" checked={hideDrafts} onchange={(e) => setHideDrafts(e.currentTarget.checked)} />
		<span>Hide your draft (unpublished) decks when starting a reading. They stay visible on
			the Decks page; partial or work-in-progress decks just won't clutter the picker.
			Saved to your account.</span>
	</label>
	{#if hideDraftsError}<p class="error">{hideDraftsError}</p>{/if}
</section>

{#if !isAdmin}
	<p class="dim">
		Your deck, spread, reversal, and reader choices are remembered automatically as you use
		them. Instance-wide settings (AI connection, voices, reversal chance) are managed by an
		admin.
	</p>
{/if}

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

	<section>
		<h2>Daily limits <small class="dim">(admin)</small></h2>
		<p class="dim">
			Per-person daily caps that stop runaway AI spend. Blank = no cap. Admins are always
			exempt. Blocked users see "resets at midnight"; drawing cards and the journal keep
			working — only AI generation pauses. A cap can be passed slightly by one in-flight
			call, never more.
		</p>
		<div class="voicerow">
			<label class="fld">
				<span>Readings / day {#if lmanaged('readings_per_day')}<em class="dim">(managed)</em>{/if}</span>
				<input type="text" inputmode="numeric" bind:value={limReadings} oninput={() => (limSaved = false)} disabled={lmanaged('readings_per_day')} placeholder="e.g. 10" />
			</label>
			<label class="fld">
				<span>LLM tokens / day {#if lmanaged('llm_tokens_per_day')}<em class="dim">(managed)</em>{/if}</span>
				<input type="text" inputmode="numeric" bind:value={limTokens} oninput={() => (limSaved = false)} disabled={lmanaged('llm_tokens_per_day')} placeholder="e.g. 150000" />
			</label>
			<label class="fld">
				<span>Voice minutes / day {#if lmanaged('tts_minutes_per_day')}<em class="dim">(managed)</em>{/if}</span>
				<input type="text" inputmode="decimal" bind:value={limMinutes} oninput={() => (limSaved = false)} disabled={lmanaged('tts_minutes_per_day')} placeholder="e.g. 30" />
			</label>
		</div>
		{#if limManaged.length}
			<p class="managed">Partly managed by <code>{configFile}</code> — edit the config file rather than this page.</p>
		{/if}
		{#if limError}<p class="error">{limError}</p>{/if}
		{#if limManaged.length < 3}
			<button onclick={saveLimits} disabled={limSaved}>{limSaved ? 'Saved' : 'Save limits'}</button>
		{/if}
	</section>

	<section>
		<h2>AI usage <small class="dim">(admin)</small></h2>
		<p class="dim">
			One ledger row per paid provider call — cached audio replays and aborted
			streams cost nothing and aren't counted. Token counts come from the
			provider when it reports them.
		</p>
		<label class="fld daysfld">
			<span>Period</span>
			<select bind:value={usageDays} onchange={loadUsage}>
				<option value={7}>Last 7 days</option>
				<option value={30}>Last 30 days</option>
				<option value={90}>Last 90 days</option>
				<option value={365}>Last year</option>
			</select>
		</label>
		{#if usage}
			{#if !usage.by_model.length}
				<p class="dim">No AI calls recorded in this period. (The ledger starts with this version — older readings predate it.)</p>
			{:else}
				<h3>By model</h3>
				<div class="tablewrap">
					<table>
						<thead><tr><th>Component</th><th>Model</th><th>Calls</th><th>Prompt tok</th><th>Output tok</th><th>Audio</th></tr></thead>
						<tbody>
							{#each usage.by_model as m (m.component + m.model)}
								<tr>
									<td>{m.component === 'llm' ? 'LLM' : 'Voice'}</td>
									<td><code>{m.model}</code></td>
									<td>{fmt(m.calls)}</td>
									<td>{m.component === 'llm' ? fmt(m.prompt_tokens) : '—'}</td>
									<td>{m.component === 'llm' ? fmt(m.completion_tokens) : '—'}</td>
									<td>{m.component === 'tts' ? `${audioMinutes(m.audio_bytes)} min · ${fmt(m.characters)} chars` : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<h3>By person</h3>
				<div class="tablewrap">
					<table>
						<thead><tr><th>Person</th><th>Component</th><th>Calls</th><th>Tokens (in / out)</th><th>Audio</th></tr></thead>
						<tbody>
							{#each usage.by_user as r (r.owner + r.component)}
								<tr>
									<td>{r.owner}</td>
									<td>{r.component === 'llm' ? 'LLM' : 'Voice'}</td>
									<td>{fmt(r.calls)}</td>
									<td>{r.component === 'llm' ? `${fmt(r.prompt_tokens)} / ${fmt(r.completion_tokens)}` : '—'}</td>
									<td>{r.component === 'tts' ? `${audioMinutes(r.audio_bytes)} min` : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				<h3>By day</h3>
				<div class="tablewrap">
					<table>
						<thead><tr><th>Day</th><th>Calls</th><th>Tokens (in / out)</th><th>Audio</th></tr></thead>
						<tbody>
							{#each usage.daily as d (d.day)}
								<tr>
									<td>{d.day}</td>
									<td>{fmt(d.calls)}</td>
									<td>{fmt(d.prompt_tokens)} / {fmt(d.completion_tokens)}</td>
									<td>{d.audio_bytes ? `${audioMinutes(d.audio_bytes)} min` : '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/if}
	</section>
{/if}


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

	.daysfld select {
		width: auto;
	}

	.checkline {
		display: flex;
		gap: 0.6rem;
		align-items: flex-start;
		cursor: pointer;
	}

	.checkline input {
		margin-top: 0.25rem;
		accent-color: var(--gold);
	}

	.tablewrap {
		overflow-x: auto;
	}

	table {
		border-collapse: collapse;
		width: 100%;
		font-size: 0.9rem;
		font-variant-numeric: tabular-nums;
	}

	th,
	td {
		text-align: left;
		padding: 0.35rem 0.9rem 0.35rem 0;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}

	th {
		color: var(--text-dim);
		font-weight: 600;
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	section h3 {
		font-size: 0.95rem;
		margin: 1.1rem 0 0.4rem;
	}
</style>

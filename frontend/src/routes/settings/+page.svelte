<script lang="ts">
	import {
		api,
		type AdminUser,
		type DesignedVoice,
		type ProviderVoice,
		type ReassignReport,
		type TtsSettings,
		type UsageSummary,
		type VoiceProvider,
		type VoiceValues
	} from '$lib/api';


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
	let ttsProvider = $state('openai');
	let ttsProviders = $state<VoiceProvider[]>([]);
	let ttsGaps = $state<Record<string, string[]>>({});
	let ttsConnections = $state<TtsSettings['connections']>({});
	// Editable per-persona blocks for the ACTIVE provider. Shape varies by
	// provider, so the form is generated from its declared fields.
	let voices = $state<Record<string, VoiceValues>>({});
	let providerVoices = $state<ProviderVoice[]>([]);
	let voiceListError = $state('');
	let previewAudio: HTMLAudioElement | null = null;
	// Voice design (providers that build a voice from prose)
	let descriptions = $state<Record<string, string>>({});
	let designOpen = $state('');           // persona whose panel is open
	let designText = $state('');
	let designBusy = $state(false);
	let designError = $state('');
	let designCandidates = $state<DesignedVoice[]>([]);

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

	let people = $state<AdminUser[]>([]);
	let me_username = $state('');
	let peopleError = $state('');
	let reassignTarget = $state<Record<string, string>>({});
	let reassignReport = $state<ReassignReport | null>(null);
	// Pending flag edits, keyed by username — nothing is sent until Save.
	let edits = $state<Record<string, { is_admin?: boolean; active?: boolean }>>({});
	const dirtyCount = $derived(Object.keys(edits).length);

	async function loadPeople() {
		people = await api.adminUsers();
		edits = {};
	}

	function flagOf(u: AdminUser, flag: 'is_admin' | 'active'): boolean {
		return edits[u.username]?.[flag] ?? u[flag];
	}

	function editFlag(u: AdminUser, flag: 'is_admin' | 'active', value: boolean) {
		const pending = { ...edits[u.username], [flag]: value };
		// drop entries that are back to the server state
		if (pending.is_admin === u.is_admin) delete pending.is_admin;
		if (pending.active === u.active) delete pending.active;
		if (Object.keys(pending).length) edits[u.username] = pending;
		else delete edits[u.username];
	}

	async function savePeople() {
		peopleError = '';
		for (const [username, patch] of Object.entries(edits)) {
			try {
				await api.adminUserUpdate(username, patch);
			} catch (e) {
				peopleError = `${username}: ${errMsgOf(e)}`;
			}
		}
		await loadPeople();
	}

	async function reassign(u: AdminUser) {
		const to = reassignTarget[u.username];
		if (!to) return;
		if (!confirm(`Move ALL of ${u.username}'s readings, settings, drafts and history to ${to}, then deactivate ${u.username}? This cannot be undone from the UI.`)) return;
		peopleError = '';
		try {
			reassignReport = await api.adminReassign(u.username, to);
			await loadPeople();
		} catch (e) {
			peopleError = errMsgOf(e);
		}
	}

	function errMsgOf(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	async function deleteUser(u: AdminUser) {
		if (!confirm(`Permanently DELETE ${u.username}? Their readings, shares, settings and drafts are erased; anything they published stays as "former member". This cannot be undone.`)) return;
		peopleError = '';
		try {
			await api.adminUserDelete(u.username);
			await loadPeople();
		} catch (e) {
			peopleError = errMsgOf(e);
		}
	}

	$effect(() => {
		api.me().then((m) => {
			isAdmin = m.is_admin;
			me_username = m.user;
			ttsEnabled = m.tts;
			autoRead = m.settings.auto_read_audio;
			hideDrafts = m.settings.hide_draft_decks;
			displayName = m.display_name;
			if (m.is_admin) {
				refreshLlm();
				refreshTts();
				refreshLimits();
				loadUsage();
				loadPeople();
				api.getReadingSettings().then((s) => {
					reversalChance = s.reversal_chance;
					reversalManaged = s.managed.includes('reversal_chance');
				});
			}
		});
	});

	async function refreshTts() {
		const s = await api.getTtsSettings();
		ttsProvider = s.provider;
		ttsProviders = s.providers;
		ttsConnections = s.connections;
		ttsBaseUrl = s.base_url;
		ttsModel = s.model;
		ttsKeySet = s.api_key_set;
		ttsManaged = s.managed;
		ttsGaps = s.gaps;
		// Blocks are provider-shaped; start from the provider's defaults so
		// every declared field has a value to bind to.
		voices = Object.fromEntries(
			Object.entries(s.voices).map(([p, v]) => [p, { ...(s.defaults[p] ?? {}), ...(v ?? {}) }])
		);
		configFile = s.config_file;
		configError = configError || s.config_error;
		descriptions = s.descriptions;
		providerVoices = [];
		voiceListError = '';
		if (activeProvider?.supports_listing) loadProviderVoices();
	}

	/** Seed the design prompt from the persona's own written character —
	 * the same prose that steers OpenAI, reused at design time. */
	function openDesign(persona: string) {
		designOpen = persona;
		designText = descriptions[persona] ?? '';
		designCandidates = [];
		designError = '';
	}

	async function runDesign() {
		designBusy = true;
		designError = '';
		designCandidates = [];
		try {
			designCandidates = await api.designVoice(designText);
		} catch (e) {
			designError = e instanceof Error ? e.message : String(e);
		} finally {
			designBusy = false;
		}
	}

	async function keepDesigned(persona: string, chosen: DesignedVoice) {
		designBusy = true;
		designError = '';
		try {
			const { voice_id } = await api.keepDesignedVoice({
				generated_voice_id: chosen.generated_voice_id,
				name: `Tarotarium ${persona}`,
				description: designText,
				rejected: designCandidates
					.filter((c) => c.generated_voice_id !== chosen.generated_voice_id)
					.map((c) => c.generated_voice_id)
			});
			voices[persona] = { ...voices[persona], voice_id };
			ttsSaved = false;
			designOpen = '';
			designCandidates = [];
			await loadProviderVoices();
		} catch (e) {
			designError = e instanceof Error ? e.message : String(e);
		} finally {
			designBusy = false;
		}
	}

	/** The active provider's field specs drive the whole form. */
	const activeProvider = $derived(ttsProviders.find((p) => p.name === ttsProvider));

	async function loadProviderVoices() {
		voiceListError = '';
		try {
			providerVoices = await api.listProviderVoices();
		} catch (e) {
			// Not fatal: the form falls back to a free-text field.
			providerVoices = [];
			voiceListError = e instanceof Error ? e.message : String(e);
		}
	}

	/** Switching provider re-renders the form against that provider's OWN
	 * stored connection and voice blocks. Nothing is carried across — sending
	 * the previous provider's model/base_url would save them under the new
	 * one (which is how ElevenLabs ended up labelled gpt-4o-mini-tts). */
	function pickProvider(name: string) {
		ttsProvider = name;
		ttsSaved = false;
		const conn = ttsConnections[name];
		ttsBaseUrl = conn?.base_url ?? '';
		ttsModel = conn?.model ?? '';
		ttsKeySet = conn?.api_key_set ?? false;
		ttsApiKey = '';
		ttsGaps = conn?.gaps ?? {};
		// That provider's OWN stored blocks (falling back to its defaults),
		// never the previous provider's values and never blanks over data
		// that is still on the server.
		voices = Object.fromEntries(
			Object.keys(conn?.defaults ?? voices).map((persona) => [
				persona,
				{ ...(conn?.defaults?.[persona] ?? {}), ...(conn?.voices?.[persona] ?? {}) }
			])
		);
		providerVoices = [];
		voiceListError = '';
		designOpen = '';
		if (ttsProviders.find((x) => x.name === name)?.supports_listing) loadProviderVoices();
	}

	function applyVoicePreset(persona: string, voiceId: string) {
		const v = providerVoices.find((x) => x.id === voiceId);
		if (!v) return;
		voices[persona] = { ...voices[persona], ...v.settings, voice_id: v.id };
		ttsSaved = false;
	}

	function preview(url: string | null) {
		if (!url) return;
		previewAudio?.pause();
		previewAudio = new Audio(url);
		previewAudio.play().catch(() => {});
	}

	async function saveTts() {
		ttsError = '';
		try {
			const editable = Object.entries(voices).filter(([p]) => !tmanaged(`voice_${p}`));
			await api.setTtsSettings({
				...(tmanaged('provider') ? {} : { provider: ttsProvider }),
				...(tmanaged('base_url') ? {} : { base_url: ttsBaseUrl }),
				...(tmanaged('model') ? {} : { model: ttsModel }),
				...(ttsApiKey && !tmanaged('api_key') ? { api_key: ttsApiKey } : {}),
				voices: Object.fromEntries(editable)
			});
			ttsApiKey = '';
			await refreshTts();
			ttsSaved = true;
		} catch (e) {
			ttsError = e instanceof Error ? e.message : String(e);
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
		<h2>People <small class="dim">(admin)</small></h2>
		<div class="people">
			{#each people as u (u.username)}
				<div class="person" class:inactive={!u.active}>
					<span class="who">
						<strong>{u.display_name}</strong>
						<small class="dim">{u.username}{u.kind === 'system' ? ' · system' : ''}</small>
					</span>
					<label class="flag" class:pending={edits[u.username]?.is_admin !== undefined}>
						<input
							type="checkbox"
							checked={flagOf(u, 'is_admin')}
							disabled={u.username === me_username && u.is_admin}
							onchange={(e) => editFlag(u, 'is_admin', e.currentTarget.checked)}
						/>
						admin
					</label>
					<label class="flag" class:pending={edits[u.username]?.active !== undefined}>
						<input
							type="checkbox"
							checked={flagOf(u, 'active')}
							disabled={u.username === me_username}
							onchange={(e) => editFlag(u, 'active', e.currentTarget.checked)}
						/>
						active
					</label>
					{#if u.kind === 'system' || !u.active}
						<span class="reassign">
							<select bind:value={reassignTarget[u.username]}>
								<option value="" disabled selected>reassign data to…</option>
								{#each people.filter((p) => p.kind === 'person' && p.active && p.username !== u.username) as t (t.username)}
									<option value={t.username}>{t.display_name}</option>
								{/each}
							</select>
							<button onclick={() => reassign(u)} disabled={!reassignTarget[u.username]}>
								Reassign
							</button>
						</span>
					{/if}
					{#if !u.is_admin && u.username !== me_username}
						<button class="danger" onclick={() => deleteUser(u)}>Delete</button>
					{/if}
				</div>
			{/each}
		</div>
		{#if dirtyCount > 0}
			<p class="savebar">
				<button class="primary" onclick={savePeople}>
					Save {dirtyCount} {dirtyCount === 1 ? 'change' : 'changes'}
				</button>
				<button onclick={() => (edits = {})}>Discard</button>
			</p>
		{/if}
		{#if reassignReport}
			<p class="dim">
				Moved to {reassignReport.to}: {reassignReport.readings} readings,
				{reassignReport.usage_rows} usage rows, {reassignReport.settings} settings,
				{reassignReport.staging_moved.length} draft folders{reassignReport.staging_collisions.length
					? ` (${reassignReport.staging_collisions.length} renamed on collision)`
					: ''}, {reassignReport.library_restamped.length} library attributions.
				{reassignReport.from} deactivated.
			</p>
		{/if}
		{#if peopleError}<p class="error">{peopleError}</p>{/if}
	</section>

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
		<div class="fld">
			<span>Provider {#if tmanaged('provider')}<em class="dim">(managed)</em>{/if}</span>
			<div class="choices provider">
				{#each ttsProviders as prov (prov.name)}
					<button
						class="choice"
						class:selected={ttsProvider === prov.name}
						disabled={tmanaged('provider')}
						onclick={() => pickProvider(prov.name)}
					>
						<strong>{prov.label}</strong>
						<small>{prov.default_model || 'any model'}</small>
					</button>
				{/each}
			</div>
		</div>
		{#if ttsProvider === 'openai'}
			<p class="dim">
				Any OpenAI-compatible <code>/audio/speech</code> endpoint. OpenAI:
				<code>https://api.openai.com/v1</code> with model <code>gpt-4o-mini-tts</code>
				(supports style instructions); self-hosted Kokoro (kokoro-fastapi):
				<code>http://kokoro:8880/v1</code> with model <code>kokoro</code> (pick a voice like
				<code>af_heart</code>; instructions are ignored). Leave the Base URL empty to turn the
				feature off — audio buttons only appear when it's configured.
			</p>
		{:else}
			<p class="dim">
				Base URL is optional — <code>{activeProvider?.default_base_url}</code> is used when blank.
				Voices are account-specific, so each persona needs one chosen below before its audio
				works. Your settings for the other provider are kept, not discarded.
			</p>
		{/if}
		<label class="fld">
			<span>Base URL {#if tmanaged('base_url')}<em class="dim">(managed)</em>{/if}</span>
			<input type="text" bind:value={ttsBaseUrl} oninput={() => (ttsSaved = false)} disabled={tmanaged('base_url')} placeholder={activeProvider?.default_base_url || 'https://api.openai.com/v1'} />
		</label>
		<label class="fld">
			<span>Model {#if tmanaged('model')}<em class="dim">(managed)</em>{/if}</span>
			<input type="text" bind:value={ttsModel} oninput={() => (ttsSaved = false)} disabled={tmanaged('model')} placeholder={activeProvider?.default_model || 'gpt-4o-mini-tts'} />
		</label>
		<label class="fld">
			<span>API key
				{#if tmanaged('api_key')}<em class="dim">(managed)</em>
				{:else if ttsKeySet}<em class="dim">(saved — leave blank to keep)</em>{/if}</span>
			<input type="password" bind:value={ttsApiKey} oninput={() => (ttsSaved = false)} disabled={tmanaged('api_key')} placeholder={ttsKeySet ? '••••••••' : 'sk-…'} autocomplete="off" />
		</label>
		{#if voiceListError}
			<p class="dim">Couldn't list voices from the provider — enter ids by hand. ({voiceListError})</p>
		{/if}
		{#each Object.entries(voices) as [p, v] (p)}
			<fieldset class="voice">
				<legend>
					{p}
					{#if tmanaged(`voice_${p}`)}<em class="dim">(managed)</em>{/if}
					{#if ttsGaps[p]?.length}<em class="gap">— no voice set</em>{/if}
				</legend>
				<!-- Rendered from the provider's declared fields, so a new
				     provider needs no changes here. -->
				{#each activeProvider?.fields ?? [] as f (f.key)}
					{#if f.kind === 'longtext'}
						<label class="fld">
							<span>{f.label}</span>
							<textarea rows="2" bind:value={v[f.key]} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)}></textarea>
						</label>
					{:else if f.kind === 'bool'}
						<label class="fld inline">
							<input type="checkbox" bind:checked={v[f.key] as boolean} onchange={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)} />
							<span>{f.label}</span>
						</label>
					{:else if f.kind === 'slider'}
						<label class="fld">
							<span>{f.label} <em class="dim">{v[f.key]}</em></span>
							<input type="range" min={f.min ?? 0} max={f.max ?? 1} step={f.step ?? 0.05} bind:value={v[f.key]} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)} />
						</label>
					{:else if f.kind === 'number'}
						<label class="fld">
							<span>{f.label}</span>
							<input type="number" min={f.min ?? undefined} max={f.max ?? undefined} step={f.step ?? undefined} bind:value={v[f.key]} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)} />
						</label>
					{:else if f.required && providerVoices.length}
						<!-- The provider can enumerate voices: pick by name, audition
						     with the provider's own preview (costs nothing). -->
						<div class="fld">
							<span>{f.label}</span>
							<div class="voicepick">
								<select bind:value={v[f.key]} onchange={(e) => applyVoicePreset(p, (e.currentTarget as HTMLSelectElement).value)} disabled={tmanaged(`voice_${p}`)}>
									<option value="">— choose a voice —</option>
									{#each providerVoices as pv (pv.id)}
										<option value={pv.id}>{pv.name}{pv.category ? ` (${pv.category})` : ''}</option>
									{/each}
								</select>
								{#each providerVoices.filter((x) => x.id === v[f.key]) as pv (pv.id)}
									<button class="audition" title="Preview this voice" onclick={() => preview(pv.preview_url)}>▶</button>
								{/each}
							</div>
							{#each providerVoices.filter((x) => x.id === v[f.key]) as pv (pv.id)}
								{#if Object.keys(pv.labels).length}
									<small class="dim">{Object.values(pv.labels).join(' · ')}</small>
								{/if}
							{/each}
						</div>
					{:else}
						<label class="fld">
							<span>{f.label}</span>
							<input type="text" bind:value={v[f.key]} oninput={() => (ttsSaved = false)} disabled={tmanaged(`voice_${p}`)} placeholder={f.help ?? ''} />
						</label>
					{/if}
				{/each}

				{#if activeProvider?.supports_design && !tmanaged(`voice_${p}`)}
					{#if designOpen !== p}
						<button class="design-open" onclick={() => openDesign(p)}>
							✨ Design a voice from {p}'s description
						</button>
					{:else}
						<div class="design">
							<p class="dim">
								Built from how {p} is written to sound — edit if you like, then generate
								candidates and keep the one that fits. Generating costs provider credits.
							</p>
							<textarea rows="5" bind:value={designText} disabled={designBusy}></textarea>
							<div class="designrow">
								<button onclick={runDesign} disabled={designBusy || designText.trim().length < 20}>
									{designBusy ? 'Designing…' : designCandidates.length ? 'Try again' : 'Generate candidates'}
								</button>
								<button onclick={() => (designOpen = '')} disabled={designBusy}>Cancel</button>
							</div>
							{#if designError}<p class="error">{designError}</p>{/if}
							{#each designCandidates as cand, i (cand.generated_voice_id)}
								<div class="candidate">
									<span class="dim">Candidate {i + 1}{cand.duration_secs ? ` · ${cand.duration_secs.toFixed(1)}s` : ''}</span>
									<!-- svelte-ignore a11y_media_has_caption -->
									<audio controls src={cand.audio}></audio>
									<button onclick={() => keepDesigned(p, cand)} disabled={designBusy}>
										Use this one
									</button>
								</div>
							{/each}
						</div>
					{/if}
				{/if}
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
	.people {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.person {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		padding: 0.4rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 8px;
	}

	.person.inactive {
		opacity: 0.55;
	}

	.person .who {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 10rem;
	}

	.person .flag {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		font-size: 0.85rem;
		color: var(--text-dim);
	}

	.person .reassign {
		display: inline-flex;
		gap: 0.4rem;
		align-items: center;
	}

	.person .reassign button {
		font-size: 0.85rem;
		padding: 0.25rem 0.7rem;
	}

	.person .danger {
		color: var(--danger);
		border-color: var(--danger);
		font-size: 0.85rem;
		padding: 0.25rem 0.7rem;
	}

	.person .flag.pending {
		color: var(--gold-bright);
	}

	.savebar {
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}

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

	.gap {
		color: var(--danger);
		font-style: normal;
		font-size: 0.85em;
	}

	.provider {
		margin-top: 0.3rem;
	}

	.voicepick {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.voicepick select {
		flex: 1;
	}

	.audition {
		padding: 0.35rem 0.7rem;
		line-height: 1;
	}

	.fld.inline {
		flex-direction: row;
		align-items: center;
		gap: 0.5rem;
	}

	.fld.inline input {
		width: auto;
	}

	.design-open {
		margin-top: 0.4rem;
		font-size: 0.9rem;
	}

	.design {
		margin-top: 0.6rem;
		padding: 0.7rem;
		border: 1px dashed var(--border);
		border-radius: var(--radius);
		background: var(--bg-raised);
	}

	.design textarea {
		width: 100%;
	}

	.designrow {
		display: flex;
		gap: 0.6rem;
		margin-top: 0.6rem;
	}

	.candidate {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		flex-wrap: wrap;
		margin-top: 0.7rem;
		padding-top: 0.7rem;
		border-top: 1px solid var(--border);
	}

	.candidate audio {
		height: 2rem;
		flex: 1;
		min-width: 12rem;
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

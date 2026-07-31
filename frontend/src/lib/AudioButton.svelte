<script lang="ts" module>
	// One shared element so two pieces never speak over each other, and so the
	// first user-gesture play unlocks programmatic playback (iOS allows later
	// .play() calls on an element that has already played from a gesture).
	let audio: HTMLAudioElement | null = null;
	let stopCurrent: (() => void) | null = null;
	let unlocked = false;

	export function audioUnlocked(): boolean {
		return unlocked;
	}
</script>

<script lang="ts">
	// `src` may be a URL (persisted pieces) or an async provider (ephemeral text
	// -> object URL). `label` is for screen readers / the hover tooltip.
	let {
		src,
		label = 'Read aloud',
		onended
	}: {
		src: string | (() => Promise<string>);
		label?: string;
		onended?: () => void;
	} = $props();

	let state_ = $state<'idle' | 'loading' | 'playing' | 'error'>('idle');
	let errorMsg = $state('');

	function stop() {
		if (audio) {
			audio.pause();
			audio.onended = null;
			audio.onerror = null;
		}
		if (stopCurrent === reset) stopCurrent = null;
		state_ = 'idle';
	}

	function reset() {
		state_ = 'idle';
	}

	/** Start playback. Exported so auto-read can trigger it programmatically. */
	export async function play(): Promise<void> {
		if (state_ === 'playing' || state_ === 'loading') return;
		stopCurrent?.(); // silence whatever else is speaking
		stopCurrent = reset;
		state_ = 'loading';
		errorMsg = '';
		try {
			const url = typeof src === 'string' ? src : await src();
			audio ??= new Audio();
			audio.src = url;
			audio.onended = () => {
				state_ = 'idle';
				if (stopCurrent === reset) stopCurrent = null;
				onended?.();
			};
			audio.onerror = () => {
				state_ = 'error';
				errorMsg = 'audio failed to load';
			};
			await audio.play();
			unlocked = true;
			state_ = 'playing';
		} catch (e) {
			// NotAllowedError = autoplay blocked pre-gesture: quietly back to idle
			// so the visible button invites the tap that will unlock audio.
			if ((e as Error).name === 'NotAllowedError') state_ = 'idle';
			else {
				state_ = 'error';
				errorMsg = String(e);
			}
			if (stopCurrent === reset) stopCurrent = null;
		}
	}

	function toggle() {
		if (state_ === 'playing') stop();
		else play();
	}

	$effect(() => () => {
		// leaving the page mid-speech: stop rather than talk over the next view
		if (state_ === 'playing' || state_ === 'loading') stop();
	});
</script>

<button
	class="audio"
	class:playing={state_ === 'playing'}
	class:err={state_ === 'error'}
	onclick={toggle}
	title={state_ === 'error' ? errorMsg : label}
	aria-label={label}
	disabled={state_ === 'loading'}
>
	{#if state_ === 'loading'}<span class="spin">◌</span>
	{:else if state_ === 'playing'}■
	{:else if state_ === 'error'}⚠
	{:else}🔊{/if}
</button>

<style>
	.audio {
		all: unset;
		cursor: pointer;
		font-size: 0.85em;
		line-height: 1;
		padding: 0.15em 0.35em;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-dim);
		vertical-align: middle;
	}

	.audio:hover {
		border-color: var(--gold);
		color: var(--gold);
	}

	.audio.playing {
		border-color: var(--gold);
		color: var(--gold);
	}

	.audio.err {
		border-color: var(--danger);
		color: var(--danger);
	}

	.audio:disabled {
		cursor: wait;
	}

	.spin {
		display: inline-block;
		animation: rot 1s linear infinite;
	}

	@keyframes rot {
		to {
			transform: rotate(360deg);
		}
	}
</style>

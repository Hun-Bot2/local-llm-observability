<script>
  import { onMount } from 'svelte';

  const API_BASE = 'http://localhost:8000';
  const LOCAL_RUNS_KEY = 'local-llm-translator:local-runs';

  let posts = [];
  let selectedPath = '';
  let selectedLang = 'en';
  let selectedModel = 'gemma4:latest';
  let backend = 'local';
  let runpodUrl = '';
  let fileDetail = null;
  let uploadedFile = null;
  let uploadStats = null;
  let runs = [];
  let localRuns = [];
  let events = [];
  let activeRun = null;
  let status = 'idle';
  let error = '';

  const langModels = {
    en: 'gemma4:latest',
    jp: 'qwen3:14b'
  };

  function loadLocalRuns() {
    try {
      localRuns = JSON.parse(localStorage.getItem(LOCAL_RUNS_KEY) || '[]');
    } catch {
      localRuns = [];
    }
  }

  function saveLocalRuns() {
    localStorage.setItem(LOCAL_RUNS_KEY, JSON.stringify(localRuns.slice(0, 20)));
  }

  function rememberLocalRun(run) {
    localRuns = [run, ...localRuns.filter((item) => item.runId !== run.runId)].slice(0, 20);
    saveLocalRuns();
  }

  function updateLocalRun(runId, patch) {
    localRuns = localRuns.map((run) => (run.runId === runId ? { ...run, ...patch } : run));
    saveLocalRuns();
  }

  $: selectedModel = selectedModel || langModels[selectedLang];
  $: tokenTotal = events.reduce((sum, event) => {
    const details = event.details || {};
    return sum + Number(details.input_tokens || 0) + Number(details.output_tokens || 0);
  }, 0);
  $: elapsedSec = activeRun?.run?.gpu_time_sec || latestEventNumber('gpu_time_sec') || 0;
  $: estimatedCost = activeRun?.run?.estimated_cost || latestEventNumber('estimated_cost') || 0;
  $: isRunning = !['idle', 'completed', 'failed'].includes(status);

  function latestEventNumber(key) {
    for (const event of [...events].reverse()) {
      const value = event.details?.[key];
      if (typeof value === 'number') return value;
    }
    return 0;
  }

  async function api(path, options) {
    const response = await fetch(`${API_BASE}${path}`, options);
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async function loadPosts() {
    error = '';
    try {
      const payload = await api('/api/posts');
      posts = payload.posts || [];
      if (!selectedPath && posts.length) {
        selectedPath = posts[0].relative_path;
        await loadFileDetail();
      }
    } catch (err) {
      error = `Failed to load posts: ${err.message}`;
    }
  }

  async function loadRuns() {
    try {
      const payload = await api('/api/runs?limit=12');
      runs = payload.runs || [];
    } catch {
      runs = [];
    }
  }

  async function loadFileDetail() {
    if (!selectedPath) return;
    error = '';
    try {
      fileDetail = await api(`/api/file-detail?path=${encodeURIComponent(selectedPath)}`);
    } catch (err) {
      error = `Failed to load file detail: ${err.message}`;
    }
  }

  async function onUpload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    uploadedFile = file;
    const text = await file.text();
    uploadStats = {
      name: file.name,
      characters: text.length,
      bytes: file.size,
      lines: text.split('\n').length
    };
  }

  async function startTranslation() {
    if (!selectedPath) return;
    events = [];
    activeRun = null;
    status = 'queued';
    error = '';

    try {
      const payload = await api('/api/translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          relative_path: selectedPath,
          lang: selectedLang,
          model: selectedModel,
          backend,
          runpod_url: runpodUrl || null
        })
      });
      status = payload.status;
      rememberLocalRun({
        runId: payload.run_id,
        status: payload.status,
        file: selectedPath,
        lang: selectedLang,
        model: selectedModel,
        backend,
        startedAt: new Date().toISOString(),
        finishedAt: null,
        events: 0
      });
      subscribeRun(payload.run_id);
    } catch (err) {
      status = 'failed';
      error = `Failed to start translation: ${err.message}`;
    }
  }

  function subscribeRun(runId) {
    const source = new EventSource(`${API_BASE}/api/runs/${runId}/events`);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data);
      events = [...events, event];
      status = event.event_type;
      updateLocalRun(runId, {
        status: event.event_type,
        events: events.length,
        finishedAt: event.event_type === 'completed' || event.event_type === 'failed' ? new Date().toISOString() : null
      });
      if (event.event_type === 'completed' || event.event_type === 'failed') {
        source.close();
        refreshRun(runId);
      }
    };
    source.onerror = () => {
      source.close();
      if (status !== 'completed' && status !== 'failed') {
        updateLocalRun(runId, { status: 'disconnected', finishedAt: new Date().toISOString() });
        error = 'Event stream disconnected. Check the controller terminal.';
      }
    };
  }

  async function refreshRun(runId) {
    try {
      activeRun = await api(`/api/runs/${runId}`);
      await loadRuns();
      await loadPosts();
    } catch {
      await loadRuns();
    }
  }

  function statusLabel(value) {
    return value.replaceAll('_', ' ');
  }

  onMount(() => {
    loadLocalRuns();
    loadPosts();
    loadRuns();
  });
</script>

<svelte:head>
  <title>Local LLM Translator</title>
</svelte:head>

<main class="page-shell">
  <section class="hero">
    <div>
      <p class="eyebrow">Local LLM Translation Studio</p>
      <h1>Visible translation runs, from file scan to saved MDX.</h1>
      <p class="hero-copy">
        A local-first control room for Korean MDX translation. It shows file structure,
        model progress, token metrics, timing, cost, and persistent run history.
      </p>
    </div>
    <div class="hero-card">
      <span class="pulse"></span>
      <p>Controller</p>
      <strong>{API_BASE}</strong>
      <small>FastAPI + local PostgreSQL + Ollama/RunPod</small>
    </div>
  </section>

  {#if error}
    <aside class="alert">{error}</aside>
  {/if}

  <section class="grid">
    <article class="panel command-panel">
      <div class="panel-head">
        <div>
          <p class="label">Run</p>
          <h2>Translate a post</h2>
        </div>
        <span class:status--running={isRunning} class="status">
          {#if isRunning}
            <i class="spinner" aria-hidden="true"></i>
          {/if}
          {statusLabel(status)}
        </span>
      </div>

      <label class="field">
        Source file from blog repo
        <select bind:value={selectedPath} on:change={loadFileDetail}>
          {#each posts as post}
            <option value={post.relative_path}>{post.relative_path}</option>
          {/each}
        </select>
      </label>

      <div class="split">
        <label class="field">
          Language
          <select bind:value={selectedLang} on:change={() => (selectedModel = langModels[selectedLang])}>
            <option value="en">English</option>
            <option value="jp">Japanese</option>
          </select>
        </label>

        <label class="field">
          Backend
          <select bind:value={backend}>
            <option value="local">Local Ollama</option>
            <option value="runpod">RunPod</option>
          </select>
        </label>
      </div>

      <label class="field">
        Model
        <input bind:value={selectedModel} placeholder="gemma4:latest" />
      </label>

      {#if backend === 'runpod'}
        <label class="field">
          RunPod URL
          <input bind:value={runpodUrl} placeholder="https://YOUR-POD-8000.proxy.runpod.net" />
        </label>
      {/if}

      <label class="upload">
        <input type="file" accept=".md,.mdx" on:change={onUpload} />
        <span>Inspect local MDX file</span>
        <small>Upload is for character/line inspection only. Translation uses repo-selected files.</small>
      </label>

      <button class:primary--running={isRunning} class="primary" on:click={startTranslation} disabled={!selectedPath || isRunning}>
        {#if isRunning}
          <i class="button-spinner" aria-hidden="true"></i>
          Translating
        {:else}
          Start translation
        {/if}
      </button>
    </article>

    <article class="panel">
      <div class="panel-head">
        <div>
          <p class="label">File</p>
          <h2>Source detail</h2>
        </div>
      </div>

      {#if fileDetail}
        <div class="stat-grid">
          <div><span>Characters</span><strong>{fileDetail.characters}</strong></div>
          <div><span>Lines</span><strong>{fileDetail.lines}</strong></div>
          <div><span>Sections</span><strong>{fileDetail.sections}</strong></div>
          <div><span>Code blocks</span><strong>{fileDetail.code_sections}</strong></div>
        </div>
        <div class="file-title">
          <span>{fileDetail.frontmatter?.category || 'uncategorized'}</span>
          <strong>{fileDetail.frontmatter?.title || fileDetail.filename}</strong>
          <p>{fileDetail.frontmatter?.description || 'No description found.'}</p>
        </div>
      {:else}
        <p class="muted">Select a source file to inspect it.</p>
      {/if}

      {#if uploadStats}
        <div class="upload-stats">
          <p>Uploaded inspection</p>
          <strong>{uploadStats.name}</strong>
          <span>{uploadStats.characters} chars · {uploadStats.lines} lines · {uploadStats.bytes} bytes</span>
        </div>
      {/if}
    </article>

    <article class="panel metrics-panel">
      <div class="panel-head">
        <div>
          <p class="label">Metrics</p>
          <h2>Run telemetry</h2>
        </div>
      </div>
      <div class="metric-row">
        <span>Elapsed</span>
        <strong>{Number(elapsedSec).toFixed(1)}s</strong>
      </div>
      <div class="metric-row">
        <span>Estimated cost</span>
        <strong>${Number(estimatedCost).toFixed(5)}</strong>
      </div>
      <div class="metric-row">
        <span>Observed tokens</span>
        <strong>{tokenTotal}</strong>
      </div>
      <div class="metric-row">
        <span>Events</span>
        <strong>{events.length}</strong>
      </div>
    </article>
  </section>

  <section class="wide-grid">
    <article class="panel history-panel">
      <div class="panel-head">
        <div>
          <p class="label">Local session record</p>
          <h2>Browser run history</h2>
        </div>
      </div>

      <div class="run-list">
        {#each localRuns as run}
          <div class="run-row run-row--local">
            <div class="run-row__top">
              <span>#{run.runId}</span>
              <strong>{statusLabel(run.status)}</strong>
            </div>
            <small title={run.file}>{run.file}</small>
            <em>{run.lang.toUpperCase()} · {run.model} · {run.events} events</em>
          </div>
        {:else}
          <p class="muted">No local browser records yet.</p>
        {/each}
      </div>
    </article>

    <article class="panel timeline-panel">
      <div class="panel-head">
        <div>
          <p class="label">Progress</p>
          <h2>Live timeline</h2>
        </div>
      </div>

      {#if events.length}
        <ol class="timeline">
          {#each events as event}
            <li class:timeline-active={event.id === events[events.length - 1]?.id && isRunning}>
              <span class="dot"></span>
              <div>
                <strong>{statusLabel(event.event_type)}</strong>
                <p>{event.message}</p>
                <small>{new Date(event.created_at).toLocaleTimeString()}</small>
              </div>
            </li>
          {/each}
        </ol>
      {:else}
        <div class="empty-state">
          <strong>No active run yet.</strong>
          <p>Start with one post. The timeline will show parsing, cache check, model call, scoring, and save events.</p>
        </div>
      {/if}
    </article>

    <article class="panel history-panel">
      <div class="panel-head">
        <div>
          <p class="label">Database record</p>
          <h2>Postgres runs</h2>
        </div>
      </div>

      <div class="run-list">
        {#each runs as run}
          <div class="run-row">
            <span>#{run.id}</span>
            <strong>{run.status}</strong>
            <small>{run.started_at ? new Date(run.started_at).toLocaleString() : 'pending'}</small>
            <em>${Number(run.estimated_cost || 0).toFixed(5)}</em>
          </div>
        {:else}
          <p class="muted">No runs recorded yet.</p>
        {/each}
      </div>
    </article>
  </section>
</main>

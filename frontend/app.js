const CONFIG = {
  apiBaseUrl: "",
};

const MOCK_DATA = {
  metrics: [
    { label: "Avg Quality", value: "0.84", note: "Composite score over recent runs" },
    { label: "Monthly Cost", value: "$3.08", note: "RunPod + storage estimate" },
    { label: "Cache Hit Rate", value: "61%", note: "Paragraph-level translation cache" },
    { label: "Tokens This Month", value: "18.7k", note: "Input + output tokens across runs" },
  ],
  runs: [
    {
      id: 48,
      status: "completed",
      file: "Algorithm_Bot_01.mdx",
      lang: "EN",
      cache: "18 / 29",
      cost: "$0.07",
      startedAt: "2026-04-09 14:25",
    },
    {
      id: 47,
      status: "failed",
      file: "Algorithm_Bot_01.mdx",
      lang: "EN",
      cache: "0 / 29",
      cost: "$0.04",
      startedAt: "2026-04-09 13:58",
    },
    {
      id: 46,
      status: "completed",
      file: "Algorithm_Bot_03.mdx",
      lang: "JP",
      cache: "24 / 31",
      cost: "$0.05",
      startedAt: "2026-04-08 09:00",
    },
  ],
  docs: [
    {
      title: "Algorithm_Bot_01_en_gemma4.mdx",
      subtitle: "English local benchmark output",
      meta: ["gemma4:latest", "Updated 12 minutes ago", "quality 0.81"],
    },
    {
      title: "Algorithm_Bot_01_en.mdx",
      subtitle: "RunPod-backed canonical English output",
      meta: ["translategemma:12b", "Updated 38 minutes ago", "quality 0.84"],
    },
    {
      title: "Algorithm_Bot_01_jp.mdx",
      subtitle: "Japanese translation",
      meta: ["qwen3:14b", "Updated yesterday", "quality 0.89"],
    },
  ],
  issues: [
    {
      title: "Algorithm_Bot_01_en.mdx line 4-67",
      description: "Frontmatter description expanded into generated prose. Tightened prompt now pending rerun.",
      meta: ["severity: medium", "type: frontmatter"],
    },
    {
      title: "Algorithm_Bot_01_en.mdx line 141",
      description: "Korean code comment remained untranslated in a fenced Python block.",
      meta: ["severity: medium", "type: code comments"],
    },
    {
      title: "Algorithm_Bot_01_en.mdx line 145",
      description: "Docusaurus deployment URL comment block was preserved but adjacent Korean comments were missed.",
      meta: ["severity: low", "type: code comments"],
    },
  ],
};

const state = {
  liveMode: false,
};

function statusClass(status) {
  if (status === "completed") return "status-pill status-pill--completed";
  if (status === "running") return "status-pill status-pill--running";
  return "status-pill status-pill--failed";
}

function renderMetrics(metrics) {
  const root = document.getElementById("metrics-grid");
  root.innerHTML = metrics
    .map(
      (metric) => `
        <article class="metric-card">
          <h3>${metric.label}</h3>
          <strong>${metric.value}</strong>
          <span>${metric.note}</span>
        </article>
      `,
    )
    .join("");
}

function renderRuns(runs) {
  const root = document.getElementById("runs-table");
  root.innerHTML = runs
    .map(
      (run) => `
        <tr>
          <td>#${run.id}</td>
          <td><span class="${statusClass(run.status)}">${run.status}</span></td>
          <td>${run.file}</td>
          <td>${run.lang}</td>
          <td>${run.cache}</td>
          <td>${run.cost}</td>
          <td>${run.startedAt}</td>
        </tr>
      `,
    )
    .join("");
}

function renderDocs(docs) {
  const root = document.getElementById("docs-list");
  root.innerHTML = docs
    .map(
      (doc) => `
        <article class="doc-card">
          <h3>${doc.title}</h3>
          <p>${doc.subtitle}</p>
          <div class="doc-meta">${doc.meta.map((item) => `<span>${item}</span>`).join("")}</div>
        </article>
      `,
    )
    .join("");
}

function renderIssues(issues) {
  const root = document.getElementById("issues-list");
  root.innerHTML = issues
    .map(
      (issue) => `
        <article class="issue-card">
          <h3>${issue.title}</h3>
          <p>${issue.description}</p>
          <div class="issue-meta">${issue.meta.map((item) => `<span>${item}</span>`).join("")}</div>
        </article>
      `,
    )
    .join("");
}

function setMode() {
  const live = Boolean(CONFIG.apiBaseUrl);
  state.liveMode = live;
  document.getElementById("status-badge").textContent = live ? "Live API" : "Mock Data";
  document.getElementById("trigger-state").textContent = live ? "Cloud Run API" : "Local Preview";
}

async function loadLiveData() {
  const response = await fetch(`${CONFIG.apiBaseUrl}/dashboard`);
  if (!response.ok) {
    throw new Error(`Dashboard API failed with status ${response.status}`);
  }
  return response.json();
}

async function boot() {
  setMode();
  let data = MOCK_DATA;

  if (state.liveMode) {
    try {
      data = await loadLiveData();
    } catch (error) {
      document.getElementById("trigger-result").textContent =
        `API fetch failed. Falling back to mock data. ${error.message}`;
      data = MOCK_DATA;
    }
  }

  renderMetrics(data.metrics);
  renderRuns(data.runs);
  renderDocs(data.docs);
  renderIssues(data.issues);
}

document.getElementById("trigger-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.getElementById("file-input").value.trim();
  const lang = document.getElementById("lang-select").value;
  const mode = document.getElementById("mode-select").value;
  const target = document.getElementById("trigger-result");

  if (!file) {
    target.textContent = "Provide a source file path before triggering translation.";
    return;
  }

  if (!state.liveMode) {
    target.textContent =
      `Preview only: would queue ${file} for ${lang.toUpperCase()} translation with trigger=${mode}.`;
    return;
  }

  target.textContent = "Sending request to Cloud Run...";

  try {
    const response = await fetch(`${CONFIG.apiBaseUrl}/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file, lang, mode }),
    });

    if (!response.ok) {
      throw new Error(`Trigger API failed with status ${response.status}`);
    }

    const payload = await response.json();
    target.textContent = `Queued run #${payload.run_id} for ${payload.file}.`;
  } catch (error) {
    target.textContent = `Trigger failed: ${error.message}`;
  }
});

boot();

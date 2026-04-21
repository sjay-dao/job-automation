const state = {
  jobs: [],
  openedJobs: new Set(),
};

const OPENED_STORAGE_KEY = "opened_job_listings_v1";

const elements = {
  runBtn: document.getElementById("runBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusText: document.getElementById("statusText"),
  csvPath: document.getElementById("csvPath"),
  searchInput: document.getElementById("searchInput"),
  minScoreInput: document.getElementById("minScoreInput"),
  sortSelect: document.getElementById("sortSelect"),
  jobsList: document.getElementById("jobsList"),
  resultsCount: document.getElementById("resultsCount"),
  totalJobs: document.getElementById("totalJobs"),
  averageScore: document.getElementById("averageScore"),
  topCompany: document.getElementById("topCompany"),
  jobCardTemplate: document.getElementById("jobCardTemplate"),
};

function loadOpenedJobs() {
  try {
    const raw = window.localStorage.getItem(OPENED_STORAGE_KEY);
    if (!raw) {
      return new Set();
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return new Set();
    }

    return new Set(parsed.filter((item) => typeof item === "string" && item.trim()));
  } catch (error) {
    console.error("Failed to load opened jobs", error);
    return new Set();
  }
}

function saveOpenedJobs() {
  try {
    window.localStorage.setItem(OPENED_STORAGE_KEY, JSON.stringify([...state.openedJobs]));
  } catch (error) {
    console.error("Failed to save opened jobs", error);
  }
}

function getJobKey(job) {
  return String(job.job_id || job.job_link || `${job.title || ""}|${job.company || ""}|${job.location || ""}`).trim();
}

function isJobOpened(job) {
  return state.openedJobs.has(getJobKey(job));
}

function markJobOpened(job) {
  const key = getJobKey(job);
  if (!key || state.openedJobs.has(key)) {
    return;
  }

  state.openedJobs.add(key);
  saveOpenedJobs();
}

function normalizeScore(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function getMatchScore(job) {
  return normalizeScore(job.match_score ?? job.score);
}

function sortJobs(jobs) {
  const sortKey = elements.sortSelect.value;
  return [...jobs].sort((left, right) => {
    if (sortKey === "score") {
      return getMatchScore(right) - getMatchScore(left);
    }
    return String(left[sortKey] || "").localeCompare(String(right[sortKey] || ""));
  });
}

function filterJobs() {
  const query = elements.searchInput.value.trim().toLowerCase();
  const minScore = normalizeScore(elements.minScoreInput.value);

  const filtered = state.jobs.filter((job) => {
    const haystack = [
      job.title,
      job.company,
      job.location,
      job.description,
      job.matched_keywords,
      job.matched_categories,
      job.score_breakdown,
      job.match_score,
    ]
      .join(" ")
      .toLowerCase();

    return haystack.includes(query) && getMatchScore(job) >= minScore;
  });

  renderJobs(sortJobs(filtered));
}

function renderSummary(jobs) {
  elements.totalJobs.textContent = String(jobs.length);

  const totalScore = jobs.reduce((sum, job) => sum + getMatchScore(job), 0);
  elements.averageScore.textContent = jobs.length ? (totalScore / jobs.length).toFixed(1) : "0";

  const companyCounts = new Map();
  for (const job of jobs) {
    const company = job.company || "Unknown";
    companyCounts.set(company, (companyCounts.get(company) || 0) + 1);
  }

  let topCompany = "-";
  let highestCount = 0;
  for (const [company, count] of companyCounts.entries()) {
    if (count > highestCount) {
      highestCount = count;
      topCompany = company;
    }
  }
  elements.topCompany.textContent = topCompany;
}

function renderJobs(jobs) {
  const visibleJobs = jobs.filter((job) => String(job.title || "").trim());
  elements.jobsList.innerHTML = "";
  elements.resultsCount.textContent = `${visibleJobs.length} job${visibleJobs.length === 1 ? "" : "s"}`;
  renderSummary(visibleJobs);

  if (!visibleJobs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No complete jobs match the current filters yet.";
    elements.jobsList.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();

  for (const job of visibleJobs) {
    const node = elements.jobCardTemplate.content.cloneNode(true);
    const opened = isJobOpened(job);
    const jobKey = getJobKey(job);
    node.querySelector(".job-score").textContent = `Match score ${getMatchScore(job)}`;
    node.querySelector(".job-title").textContent = job.title;
    node.querySelector(".job-company").textContent = `${job.company || "Unknown company"} | ${job.search_keyword || "General search"}`;
    const statusNode = node.querySelector(".job-status");
    if (opened) {
      statusNode.textContent = "Opened listing";
      statusNode.classList.add("job-status--opened");
      node.querySelector(".job-card").classList.add("job-card--opened");
    } else {
      statusNode.textContent = "";
    }

    const linkNode = node.querySelector(".job-link");
    linkNode.href = job.job_link || "#";
    linkNode.addEventListener("click", () => {
      if (jobKey) {
        markJobOpened(job);
      }
      statusNode.textContent = "Opened listing";
      statusNode.classList.add("job-status--opened");
      node.querySelector(".job-card").classList.add("job-card--opened");
    });
    node.querySelector(".job-meta").textContent =
      `${job.location || "Unknown location"} | ${job.date_posted || "No date label"} | Applicants: ${job.applicant_count || "n/a"} | Categories: ${job.matched_categories || "n/a"}`;
    node.querySelector(".job-breakdown").textContent = job.score_breakdown || "No score breakdown available.";
    node.querySelector(".job-description").textContent = job.description || "No description captured.";
    fragment.appendChild(node);
  }

  elements.jobsList.appendChild(fragment);
}

async function loadJobs() {
  elements.statusText.textContent = "Loading jobs";
  state.openedJobs = loadOpenedJobs();
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  state.jobs = payload.jobs || [];
  elements.csvPath.textContent = payload.csv_path || "";
  elements.statusText.textContent = `Loaded ${state.jobs.length} jobs`;
  filterJobs();
}

async function runScraper() {
  elements.runBtn.disabled = true;
  elements.statusText.textContent = "Running scraper";
  try {
    const response = await fetch("/run", { method: "POST" });
    const payload = await response.json();
    elements.csvPath.textContent = payload.output_csv || "";
    elements.statusText.textContent = "Scrape finished";
    await loadJobs();
  } catch (error) {
    elements.statusText.textContent = "Run failed";
    console.error(error);
  } finally {
    elements.runBtn.disabled = false;
  }
}

elements.runBtn.addEventListener("click", runScraper);
elements.refreshBtn.addEventListener("click", loadJobs);
elements.searchInput.addEventListener("input", filterJobs);
elements.minScoreInput.addEventListener("input", filterJobs);
elements.sortSelect.addEventListener("change", filterJobs);

loadJobs().catch((error) => {
  elements.statusText.textContent = "Failed to load jobs";
  console.error(error);
});

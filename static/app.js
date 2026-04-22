const STATUS_OPTIONS = ["New", "Viewed", "Applied", "For interview", "Rejected"];

const state = {
  jobs: [],
};

const elements = {
  runBtn: document.getElementById("runBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  statusText: document.getElementById("statusText"),
  csvPath: document.getElementById("csvPath"),
  searchInput: document.getElementById("searchInput"),
  minScoreInput: document.getElementById("minScoreInput"),
  sortSelect: document.getElementById("sortSelect"),
  sourceFilter: document.getElementById("sourceFilter"),
  statusFilter: document.getElementById("statusFilter"),
  postedFromInput: document.getElementById("postedFromInput"),
  postedToInput: document.getElementById("postedToInput"),
  jobsList: document.getElementById("jobsList"),
  resultsCount: document.getElementById("resultsCount"),
  totalJobs: document.getElementById("totalJobs"),
  statusBreakdown: document.getElementById("statusBreakdown"),
  averageScore: document.getElementById("averageScore"),
  topCompany: document.getElementById("topCompany"),
  jobCardTemplate: document.getElementById("jobCardTemplate"),
};

function normalizeScore(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function getMatchScore(job) {
  return normalizeScore(job.match_score ?? job.score);
}

function getJobKey(job) {
  return String(job.job_uid || job.job_id || job.job_link || `${job.title || ""}|${job.company || ""}|${job.location || ""}`).trim();
}

function normalizeStatus(value) {
  const status = String(value || "").trim();
  return STATUS_OPTIONS.includes(status) ? status : "New";
}

function parsePostedDateLabel(label) {
  const text = String(label || "").trim().toLowerCase();
  if (!text) {
    return "";
  }

  if (text === "today" || text.includes("just now")) {
    return new Date().toISOString().slice(0, 10);
  }
  if (text.includes("yesterday")) {
    const date = new Date();
    date.setDate(date.getDate() - 1);
    return date.toISOString().slice(0, 10);
  }

  const relativePatterns = [
    [/(\d+)\s*(?:\+?\s*)?(?:minute|minutes|min|mins)\b/, 0],
    [/(\d+)\s*(?:\+?\s*)?(?:hour|hours|hr|hrs)\b/, 0],
    [/(\d+)\s*(?:\+?\s*)?(?:day|days)\b/, 1],
    [/(\d+)\s*(?:\+?\s*)?(?:week|weeks)\b/, 7],
    [/(\d+)\s*(?:\+?\s*)?(?:month|months)\b/, 30],
    [/(\d+)\s*(?:\+?\s*)?(?:year|years)\b/, 365],
  ];

  for (const [pattern, multiplier] of relativePatterns) {
    const match = text.match(pattern);
    if (match) {
      const ageDays = Number.parseInt(match[1], 10) * multiplier;
      const date = new Date();
      date.setDate(date.getDate() - ageDays);
      return date.toISOString().slice(0, 10);
    }
  }

  const parsed = new Date(label);
  if (!Number.isNaN(parsed.getTime())) {
    return parsed.toISOString().slice(0, 10);
  }

  return "";
}

function normalizeJob(job) {
  return {
    ...job,
    job_uid: String(job.job_uid || getJobKey(job)).trim(),
    source: String(job.source || "LinkedIn").trim() || "LinkedIn",
    status: normalizeStatus(job.status),
    posted_date: String(job.posted_date || parsePostedDateLabel(job.date_posted) || "").trim(),
    last_updated: String(job.last_updated || "").trim(),
  };
}

function getPostedDate(job) {
  return String(job.posted_date || parsePostedDateLabel(job.date_posted) || "").trim();
}

function formatPostedLabel(job) {
  const postedDate = getPostedDate(job);
  const rawLabel = String(job.date_posted || "").trim();

  if (postedDate && rawLabel && postedDate !== rawLabel) {
    return `${postedDate} | ${rawLabel}`;
  }

  return postedDate || rawLabel || "Unknown";
}

function formatUpdatedLabel(job) {
  const value = String(job.last_updated || "").trim();
  if (!value) {
    return "Unknown";
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function sortJobs(jobs) {
  const sortKey = elements.sortSelect.value;
  return [...jobs].sort((left, right) => {
    if (sortKey === "score") {
      return getMatchScore(right) - getMatchScore(left);
    }

    if (sortKey === "posted_date") {
      return String(getPostedDate(right) || "").localeCompare(String(getPostedDate(left) || ""));
    }

    if (sortKey === "last_updated") {
      return String(right.last_updated || "").localeCompare(String(left.last_updated || ""));
    }

    return String(left[sortKey] || "").localeCompare(String(right[sortKey] || ""));
  });
}

function matchesDateRange(job) {
  const postedDate = getPostedDate(job);
  if (!postedDate) {
    return !elements.postedFromInput.value && !elements.postedToInput.value;
  }

  if (elements.postedFromInput.value && postedDate < elements.postedFromInput.value) {
    return false;
  }

  if (elements.postedToInput.value && postedDate > elements.postedToInput.value) {
    return false;
  }

  return true;
}

function filterJobs() {
  const query = elements.searchInput.value.trim().toLowerCase();
  const minScore = normalizeScore(elements.minScoreInput.value);
  const sourceFilter = elements.sourceFilter.value;
  const statusFilter = elements.statusFilter.value;

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
      job.source,
      job.status,
      job.posted_date,
      job.date_posted,
    ]
      .join(" ")
      .toLowerCase();

    const matchesQuery = !query || haystack.includes(query);
    const matchesScore = getMatchScore(job) >= minScore;
    const matchesSource = sourceFilter === "all" || job.source === sourceFilter;
    const matchesStatus = statusFilter === "all" || job.status === statusFilter;
    const matchesDates = matchesDateRange(job);

    return matchesQuery && matchesScore && matchesSource && matchesStatus && matchesDates;
  });

  renderJobs(sortJobs(filtered));
}

function renderSummary(jobs) {
  elements.totalJobs.textContent = String(jobs.length);

  const statusCounts = new Map(STATUS_OPTIONS.map((status) => [status, 0]));

  const totalScore = jobs.reduce((sum, job) => sum + getMatchScore(job), 0);
  elements.averageScore.textContent = jobs.length ? (totalScore / jobs.length).toFixed(1) : "0";

  const companyCounts = new Map();
  for (const job of jobs) {
    const company = job.company || "Unknown";
    companyCounts.set(company, (companyCounts.get(company) || 0) + 1);
    statusCounts.set(job.status, (statusCounts.get(job.status) || 0) + 1);
  }

  const statusText = STATUS_OPTIONS
    .map((status) => `${status}: ${statusCounts.get(status) || 0}`)
    .join(" | ");
  elements.statusBreakdown.textContent = statusText;

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

async function saveJobStatus(job, nextStatus) {
  const payload = {
    job_key: getJobKey(job),
    status: nextStatus,
  };

  const response = await fetch("/api/jobs/status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.error || "Failed to update job status");
  }

  return response.json();
}

async function applyJobStatus(job, nextStatus) {
  const normalizedStatus = normalizeStatus(nextStatus);
  if (job.status === normalizedStatus) {
    return;
  }

  elements.statusText.textContent = `Updating status to ${normalizedStatus}`;
  try {
    const payload = await saveJobStatus(job, normalizedStatus);
    job.status = normalizedStatus;
    if (payload?.job_last_updated) {
      job.last_updated = payload.job_last_updated;
    }
    elements.statusText.textContent = `Updated ${job.title || "job"} to ${normalizedStatus}`;
    filterJobs();
  } catch (error) {
    elements.statusText.textContent = "Status update failed";
    console.error(error);
  }
}

function bindStatusSelect(selectNode, job) {
  selectNode.innerHTML = "";
  for (const optionValue of STATUS_OPTIONS) {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = optionValue;
    selectNode.appendChild(option);
  }
  selectNode.value = job.status;
  selectNode.addEventListener("change", () => {
    void applyJobStatus(job, selectNode.value);
  });
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
    const card = node.querySelector(".job-card");
    const titleNode = node.querySelector(".job-title");
    const companyNode = node.querySelector(".job-company");
    const metaNode = node.querySelector(".job-meta");
    const breakdownNode = node.querySelector(".job-breakdown");
    const descriptionNode = node.querySelector(".job-description");
    const scoreNode = node.querySelector(".job-score");
    const linkNode = node.querySelector(".job-link");
    const statusSelect = node.querySelector(".job-status-select");

    scoreNode.textContent = `Match score ${getMatchScore(job)}`;
    titleNode.textContent = job.title || "Untitled role";
    companyNode.textContent = `${job.company || "Unknown company"} | ${job.search_keyword || "General search"}`;
    metaNode.textContent =
      `${job.location || "Unknown location"} | Source: ${job.source || "Unknown"} | ` +
      `Posted on portal: ${formatPostedLabel(job)} | Updated: ${formatUpdatedLabel(job)} | ` +
      `Applicants: ${job.applicant_count || "n/a"} | Categories: ${job.matched_categories || "n/a"}`;
    breakdownNode.textContent = job.score_breakdown || "No score breakdown available.";
    descriptionNode.textContent = job.description || "No description captured.";

    bindStatusSelect(statusSelect, job);
    card.dataset.status = job.status;
    card.dataset.postedDate = getPostedDate(job);
    if (job.status !== "New") {
      card.classList.add("job-card--active");
    }

    linkNode.href = job.job_link || "#";
    linkNode.addEventListener("click", () => {
      if (job.status === "New") {
        void applyJobStatus(job, "Viewed");
      }
    });

    fragment.appendChild(node);
  }

  elements.jobsList.appendChild(fragment);
}

async function loadJobs() {
  elements.statusText.textContent = "Loading jobs";
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  state.jobs = (payload.jobs || []).map(normalizeJob);
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
elements.refreshBtn.addEventListener("click", () => {
  void loadJobs();
});
elements.searchInput.addEventListener("input", filterJobs);
elements.minScoreInput.addEventListener("input", filterJobs);
elements.sortSelect.addEventListener("change", filterJobs);
elements.sourceFilter.addEventListener("change", filterJobs);
elements.statusFilter.addEventListener("change", filterJobs);
elements.postedFromInput.addEventListener("change", filterJobs);
elements.postedToInput.addEventListener("change", filterJobs);

loadJobs().catch((error) => {
  elements.statusText.textContent = "Failed to load jobs";
  console.error(error);
});

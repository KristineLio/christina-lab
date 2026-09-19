/*
 * CHRISTINA LAB — FRONTEND WORKFLOW / UI CONTROLLER
 *
 * This file implements the product workflow and interactive UI:
 * Dashboard, Discover, Video Analysis, Saved Research, Ideas,
 * Experiments, My Videos, Patterns, Analytics, Watchlists, and Settings.
 *
 * Live research, Saved Research, Ideas, Experiments, Dashboard, and Patterns
 * now use the FastAPI + SQLite backend. Remaining demo-only screens are kept
 * isolated while later milestones replace them with creator-owned data.
 */

(function () {
  const D = window.CL_DATA;
  const $ = (id) => document.getElementById(id);
  const API_BASE =
    window.CL_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1") && location.port !== "8000"
      ? "http://127.0.0.1:8000"
      : "");

  const LIVE_SESSION_KEY = "christinaLab.liveResearch.v2";

  function readLiveSession() {
    try {
      const raw = sessionStorage.getItem(LIVE_SESSION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && Array.isArray(parsed.videos) ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  const restoredLiveSession = readLiveSession();

  const state = {
    route: location.hash.slice(1) || "/",
    query: restoredLiveSession?.query || "",
    searched: Boolean(restoredLiveSession?.searched && restoredLiveSession?.videos?.length),
    filters: { time: "7d", type: "All", minViews: 0, sort: "opp", topic: "All" },
    saved: new Set(),
    savedResearch: [],
    ideas: [],
    experiments: [],
    notes: {},
    workflowSummary: null,
    learningSignals: [],
    workflowLoading: false,
    workflowLoaded: false,
    workflowError: "",
    collections: "All",
    savedView: "grid",
    watchTab: "channels",
    loading: false,
    error: false,
    connected: false,
    niches: "trading, AI tools, build in public",
    liveVideos: restoredLiveSession?.videos || [],
    apiError: "",
    dashboardData: null,
    dashboardLoading: false,
    dashboardError: "",
    patternsData: null,
    patternsLoading: false,
    patternsError: "",
  };

  function writeLiveSession() {
    try {
      sessionStorage.setItem(
        LIVE_SESSION_KEY,
        JSON.stringify({
          query: state.query,
          searched: state.searched,
          videos: state.liveVideos,
        })
      );
    } catch (_) {}
  }

  function fmt(n) {
    if (n == null) return "—";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "K";
    return String(n);
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);
  }

  function allKnownVideos() {
    const liveIds = new Set(state.liveVideos.map((v) => v.id));
    return [...state.liveVideos, ...D.videos.filter((v) => !liveIds.has(v.id))];
  }

  function videoById(id) {
    const live = allKnownVideos().find((v) => v.id === id);
    if (live) return live;
    const saved = state.savedResearch.find((v) => (v.videoId || v.id) === id);
    return saved ? { ...saved, id: saved.videoId || saved.id, source: "saved-research", persistedResearch: true } : null;
  }

  function ratioLabel(value) {
    if (value == null) return "—";
    const ratio = Number(value);
    if (!Number.isFinite(ratio)) return "—";
    if (ratio >= 0.1) return ratio.toFixed(2) + "×";
    if (ratio >= 0.001) return ratio.toFixed(3) + "×";
    return ratio.toFixed(4) + "×";
  }

  function ratioPercentLabel(value) {
    if (value == null) return "—";
    const percent = Number(value) * 100;
    if (!Number.isFinite(percent)) return "—";
    if (percent >= 1) return percent.toFixed(1) + "%";
    if (percent >= 0.1) return percent.toFixed(2) + "%";
    return percent.toFixed(3) + "%";
  }

  function outlierLabel(v) {
    return v.outlier == null ? "Baseline pending" : v.outlier.toFixed(1) + "×";
  }
  function level(x) {
    if (x >= 8) return "extreme";
    if (x >= 4) return "strong";
    if (x >= 2) return "interesting";
    return "normal";
  }
  function levelLabel(x) {
    return { extreme: "Extreme", strong: "Strong", interesting: "Interesting", normal: "Normal" }[level(x)];
  }
  function toast(msg) {
    const t = $("toast");
    t.hidden = false;
    t.textContent = msg;
    clearTimeout(toast._id);
    toast._id = setTimeout(() => (t.hidden = true), 2200);
  }
  function img(alt, cls, src) {
    return `<img class="${cls || "thumb"}" src="${esc(src || "thumb.jpg")}" alt="${esc(alt)}" />`;
  }

  function videoImg(v, cls) {
    return img(v.thumbAlt, cls, v.thumbnail);
  }
  function icon(d) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${d}</svg>`;
  }

  function ageLabel(hours) {
    const value = Number(hours || 0);
    if (value < 1) return "<1h";
    if (value < 24) return Math.round(value) + "h";
    if (value < 24 * 30) return Math.round(value / 24) + "d";
    return Math.round(value / (24 * 30)) + "mo";
  }

  async function apiJson(path, options = {}) {
    const config = { ...options };
    if (config.body && typeof config.body !== "string") {
      config.headers = { "Content-Type": "application/json", ...(config.headers || {}) };
      config.body = JSON.stringify(config.body);
    }
    const response = await fetch(API_BASE + path, config);
    if (!response.ok) {
      let message = "Christina Lab backend could not complete this request.";
      try {
        const payload = await response.json();
        if (payload.detail) message = payload.detail;
      } catch (_) {}
      throw new Error(message);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function fetchJson(path) {
    return apiJson(path);
  }

  function workflowRoute(path = state.route) {
    const clean = String(path || "/").split("?")[0] || "/";
    return (
      clean === "/discover" ||
      clean === "/saved" ||
      clean === "/ideas" ||
      clean === "/lab" ||
      clean === "/videos" ||
      clean.startsWith("/experiment/") ||
      clean.startsWith("/video/")
    );
  }

  async function loadWorkflowData(force = false) {
    if (state.workflowLoading || (state.workflowLoaded && !force)) return;
    state.workflowLoading = true;
    state.workflowError = "";
    if (workflowRoute()) render();
    try {
      const payload = await fetchJson("/api/workflow");
      state.savedResearch = Array.isArray(payload.savedResearch) ? payload.savedResearch : [];
      state.saved = new Set(state.savedResearch.map((item) => item.videoId || item.id));
      state.ideas = Array.isArray(payload.ideas) ? payload.ideas : [];
      state.experiments = Array.isArray(payload.experiments) ? payload.experiments : [];
      state.workflowSummary = payload.summary || null;
      state.learningSignals = Array.isArray(payload.learningSignals) ? payload.learningSignals : [];
      state.notes = Object.fromEntries(
        state.savedResearch.map((item) => [
          item.videoId || item.id,
          { why: item.why || "", adapt: item.adapt || "", angle: item.angle || "" },
        ])
      );
      state.workflowLoaded = true;
    } catch (error) {
      state.workflowError = error?.message || "Could not load the creator workflow.";
    } finally {
      state.workflowLoading = false;
      if (workflowRoute()) render();
    }
  }

  async function loadDashboardData(force = false) {
    if (state.dashboardLoading || (state.dashboardData && !force)) return;
    state.dashboardLoading = true;
    state.dashboardError = "";
    if ((state.route.split("?")[0] || "/") === "/") render();
    try {
      state.dashboardData = await fetchJson("/api/dashboard");
    } catch (error) {
      state.dashboardError = error?.message || "Could not load persisted dashboard data.";
    } finally {
      state.dashboardLoading = false;
      if ((state.route.split("?")[0] || "/") === "/") render();
    }
  }

  async function loadPatternsData(force = false) {
    if (state.patternsLoading || (state.patternsData && !force)) return;
    state.patternsLoading = true;
    state.patternsError = "";
    if (state.route.split("?")[0] === "/patterns") render();
    try {
      state.patternsData = await fetchJson("/api/patterns");
    } catch (error) {
      state.patternsError = error?.message || "Could not load persisted pattern data.";
    } finally {
      state.patternsLoading = false;
      if (state.route.split("?")[0] === "/patterns") render();
    }
  }

  function loadRouteData(path = state.route) {
    const clean = String(path || "/").split("?")[0] || "/";
    if (clean === "/") loadDashboardData();
    if (clean === "/patterns") loadPatternsData();
    if (workflowRoute(clean)) loadWorkflowData();
  }

  function navigate(path) {
    state.route = path;
    location.hash = path === "/" ? "" : path;
    render();
    loadRouteData(path);
  }

  window.addEventListener("hashchange", () => {
    state.route = location.hash.slice(1) || "/";
    render();
    loadRouteData(state.route);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette();
    }
    if (e.key === "Escape") {
      $("palette").hidden = true;
      $("modal").hidden = true;
    }
  });

  function openPalette() {
    const el = $("palette");
    el.hidden = false;
    el.innerHTML = `<div class="palette">
      <input id="palq" placeholder="Search Christina Lab…" />
      <div id="palhits"></div>
    </div>`;
    const hits = [
      ["Discover videos", "/discover"],
      ["Create idea", "/ideas"],
      ["Open saved research", "/saved"],
      ["Open experiments", "/lab"],
      ["Dashboard", "/"],
      ["Analytics", "/analytics"],
    ];
    const draw = (q) => {
      const f = hits.filter((h) => h[0].toLowerCase().includes(q.toLowerCase()));
      $("palhits").innerHTML = f.map((h) => `<div class="hit" data-to="${h[1]}">${h[0]}</div>`).join("");
    };
    draw("");
    $("palq").focus();
    $("palq").oninput = (e) => draw(e.target.value);
    el.onclick = (e) => {
      const to = e.target.dataset.to;
      if (to) {
        el.hidden = true;
        navigate(to);
      }
      if (e.target === el) el.hidden = true;
    };
  }

  async function saveVideo(id) {
    try {
      const existing = state.notes[id] || { why: "", adapt: "", angle: "" };
      const item = await apiJson("/api/research/" + encodeURIComponent(id), {
        method: "PUT",
        body: existing,
      });
      const index = state.savedResearch.findIndex((row) => (row.videoId || row.id) === id);
      if (index >= 0) state.savedResearch[index] = item;
      else state.savedResearch.unshift(item);
      state.saved.add(id);
      state.notes[id] = { why: item.why || "", adapt: item.adapt || "", angle: item.angle || "" };
      toast("Saved to Research");
      render();
    } catch (error) {
      toast(error?.message || "Could not save research");
    }
  }

  async function unsave(id) {
    try {
      await apiJson("/api/research/" + encodeURIComponent(id), { method: "DELETE" });
      state.saved.delete(id);
      state.savedResearch = state.savedResearch.filter((row) => (row.videoId || row.id) !== id);
      delete state.notes[id];
      toast("Video removed from Saved Research");
      render();
    } catch (error) {
      toast(error?.message || "Could not remove research");
    }
  }

  function ideaFrom(vid) {
    const v = videoById(vid);
    openIdeaModal(v);
  }

  function openIdeaModal(src) {
    const m = $("modal");
    const sourceNotes = src ? state.notes[src.id] || { why: "", adapt: "", angle: "" } : { why: "", adapt: "", angle: "" };
    const sourceType = src?.type === "Short" ? "Short" : "Long-form";
    m.hidden = false;
    m.innerHTML = `<div class="modal idea-modal">
      <h2 style="margin:0 0 6px;font-size:16px">Create idea</h2>
      <p class="meta" style="margin-top:0">${src ? "Source: " + esc(src.title) : "Standalone creator idea"}</p>
      <form class="form" id="ideaForm">
        <label>Working title <input name="title" required value="${src ? esc(src.title) : ""}" /></label>
        <label>Hook <input name="hook" placeholder="The first line viewers hear" /></label>
        <label>Topic <input name="topic" value="${src ? esc(src.topic || "") : ""}" /></label>
        <label>Content type
          <select name="type">
            <option ${sourceType === "Short" ? "selected" : ""}>Short</option>
            <option ${sourceType === "Long-form" ? "selected" : ""}>Long-form</option>
          </select>
        </label>
        <label>Angle <input name="angle" value="${esc(sourceNotes.angle || "")}" placeholder="Your differentiated angle" /></label>
        <label>Audience <input name="audience" /></label>
        <label>Hypothesis
          <textarea name="hypothesis" rows="3">${esc(sourceNotes.adapt || "What exactly do you expect this idea to prove?")}</textarea>
        </label>
        <label>Notes <textarea name="notes" rows="2">${esc(sourceNotes.why || "")}</textarea></label>
        <label>Priority <select name="priority"><option>High</option><option selected>Med</option><option>Low</option></select></label>
        <label>Status <select name="status"><option>Draft</option><option>Ready</option><option>Published</option></select></label>
        <div class="actions"><button class="btn ghost" type="button" id="cancelM">Cancel</button><button class="btn primary" type="submit">Create idea</button></div>
      </form>
    </div>`;
    $("cancelM").onclick = () => (m.hidden = true);
    m.onclick = (e) => {
      if (e.target === m) m.hidden = true;
    };
    $("ideaForm").onsubmit = async (e) => {
      e.preventDefault();
      const submit = e.submitter;
      if (submit) submit.disabled = true;
      const f = new FormData(e.target);
      try {
        if (src && !state.saved.has(src.id)) {
          await apiJson("/api/research/" + encodeURIComponent(src.id), {
            method: "PUT",
            body: sourceNotes,
          });
        }
        await apiJson("/api/ideas", {
          method: "POST",
          body: {
            sourceVideoId: src?.id || null,
            title: f.get("title"),
            hook: f.get("hook"),
            topic: f.get("topic"),
            contentType: f.get("type"),
            angle: f.get("angle"),
            audience: f.get("audience"),
            hypothesis: f.get("hypothesis"),
            notes: f.get("notes"),
            priority: f.get("priority"),
            status: f.get("status"),
          },
        });
        m.hidden = true;
        state.workflowLoaded = false;
        await loadWorkflowData(true);
        toast("Idea created and persisted");
        navigate("/ideas");
      } catch (error) {
        toast(error?.message || "Could not create idea");
        if (submit) submit.disabled = false;
      }
    };
  }

  function inheritedExperimentStatus(ideaStatus) {
    if (ideaStatus === "Ready") return "Ready";
    if (ideaStatus === "Published") return "Published";
    return "Draft";
  }

  function experimentStatusOptions(status) {
    return ["Draft", "Ready", "Published"]
      .map((value) => `<option ${value === status ? "selected" : ""}>${value}</option>`)
      .join("");
  }

  function openExperimentModal(idea = null) {
    if (!state.ideas.length) {
      toast("Create an idea first");
      navigate("/ideas");
      return;
    }
    const selected = idea || state.ideas[0];
    const inheritedStatus = inheritedExperimentStatus(selected.status);
    const m = $("modal");
    m.hidden = false;
    m.innerHTML = `<div class="modal">
      <h2 style="margin:0 0 6px;font-size:16px">Create experiment</h2>
      <p class="meta" style="margin-top:0">Turn an idea into a measurable test. New experiments inherit the source idea's workflow status.</p>
      <form class="form" id="experimentForm">
        <label>Idea
          <select name="ideaId" id="experimentIdea">
            ${state.ideas.map((item) => `<option value="${item.id}" ${String(item.id) === String(selected.id) ? "selected" : ""}>${esc(item.title)}</option>`).join("")}
          </select>
        </label>
        <label>Experiment name <input name="name" required value="${esc(selected.title)}" /></label>
        <label>Hypothesis <textarea name="hypothesis" rows="3">${esc(selected.hypothesis || "")}</textarea></label>
        <label>Status <select name="status">${experimentStatusOptions(inheritedStatus)}</select></label>
        <div class="actions"><button class="btn ghost" type="button" id="cancelM">Cancel</button><button class="btn primary" type="submit">Create experiment</button></div>
      </form>
    </div>`;
    $("cancelM").onclick = () => (m.hidden = true);
    m.onclick = (e) => {
      if (e.target === m) m.hidden = true;
    };
    $("experimentIdea").onchange = (e) => {
      const nextIdea = state.ideas.find((item) => String(item.id) === String(e.target.value));
      if (!nextIdea) return;
      const form = $("experimentForm");
      form.name.value = nextIdea.title;
      form.hypothesis.value = nextIdea.hypothesis || "";
      form.status.value = inheritedExperimentStatus(nextIdea.status);
    };
    $("experimentForm").onsubmit = async (e) => {
      e.preventDefault();
      const submit = e.submitter;
      if (submit) submit.disabled = true;
      const f = new FormData(e.target);
      try {
        const experiment = await apiJson("/api/experiments", {
          method: "POST",
          body: {
            ideaId: Number(f.get("ideaId")),
            name: f.get("name"),
            hypothesis: f.get("hypothesis"),
            status: f.get("status"),
            decision: "UNDECIDED",
          },
        });
        m.hidden = true;
        state.workflowLoaded = false;
        await loadWorkflowData(true);
        toast("Experiment created");
        navigate("/experiment/" + experiment.id);
      } catch (error) {
        toast(error?.message || "Could not create experiment");
        if (submit) submit.disabled = false;
      }
    };
  }

  const NAV = [
    ["Overview", null],
    ["Dashboard", "/", "dash"],
    ["Research", null],
    ["Discover", "/discover", "search"],
    ["Saved Research", "/saved", "bookmark"],
    ["Watchlists", "/watchlists", "eye"],
    ["Create", null],
    ["Ideas", "/ideas", "light"],
    ["Lab", null],
    ["Experiments", "/lab", "flask"],
    ["My Videos", "/videos", "play"],
    ["Insights", null],
    ["Patterns", "/patterns", "grid"],
    ["Analytics", "/analytics", "chart"],
    ["System", null],
    ["Settings", "/settings", "cog"],
  ];

  function layout(title, body) {
    const path = state.route.split("?")[0];
    const videoId = path.startsWith("/video/") ? path.slice(7) : "";
    const expId = path.startsWith("/experiment/") ? path.slice(12) : "";
    return `
    <div class="app">
      <div class="drawer-bg" id="dbg"></div>
      <aside class="sidebar" id="sb">
        <div class="brand">Christina <span>Lab</span></div>
        <nav class="nav">
          ${NAV.map((n) =>
            n[1] == null
              ? `<div class="nav-sec">${n[0]}</div>`
              : `<a href="#${n[1] === "/" ? "" : n[1]}" class="${path === n[1] || (n[1] === "/discover" && path.startsWith("/video")) || (n[1] === "/lab" && path.startsWith("/experiment")) ? "active" : ""}">${n[0]}</a>`
          ).join("")}
        </nav>
        <div class="profile">
          <img class="avatar" src="https://api.dicebear.com/7.x/avataaars/svg?seed=Christina" alt="Christina avatar" />
          <div><div>Christina</div><small>Workspace · Demo</small></div>
        </div>
      </aside>
      <div class="main">
        <header class="top">
          <button class="btn menu-btn" id="menu">Menu</button>
          <h1>${title}</h1>
          <div class="grow"></div>
          <input class="search-mini" id="gs" placeholder="Search app…  ⌘K" />
          <span class="badge">Christina workspace</span>
        </header>
        <div class="page">${body}</div>
      </div>
    </div>`;
  }

  function filteredVideos() {
    let list = (state.searched ? state.liveVideos : D.videos).slice();
    const q = state.query.trim().toLowerCase();
    if (q) {
      list = list.filter(
        (v) =>
          v.title.toLowerCase().includes(q) ||
          v.topic.toLowerCase().includes(q) ||
          v.channel.toLowerCase().includes(q)
      );
    }
    if (state.filters.type !== "All") {
      const wantedType =
        state.filters.type === "Shorts"
          ? "Short"
          : state.filters.type === "Regular long-form"
          ? "Long-form"
          : state.filters.type;
      list = list.filter((v) => v.type === wantedType);
    }
    if (state.filters.topic !== "All") list = list.filter((v) => v.topic === state.filters.topic);
    list = list.filter((v) => v.views >= (+state.filters.minViews || 0));

    const value = (item, key, fallback = -Infinity) => {
      const n = item[key];
      return Number.isFinite(n) ? n : fallback;
    };

    const s = state.filters.sort;
    list.sort((a, b) => {
      if (s === "out") return value(b, "outlier") - value(a, "outlier");
      if (s === "views") return value(b, "views", 0) - value(a, "views", 0);
      if (s === "vpd") return value(b, "viewsDay", 0) - value(a, "viewsDay", 0);
      if (s === "eng") return value(b, "engagement", 0) - value(a, "engagement", 0);
      return value(b, "opportunity", -1) - value(a, "opportunity", -1);
    });
    return list;
  }

  async function runDiscoverSearch(query) {
    const clean = String(query || "").trim();
    if (!clean) return;

    const days = { "24h": 1, "3d": 3, "7d": 7, "30d": 30 }[state.filters.time] || 7;
    state.query = clean;
    state.searched = true;
    state.loading = true;
    state.apiError = "";
    render();

    try {
      const url =
        API_BASE +
        "/api/discover?q=" +
        encodeURIComponent(clean) +
        "&published_after_days=" +
        days +
        "&max_results=25";
      const response = await fetch(url);
      if (!response.ok) {
        let message = "The YouTube backend could not load this search.";
        try {
          const payload = await response.json();
          if (payload.detail) message = payload.detail;
        } catch (_) {}
        throw new Error(message);
      }

      const payload = await response.json();
      state.liveVideos = Array.isArray(payload.videos) ? payload.videos : [];
      state.dashboardData = null;
      state.patternsData = null;
      writeLiveSession();
    } catch (error) {
      state.liveVideos = [];
      state.apiError = error?.message || "The YouTube backend could not load this search.";
    } finally {
      state.loading = false;
      render();
    }
  }

  function dash() {
    if (state.dashboardLoading && !state.dashboardData) {
      return `<div class="card" style="padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
    }
    if (state.dashboardError && !state.dashboardData) {
      return `<div class="empty"><h3>Couldn't load the research dashboard</h3><p>${esc(state.dashboardError)}</p><button class="btn primary" id="retryDashboard">Retry</button></div>`;
    }

    const d = state.dashboardData;
    if (!d) {
      return `<div class="empty"><h3>Loading real research data…</h3><p>The Dashboard now reads from Christina Lab's persisted SQLite research history.</p></div>`;
    }

    const m = d.metrics || {};
    const opportunities = Array.isArray(d.topOpportunities) ? d.topOpportunities : [];
    const growth = Array.isArray(d.fastestActualGrowth) ? d.fastestActualGrowth : [];
    const mix = Array.isArray(d.contentMix) ? d.contentMix : [];
    const maturity = d.dataMaturity || {};

    return `
      <div class="loop">Discover → Analyze → Snapshot → Compare → <b>Learn</b></div>
      <div style="font-size:22px;font-weight:600">Christina Lab research dashboard</div>
      <p class="sub">Real metrics from your local research database — no demo counters.</p>

      <div class="metrics">
        <div class="metric"><label>Public Videos Observed</label><div class="val num">${fmt(m.videosTracked || 0)}</div><div class="sec">candidates + channel-history videos</div></div>
        <div class="metric"><label>Metric Snapshots</label><div class="val num">${fmt(m.snapshotsStored || 0)}</div><div class="sec">timestamped public observations</div></div>
        <div class="metric"><label>Measured Growth Histories</label><div class="val num">${fmt(m.videosWithMultipleSnapshots || 0)}</div><div class="sec">videos with 2+ observations</div></div>
        <div class="metric"><label>Analyzed Search Results</label><div class="val num">${fmt(m.analyzedCandidates || 0)}</div><div class="sec">${fmt(m.topicsTracked || 0)} persisted Discover topics</div></div>
      </div>

      <div class="card">
        <div class="card-h">
          <h2>Strongest Persisted Opportunities</h2>
          <p>Latest real Opportunity Score stored for each analyzed video.</p>
        </div>
        ${opportunities.length
          ? opportunities.map((v) => `
            <div class="opp">
              ${img("Thumbnail for " + v.title, "thumb", v.thumbnail)}
              <div>
                <div class="t">${esc(v.title)}</div>
                <div class="meta">${esc(v.channel)} · ${esc(v.type)} · ${ageLabel(v.ageHours)} · ${fmt(v.views)} views · ${fmt(v.viewsDay)} / 24h pace · ${Number(v.engagement || 0).toFixed(2)}% eng · search: ${esc(v.topic || "—")}</div>
              </div>
              <div class="actions">
                <span class="num"><b>${v.opportunity}/100</b></span>
                <span class="outlier num">${v.outlier == null ? "—" : Number(v.outlier).toFixed(1) + "×"}</span>
                <span class="badge ${v.baselineMethod === "historical-snapshot-median" ? "strong" : ""}">${v.baselineMethod === "historical-snapshot-median" ? "Historical" : "Estimated"}</span>
              </div>
            </div>`).join("")
          : `<div class="empty"><p>No persisted Opportunity Scores yet. Run a fresh Discover search after Milestone 5 and they will appear here.</p><button class="btn primary" data-go="/discover">Open Discover</button></div>`}
      </div>

      <div class="grid2">
        <div class="card">
          <div class="card-h"><h2>Fastest Actual Growth</h2><p>Measured between stored snapshots, not extrapolated.</p></div>
          ${growth.length
            ? `<div class="rank" style="color:var(--dim)"><span>Video</span><span>Type</span><span>Δ views</span><span>Actual / hour</span></div>` +
              growth.map((v) => `<div class="rank"><span>${esc(v.title)}</span><span>${esc(v.type)}</span><span class="num">+${fmt(v.deltaViews)}</span><span class="num">${fmt(v.actualViewsHour)}/h</span></div>`).join("")
            : `<div class="empty"><p>No actual growth pairs yet. Revisit tracked videos at least 15 minutes later to create second snapshots.</p></div>`}
        </div>

        <div class="card">
          <div class="card-h"><h2>Dataset Mix</h2><p>What Christina Lab has actually observed.</p></div>
          ${mix.length
            ? mix.map((row) => `<div class="rank"><span>${esc(row.type)}</span><span></span><span></span><span class="num">${fmt(row.count)} videos</span></div>`).join("")
            : `<div class="empty"><p>No tracked videos yet.</p></div>`}
        </div>
      </div>

      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 6px;font-size:14px">Data maturity</h2>
        <p class="meta" style="margin:0">
          ${fmt(m.historicalBaselinesReady || 0)} videos have produced a stored historical same-age baseline so far ·
          ${fmt(maturity.videosWithMultipleSnapshots || 0)} videos have real growth history ·
          ${fmt(maturity.needsMoreHistory || 0)} tracked videos still need another observation.
        </p>
      </div>`;
  }

  function oppRow(v) {
    const saved = state.saved.has(v.id);
    return `<div class="opp">
      ${videoImg(v)}
      <div>
        <div class="t">${esc(v.title)}</div>
        <div class="meta">${esc(v.channel)} · ${esc(v.age)} · ${fmt(v.views)} views · <span class="tip" title="Current average views/hour × 24. This is an extrapolated pace, not actual views received in 24 hours.">${fmt(v.viewsDay)} / 24h pace</span> ·
          <span class="tip" title="Likes + comments relative to views.">${Number(v.engagement || 0).toFixed(2)}% eng</span> · ${esc(v.topic)} · ${esc(v.type)}</div>
      </div>
      <div class="actions">
        ${v.outlier == null
          ? `<span class="meta">Need 3 recent uploads</span>`
          : `<span class="outlier num tip" title="Average views/hour for this video divided by the median average views/hour of recent channel uploads.">${v.outlier.toFixed(1)}×</span>
             <span class="badge ${level(v.outlier)}">${levelLabel(v.outlier)}</span>`}
        ${Number.isFinite(v.opportunity) ? `<span class="num" title="Opportunity Score">${v.opportunity}/100</span>` : ""}
        <button class="btn" data-act="${saved ? "unsave" : "save"}" data-id="${v.id}">${saved ? "Saved" : "Save"}</button>
        <button class="btn primary" data-act="analyze" data-id="${v.id}">Analyze</button>
      </div>
    </div>`;
  }

  function discover() {
    const list = state.searched ? filteredVideos() : [];
    const topicSource = state.searched ? state.liveVideos : D.videos;
    const topics = ["All", ...new Set(topicSource.map((v) => v.topic).filter(Boolean))];
    const option = (value, label) =>
      `<option value="${value}" ${state.filters.time === value ? "selected" : ""}>${label}</option>`;

    return `
      <p class="sub">Search real public YouTube data and compare velocity, engagement, and audience-normalized reach.</p>
      <form class="search-lg" id="ds">
        <input name="q" value="${esc(state.query)}" placeholder="Search topics, keywords, or channels..." />
        <button class="btn primary" type="submit">Search YouTube</button>
      </form>
      <div class="filters">
        <select id="ftime">
          ${option("24h", "Last 24 hours")}
          ${option("3d", "3 days")}
          ${option("7d", "7 days")}
          ${option("30d", "30 days")}
        </select>
        <select id="ftype">
          <option ${state.filters.type === "All" ? "selected" : ""}>All</option>
          <option ${state.filters.type === "Shorts" ? "selected" : ""}>Shorts</option>
          <option ${state.filters.type === "Regular long-form" ? "selected" : ""}>Regular long-form</option>
          <option ${state.filters.type === "Livestream" ? "selected" : ""}>Livestream</option>
        </select>
        <input id="fmin" type="number" value="${state.filters.minViews || ""}" placeholder="Min views" style="width:110px" />
        <select id="ftopic">${topics
          .map((t) => `<option ${state.filters.topic === t ? "selected" : ""}>${esc(t)}</option>`)
          .join("")}</select>
        <select id="fsort">
          <option value="opp" ${state.filters.sort === "opp" ? "selected" : ""}>Best Opportunities</option>
          <option value="out" ${state.filters.sort === "out" ? "selected" : ""}>Outlier Score</option>
          <option value="views" ${state.filters.sort === "views" ? "selected" : ""}>Views</option>
          <option value="vpd" ${state.filters.sort === "vpd" ? "selected" : ""}>24h Run Rate</option>
          <option value="eng" ${state.filters.sort === "eng" ? "selected" : ""}>Engagement</option>
        </select>
        <button class="btn ghost" id="resetF">Reset filters</button>
      </div>
      ${state.searched && !state.loading && !state.apiError
        ? `<div class="meta" style="margin:-4px 0 12px">Live YouTube Data · Milestone 4 now stores real metric snapshots over time. Historical same-age baselines are used when enough observations exist; otherwise Christina Lab clearly falls back to a provisional velocity estimate.</div>`
        : ""}
      ${
        state.loading
          ? `<div class="card" style="padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`
          : state.apiError
          ? `<div class="empty"><h3>Couldn't load YouTube results</h3><p>${esc(state.apiError)}</p><button class="btn" id="retry">Retry</button></div>`
          : !state.searched
          ? `<div class="empty">
              <h3>Find your next content opportunity.</h3>
              <p>Search real YouTube data by topic, niche, keyword, or channel.</p>
              <div class="chips">${["AI tools", "coding projects", "trading mistakes", "trading signals", "build in public", "creator growth"]
                .map((s) => `<button class="chip" data-sug="${esc(s)}">${esc(s)}</button>`)
                .join("")}</div>
            </div>`
          : list.length === 0
          ? `<div class="empty"><h3>No YouTube videos found for this search.</h3><p>Try a broader keyword or longer time range.</p></div>`
          : `<div class="card desk-only"><table class="table">
              <thead><tr><th></th><th>Video</th><th>Age</th><th>Views</th><th>24h run rate</th><th>V/sub</th><th>Eng</th><th>Outlier</th><th>Opp</th><th></th></tr></thead>
              <tbody>${list
                .map(
                  (v) => `<tr>
                    <td>${videoImg(v)}</td>
                    <td><div class="t">${esc(v.title)}</div><div class="meta">${esc(v.channel)} · ${fmt(v.subs)} subs · ${esc(v.duration)} · ${esc(v.type)} · ${esc(v.topic)}</div></td>
                    <td>${esc(v.age)}</td>
                    <td class="num">${fmt(v.views)}</td>
                    <td class="num tip" title="Current average views/hour × 24. This is an extrapolated pace, not actual views received in 24 hours.">${fmt(v.viewsDay)}</td>
                    <td class="num">${ratioLabel(v.viewsSub)}</td>
                    <td class="num">${Number(v.engagement || 0).toFixed(2)}%</td>
                    <td>${v.outlier == null
                      ? `<span class="meta">Need more channel history</span>`
                      : `<span class="outlier num tip" title="${v.baselineMethod === "historical-snapshot-median" ? "Compared with real same-age snapshots from previous videos." : "Provisional estimate based on recent videos' average lifetime velocity while snapshots accumulate."}">${v.outlier.toFixed(1)}×</span>
                         <div class="meta">${v.baselineMethod === "historical-snapshot-median" ? "historical" : "estimated"} · expected ~${fmt(v.baseline)} by ${esc(v.age)} · ${v.baselineSampleSize} samples</div>`}</td>
                    <td class="num tip" title="Explainable Opportunity Score v1.2. Open Analyze to see every component and guardrail.">${v.opportunity == null ? "—" : "<b>" + v.opportunity + "/100</b>"}</td>
                    <td class="actions">
                      <button class="btn" data-act="${state.saved.has(v.id) ? "unsave" : "save"}" data-id="${esc(v.id)}">${state.saved.has(v.id) ? "Saved" : "Save"}</button>
                      <button class="btn" data-act="analyze" data-id="${esc(v.id)}">Analyze</button>
                      <button class="btn primary" data-act="idea" data-id="${esc(v.id)}">Turn into Idea</button>
                    </td>
                  </tr>`
                )
                .join("")}</tbody></table></div>
             <div class="card" style="display:none" id="mlist">${list.map((v) => oppRow(v) + extraActs(v)).join("")}</div>`
      }`;
  }

  function extraActs(v) {
    return "";
  }

  function liveAnalysis(v, related, n) {
    const baselineReady = v.outlier != null && v.baseline != null;
    const historicalBaseline = v.baselineMethod === "historical-snapshot-median";
    const components = Array.isArray(v.opportunityComponents) ? v.opportunityComponents : [];
    const guardrails = Array.isArray(v.opportunityGuardrails) ? v.opportunityGuardrails : [];
    const snapshots = Array.isArray(v.snapshotHistory) ? v.snapshotHistory : [];
    const baselineLabel = historicalBaseline ? "Historical same-age Outlier" : "Estimated Outlier";
    const baselineDetail = historicalBaseline
      ? `median of ${v.baselineSampleSize} real snapshots near ${Number(v.historicalTargetAgeHours || v.ageHours || 0).toFixed(1)}h (±${Number(v.historicalToleranceHours || 0).toFixed(1)}h)`
      : `provisional velocity estimate · ${v.historicalSnapshotSampleSize || 0}/3 same-age historical samples available`;

    return `
      <div class="video-head">
        ${videoImg(v, "thumb")}
        <div>
          <div class="t" style="font-size:18px">${esc(v.title)}</div>
          <div class="meta">${[v.channel, v.published, v.duration, v.type, v.liveStatus && v.liveStatus !== "none" ? v.liveStatus : ""].filter(Boolean).map(esc).join(" · ")}</div>
          <div class="actions" style="margin-top:12px">
            <a class="btn" href="${esc(v.youtubeUrl)}" target="_blank" rel="noreferrer">Open on YouTube</a>
            <button class="btn" data-act="${state.saved.has(v.id) ? "unsave" : "save"}" data-id="${esc(v.id)}">${state.saved.has(v.id) ? "Saved" : "Save Research"}</button>
            <button class="btn primary" data-act="idea" data-id="${esc(v.id)}">Turn into Idea</button>
          </div>
        </div>
      </div>

      <div class="metrics">
        <div class="metric"><label>Opportunity Score</label><div class="val num">${v.opportunity == null ? "—" : v.opportunity + "/100"}</div><div class="sec">Explainable v1.2 score</div></div>
        <div class="metric"><label>Views</label><div class="val num">${Number(v.views || 0).toLocaleString()}</div></div>
        <div class="metric"><label class="tip" title="Current average views/hour × 24. This is an extrapolated pace, not actual views received in 24 hours.">24h Run Rate</label><div class="val num">${fmt(v.viewsDay)}</div></div>
        <div class="metric"><label>Engagement Rate</label><div class="val num">${Number(v.engagement || 0).toFixed(2)}%</div></div>
        <div class="metric"><label>Views / Subscriber</label><div class="val num">${ratioLabel(v.viewsSub)}</div><div class="sec">${v.viewsSub == null ? "Subscriber count unavailable" : ratioPercentLabel(v.viewsSub) + " of subscriber count"}</div></div>
        <div class="metric"><label class="tip" title="${historicalBaseline ? "Real same-age snapshot comparison." : "Temporary estimate while real same-age history accumulates."}">${baselineLabel}</label><div class="val num outlier">${baselineReady ? v.outlier.toFixed(1) + "×" : "—"}</div></div>
        <div class="metric"><label>${historicalBaseline ? "Historical Expected Views" : "Estimated Views at This Age"}</label><div class="val num">${baselineReady ? fmt(v.baseline) : "—"}</div><div class="sec">${baselineReady ? esc(baselineDetail) : "Need at least 3 usable comparison samples"}</div></div>
        <div class="metric"><label>Snapshots Stored</label><div class="val num">${snapshots.length}</div><div class="sec">${snapshots.length >= 2 ? "real growth history started" : "first observation — check again later"}</div></div>
      </div>

      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 4px;font-size:14px">Why Opportunity = ${v.opportunity == null ? "—" : v.opportunity + "/100"}</h2>
        <p class="meta" style="margin-top:0">No hidden AI judgment. Component points total ${v.opportunityRaw ?? "—"} before guardrails. Historical snapshot baselines receive full confidence; the older velocity approximation is deliberately limited while history is collected.</p>
        <div style="display:grid;gap:6px;margin-top:10px">
          ${components.length
            ? components.map((component) => `
                <div class="rank" style="grid-template-columns:72px 1fr auto">
                  <span class="num">+${component.score}/${component.max}</span>
                  <span>${esc(component.label)}</span>
                  <span class="meta">${esc(component.key)}</span>
                </div>`).join("")
            : `<div class="meta">Opportunity breakdown unavailable.</div>`}
        </div>
        <div style="margin-top:12px">
          <div class="sec">GUARDRAILS</div>
          ${guardrails.length
            ? `<ul style="margin-bottom:0">${guardrails.map((g) => `<li>${esc(g.label)}</li>`).join("")}</ul>`
            : `<p class="meta" style="margin-bottom:0">No guardrails changed this score.</p>`}
        </div>
      </div>

      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 4px;font-size:14px">Real snapshot history</h2>
        <p class="meta" style="margin-top:0">Each time Christina Lab sees this video again (at least 15 minutes later), it stores another public-metric observation. This is how the app learns actual 1h → 6h → 12h → 24h → 48h growth over time.</p>
        ${snapshots.length
          ? `<div style="display:grid;gap:6px">${snapshots.map((s) => `
              <div class="rank" style="grid-template-columns:90px 1fr 1fr 1fr">
                <span class="num">${Number(s.ageHours).toFixed(1)}h</span>
                <span>${Number(s.views).toLocaleString()} views</span>
                <span class="meta">${Number(s.likes).toLocaleString()} likes</span>
                <span class="meta">${Number(s.comments).toLocaleString()} comments</span>
              </div>`).join("")}</div>`
          : `<div class="meta">No snapshots stored yet.</div>`}
      </div>

      <div class="card why" style="margin-top:12px">
        <h2 style="margin:0 0 8px;font-size:14px">Signal details</h2>
        <ul>
          ${baselineReady
            ? historicalBaseline
              ? `<li><b>${v.outlier.toFixed(1)}× historical same-age outlier:</b> ${fmt(v.views)} current views vs a ${fmt(v.baseline)} median from previous ${esc(v.type)} videos observed at approximately the same age.</li>`
              : `<li><b>${v.outlier.toFixed(1)}× provisional outlier:</b> ${fmt(v.views)} current views vs ~${fmt(v.baseline)} estimated from recent lifetime-average velocity. Real same-age snapshots are still accumulating.</li>`
            : `<li>There is not enough usable channel history to calculate a baseline yet.</li>`}
          <li>${fmt(v.viewsDay)} projected 24h run rate from the video's current average pace; this is not actual 24-hour views.</li>
          <li>${Number(v.engagement || 0).toFixed(2)}% public engagement from likes + comments relative to views.</li>
          <li>${v.viewsSub == null ? "Subscriber count is hidden or unavailable." : ratioLabel(v.viewsSub) + " views/subscriber, equal to " + ratioPercentLabel(v.viewsSub) + " of the current subscriber count."}</li>
          <li>Content classification: <b>${esc(v.type)}</b>${v.liveStatus === "replay" ? " (livestream replay)" : v.liveStatus === "live" ? " (currently live)" : ""}.</li>
        </ul>
        <p class="meta" style="margin-bottom:0">Opportunity Score v1.2 and outlier metrics are Christina Lab derived metrics from public YouTube data, not official YouTube metrics.</p>
      </div>

      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 10px;font-size:14px">Creator notes</h2>
        <form class="form" id="noteForm" data-vid="${esc(v.id)}">
          <label>Why did you save this?<textarea name="why" rows="2">${esc(n.why)}</textarea></label>
          <label>How could you adapt this idea without copying it?<textarea name="adapt" rows="2">${esc(n.adapt)}</textarea></label>
          <label>What unique angle could you add?<textarea name="angle" rows="2">${esc(n.angle)}</textarea></label>
          <button class="btn primary" type="submit">Save note</button>
        </form>
      </div>

      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Related live results</h2><p>Other videos returned for the same search.</p></div>
        ${related.length
          ? related.map((r) => `<div class="opp">${videoImg(r)}<div><div class="t">${esc(r.title)}</div><div class="meta">${esc(r.channel)} · ${esc(r.type)} · ${fmt(r.viewsDay)} / 24h pace</div></div><span class="num">${r.opportunity == null ? "—" : r.opportunity + "/100"}</span></div>`).join("")
          : `<div class="empty"><p>No related live results in this search set.</p></div>`}
      </div>`;
  }

  function analysis(id) {
    const v = videoById(id);
    if (!v) {
      return `
        <div class="empty">
          <h3>Live research result not available.</h3>
          <p>Christina Lab will not substitute demo analysis for a missing live YouTube result. Return to Discover and run the search again.</p>
          <button class="btn primary" data-go="/discover">Back to Discover</button>
        </div>`;
    }
    const related = allKnownVideos().filter((x) => x.topic === v.topic && x.id !== v.id).slice(0, 4);
    const n = state.notes[v.id] || { why: "", adapt: "", angle: "" };
    if (v.source === "youtube" || v.persistedResearch) return liveAnalysis(v, related, n);
    return `
      <div class="video-head">
        ${img(v.thumbAlt, "thumb")}
        <div>
          <div class="t" style="font-size:18px">${v.title}</div>
          <div class="meta">${v.channel} · ${v.published} · ${v.duration} · ${v.type}</div>
          <div class="actions" style="margin-top:12px">
            <a class="btn" href="https://youtube.com" target="_blank" rel="noreferrer">Open on YouTube</a>
            <button class="btn" data-act="${state.saved.has(v.id) ? "unsave" : "save"}" data-id="${v.id}">${state.saved.has(v.id) ? "Saved" : "Save Research"}</button>
            <button class="btn primary" data-act="idea" data-id="${v.id}">Turn into Idea</button>
          </div>
        </div>
      </div>
      <div class="metrics">
        <div class="metric"><label>Views</label><div class="val num">${v.views.toLocaleString()}</div></div>
        <div class="metric"><label class="tip" title="Current average views/hour × 24. This is an extrapolated pace, not actual views received in 24 hours.">24h Run Rate</label><div class="val num">${fmt(v.viewsDay)}</div></div>
        <div class="metric"><label class="tip" title="Likes + comments relative to views.">Engagement Rate</label><div class="val num">${v.engagement}%</div></div>
        <div class="metric"><label>Views / Subscriber</label><div class="val num">${v.viewsSub}×</div></div>
        <div class="metric"><label class="tip" title="Performance relative to the channel's typical recent video.">Outlier Score</label><div class="val num outlier">${v.outlier == null ? "Baseline pending" : v.outlier.toFixed(1) + "×"}</div></div>
        <div class="metric"><label>Channel Baseline</label><div class="val num">${fmt(v.baseline)}</div></div>
      </div>
      <div class="grid2">
        <div class="card">
          <div class="card-h"><h2>Performance vs Channel Baseline</h2></div>
          <div class="chart">${spark(v)}</div>
          <div class="meta" style="padding:0 14px 12px">0h · 6h · 12h · 24h · 48h · 7d</div>
        </div>
        <div class="card why">
          <h2 style="margin:0 0 8px;font-size:14px">Why this is interesting</h2>
          <ul>
            <li>${v.outlier == null ? "Baseline pending" : v.outlier.toFixed(1) + "×"} above channel baseline</li>
            <li>Unusually high views during the first ${v.age}</li>
            <li>Engagement ${Math.round((v.engagement / 5.8 - 1) * 100)}% vs a typical 5.8% channel rate</li>
            <li>Topic appearing across multiple recent outliers</li>
          </ul>
        </div>
      </div>
      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 10px;font-size:14px">Content Analysis</h2>
        <div class="grid2" style="font-size:13px">
          <div>Topic<br><b>${v.topic}</b></div>
          <div>Audience<br><b>Beginner builders / traders in this niche</b></div>
          <div>Pain point<br><b>Wanting a clearer edge without copying blindly</b></div>
          <div>Hook type<br><b>Contradiction / challenge</b></div>
          <div>Title pattern<br><b>“Why X doesn’t work” / “I built X in Y”</b></div>
          <div>Format<br><b>${v.type === "Short" ? "Short diagnosis" : "Build-in-public / case"}</b></div>
          <div>Possible success factors<br><b>Clear transformation, curiosity, visible result</b></div>
          <div>Content angle<br><b>Surprising problem, not a tutorial</b></div>
        </div>
      </div>
      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 10px;font-size:14px">Creator notes</h2>
        <form class="form" id="noteForm" data-vid="${v.id}">
          <label>Why did you save this?<textarea name="why" rows="2">${n.why}</textarea></label>
          <label>How could you adapt this idea without copying it?<textarea name="adapt" rows="2">${n.adapt}</textarea></label>
          <label>What unique angle could you add?<textarea name="angle" rows="2">${n.angle}</textarea></label>
          <button class="btn primary" type="submit">Save note</button>
        </form>
      </div>
      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Related opportunities</h2><p>Is this a one-off, or a broader pattern?</p></div>
        ${related.map((r) => `<div class="opp">${img(r.thumbAlt)}<div><div class="t">${r.title}</div><div class="meta">${r.channel} · ${r.topic}</div></div><span class="outlier">${r.outlier.toFixed(1)}×</span></div>`).join("")}
      </div>`;
  }

  function spark(v) {
    const cur = [0, v.views * 0.18, v.views * 0.35, v.views * 0.55, v.views * 0.78, v.views];
    const base = [0, v.baseline * 0.12, v.baseline * 0.28, v.baseline * 0.48, v.baseline * 0.7, v.baseline];
    const max = Math.max(...cur, ...base) || 1;
    const pts = (arr) => arr.map((y, i) => `${(i / 5) * 280},${120 - (y / max) * 110}`).join(" ");
    return `<svg viewBox="0 0 300 140" aria-label="Performance chart">
      <polyline fill="none" stroke="#3d4656" stroke-width="2" points="${pts(base)}" />
      <polyline fill="none" stroke="#5b8def" stroke-width="2.5" points="${pts(cur)}" />
    </svg>`;
  }

  function workflowGate() {
    if (state.workflowLoading && !state.workflowLoaded) {
      return `<div class="card" style="padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
    }
    if (state.workflowError && !state.workflowLoaded) {
      return `<div class="empty"><h3>Couldn't load the creator workflow</h3><p>${esc(state.workflowError)}</p><button class="btn primary" id="retryWorkflow">Retry</button></div>`;
    }
    return "";
  }

  function saved() {
    const gate = workflowGate();
    if (gate) return gate;
    const items = state.savedResearch.slice();
    return `
      <p class="sub">Persisted research you deliberately chose to keep. Notes survive refreshes and become the source material for ideas.</p>
      <div class="filters">
        <button class="btn ${state.savedView === "grid" ? "primary" : ""}" data-view="grid">Grid</button>
        <button class="btn ${state.savedView === "table" ? "primary" : ""}" data-view="table">Table</button>
        <span class="meta">${items.length} saved research item${items.length === 1 ? "" : "s"}</span>
      </div>
      ${items.length === 0
        ? `<div class="empty"><h3>No saved research yet.</h3><p>Save a real Discover result, write why it matters, then turn it into an idea.</p><button class="btn primary" data-go="/discover">Explore Videos</button></div>`
        : state.savedView === "grid"
        ? `<div class="grid2">${items.map((v) => `
            <div class="card" style="padding:12px">
              ${videoImg(v)}
              <div class="t" style="margin-top:8px">${esc(v.title)}</div>
              <div class="meta">${esc(v.channel)} · ${esc(v.topic || "Unspecified")} · ${esc(v.type)} · ${fmt(v.views)} views</div>
              <div class="actions" style="margin:8px 0">
                <span class="num">${v.opportunity == null ? "—" : v.opportunity + "/100"}</span>
                <span class="outlier">${v.outlier == null ? "Baseline pending" : Number(v.outlier).toFixed(1) + "×"}</span>
                <span class="badge">${v.ideaCount || 0} idea${Number(v.ideaCount || 0) === 1 ? "" : "s"}</span>
              </div>
              <div class="meta"><b>Why:</b> ${esc(v.why || "Not written yet")}</div>
              <div class="meta" style="margin-top:4px"><b>Adapt:</b> ${esc(v.adapt || "Not written yet")}</div>
              <div class="meta" style="margin-top:4px"><b>Angle:</b> ${esc(v.angle || "Not written yet")}</div>
              <div class="actions" style="margin-top:10px">
                <button class="btn" data-act="analyze" data-id="${esc(v.videoId || v.id)}">Open research</button>
                <button class="btn primary" data-act="idea" data-id="${esc(v.videoId || v.id)}">Turn into Idea</button>
                <button class="btn ghost" data-act="unsave" data-id="${esc(v.videoId || v.id)}">Remove</button>
              </div>
            </div>`).join("")}</div>`
        : `<div class="card"><table class="table"><thead><tr><th>Research</th><th>Opp</th><th>Outlier</th><th>Notes</th><th></th></tr></thead><tbody>
            ${items.map((v) => `<tr>
              <td><div class="t">${esc(v.title)}</div><div class="meta">${esc(v.channel)} · ${esc(v.topic || "Unspecified")}</div></td>
              <td class="num">${v.opportunity == null ? "—" : v.opportunity + "/100"}</td>
              <td class="outlier">${v.outlier == null ? "—" : Number(v.outlier).toFixed(1) + "×"}</td>
              <td>${[v.why, v.adapt, v.angle].filter(Boolean).length}/3 prompts</td>
              <td class="actions"><button class="btn primary" data-act="idea" data-id="${esc(v.videoId || v.id)}">Idea</button><button class="btn ghost" data-act="unsave" data-id="${esc(v.videoId || v.id)}">Remove</button></td>
            </tr>`).join("")}
          </tbody></table></div>`}
    `;
  }

  function ideas() {
    const gate = workflowGate();
    if (gate) return gate;
    const cols = ["Draft", "Ready", "Published"];
    return `
      <p class="sub">Persisted idea pipeline: Draft → Ready → Published. Drag cards between stages; every move is saved to SQLite.</p>
      <div class="actions" style="margin-bottom:12px">
        <button class="btn primary" id="newIdea">Create idea</button>
        <span class="meta">${state.ideas.length} persisted idea${state.ideas.length === 1 ? "" : "s"}</span>
      </div>
      ${state.ideas.length === 0 ? `<div class="empty"><h3>No ideas yet.</h3><p>Turn a Saved Research item into your first testable content idea.</p><button class="btn primary" data-go="/saved">Open Saved Research</button></div>` : `
      <div class="kanban">
        ${cols.map((colName) => {
          const cards = state.ideas.filter((idea) => idea.status === colName);
          return `<div class="kcol" data-col="${colName}"><h3>${colName} · ${cards.length}</h3>
            ${cards.map((idea) => `<div class="icard" draggable="true" data-idea="${idea.id}">
              <div class="t">${esc(idea.title)}</div>
              <div class="hook">${esc(idea.hook || idea.hypothesis || "No hook/hypothesis written yet")}</div>
              <div class="meta">${esc(idea.topic || "Unspecified")} · ${esc(idea.type)} · ${esc(idea.priority)} priority${idea.sourceVideoId ? " · sourced from research" : ""}</div>
              <div class="actions" style="margin-top:8px">
                <button class="btn primary" data-create-exp="${idea.id}">Create Experiment</button>
              </div>
            </div>`).join("")}
          </div>`;
        }).join("")}
      </div>`}
    `;
  }

  function lab() {
    const gate = workflowGate();
    if (gate) return gate;
    const e = state.experiments;
    const summary = state.workflowSummary || {};
    const decisions = summary.decisions || {};
    const learning = state.learningSignals || [];
    return `
      <div style="font-size:20px;font-weight:600">Christina Lab experiments</div>
      <p class="sub">Ideas become measurable tests. Record the actual result, then choose GO / TEST / HOLD based on your evidence.</p>
      <div class="actions" style="margin-bottom:12px"><button class="btn primary" id="newExperiment">Create experiment</button></div>
      <div class="metrics">
        <div class="metric"><label>Experiments</label><div class="val num">${summary.experiments ?? e.length}</div></div>
        <div class="metric"><label>Published</label><div class="val num">${summary.publishedExperiments ?? e.filter((x) => x.status === "Published").length}</div></div>
        <div class="metric"><label>GO</label><div class="val num">${decisions.GO || 0}</div></div>
        <div class="metric"><label>TEST</label><div class="val num">${decisions.TEST || 0}</div></div>
        <div class="metric"><label>HOLD</label><div class="val num">${decisions.HOLD || 0}</div></div>
        <div class="metric"><label>Average 24h Views</label><div class="val num">${summary.average24hViews == null ? "—" : fmt(summary.average24hViews)}</div></div>
        <div class="metric"><label>Average Subscriber Gain</label><div class="val num">${summary.averageSubscriberGain == null ? "—" : (summary.averageSubscriberGain >= 0 ? "+" : "") + summary.averageSubscriberGain}</div></div>
      </div>

      ${e.length ? `<div class="card">
        <table class="table">
          <thead><tr><th>Experiment</th><th>Topic</th><th>Status</th><th>24h</th><th>7d</th><th>Ret.</th><th>Subs</th><th>Decision</th></tr></thead>
          <tbody>
            ${e.map((x) => `<tr>
              <td><a href="#/experiment/${x.id}">EXP-${String(x.id).padStart(3, "0")}</a><div class="meta">${esc(x.name)}</div></td>
              <td>${esc(x.topic || "Unspecified")}<div class="meta">${esc(x.format)}</div></td>
              <td>${esc(x.status)}</td>
              <td class="num">${x.v24 == null ? "—" : fmt(x.v24)}</td>
              <td class="num">${x.v7 == null ? "—" : fmt(x.v7)}</td>
              <td>${x.retention == null ? "—" : Number(x.retention).toFixed(1) + "%"}</td>
              <td>${x.subs == null ? "—" : (x.subs >= 0 ? "+" : "") + x.subs}</td>
              <td>
                <select class="dec" data-exp="${x.id}">
                  <option value="UNDECIDED" ${x.decision === "UNDECIDED" ? "selected" : ""}>Undecided</option>
                  <option ${x.decision === "GO" ? "selected" : ""}>GO</option>
                  <option ${x.decision === "TEST" ? "selected" : ""}>TEST</option>
                  <option ${x.decision === "HOLD" ? "selected" : ""}>HOLD</option>
                </select>
              </td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>` : `<div class="empty"><h3>No experiments yet.</h3><p>Create an experiment from a Ready idea, then record what actually happened.</p><button class="btn primary" data-go="/ideas">Open Ideas</button></div>`}

      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>What Christina Lab is learning</h2><p>Creator-specific evidence from your persisted experiments — not market popularity.</p></div>
        ${learning.length
          ? learning.map((row) => `<div class="rank"><span><b>${esc(row.topic)}</b></span><span>${row.experiments} experiment${row.experiments === 1 ? "" : "s"}</span><span>GO ${row.GO || 0} · TEST ${row.TEST || 0} · HOLD ${row.HOLD || 0}</span><span>${row.avg24hViews == null ? "24h pending" : fmt(row.avg24hViews) + " avg 24h"}${row.avgSubscriberGain == null ? "" : " · " + (row.avgSubscriberGain >= 0 ? "+" : "") + row.avgSubscriberGain + " subs"}</span></div>`).join("")
          : `<div class="empty"><p>No creator-specific evidence yet. Publish a test, enter its real result, and make a GO / TEST / HOLD decision.</p></div>`}
      </div>
      <p class="sub">GO = evidence worth scaling. TEST = promising but needs another run. HOLD = not a current priority. Christina Lab stores your decision; it does not make the decision for you.</p>
    `;
  }

  function experiment(id) {
    const gate = workflowGate();
    if (gate) return gate;
    const x = state.experiments.find((item) => String(item.id) === String(id));
    if (!x) {
      return `<div class="empty"><h3>Experiment not found.</h3><p>It may not have been created yet or was loaded before the latest workflow refresh.</p><button class="btn" data-go="/lab">Back to Experiments</button></div>`;
    }
    const idea = state.ideas.find((item) => String(item.id) === String(x.ideaId));
    return `
      <p class="sub">EXP-${String(x.id).padStart(3, "0")} · ${esc(x.status)} · source idea ${idea ? esc(idea.title) : "#" + x.ideaId}</p>
      <h2 style="margin-top:0">${esc(x.name)}</h2>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <div class="meta">Hypothesis</div>
        <p>${esc(x.hypothesis || "No hypothesis recorded yet.")}</p>
      </div>
      <div class="metrics">
        <div class="metric"><label>24h views</label><div class="val num">${x.v24 == null ? "—" : fmt(x.v24)}</div></div>
        <div class="metric"><label>7d views</label><div class="val num">${x.v7 == null ? "—" : fmt(x.v7)}</div></div>
        <div class="metric"><label>Retention</label><div class="val num">${x.retention == null ? "—" : Number(x.retention).toFixed(1) + "%"}</div></div>
        <div class="metric"><label>Subscribers</label><div class="val num">${x.subs == null ? "—" : (x.subs >= 0 ? "+" : "") + x.subs}</div></div>
        <div class="metric"><label>CTR</label><div class="val num">${x.ctr == null ? "—" : Number(x.ctr).toFixed(1) + "%"}</div></div>
        <div class="metric"><label>Decision</label><div class="val">${esc(x.decision === "UNDECIDED" ? "Undecided" : x.decision)}</div></div>
      </div>

      <div class="card" style="padding:14px">
        <h2 style="font-size:14px;margin:0 0 10px">Record actual result</h2>
        <form class="form" id="experimentResultForm" data-exp="${x.id}">
          <label>Status <select name="status"><option ${x.status === "Draft" ? "selected" : ""}>Draft</option><option ${x.status === "Ready" ? "selected" : ""}>Ready</option><option ${x.status === "Published" ? "selected" : ""}>Published</option></select></label>
          <label>Published date <input name="publishedAt" type="date" value="${esc(x.publishedAt || "")}" /></label>
          <div class="grid2">
            <label>24h views <input name="v24" type="number" min="0" value="${x.v24 ?? ""}" /></label>
            <label>7d views <input name="v7" type="number" min="0" value="${x.v7 ?? ""}" /></label>
            <label>Retention % <input name="retention" type="number" min="0" max="100" step="0.1" value="${x.retention ?? ""}" /></label>
            <label>Subscriber gain <input name="subs" type="number" value="${x.subs ?? ""}" /></label>
            <label>CTR % <input name="ctr" type="number" min="0" max="100" step="0.1" value="${x.ctr ?? ""}" /></label>
          </div>
          <label>Result summary <textarea name="result" rows="2">${esc(x.result || "")}</textarea></label>
          <label>What did we learn? <textarea name="lesson" rows="3">${esc(x.lesson || "")}</textarea></label>
          <label>Next test <textarea name="next" rows="2">${esc(x.next || "")}</textarea></label>
          <label>Decision
            <select name="decision">
              <option value="UNDECIDED" ${x.decision === "UNDECIDED" ? "selected" : ""}>Undecided</option>
              <option ${x.decision === "GO" ? "selected" : ""}>GO</option>
              <option ${x.decision === "TEST" ? "selected" : ""}>TEST</option>
              <option ${x.decision === "HOLD" ? "selected" : ""}>HOLD</option>
            </select>
          </label>
          <button class="btn primary" type="submit">Save experiment result</button>
        </form>
      </div>
    `;
  }

  function videosPage() {
    const gate = workflowGate();
    if (gate) return gate;
    const published = state.experiments.filter((item) => item.status === "Published");
    return `<p class="sub">Published creator experiments. YouTube Creator Analytics is not connected yet, so these are the real results you entered manually.</p>
      ${published.length ? `<div class="card">${published.map((x) => `<div class="opp" style="grid-template-columns:1fr auto">
        <div><div class="t">${esc(x.name)}</div>
        <div class="meta">${esc(x.publishedAt || "date not recorded")} · ${esc(x.format)} · 24h ${x.v24 == null ? "—" : fmt(x.v24)} · 7d ${x.v7 == null ? "—" : fmt(x.v7)} · ${x.subs == null ? "—" : (x.subs >= 0 ? "+" : "") + x.subs + " subs"} · ${x.retention == null ? "—" : Number(x.retention).toFixed(1) + "% retention"}</div></div>
        <div><a href="#/experiment/${x.id}">EXP-${String(x.id).padStart(3, "0")}</a> <span class="badge ${String(x.decision || "").toLowerCase()}">${esc(x.decision === "UNDECIDED" ? "Undecided" : x.decision)}</span></div>
      </div>`).join("")}</div>` : `<div class="empty"><h3>No published experiments yet.</h3><p>When you publish an experiment and save its result, it will appear here.</p><button class="btn primary" data-go="/lab">Open Experiments</button></div>`}`;
  }

  function patterns() {
    if (state.patternsLoading && !state.patternsData) {
      return `<div class="card" style="padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
    }
    if (state.patternsError && !state.patternsData) {
      return `<div class="empty"><h3>Couldn't load persisted patterns</h3><p>${esc(state.patternsError)}</p><button class="btn primary" id="retryPatterns">Retry</button></div>`;
    }

    const p = state.patternsData;
    if (!p) {
      return `<div class="empty"><h3>Loading real patterns…</h3><p>Patterns are now calculated from persisted research rather than mock examples.</p></div>`;
    }

    const dataset = p.dataset || {};
    const topics = Array.isArray(p.topics) ? p.topics : [];
    const types = Array.isArray(p.contentTypes) ? p.contentTypes : [];
    const terms = Array.isArray(p.titleSignals) ? p.titleSignals : [];
    const growth = Array.isArray(p.actualGrowthLeaders) ? p.actualGrowthLeaders : [];

    return `
      <p class="sub">Repeated signals calculated from Christina Lab's persisted YouTube research. No invented hook labels or fake percentages.</p>

      <div class="metrics">
        <div class="metric"><label>Public Videos Observed</label><div class="val num">${fmt(dataset.videosTracked || 0)}</div><div class="sec">all persisted research videos</div></div>
        <div class="metric"><label>Metric Snapshots</label><div class="val num">${fmt(dataset.snapshotsStored || 0)}</div><div class="sec">timestamped observations</div></div>
        <div class="metric"><label>Analyzed Search Results</label><div class="val num">${fmt(dataset.analyzedCandidates || 0)}</div><div class="sec">Discover candidates with stored scores</div></div>
        <div class="metric"><label>Measured Growth Histories</label><div class="val num">${fmt(dataset.growthPairs || 0)}</div><div class="sec">videos with 2+ snapshots</div></div>
      </div>

      <div class="grid2">
        <div class="card">
          <div class="card-h"><h2>Search Topic Signals</h2><p>Based on persisted Discover searches. More different queries = a more useful comparison.</p></div>
          ${topics.length
            ? topics.map((row) => `<div class="rank"><span>${esc(row.topic)}</span><span>${fmt(row.videos)} analyzed videos</span><span>avg opp ${row.avgOpportunity == null ? "—" : Number(row.avgOpportunity).toFixed(1)}</span><span class="outlier">${row.medianOutlier == null ? "—" : Number(row.medianOutlier).toFixed(1) + "× median"}</span></div>`).join("") +
              (topics.length < 3 ? `<div class="meta" style="padding:10px 14px">Only ${topics.length} persisted search topic${topics.length === 1 ? "" : "s"} so far. Try distinct searches such as <b>AI tools</b>, <b>trading journal</b>, <b>copy trading</b>, and <b>build in public</b> to make cross-topic patterns more informative.</div>` : "")
            : `<div class="empty"><p>No persisted search-topic pattern yet. Run distinct Discover searches such as AI tools, trading journal, copy trading, and build in public.</p></div>`}
        </div>

        <div class="card">
          <div class="card-h"><h2>Content Type Patterns</h2><p>Real latest metrics by Short, Long-form, and Livestream cohorts.</p></div>
          ${types.length
            ? types.map((row) => `<div class="rank"><span>${esc(row.type)}</span><span>${fmt(row.videos)} videos · ${fmt(row.growthSampleSize || 0)} growth histories</span><span>median ${fmt(row.medianLatestViews)} views · ${Number(row.medianEngagement || 0).toFixed(2)}% eng</span><span>${row.growthSampleSize ? "median " + fmt(row.medianActualGrowthPerHour) + "/h · top quartile " + fmt(row.topQuartileActualGrowthPerHour) + "/h" : "growth history pending"}</span></div>
              ${row.growthSampleSize ? `<div class="meta" style="padding:0 14px 8px">${row.positiveGrowthShare == null ? "—" : Number(row.positiveGrowthShare).toFixed(1) + "%"} of measured histories had positive view growth.</div>` : ""}`).join("")
            : `<div class="empty"><p>No content-type observations yet.</p></div>`}
        </div>
      </div>

      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Repeated Title Signals</h2><p>Creative patterns from analyzed Discover candidates only — baseline/channel-history uploads are excluded. Signals must repeat across at least two different channels, with SEO/noise filtering and phrase normalization applied.</p></div>
        ${terms.length
          ? terms.map((row) => `<div class="rank"><span><b>${esc(row.term)}</b> <span class="badge">${row.termType === "phrase" ? "Phrase" : "Specific word"}</span></span><span>${fmt(row.videos)} analyzed titles · ${fmt(row.channels)} channels</span><span>${fmt(row.opportunitySampleSize || 0)} scored candidates</span><span>avg opp ${row.avgOpportunity == null ? "—" : Number(row.avgOpportunity).toFixed(1)}</span></div>`).join("")
          : `<div class="empty"><p>No sufficiently specific cross-channel pattern has repeated among analyzed Discover candidates yet.</p></div>`}
      </div>

      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Actual Growth Leaders</h2><p>Only measured growth between stored observations — no 24h extrapolation.</p></div>
        ${growth.length
          ? `<div class="rank" style="color:var(--dim)"><span>Video</span><span>Snapshots</span><span>Growth</span><span>Actual pace</span></div>` +
            growth.map((row) => `<div class="rank"><span>${esc(row.title)}</span><span>${row.snapshotCount}</span><span class="num">+${fmt(row.deltaViews)}${row.growthPercent == null ? "" : " · +" + row.growthPercent + "%"}</span><span class="num">${fmt(row.actualViewsHour)}/h</span></div>`).join("")
          : `<div class="empty"><p>No videos have two snapshots yet. Revisit research later to create real growth pairs.</p></div>`}
      </div>

      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="font-size:14px;margin:0 0 6px">How to read this page</h2>
        <p class="meta" style="margin:0">Creative title patterns use analyzed Discover candidates only; channel-history videos remain available for baselines and growth intelligence but cannot contaminate creative pattern discovery. Multi-word phrases rank ahead of single words and still require at least two different channels.</p>
      </div>`;
  }

  function analytics() {
    return `
      <p class="sub">What the market rewards vs what actually works for Christina.</p>
      <div class="grid2">
        <div class="card"><div class="card-h"><h2>Market Signals</h2><p>What appears to work broadly.</p></div>
          ${[
            ["AI challenge videos", "Strong"],
            ["Trading mistakes", "Moderate"],
            ["Copy trading contradictions", "Strong"],
            ["Build in public", "Interesting"],
          ]
            .map((r) => `<div class="rank"><span>${r[0]}</span><span></span><span></span><span class="badge strong">${r[1]}</span></div>`)
            .join("")}
        </div>
        <div class="card"><div class="card-h"><h2>Christina Signals</h2><p>What appears to work for this creator.</p></div>
          ${[
            ["AI challenge videos", "TEST"],
            ["Trading mistakes", "GO"],
            ["Copy trading contradictions", "GO"],
            ["Build in public", "HOLD"],
          ]
            .map((r) => `<div class="rank"><span>${r[0]}</span><span></span><span></span><span class="badge ${r[1].toLowerCase()}">${r[1]}</span></div>`)
            .join("")}
        </div>
      </div>
      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Average 24h views by topic</h2></div>
        <div class="chart">${bars([
          ["Copy", 7420],
          ["Risk", 9180],
          ["AI", 4120],
          ["Signals", 6800],
        ])}</div>
      </div>`;
  }
  function bars(rows) {
    const m = Math.max(...rows.map((r) => r[1]));
    return rows
      .map(
        (r) =>
          `<div style="display:flex;align-items:center;gap:8px;padding:4px 14px;font-size:12px"><span style="width:70px">${r[0]}</span><div style="height:10px;background:#2a3d63;width:${(r[1] / m) * 70}%"></div><span class="num">${fmt(r[1])}</span></div>`
      )
      .join("");
  }

  function watchlists() {
    return `
      <p class="sub">Channels and topics worth scanning again.</p>
      <div class="tabs">
        <button class="btn ${state.watchTab === "channels" ? "primary" : ""}" data-tab="channels">Channels</button>
        <button class="btn ${state.watchTab === "topics" ? "primary" : ""}" data-tab="topics">Topics</button>
      </div>
      ${
        state.watchTab === "channels"
          ? `<div class="card">${[
              ["SignalDesk", "84K", 3, 2, "14.5K", "Copy trading 6.8×", "Watching"],
              ["BuildFast", "61K", 4, 3, "17.6K", "AI 24h 8.4×", "Hot"],
              ["RiskDesk", "121K", 2, 1, "16.6K", "Mistakes 2.4×", "Steady"],
            ]
              .map(
                (r) => `<div class="opp" style="grid-template-columns:40px 1fr">
                <img class="avatar" src="https://api.dicebear.com/7.x/identicon/svg?seed=${r[0]}" alt="${r[0]} channel avatar" />
                <div><div class="t">${r[0]}</div><div class="meta">${r[1]} subs · ${r[2]} recent uploads · ${r[3]} outliers · baseline ${r[4]} · ${r[5]} · ${r[6]}</div></div>
              </div>`
              )
              .join("")}</div>`
          : `<div class="card">${[
              ["Copy Trading", 18, 5, "High", "2h ago"],
              ["AI building", 22, 7, "Extreme", "1h ago"],
              ["Creator growth", 14, 4, "High", "4h ago"],
            ]
              .map((r) => `<div class="rank"><span>${r[0]}</span><span>${r[1]} analyzed</span><span>${r[2]} outliers</span><span>${r[3]} · ${r[4]}</span></div>`)
              .join("")}</div>`
      }`;
  }

  function settings() {
    return `
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">General</h2>
        <p class="meta">Workspace name: Christina Lab · Language: English</p>
      </div>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">YouTube Data API</h2>
        <p class="meta">Status: ${state.connected ? "Connected (demo)" : "Not connected"}</p>
        <p>Connect YouTube later to retrieve real research data.</p>
        <button class="btn primary" id="yt1">${state.connected ? "Disconnect" : "Connect"}</button>
      </div>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">YouTube Creator Analytics</h2>
        <p class="meta">Status: Not connected</p>
        <p>Connect your own channel to automatically import experiment performance.</p>
        <button class="btn" id="yt2">Connect</button>
      </div>
      <div class="card" style="padding:14px">
        <h2 style="font-size:14px">Research preferences</h2>
        <form class="form" id="prefs">
          <label>Primary niches <input name="n" value="${state.niches}" /></label>
          <label>Content types <select><option>All</option><option>Shorts</option><option>Long-form</option></select></label>
          <label>Minimum views <input type="number" value="5000" /></label>
          <label>Preferred video age <select><option>7 days</option><option>30 days</option></select></label>
          <button class="btn primary" type="submit">Save preferences</button>
        </form>
      </div>`;
  }

  function render() {
    const path = state.route.split("?")[0] || "/";
    let title = "Dashboard";
    let body = "";
    if (path === "/" || path === "") {
      title = "Dashboard";
      body = dash();
    } else if (path === "/discover") {
      title = "Discover";
      body = discover();
    } else if (path.startsWith("/video/")) {
      title = "Video analysis";
      body = analysis(path.slice(7));
    } else if (path === "/saved") {
      title = "Saved Research";
      body = saved();
    } else if (path === "/ideas") {
      title = "Ideas";
      body = ideas();
    } else if (path === "/lab") {
      title = "Experiments";
      body = lab();
    } else if (path.startsWith("/experiment/")) {
      title = "Experiment";
      body = experiment(path.slice(12));
    } else if (path === "/videos") {
      title = "My Videos";
      body = videosPage();
    } else if (path === "/patterns") {
      title = "Patterns";
      body = patterns();
    } else if (path === "/analytics") {
      title = "Analytics";
      body = analytics();
    } else if (path === "/watchlists") {
      title = "Watchlists";
      body = watchlists();
    } else if (path === "/settings") {
      title = "Settings";
      body = settings();
    } else {
      title = "Not found";
      body = `<div class="empty"><h3>That page isn't here.</h3><button class="btn" data-go="/">Back to dashboard</button></div>`;
    }
    $("app").innerHTML = layout(title, body);
    bind();
  }

  function bind() {
    const menu = document.getElementById("menu");
    const sb = document.getElementById("sb");
    const dbg = document.getElementById("dbg");
    if (menu) {
      menu.onclick = () => {
        sb.classList.toggle("open");
        dbg.classList.toggle("show");
      };
    }
    if (dbg) dbg.onclick = () => {
      sb.classList.remove("open");
      dbg.classList.remove("show");
    };
    document.getElementById("gs")?.addEventListener("focus", openPalette);
    document.querySelectorAll("[data-act]").forEach((b) => {
      b.onclick = () => {
        const id = b.dataset.id;
        if (b.dataset.act === "save") saveVideo(id);
        if (b.dataset.act === "unsave") unsave(id);
        if (b.dataset.act === "analyze") navigate("/video/" + id);
        if (b.dataset.act === "idea") ideaFrom(id);
      };
    });
    document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => navigate(b.dataset.go)));
    document.querySelectorAll("[data-sug]").forEach((b) => {
      b.onclick = () => runDiscoverSearch(b.dataset.sug);
    });
    document.querySelectorAll("[data-view]").forEach((b) => {
      b.onclick = () => {
        state.savedView = b.dataset.view;
        render();
      };
    });
    document.querySelectorAll("[data-tab]").forEach((b) => {
      b.onclick = () => {
        state.watchTab = b.dataset.tab;
        render();
      };
    });
    const ds = document.getElementById("ds");
    if (ds)
      ds.onsubmit = (e) => {
        e.preventDefault();
        runDiscoverSearch(ds.q.value);
      };
    const reset = document.getElementById("resetF");
    if (reset)
      reset.onclick = () => {
        state.filters = { time: "7d", type: "All", minViews: 0, sort: "opp", topic: "All" };
        state.query = "";
        state.searched = false;
        state.liveVideos = [];
        state.apiError = "";
        try { sessionStorage.removeItem(LIVE_SESSION_KEY); } catch (_) {}
        render();
      };
    ["ftime", "ftype", "fsort", "ftopic", "fmin"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.onchange = () => {
        if (id === "ftime") state.filters.time = el.value;
        if (id === "ftype") state.filters.type = el.value;
        if (id === "fsort") state.filters.sort = el.value;
        if (id === "ftopic") state.filters.topic = el.value;
        if (id === "fmin") state.filters.minViews = +el.value || 0;
        if (id === "ftime" && state.searched) runDiscoverSearch(state.query);
        else if (state.searched) render();
      };
    });
    document.getElementById("newIdea")?.addEventListener("click", () => openIdeaModal(null));
    document.getElementById("newExperiment")?.addEventListener("click", () => openExperimentModal(null));
    document.querySelectorAll("[data-create-exp]").forEach((button) => {
      button.onclick = () => {
        const idea = state.ideas.find((item) => String(item.id) === String(button.dataset.createExp));
        if (idea) openExperimentModal(idea);
      };
    });
    document.querySelectorAll(".dec").forEach((s) => {
      s.onchange = async () => {
        const experimentId = Number(s.dataset.exp);
        try {
          await apiJson("/api/experiments/" + experimentId, {
            method: "PATCH",
            body: { decision: s.value },
          });
          state.workflowLoaded = false;
          await loadWorkflowData(true);
          toast("Decision changed to " + (s.value === "UNDECIDED" ? "Undecided" : s.value));
        } catch (error) {
          toast(error?.message || "Could not update decision");
        }
      };
    });
    document.getElementById("noteForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const f = new FormData(form);
      const notes = { why: f.get("why"), adapt: f.get("adapt"), angle: f.get("angle") };
      try {
        const item = await apiJson("/api/research/" + encodeURIComponent(form.dataset.vid), {
          method: "PUT",
          body: notes,
        });
        state.notes[form.dataset.vid] = notes;
        state.saved.add(form.dataset.vid);
        const index = state.savedResearch.findIndex((row) => (row.videoId || row.id) === form.dataset.vid);
        if (index >= 0) state.savedResearch[index] = item;
        else state.savedResearch.unshift(item);
        toast("Research notes saved");
        render();
      } catch (error) {
        toast(error?.message || "Could not save research notes");
      }
    });
    document.getElementById("experimentResultForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const f = new FormData(form);
      const numberOrNull = (name) => {
        const raw = String(f.get(name) ?? "").trim();
        return raw === "" ? null : Number(raw);
      };
      try {
        await apiJson("/api/experiments/" + Number(form.dataset.exp), {
          method: "PATCH",
          body: {
            status: f.get("status"),
            publishedAt: String(f.get("publishedAt") || "").trim() || null,
            v24: numberOrNull("v24"),
            v7: numberOrNull("v7"),
            retention: numberOrNull("retention"),
            subs: numberOrNull("subs"),
            ctr: numberOrNull("ctr"),
            result: f.get("result"),
            lesson: f.get("lesson"),
            next: f.get("next"),
            decision: f.get("decision"),
          },
        });
        state.workflowLoaded = false;
        await loadWorkflowData(true);
        toast("Experiment result saved");
      } catch (error) {
        toast(error?.message || "Could not save experiment result");
      }
    });
    document.getElementById("yt1")?.addEventListener("click", () => {
      state.connected = !state.connected;
      toast(state.connected ? "YouTube connected (demo)" : "Disconnected");
      render();
    });
    document.getElementById("yt2")?.addEventListener("click", () => toast("Creator Analytics stays a placeholder in this demo"));
    document.getElementById("prefs")?.addEventListener("submit", (e) => {
      e.preventDefault();
      state.niches = new FormData(e.target).get("n");
      toast("Preferences saved");
    });
    document.querySelectorAll(".icard").forEach((card) => {
      card.ondragstart = (e) => e.dataTransfer.setData("id", card.dataset.idea);
    });
    document.querySelectorAll(".kcol").forEach((col) => {
      col.ondragover = (e) => e.preventDefault();
      col.ondrop = async (e) => {
        e.preventDefault();
        const id = Number(e.dataTransfer.getData("id"));
        const idea = state.ideas.find((item) => Number(item.id) === id);
        if (!idea || idea.status === col.dataset.col) return;
        const previous = idea.status;
        idea.status = col.dataset.col;
        render();
        try {
          await apiJson("/api/ideas/" + id, {
            method: "PATCH",
            body: { status: col.dataset.col },
          });
          state.workflowLoaded = false;
          await loadWorkflowData(true);
          toast("Idea moved to " + col.dataset.col);
        } catch (error) {
          idea.status = previous;
          render();
          toast(error?.message || "Could not move idea");
        }
      };
    });
    document.getElementById("retry")?.addEventListener("click", () => {
      runDiscoverSearch(state.query);
    });
    document.getElementById("retryDashboard")?.addEventListener("click", () => {
      state.dashboardData = null;
      loadDashboardData(true);
    });
    document.getElementById("retryPatterns")?.addEventListener("click", () => {
      state.patternsData = null;
      loadPatternsData(true);
    });
    document.getElementById("retryWorkflow")?.addEventListener("click", () => {
      state.workflowLoaded = false;
      loadWorkflowData(true);
    });
  }

  render();
  loadRouteData(state.route);
})();

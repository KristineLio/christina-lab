/*
 * CHRISTINA LAB — FRONTEND WORKFLOW / UI CONTROLLER
 *
 * This file implements the product workflow and interactive UI:
 * Dashboard, Discover, Video Analysis, Saved Research, Ideas,
 * Experiments, My Videos, Patterns, Analytics, Watchlists, and Settings.
 *
 * Today it reads demo data from window.CL_DATA (data.js) and keeps most
 * user changes in browser memory. As the backend is built, these in-memory
 * operations will be replaced by API calls while preserving the same UI flow.
 */

(function () {
  const D = window.CL_DATA;
  const $ = (id) => document.getElementById(id);
  const API_BASE =
    window.CL_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1") && location.port !== "8000"
      ? "http://127.0.0.1:8000"
      : "");

  const LIVE_SESSION_KEY = "christinaLab.liveResearch.v1";

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
    saved: new Set(D.savedSeed),
    ideas: D.ideas.map((x) => ({ ...x })),
    experiments: D.experiments.map((x) => ({ ...x })),
    notes: {},
    collections: "All",
    savedView: "grid",
    watchTab: "channels",
    loading: false,
    error: false,
    connected: false,
    niches: "trading, AI tools, build in public",
    liveVideos: restoredLiveSession?.videos || [],
    apiError: "",
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
    return allKnownVideos().find((v) => v.id === id);
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

  function navigate(path) {
    state.route = path;
    location.hash = path === "/" ? "" : path;
    render();
  }

  window.addEventListener("hashchange", () => {
    state.route = location.hash.slice(1) || "/";
    render();
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

  function saveVideo(id) {
    state.saved.add(id);
    toast("Saved to Research");
    render();
  }
  function unsave(id) {
    state.saved.delete(id);
    toast("Video removed");
    render();
  }
  function ideaFrom(vid) {
    const v = videoById(vid);
    openIdeaModal(v);
  }

  function openIdeaModal(src) {
    const m = $("modal");
    m.hidden = false;
    m.innerHTML = `<div class="modal">
      <h2 style="margin:0 0 12px;font-size:16px">Create idea</h2>
      <form class="form" id="ideaForm">
        <label>Working title <input name="title" required value="${src ? esc("Why " + src.title.replace(/^Why /, "")) : ""}" /></label>
        <label>Hook <input name="hook" placeholder="The first line viewers hear" /></label>
        <label>Topic <input name="topic" value="${src ? esc(src.topic) : ""}" /></label>
        <label>Content type <select name="type"><option>Short</option><option>Long-form</option></select></label>
        <label>Angle <input name="angle" /></label>
        <label>Audience <input name="audience" /></label>
        <label>Why do you think this video will work?
          <textarea name="hypothesis" rows="3">Several recent videos using this structure are outperforming channel baselines. I want to test it without copying the original.</textarea>
        </label>
        <label>Notes <textarea name="notes" rows="2"></textarea></label>
        <label>Priority <select name="priority"><option>High</option><option>Med</option><option>Low</option></select></label>
        <label>Status <select name="status"><option>Inbox</option><option>Researching</option><option>Ready</option></select></label>
        <div class="actions"><button class="btn ghost" type="button" id="cancelM">Cancel</button><button class="btn primary" type="submit">Create idea</button></div>
      </form>
    </div>`;
    $("cancelM").onclick = () => (m.hidden = true);
    m.onclick = (e) => {
      if (e.target === m) m.hidden = true;
    };
    $("ideaForm").onsubmit = (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      state.ideas.unshift({
        id: "idea-" + Date.now(),
        title: f.get("title"),
        hook: f.get("hook"),
        topic: f.get("topic"),
        type: f.get("type"),
        sources: src ? 1 : 0,
        priority: f.get("priority"),
        created: "Today",
        status: f.get("status"),
        hypothesis: f.get("hypothesis"),
        angle: f.get("angle"),
        audience: f.get("audience"),
      });
      m.hidden = true;
      toast("Idea created");
      navigate("/ideas");
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
      list = list.filter((v) => v.type === (state.filters.type === "Shorts" ? "Short" : "Long-form"));
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
    const opps = D.videos.slice(0, 5);
    const pipe = ["Inbox", "Researching", "Ready", "Recorded", "Published"];
    return `
      <div class="loop">Discover → Analyze → Save → Create Idea → Publish → Measure → <b>Learn</b></div>
      <div style="font-size:22px;font-weight:600">Good afternoon, Christina</div>
      <p class="sub">Here are today's strongest content signals.</p>
      <div class="metrics">
        <div class="metric"><label>Videos Scanned</label><div class="val num">1,284</div><div class="sec">+186 today</div></div>
        <div class="metric"><label>Outliers Found</label><div class="val num">37</div><div class="sec">12 strong</div></div>
        <div class="metric"><label>Saved Research</label><div class="val num">${state.saved.size}</div><div class="sec">5 added this week</div></div>
        <div class="metric"><label>Active Experiments</label><div class="val num">6</div><div class="sec">2 awaiting results</div></div>
      </div>
      <div class="card">
        <div class="card-h"><h2>Today's Opportunities</h2><p>Videos showing unusually strong early performance.</p></div>
        ${opps.map((v) => oppRow(v)).join("")}
      </div>
      <div class="grid2">
        <div class="card">
          <div class="card-h"><h2>Fastest Growing</h2></div>
          <div class="rank" style="color:var(--dim)"><span>Video</span><span>Age</span><span>Views/hour</span><span>Momentum</span></div>
          ${D.videos
            .slice()
            .sort((a, b) => b.viewsHour - a.viewsHour)
            .slice(0, 5)
            .map(
              (v) =>
                `<div class="rank"><span>${v.title}</span><span>${v.age}</span><span class="num">${fmt(v.viewsHour)}</span><span>${v.momentum}</span></div>`
            )
            .join("")}
        </div>
        <div class="card">
          <div class="card-h"><h2>Biggest Outliers</h2></div>
          <div class="rank" style="color:var(--dim)"><span>Video</span><span>Channel</span><span>Baseline</span><span>Outlier</span></div>
          ${D.videos
            .slice()
            .sort((a, b) => b.outlier - a.outlier)
            .slice(0, 5)
            .map(
              (v) =>
                `<div class="rank"><span>${v.title}</span><span>${v.channel}</span><span class="num">${fmt(v.baseline)}</span><span class="outlier num">${v.outlier == null ? "Baseline pending" : v.outlier.toFixed(1) + "×"}</span></div>`
            )
            .join("")}
        </div>
      </div>
      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Content Pipeline</h2></div>
        <div class="pipe">
          ${pipe
            .map((s) => {
              const n = state.ideas.filter((i) => i.status === s).length;
              return `<div class="col"><div class="sec">${s}</div><div class="n num">${n}</div></div>`;
            })
            .join("")}
        </div>
      </div>
      <div class="card" style="margin-top:12px">
        <div class="card-h"><h2>Recent Experiments</h2></div>
        ${state.experiments
          .slice(0, 4)
          .map(
            (e) =>
              `<div class="opp" style="grid-template-columns:1fr auto">
                <div><div class="t">${e.name}</div><div class="meta">${e.status} · 24h ${e.v24 ? fmt(e.v24) : "—"} views</div></div>
                <span class="badge ${e.decision.toLowerCase()}">${e.decision}</span>
              </div>`
          )
          .join("")}
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
          <option ${state.filters.type === "Long-form" ? "selected" : ""}>Long-form</option>
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
        ? `<div class="meta" style="margin:-4px 0 12px">Live YouTube Data · Opportunity Score v1.1 combines age-adjusted outlier, 24h run rate, engagement, views/subscriber, freshness, and baseline confidence with explicit guardrails.</div>`
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
                    <td><div class="t">${esc(v.title)}</div><div class="meta">${esc(v.channel)} · ${fmt(v.subs)} subs · ${esc(v.duration)} · ${esc(v.topic)}</div></td>
                    <td>${esc(v.age)}</td>
                    <td class="num">${fmt(v.views)}</td>
                    <td class="num tip" title="Current average views/hour × 24. This is an extrapolated pace, not actual views received in 24 hours.">${fmt(v.viewsDay)}</td>
                    <td class="num">${ratioLabel(v.viewsSub)}</td>
                    <td class="num">${Number(v.engagement || 0).toFixed(2)}%</td>
                    <td>${v.outlier == null
                      ? `<span class="meta">Need more channel history</span>`
                      : `<span class="outlier num tip" title="Average views/hour for this video divided by the median average views/hour of recent channel uploads.">${v.outlier.toFixed(1)}×</span>
                         <div class="meta">expected ~${fmt(v.baseline)} by ${esc(v.age)} · ${v.baselineSampleSize} ${v.baselineScope === "same-format" ? "same-format" : "recent"} videos</div>`}</td>
                    <td class="num tip" title="Explainable Opportunity Score v1.1. Open Analyze to see every component and guardrail.">${v.opportunity == null ? "—" : "<b>" + v.opportunity + "/100</b>"}</td>
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
    const baselineScope =
      v.baselineScope === "same-format"
        ? "recent same-format uploads"
        : v.baselineScope === "all-formats"
        ? "recent uploads across formats"
        : "recent uploads";
    const baselineReady = v.outlier != null && v.baseline != null;
    const components = Array.isArray(v.opportunityComponents) ? v.opportunityComponents : [];
    const guardrails = Array.isArray(v.opportunityGuardrails) ? v.opportunityGuardrails : [];

    return `
      <div class="video-head">
        ${videoImg(v, "thumb")}
        <div>
          <div class="t" style="font-size:18px">${esc(v.title)}</div>
          <div class="meta">${esc(v.channel)} · ${esc(v.published)} · ${esc(v.duration)} · ${esc(v.type)}</div>
          <div class="actions" style="margin-top:12px">
            <a class="btn" href="${esc(v.youtubeUrl)}" target="_blank" rel="noreferrer">Open on YouTube</a>
            <button class="btn" data-act="${state.saved.has(v.id) ? "unsave" : "save"}" data-id="${esc(v.id)}">${state.saved.has(v.id) ? "Saved" : "Save Research"}</button>
            <button class="btn primary" data-act="idea" data-id="${esc(v.id)}">Turn into Idea</button>
          </div>
        </div>
      </div>

      <div class="metrics">
        <div class="metric"><label>Opportunity Score</label><div class="val num">${v.opportunity == null ? "—" : v.opportunity + "/100"}</div><div class="sec">Explainable v1.1 score</div></div>
        <div class="metric"><label>Views</label><div class="val num">${Number(v.views || 0).toLocaleString()}</div></div>
        <div class="metric"><label class="tip" title="Current average views/hour × 24. This is an extrapolated pace, not actual views received in 24 hours.">24h Run Rate</label><div class="val num">${fmt(v.viewsDay)}</div></div>
        <div class="metric"><label>Engagement Rate</label><div class="val num">${Number(v.engagement || 0).toFixed(2)}%</div></div>
        <div class="metric"><label>Views / Subscriber</label><div class="val num">${ratioLabel(v.viewsSub)}</div><div class="sec">${v.viewsSub == null ? "Subscriber count unavailable" : ratioPercentLabel(v.viewsSub) + " of subscriber count"}</div></div>
        <div class="metric"><label class="tip" title="Average views/hour for this video divided by the median average views/hour of recent channel uploads.">Age-adjusted Outlier</label><div class="val num outlier">${baselineReady ? v.outlier.toFixed(1) + "×" : "—"}</div></div>
        <div class="metric"><label>Expected Views at This Age</label><div class="val num">${baselineReady ? fmt(v.baseline) : "—"}</div><div class="sec">${baselineReady ? "median " + fmt(v.baselineVelocity) + "/hour · " + v.baselineSampleSize + " " + baselineScope : "Need at least 3 usable recent uploads"}</div></div>
      </div>

      <div class="card" style="margin-top:12px;padding:14px">
        <h2 style="margin:0 0 4px;font-size:14px">Why Opportunity = ${v.opportunity == null ? "—" : v.opportunity + "/100"}</h2>
        <p class="meta" style="margin-top:0">No hidden AI judgment: these points come directly from the signals below. Component points total ${v.opportunityRaw ?? "—"} before guardrails.</p>
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

      <div class="card why" style="margin-top:12px">
        <h2 style="margin:0 0 8px;font-size:14px">Signal details</h2>
        <ul>
          ${baselineReady
            ? `<li><b>${v.outlier.toFixed(1)}× age-adjusted outlier:</b> ${fmt(v.views)} current views vs ~${fmt(v.baseline)} expected by ${esc(v.age)} from the channel's recent median view velocity.</li>`
            : `<li>There is not enough usable recent channel history to calculate a stable median baseline yet.</li>`}
          <li>${fmt(v.viewsDay)} projected 24h run rate from the video's current average pace; this is not actual 24-hour views.</li>
          <li>${Number(v.engagement || 0).toFixed(2)}% public engagement from likes + comments relative to views.</li>
          <li>${v.viewsSub == null ? "Subscriber count is hidden or unavailable." : ratioLabel(v.viewsSub) + " views/subscriber, equal to " + ratioPercentLabel(v.viewsSub) + " of the current subscriber count."}</li>
        </ul>
        <p class="meta" style="margin-bottom:0">Opportunity Score v1.1 and the age-adjusted outlier are Christina Lab derived metrics from public YouTube data, not official YouTube metrics.</p>
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
          ? related.map((r) => `<div class="opp">${videoImg(r)}<div><div class="t">${esc(r.title)}</div><div class="meta">${esc(r.channel)} · ${fmt(r.viewsDay)} / 24h pace</div></div><span class="num">${r.opportunity == null ? "—" : r.opportunity + "/100"}</span></div>`).join("")
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
    if (v.source === "youtube") return liveAnalysis(v, related, n);
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

  function saved() {
    const items = allKnownVideos().filter((v) => state.saved.has(v.id));
    return `
      <p class="sub">Your library of interesting videos, formats, hooks and opportunities.</p>
      <div class="filters">
        <button class="btn ${state.savedView === "grid" ? "primary" : ""}" data-view="grid">Grid</button>
        <button class="btn ${state.savedView === "table" ? "primary" : ""}" data-view="table">Table</button>
        <select id="scol"><option>All</option><option>Trading Psychology</option><option>RiskDesk Ideas</option><option>Build in Public</option><option>AI Tools</option><option>YouTube Growth</option></select>
      </div>
      ${
        items.length === 0
          ? `<div class="empty"><h3>No saved research yet.</h3><p>Discover interesting videos and save the strongest opportunities here.</p><button class="btn primary" data-go="/discover">Explore Videos</button></div>`
          : state.savedView === "grid"
          ? `<div class="grid2">${items
              .map(
                (v) => `<div class="card" style="padding:12px">${videoImg(v)}
                <div class="t" style="margin-top:8px">${v.title}</div>
                <div class="meta">${v.channel} · ${v.topic} · saved recently</div>
                <div class="actions" style="margin-top:8px">
                  <span class="outlier">${v.outlier == null ? "Baseline pending" : v.outlier.toFixed(1) + "×"}</span>
                  <button class="btn" data-act="analyze" data-id="${v.id}">Open analysis</button>
                  <button class="btn primary" data-act="idea" data-id="${v.id}">Turn into Idea</button>
                  <button class="btn ghost" data-act="unsave" data-id="${v.id}">Remove</button>
                </div></div>`
              )
              .join("")}</div>`
          : `<div class="card"><table class="table"><thead><tr><th>Video</th><th>Outlier</th><th>Views</th><th></th></tr></thead><tbody>
            ${items
              .map(
                (v) => `<tr><td>${v.title}<div class="meta">${v.channel}</div></td><td class="outlier">${v.outlier == null ? "Baseline pending" : v.outlier.toFixed(1) + "×"}</td><td>${fmt(v.views)}</td>
                <td><button class="btn" data-act="unsave" data-id="${v.id}">Remove</button></td></tr>`
              )
              .join("")}</tbody></table></div>`
      }`;
  }

  function ideas() {
    const cols = ["Inbox", "Researching", "Ready", "Recorded", "Published", "Analyzing"];
    return `
      <p class="sub">Turn research findings into a content production pipeline.</p>
      <div class="actions" style="margin-bottom:12px"><button class="btn primary" id="newIdea">Create idea</button></div>
      <div class="kanban">
        ${cols
          .map((c) => {
            const cards = state.ideas.filter((i) => i.status === c);
            return `<div class="kcol" data-col="${c}"><h3>${c} · ${cards.length}</h3>
              ${cards
                .map(
                  (i) => `<div class="icard" draggable="true" data-idea="${i.id}">
                    <div class="t">${i.title}</div>
                    <div class="hook">${i.hook}</div>
                    <div class="meta">${i.topic} · ${i.type} · ${i.sources} sources · ${i.priority}</div>
                  </div>`
                )
                .join("")}
            </div>`;
          })
          .join("")}
      </div>`;
  }

  function lab() {
    const e = state.experiments;
    const pub = e.filter((x) => x.status === "Published").length;
    const avg = Math.round(e.filter((x) => x.v24).reduce((s, x) => s + x.v24, 0) / e.filter((x) => x.v24).length);
    const avgS = Math.round(e.filter((x) => x.subs).reduce((s, x) => s + x.subs, 0) / e.filter((x) => x.subs).length);
    return `
      <div style="font-size:20px;font-weight:600">Christina Lab</div>
      <p class="sub">Turn content ideas into measurable experiments.</p>
      <div class="metrics">
        <div class="metric"><label>Experiments</label><div class="val num">${e.length}</div></div>
        <div class="metric"><label>Published</label><div class="val num">${pub}</div></div>
        <div class="metric"><label>GO</label><div class="val num">${e.filter((x) => x.decision === "GO").length}</div></div>
        <div class="metric"><label>TEST</label><div class="val num">${e.filter((x) => x.decision === "TEST").length}</div></div>
        <div class="metric"><label>HOLD</label><div class="val num">${e.filter((x) => x.decision === "HOLD").length}</div></div>
        <div class="metric"><label>Average 24h Views</label><div class="val num">${fmt(avg)}</div></div>
        <div class="metric"><label>Average Subscriber Gain</label><div class="val num">+${avgS}</div></div>
      </div>
      <div class="card">
        <table class="table">
          <thead><tr><th>Experiment</th><th>Topic</th><th>Format</th><th>24h</th><th>7d</th><th>Ret.</th><th>Subs</th><th>Decision</th></tr></thead>
          <tbody>
            ${e
              .map(
                (x) => `<tr>
                  <td><a href="#/experiment/${x.id}">${x.id}</a><div class="meta">${x.name}</div></td>
                  <td>${x.topic}</td><td>${x.format}</td>
                  <td class="num">${x.v24 ? fmt(x.v24) : '<span class="dim">Not connected</span>'}</td>
                  <td class="num">${x.v7 ? fmt(x.v7) : "—"}</td>
                  <td>${x.retention ?? "—"}</td>
                  <td>${x.subs != null ? "+" + x.subs : "—"}</td>
                  <td>
                    <select class="dec" data-exp="${x.id}">
                      <option ${x.decision === "GO" ? "selected" : ""}>GO</option>
                      <option ${x.decision === "TEST" ? "selected" : ""}>TEST</option>
                      <option ${x.decision === "HOLD" ? "selected" : ""}>HOLD</option>
                    </select>
                  </td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
      <p class="sub">GO = strong evidence to scale. TEST = promising, need more runs. HOLD = not a priority yet. Decisions are yours — not AI certainty.</p>`;
  }

  function experiment(id) {
    const x = state.experiments.find((e) => e.id === id) || state.experiments[0];
    return `
      <p class="sub">${x.id} · ${x.status}</p>
      <h2 style="margin-top:0">${x.name}</h2>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <div class="meta">Hypothesis</div>
        <p>${x.hypothesis}</p>
        <div class="meta">Source research · original idea ${x.ideaId}</div>
      </div>
      <div class="metrics">
        <div class="metric"><label>24h views</label><div class="val num">${x.v24 ? fmt(x.v24) : "Not connected"}</div></div>
        <div class="metric"><label>7d views</label><div class="val num">${x.v7 ? fmt(x.v7) : "—"}</div></div>
        <div class="metric"><label>Retention</label><div class="val num">${x.retention ?? "—"}%</div></div>
        <div class="metric"><label>Subscribers</label><div class="val num">${x.subs != null ? "+" + x.subs : "—"}</div></div>
      </div>
      <div class="card why">
        <h2 style="font-size:14px;margin:0 0 8px">What did we learn?</h2>
        <p>${x.lesson || "Publish first, then write the learning."}</p>
        <div class="meta">Next test</div>
        <p>${x.next}</p>
        <label>Decision
          <select class="dec" data-exp="${x.id}">
            <option ${x.decision === "GO" ? "selected" : ""}>GO</option>
            <option ${x.decision === "TEST" ? "selected" : ""}>TEST</option>
            <option ${x.decision === "HOLD" ? "selected" : ""}>HOLD</option>
          </select>
        </label>
      </div>`;
  }

  function videosPage() {
    return `<p class="sub">Christina's published YouTube videos, tied to experiments.</p>
      <div class="card">${D.myVideos
        .map(
          (v) => `<div class="opp">
            ${img("Published video thumbnail for " + v.title)}
            <div><div class="t">${v.title}</div>
            <div class="meta">${v.date} · ${v.type} · ${fmt(v.views)} views · 24h ${fmt(v.v24)} · 7d ${fmt(v.v7)} · +${v.subs} subs · ${v.retention}% ret · CTR ${v.ctr}%</div></div>
            <div><a href="#/experiment/${v.exp}">${v.exp}</a> <span class="badge ${v.decision.toLowerCase()}">${v.decision}</span></div>
          </div>`
        )
        .join("")}</div>`;
  }

  function patterns() {
    return `
      <p class="sub">Repeated signals from market research and your own results.</p>
      <div class="grid2">
        <div class="card"><div class="card-h"><h2>Rising Topics</h2></div>
          ${[
            ["AI agents", "+42%"],
            ["Trading psychology", "+18%"],
            ["Build in public", "+31%"],
            ["Copy Trading", "+24%"],
          ]
            .map((r) => `<div class="rank"><span>${r[0]}</span><span></span><span></span><span class="outlier">${r[1]} mentions</span></div>`)
            .join("")}
        </div>
        <div class="card"><div class="card-h"><h2>Winning Hook Types</h2></div>
          ${["Contradiction", "Challenge", "Mistake", "Before / After", "Unexpected Result", "Question"]
            .map((h, i) => `<div class="rank"><span>${h}</span><span></span><span></span><span>${[92, 88, 81, 74, 70, 61][i]}</span></div>`)
            .join("")}
        </div>
      </div>
      <div class="card" style="margin-top:12px"><div class="card-h"><h2>Title Patterns</h2></div>
        ${[
          ["I built X in Y hours", 14, "6.1×", "TEST"],
          ["Why X doesn't work", 11, "5.4×", "GO"],
          ["X mistakes beginners make", 9, "4.2×", "GO"],
          ["I tested X for 30 days", 7, "4.8×", "TEST"],
        ]
          .map(
            (r) =>
              `<div class="rank"><span>${r[0]}</span><span>${r[1]} videos</span><span>avg outlier ${r[2]}</span><span class="badge ${r[3].toLowerCase()}">${r[3]} for Christina</span></div>`
          )
          .join("")}
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
    document.querySelectorAll(".dec").forEach((s) => {
      s.onchange = () => {
        const ex = state.experiments.find((e) => e.id === s.dataset.exp);
        if (ex) ex.decision = s.value;
        toast("Decision changed to " + s.value);
        render();
      };
    });
    document.getElementById("noteForm")?.addEventListener("submit", (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      state.notes[e.target.dataset.vid] = { why: f.get("why"), adapt: f.get("adapt"), angle: f.get("angle") };
      toast("Note saved");
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
      col.ondrop = (e) => {
        e.preventDefault();
        const id = e.dataTransfer.getData("id");
        const idea = state.ideas.find((i) => i.id === id);
        if (idea) idea.status = col.dataset.col;
        toast("Idea moved to " + col.dataset.col);
        render();
      };
    });
    document.getElementById("retry")?.addEventListener("click", () => {
      runDiscoverSearch(state.query);
    });
  }

  render();
})();

/*
 * CHRISTINA LAB — FRONTEND WORKFLOW / UI CONTROLLER
 *
 * This file implements the product workflow and interactive UI:
 * Research → Create → Test → Learn, with contextual AI assistance inside the workflow.
 *
 * Production views use the FastAPI backend and persisted Christina Lab data.
 * Demo/mock datasets are intentionally not loaded in the live workspace.
 */

(function () {
  const $ = (id) => document.getElementById(id);
  const API_BASE =
    window.CL_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1") && location.port !== "8000"
      ? "http://127.0.0.1:8000"
      : "");

  const LIVE_SESSION_KEY = "christinaLab.liveResearch.v2";
  const WORKSPACE_STORAGE_KEY = "christinaLab.workspaceAccess.v1";
  const AI_DISCLOSURE_PREFIX = "christinaLab.aiDisclosure.v1.";
  const GOOGLE_DISCLOSURE_KEY = "christinaLab.googleDisclosure.v1";

  function validWorkspaceKey(value) {
    return /^clw_[A-Za-z0-9_-]{24,100}$/.test(String(value || ""));
  }

  function randomWorkspaceKey() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    const token = btoa(String.fromCharCode(...bytes))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/g, "");
    return "clw_" + token;
  }

  function workspaceLink(accessKey) {
    const url = new URL(location.href);
    url.search = "";
    url.searchParams.set("workspace", accessKey);
    url.hash = "";
    return url.toString();
  }

  function workspaceHeaders(extra = {}) {
    const headers = { ...(extra || {}) };
    if (state.workspaceAccessKey) {
      headers["X-Christina-Workspace"] = state.workspaceAccessKey;
    }
    return headers;
  }

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
    discoverMode: restoredLiveSession?.discoverMode || "trend",
    searched: Boolean(restoredLiveSession?.searched && restoredLiveSession?.videos?.length),
    filters: {
      time: restoredLiveSession?.time || (restoredLiveSession?.discoverMode === "reference" ? "any" : "7d"),
      type: "All",
      minViews: 0,
      sort: "opp",
      topic: "All",
    },
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
    loading: false,
    error: false,
    niches: "coding, AI, career, build in public",
    liveVideos: restoredLiveSession?.videos || [],
    apiError: "",
    dashboardData: null,
    dashboardLoading: false,
    dashboardError: "",
    patternsData: null,
    patternsLoading: false,
    patternsError: "",
    publicConfigLoaded: false,
    publicConfigError: "",
    youtubeConfigured: false,
    googleOAuthClientId: "",
    googleDriveScope: "https://www.googleapis.com/auth/drive.file",
    googleAccessToken: "",
    googleTokenExpiresAt: 0,
    creatorAgentConfigured: false,
    creatorAgentProvider: "gemini",
    creatorAgentModel: "",
    creatorAgentProviders: null,
    workspaceAccessKey: "",
    workspaceReady: false,
    workspaceType: "",
    workspaceIsOwner: false,
    workspaceError: "",
  };

  function writeLiveSession() {
    try {
      sessionStorage.setItem(
        LIVE_SESSION_KEY,
        JSON.stringify({
          query: state.query,
          discoverMode: state.discoverMode,
          time: state.filters.time,
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
    const liveIds = new Set(state.liveVideos.map((v) => String(v.id)));
    const saved = state.savedResearch
      .map((v) => ({ ...v, id: v.videoId || v.id, source: "saved-research", persistedResearch: true }))
      .filter((v) => v.id && !liveIds.has(String(v.id)));
    return [...state.liveVideos, ...saved];
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
    config.headers = workspaceHeaders(config.headers || {});
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

  async function bootstrapWorkspace() {
    state.workspaceError = "";
    const queryKey = new URLSearchParams(location.search).get("workspace");
    let accessKey = validWorkspaceKey(queryKey)
      ? queryKey
      : String(localStorage.getItem(WORKSPACE_STORAGE_KEY) || "");

    if (!validWorkspaceKey(accessKey)) {
      accessKey = "";
      try {
        const response = await fetch(API_BASE + "/api/workspace/claim-owner", { method: "POST" });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.detail || "This private alpha workspace is already claimed.");
        }
        accessKey = String(payload.accessKey || "");
        if (!validWorkspaceKey(accessKey)) throw new Error("Owner workspace claim did not return a valid key.");
        localStorage.setItem(WORKSPACE_STORAGE_KEY, accessKey);
      } catch (error) {
        state.workspaceError = error?.message || "Open Christina Lab from a valid owner or tester invite link.";
        state.workspaceReady = false;
        return;
      }
    } else {
      localStorage.setItem(WORKSPACE_STORAGE_KEY, accessKey);
    }

    state.workspaceAccessKey = accessKey;
    window.CL_WORKSPACE_ID = accessKey;

    try {
      const status = await apiJson("/api/workspace/status");
      state.workspaceType = String(status.workspaceType || "tester");
      state.workspaceIsOwner = Boolean(status.isOwner);
      state.workspaceReady = true;
    } catch (error) {
      state.workspaceError = error?.message || "Could not verify this private alpha workspace.";
      state.workspaceReady = false;
    }
  }

  function aiDisclosureKey(kind) {
    return AI_DISCLOSURE_PREFIX + String(state.workspaceAccessKey || "").slice(-12) + "." + String(kind || "general");
  }

  function confirmAiShare(kind, details) {
    const key = aiDisclosureKey(kind);
    try {
      if (localStorage.getItem(key) === "accepted") return true;
    } catch (_) {}
    const provider = state.creatorAgentProvider || "the configured AI provider";
    const accepted = window.confirm(
      "What will be shared with AI?\n\n" +
      String(details || "Only the context needed for this generation.") +
      "\n\nProvider: " + provider +
      "\n\nNot included: your Google Drive contents, unrelated experiments, or social account access.\n\nContinue?"
    );
    if (accepted) {
      try { localStorage.setItem(key, "accepted"); } catch (_) {}
    }
    return accepted;
  }
  window.CL_CONFIRM_AI_SHARE = confirmAiShare;

  async function loadPublicConfig(force = false) {
    if (state.publicConfigLoaded && !force) return;
    state.publicConfigError = "";
    try {
      const payload = await fetchJson("/api/config/public");
      state.youtubeConfigured = Boolean(payload.youtubeConfigured);
      state.googleOAuthClientId = String(payload.googleOAuthClientId || "").trim();
      state.googleDriveScope = String(payload.googleDriveScope || "https://www.googleapis.com/auth/drive.file");
      state.creatorAgentConfigured = Boolean(payload.creatorAgentConfigured);
      state.creatorAgentProvider = String(payload.creatorAgentProvider || "gemini").trim();
      state.creatorAgentModel = String(payload.creatorAgentModel || "").trim();
      state.creatorAgentProviders = payload.creatorAgentProviders || null;
      state.publicConfigLoaded = true;
    } catch (error) {
      state.publicConfigError = error?.message || "Could not load cloud integration settings.";
    }
  }

  function googleDocsConfigured() {
    return Boolean(state.googleOAuthClientId);
  }

  async function ensureGoogleAccessToken() {
    await loadPublicConfig();
    if (!state.googleOAuthClientId) {
      throw new Error("Google Docs is not configured yet. Add GOOGLE_OAUTH_CLIENT_ID to Christina Lab first.");
    }

    const now = Date.now();
    if (state.googleAccessToken && state.googleTokenExpiresAt > now + 60_000) {
      return state.googleAccessToken;
    }

    try {
      if (localStorage.getItem(GOOGLE_DISCLOSURE_KEY) !== "accepted") {
        const accepted = window.confirm(
          "Connect Google Drive?\n\nChristina Lab requests Google\'s drive.file permission. This lets it create and work with files created through Christina Lab; it does not grant access to your entire Drive.\n\nThe Google access token stays in this browser session and is not stored in Christina Lab\'s database.\n\nContinue?"
        );
        if (!accepted) throw new Error("Google Drive connection cancelled.");
        localStorage.setItem(GOOGLE_DISCLOSURE_KEY, "accepted");
      }
    } catch (error) {
      if (error?.message) throw error;
    }

    if (!window.google?.accounts?.oauth2) {
      throw new Error("Google sign-in is still loading. Wait a moment and try again.");
    }

    return new Promise((resolve, reject) => {
      const client = window.google.accounts.oauth2.initTokenClient({
        client_id: state.googleOAuthClientId,
        scope: state.googleDriveScope,
        callback: (response) => {
          if (response?.error) {
            reject(new Error(response.error_description || response.error));
            return;
          }
          state.googleAccessToken = response.access_token || "";
          const expiresIn = Number(response.expires_in || 3600);
          state.googleTokenExpiresAt = Date.now() + Math.max(expiresIn - 60, 60) * 1000;
          if (!state.googleAccessToken) {
            reject(new Error("Google did not return an access token."));
            return;
          }
          resolve(state.googleAccessToken);
        },
      });
      client.requestAccessToken({ prompt: "consent" });
    });
  }

  function googleDocName(filename) {
    return String(filename || "Christina Lab document")
      .replace(/\.(docx|txt|md)$/i, "")
      .trim() || "Christina Lab document";
  }

  function canConvertToGoogleDocs(doc) {
    return /\.(docx|txt|md)$/i.test(String(doc?.filename || ""));
  }

  async function uploadDocumentToGoogleDocs(idea, doc) {
    if (!canConvertToGoogleDocs(doc)) {
      throw new Error("Google Docs conversion currently supports DOCX, TXT, and Markdown files.");
    }

    const token = await ensureGoogleAccessToken();
    const sourceResponse = await fetch(
      API_BASE + "/api/idea-documents/" + encodeURIComponent(doc.id),
      { headers: workspaceHeaders() }
    );
    if (!sourceResponse.ok) {
      throw new Error("Could not read the Christina Lab document.");
    }
    const sourceBlob = await sourceResponse.blob();

    const boundary = "christina_lab_" + Math.random().toString(36).slice(2);
    const metadata = {
      name: googleDocName(doc.filename),
      mimeType: "application/vnd.google-apps.document",
      description: "Exported from Christina Lab · " + String(idea.title || "Creator idea"),
    };
    const multipart = new Blob(
      [
        "--" + boundary + "\r\n",
        "Content-Type: application/json; charset=UTF-8\r\n\r\n",
        JSON.stringify(metadata),
        "\r\n--" + boundary + "\r\n",
        "Content-Type: " + (doc.contentType || "application/octet-stream") + "\r\n\r\n",
        sourceBlob,
        "\r\n--" + boundary + "--",
      ],
      { type: "multipart/related; boundary=" + boundary }
    );

    const response = await fetch(
      "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,mimeType,webViewLink",
      {
        method: "POST",
        headers: { Authorization: "Bearer " + token },
        body: multipart,
      }
    );

    let payload = {};
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
      const message = payload?.error?.message || "Google Drive could not create the Google Doc.";
      throw new Error(message);
    }

    const webUrl = payload.webViewLink || ("https://docs.google.com/document/d/" + payload.id + "/edit");
    await apiJson("/api/idea-documents/" + encodeURIComponent(doc.id) + "/cloud", {
      method: "PATCH",
      body: {
        provider: "google_docs",
        fileId: payload.id,
        url: webUrl,
      },
    });
    return { ...payload, webViewLink: webUrl };
  }

  function workflowRoute(path = state.route) {
    const clean = String(path || "/").split("?")[0] || "/";
    return (
      clean === "/" ||
      clean === "/discover" ||
      clean === "/saved" ||
      clean === "/ideas" ||
      clean === "/agent" ||
      clean === "/lab" ||
      clean === "/videos" ||
      clean === "/analytics" ||
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
    if (["/patterns", "/analytics"].includes(state.route.split("?")[0])) render();
    try {
      state.patternsData = await fetchJson("/api/patterns");
    } catch (error) {
      state.patternsError = error?.message || "Could not load persisted pattern data.";
    } finally {
      state.patternsLoading = false;
      if (["/patterns", "/analytics"].includes(state.route.split("?")[0])) render();
    }
  }

  function loadRouteData(path = state.route) {
    if (!state.workspaceReady) return;
    const clean = String(path || "/").split("?")[0] || "/";
    if (clean === "/") loadDashboardData();
    if (clean === "/patterns" || clean === "/analytics") loadPatternsData();
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
      ["Discover market signals", "/discover"],
      ["Turn saved research into an idea", "/saved"],
      ["Open ideas and production packs", "/ideas"],
      ["Open experiments", "/lab"],
      ["Review published videos", "/videos"],
      ["Learn from patterns", "/patterns"],
      ["Compare market vs creator evidence", "/analytics"],
      ["Dashboard", "/"],
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

  async function agentIdeaFromSaved(vid, contentType, button) {
    if (!contentType) {
      toast("Choose Short or Long-form first.");
      return;
    }
    if (!["Short", "Long-form"].includes(contentType)) {
      toast("Choose a valid content type.");
      return;
    }

    if (!confirmAiShare(
      "saved-research-idea",
      "This saved research item's title, metrics, Why / Adapt / Angle notes, and your chosen " + contentType + " format will be sent for idea generation."
    )) return;

    const original = button ? button.textContent : "";
    if (button) {
      button.disabled = true;
      button.textContent = "Agent working…";
    }

    try {
      const result = await apiJson("/api/research/" + encodeURIComponent(vid) + "/agent-idea", {
        method: "POST",
        body: { contentType },
      });
      state.workflowLoaded = false;
      await loadWorkflowData(true);
      toast(contentType + " idea created by the agent");
      navigate("/ideas");
      return result;
    } catch (error) {
      toast(error?.message || "AI assistance could not turn this research into an idea.");
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = original;
      }
    }
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

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("Could not read the selected file."));
      reader.onload = () => {
        const value = String(reader.result || "");
        resolve(value.includes(",") ? value.split(",", 2)[1] : value);
      };
      reader.readAsDataURL(file);
    });
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(bytes >= 10240 ? 0 : 1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  async function copyIdeaDocumentText(documentId, label) {
    const response = await fetch(
      API_BASE + "/api/idea-documents/" + encodeURIComponent(documentId),
      { headers: workspaceHeaders() }
    );
    if (!response.ok) throw new Error("Could not load document text.");
    const text = await response.text();
    await navigator.clipboard.writeText(text);
    toast((label || "Document") + " copied");
  }

  async function downloadIdeaDocument(doc) {
    const response = await fetch(
      API_BASE + "/api/idea-documents/" + encodeURIComponent(doc.id),
      { headers: workspaceHeaders() }
    );
    if (!response.ok) throw new Error("Could not download this document.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = String(doc.filename || "christina-lab-document");
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function ideaProductionPlatform(doc, ideaId) {
    const filename = String(doc?.filename || "").toLowerCase();
    const prefix = "idea-" + String(ideaId) + "-";
    if (!filename.startsWith(prefix) || !filename.endsWith(".md")) return "";
    const platforms = [
      ["youtube-shorts", "YouTube Shorts"],
      ["youtube", "YouTube"],
      ["tiktok", "TikTok"],
      ["pinterest", "Pinterest"],
      ["instagram", "Instagram"],
    ];
    const match = platforms.find(([slug]) => filename.startsWith(prefix + slug + "-"));
    return match ? match[1] : "";
  }

  function ideaProductionDuration(doc, ideaId) {
    const filename = String(doc?.filename || "").toLowerCase();
    const marker = "idea-" + String(ideaId) + "-youtube-";
    if (!filename.startsWith(marker)) return null;
    const match = filename.slice(marker.length).match(/^(\d+)min-/);
    return match ? Number(match[1]) : null;
  }

  function latestIdeaProductionPlatform(documents, ideaId, ideaType = "Short") {
    const generated = documents
      .filter((doc) => ideaProductionPlatform(doc, ideaId))
      .slice()
      .sort((a, b) => String(b.uploadedAt || "").localeCompare(String(a.uploadedAt || "")));
    return generated.length
      ? ideaProductionPlatform(generated[0], ideaId)
      : (String(ideaType || "") === "Short" ? "YouTube Shorts" : "YouTube");
  }

  function latestIdeaProductionDuration(documents, ideaId) {
    const generated = documents
      .filter((doc) => ideaProductionPlatform(doc, ideaId) === "YouTube" && ideaProductionDuration(doc, ideaId))
      .slice()
      .sort((a, b) => String(b.uploadedAt || "").localeCompare(String(a.uploadedAt || "")));
    return generated.length ? ideaProductionDuration(generated[0], ideaId) : 7;
  }

  function isTextIdeaDocument(doc) {
    return String(doc?.contentType || "").startsWith("text/") || /\.(md|txt)$/i.test(String(doc?.filename || ""));
  }

  function productionAssetMeta(kind, isLongForm = false) {
    return {
      script: {
        title: "Script",
        description: "Voiceover, dialogue and on-screen copy for the piece.",
        openLabel: "Read script",
        copyLabel: "Copy script",
      },
      plan: {
        title: "Production Plan",
        description: "Shots, timing, overlays, edit notes and definition of done.",
        openLabel: "View plan",
        copyLabel: "Copy plan",
      },
      video_prompt: isLongForm
        ? {
            title: "AI Generation Pack",
            description: "Timeline-mapped AI scene prompts plus real-footage, screen-recording and assembly guidance for the full YouTube production.",
            openLabel: "View AI pack",
            copyLabel: "Copy AI pack",
          }
        : {
            title: "AI Video Prompt",
            description: "Copy-paste-ready prompt for AI Studio / Veo.",
            openLabel: "View prompt",
            copyLabel: "Copy prompt",
          },
      photo_reference: {
        title: "Photo Reference",
        description: "Visual brief, real-capture direction and image-generation prompt.",
        openLabel: "View brief",
        copyLabel: "Copy image prompt",
      },
    }[kind] || {
      title: "Document",
      description: "Creative source material for this idea.",
      openLabel: "Open",
      copyLabel: "Copy",
    };
  }

  function renderCreatorDocumentText(raw) {
    const inline = (value) => esc(value)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    return String(raw || "")
      .replace(/\r/g, "")
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return '<div class="creator-doc-space"></div>';
        if (/^###\s+/.test(trimmed)) return "<h4>" + inline(trimmed.replace(/^###\s+/, "")) + "</h4>";
        if (/^##\s+/.test(trimmed)) return "<h3>" + inline(trimmed.replace(/^##\s+/, "")) + "</h3>";
        if (/^#\s+/.test(trimmed)) return "<h2>" + inline(trimmed.replace(/^#\s+/, "")) + "</h2>";
        if (/^[-*]\s+/.test(trimmed)) return '<div class="creator-doc-bullet"><span>•</span><div>' + inline(trimmed.replace(/^[-*]\s+/, "")) + "</div></div>";
        if (/^\d+\.\s+/.test(trimmed)) {
          const match = trimmed.match(/^(\d+)\.\s+(.*)$/);
          return '<div class="creator-doc-number"><span>' + esc(match?.[1] || "") + '.</span><div>' + inline(match?.[2] || trimmed) + "</div></div>";
        }
        return "<p>" + inline(trimmed) + "</p>";
      })
      .join("");
  }

  async function openIdeaDocumentsModal(idea) {
    const m = $("modal");
    m.hidden = false;
    m.innerHTML = `<div class="modal idea-modal production-pack-modal">
      <h2 style="margin:0 0 6px;font-size:16px">Production Pack</h2>
      <p class="meta" style="margin-top:0">${esc(idea.title)}</p>
      <div class="card" style="padding:14px"><div class="skel"></div><div class="skel"></div></div>
    </div>`;
    m.onclick = (e) => {
      if (e.target === m) m.hidden = true;
    };

    try {
      const payload = await fetchJson("/api/ideas/" + encodeURIComponent(idea.id) + "/documents");
      const items = Array.isArray(payload.items) ? payload.items : [];
      renderIdeaDocumentsModal(
        idea,
        items,
        latestIdeaProductionPlatform(items, idea.id, idea.type),
        latestIdeaProductionDuration(items, idea.id)
      );
    } catch (error) {
      m.innerHTML = `<div class="modal idea-modal production-pack-modal">
        <h2 style="margin:0 0 6px;font-size:16px">Production Pack</h2>
        <p class="meta">${esc(error?.message || "Could not load production assets.")}</p>
        <div class="actions"><button class="btn ghost" id="cancelM">Close</button></div>
      </div>`;
      $("cancelM").onclick = () => (m.hidden = true);
    }
  }

  function renderIdeaDocumentsModal(idea, documents, selectedPlatform = "", selectedDurationMinutes = null) {
    const m = $("modal");
    const isLongForm = String(idea.type || "") !== "Short";
    const allowedPlatforms = isLongForm
      ? ["YouTube"]
      : ["YouTube Shorts", "TikTok", "Pinterest", "Instagram"];
    if (!allowedPlatforms.includes(selectedPlatform)) {
      selectedPlatform = isLongForm ? "YouTube" : "YouTube Shorts";
    }
    const targetDurationMinutes = isLongForm
      ? Math.min(20, Math.max(3, Number(selectedDurationMinutes) || latestIdeaProductionDuration(documents, idea.id) || 7))
      : null;
    const kinds = {
      script: "Script",
      plan: "Production Plan",
      reference: "Reference",
      video_prompt: isLongForm ? "AI Generation Pack" : "AI Video Prompt",
      photo_reference: "Photo Reference",
      other: "Other",
    };
    const productionKinds = ["script", "plan", "video_prompt", "photo_reference"];
    const generatedDocs = documents.filter((doc) =>
      allowedPlatforms.includes(ideaProductionPlatform(doc, idea.id))
    );
    const selectedGenerated = generatedDocs
      .filter((doc) => ideaProductionPlatform(doc, idea.id) === selectedPlatform)
      .slice()
      .sort((a, b) => String(b.uploadedAt || "").localeCompare(String(a.uploadedAt || "")));
    const latestByKind = {};
    selectedGenerated.forEach((doc) => {
      if (productionKinds.includes(doc.kind) && !latestByKind[doc.kind]) latestByKind[doc.kind] = doc;
    });
    const packDocs = productionKinds.map((kind) => latestByKind[kind]).filter(Boolean);
    const generatedDocIds = new Set(generatedDocs.map((doc) => String(doc.id)));
    const additionalDocs = documents.filter((doc) => !generatedDocIds.has(String(doc.id)));
    const generatedPlatforms = [...new Set(generatedDocs.map((doc) => ideaProductionPlatform(doc, idea.id)).filter(Boolean))];

    const productionCard = (doc) => {
      const meta = productionAssetMeta(doc.kind, isLongForm);
      const googleAction = canConvertToGoogleDocs(doc)
        ? doc.cloudUrl
          ? `<a class="btn primary" href="${esc(doc.cloudUrl)}" target="_blank" rel="noopener">Open Google Doc ✓</a>`
          : `<button class="btn" type="button" data-google-doc="${doc.id}">Create Google Doc</button>`
        : "";
      return `<article class="production-asset-card">
        <div class="production-asset-main">
          <div class="production-asset-kicker">${esc(selectedPlatform)} · ${esc(idea.type || "Content")}${isLongForm ? " · " + esc(String(ideaProductionDuration(doc, idea.id) || targetDurationMinutes)) + " min target" : ""}</div>
          <h3>${esc(meta.title)}</h3>
          <p>${esc(meta.description)}</p>
          ${doc.cloudUploadedAt ? '<div class="production-sync-state">✓ Google Docs synced</div>' : ""}
        </div>
        <div class="production-asset-actions">
          ${isTextIdeaDocument(doc) ? `<button class="btn primary" type="button" data-view-doc="${doc.id}">${esc(meta.openLabel)}</button>` : ""}
          ${isTextIdeaDocument(doc) ? `<button class="btn" type="button" data-copy-doc="${doc.id}" data-copy-label="${esc(meta.title)}">${esc(meta.copyLabel)}</button>` : ""}
          ${googleAction}
          <details class="production-more">
            <summary>More</summary>
            <div class="production-more-menu">
              <div class="production-file-name">${esc(doc.filename)}</div>
              <button class="btn ghost" type="button" data-download-doc="${doc.id}">Download file</button>
              ${doc.cloudUrl && canConvertToGoogleDocs(doc) ? `<button class="btn ghost" type="button" data-google-doc="${doc.id}">Create new Google Doc</button>` : ""}
              <button class="btn danger" type="button" data-delete-doc="${doc.id}">Delete</button>
            </div>
          </details>
        </div>
      </article>`;
    };

    m.innerHTML = `<div class="modal idea-modal production-pack-modal">
      <div class="production-pack-head">
        <div>
          <div class="eyebrow">CREATOR ASSETS</div>
          <h2>Production Pack</h2>
          <p>Everything needed to take <b>${esc(idea.title)}</b> from idea to production—without needing to understand the underlying file format.</p>
        </div>
        <button class="btn ghost" type="button" id="cancelM">Close</button>
      </div>

      <section class="agent-production-docs production-generator">
        <div class="agent-production-docs-head">
          <div>
            <span class="badge strong">Generate</span>
            <h3>Build a production pack</h3>
            <p class="meta">Idea format: <b>${esc(idea.type || "Long-form")}</b>. ${isLongForm ? "Choose the target YouTube runtime; the script and full production timeline will be sized to it." : "Choose where this piece will be published."}</p>
          </div>
        </div>
        <div class="agent-production-controls ${isLongForm ? "long-form-production-controls" : ""}">
          <label>Platform
            <select id="ideaDocsPlatform">
              ${allowedPlatforms.map((platform) =>
                `<option value="${esc(platform)}" ${platform === selectedPlatform ? "selected" : ""}>${esc(platform)}</option>`
              ).join("")}
            </select>
          </label>
          ${isLongForm ? `<label>Target video length
            <div class="duration-input-wrap">
              <input id="ideaDocsDuration" type="number" min="3" max="20" step="1" value="${targetDurationMinutes}" />
              <span>minutes</span>
            </div>
            <small>Aim for 3–20 minutes. The script and timestamped plan will be sized to this target.</small>
          </label>` : ""}
          <button class="btn primary" type="button" id="generateIdeaDocs">${packDocs.length ? "Regenerate production pack" : "Generate production pack"}</button>
        </div>
        ${generatedPlatforms.length && !isLongForm
          ? `<div class="production-pack-tabs">
              <span class="meta">Available packs:</span>
              ${generatedPlatforms.map((platform) => `<button class="btn ${platform === selectedPlatform ? "primary" : "ghost"}" type="button" data-pack-platform="${esc(platform)}">${esc(platform)}</button>`).join("")}
            </div>`
          : isLongForm && packDocs.length
            ? `<div class="production-pack-tabs"><span class="meta">Current pack: YouTube · ${targetDurationMinutes} min target · 16:9</span></div>`
            : ""}
      </section>

      <section id="ideaDocumentPreview" class="production-preview" hidden></section>

      <section class="production-assets-section">
        <div class="section-label-row production-section-label">
          <div>
            <div class="eyebrow">${esc(selectedPlatform.toUpperCase())}${isLongForm ? " · " + esc(String(targetDurationMinutes)) + " MIN TARGET" : ""}</div>
            <h2>Your production assets</h2>
          </div>
          <p>Read them here, copy what you need, or move editable documents into Google Docs.</p>
        </div>
        ${packDocs.length
          ? `<div class="production-assets-grid">${packDocs.map(productionCard).join("")}</div>`
          : `<div class="production-pack-empty">
              <h3>No ${esc(selectedPlatform)}${isLongForm ? " " + esc(String(targetDurationMinutes)) + "-minute" : ""} production pack yet.</h3>
              <p>Generate one above and Christina Lab will create the Script, Production Plan, ${isLongForm ? "AI Generation Pack" : "AI Video Prompt"} and Photo Reference.</p>
            </div>`}
      </section>

      <details class="manual-documents">
        <summary>Add your own files</summary>
        <div class="manual-documents-body">
          <p class="meta">Attach a script, plan, reference image, PDF or other material you created outside Christina Lab.</p>
          <form class="form" id="documentForm">
            <label>Document type
              <select name="kind">
                <option value="script">Script</option>
                <option value="plan">Production Plan / PRD</option>
                <option value="video_prompt">Video Prompt</option>
                <option value="photo_reference">Photo Reference</option>
                <option value="reference">Reference</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label>File
              <input name="file" type="file" required accept=".docx,.pdf,.md,.txt,.png,.jpg,.jpeg,.webp" />
            </label>
            <div class="meta">DOCX, PDF, Markdown, text, PNG, JPG, or WebP · maximum 5 MB per file.</div>
            <div class="actions">
              <button class="btn primary" type="submit">Add file</button>
            </div>
          </form>
        </div>
      </details>

      ${additionalDocs.length ? `<section class="additional-files">
        <div class="section-label-row production-section-label">
          <div>
            <div class="eyebrow">YOUR FILES</div>
            <h2>Additional files</h2>
          </div>
          <p>Manual uploads and source material kept with this idea.</p>
        </div>
        <div class="additional-file-list">
          ${additionalDocs.map((doc) => `<div class="additional-file-row">
            <div>
              <b>${esc(kinds[doc.kind] || doc.kind || "Other")}</b>
              <div class="meta">${esc(doc.filename)} · ${formatBytes(doc.sizeBytes)}${doc.cloudUploadedAt ? " · Google Docs synced" : ""}</div>
            </div>
            <div class="actions">
              ${isTextIdeaDocument(doc) ? `<button class="btn" type="button" data-view-doc="${doc.id}">Open</button>` : ""}
              ${isTextIdeaDocument(doc) ? `<button class="btn" type="button" data-copy-doc="${doc.id}" data-copy-label="${esc(kinds[doc.kind] || "Document")}">Copy</button>` : ""}
              ${canConvertToGoogleDocs(doc)
                ? doc.cloudUrl
                  ? `<a class="btn primary" href="${esc(doc.cloudUrl)}" target="_blank" rel="noopener">Open Google Doc ✓</a>`
                  : `<button class="btn" type="button" data-google-doc="${doc.id}">Create Google Doc</button>`
                : ""}
              <button class="btn ghost" type="button" data-download-doc="${doc.id}">Download</button>
              <button class="btn ghost" type="button" data-delete-doc="${doc.id}">Delete</button>
            </div>
          </div>`).join("")}
        </div>
      </section>` : ""}
    </div>`;

    $("cancelM").onclick = () => (m.hidden = true);
    m.onclick = (e) => {
      if (e.target === m) m.hidden = true;
    };

    const platformSelect = $("ideaDocsPlatform");
    if (platformSelect) {
      platformSelect.onchange = () => renderIdeaDocumentsModal(idea, documents, platformSelect.value, targetDurationMinutes);
    }
    document.querySelectorAll("[data-pack-platform]").forEach((button) => {
      button.onclick = () => renderIdeaDocumentsModal(idea, documents, button.dataset.packPlatform, targetDurationMinutes);
    });

    const generateDocsButton = $("generateIdeaDocs");
    if (generateDocsButton) {
      generateDocsButton.onclick = async () => {
        const platform = $("ideaDocsPlatform")?.value || selectedPlatform;
        const durationInput = $("ideaDocsDuration");
        const requestedDuration = isLongForm ? Number(durationInput?.value || targetDurationMinutes) : null;
        if (isLongForm && (!Number.isFinite(requestedDuration) || requestedDuration < 3 || requestedDuration > 20)) {
          toast("Choose a target length between 3 and 20 minutes");
          return;
        }
        if (!confirmAiShare(
          "production-pack",
          "This Idea's title, hook, topic, angle, audience, hypothesis, attached saved-research context, selected platform" +
            (isLongForm ? ", and target runtime" : "") +
            " will be sent to generate the Production Pack."
        )) return;
        const original = generateDocsButton.textContent;
        generateDocsButton.disabled = true;
        generateDocsButton.textContent = "Generating…";
        try {
          const result = await apiJson("/api/ideas/" + encodeURIComponent(idea.id) + "/agent-documents", {
            method: "POST",
            body: {
              platform,
              targetDurationMinutes: isLongForm ? requestedDuration : null,
            },
          });
          const payload = await fetchJson("/api/ideas/" + encodeURIComponent(idea.id) + "/documents");
          const items = Array.isArray(payload.items) ? payload.items : [];
          idea.documentCount = items.length;
          toast((result.documents || []).length + " production assets generated");
          renderIdeaDocumentsModal(idea, items, platform, isLongForm ? requestedDuration : null);
        } catch (error) {
          toast(error?.message || "AI assistance could not generate the production pack");
          generateDocsButton.disabled = false;
          generateDocsButton.textContent = original;
        }
      };
    }

    document.querySelectorAll("[data-view-doc]").forEach((button) => {
      button.onclick = async () => {
        const doc = documents.find((item) => String(item.id) === String(button.dataset.viewDoc));
        if (!doc) return;
        const preview = $("ideaDocumentPreview");
        const meta = productionAssetMeta(doc.kind, isLongForm);
        preview.hidden = false;
        preview.innerHTML = '<div class="production-preview-loading"><div class="skel"></div><div class="skel"></div></div>';
        preview.scrollIntoView({ behavior: "smooth", block: "start" });
        try {
          const response = await fetch(
            API_BASE + "/api/idea-documents/" + encodeURIComponent(doc.id),
            { headers: workspaceHeaders() }
          );
          if (!response.ok) throw new Error("Could not load this document.");
          const raw = await response.text();
          preview.innerHTML = `<div class="production-preview-head">
              <div>
                <div class="eyebrow">PREVIEW</div>
                <h2>${esc(meta.title)}</h2>
                <p>${esc(meta.description)}</p>
              </div>
              <button class="btn ghost" type="button" id="closeDocumentPreview">Close preview</button>
            </div>
            <div class="creator-document">${renderCreatorDocumentText(raw)}</div>
            <div class="production-preview-actions">
              <button class="btn primary" type="button" data-preview-copy="${doc.id}" data-preview-label="${esc(meta.title)}">${esc(meta.copyLabel)}</button>
              ${doc.cloudUrl ? `<a class="btn" href="${esc(doc.cloudUrl)}" target="_blank" rel="noopener">Open Google Doc ✓</a>` : ""}
            </div>`;
          $("closeDocumentPreview").onclick = () => {
            preview.hidden = true;
            preview.innerHTML = "";
          };
          preview.querySelector("[data-preview-copy]")?.addEventListener("click", async (e) => {
            const copyButton = e.currentTarget;
            copyButton.disabled = true;
            try {
              await copyIdeaDocumentText(copyButton.dataset.previewCopy, copyButton.dataset.previewLabel);
            } catch (error) {
              toast(error?.message || "Could not copy document");
            } finally {
              copyButton.disabled = false;
            }
          });
        } catch (error) {
          preview.innerHTML = `<div class="production-preview-head"><div><h2>Could not open this asset</h2><p>${esc(error?.message || "Could not load document.")}</p></div><button class="btn ghost" type="button" id="closeDocumentPreview">Close</button></div>`;
          $("closeDocumentPreview").onclick = () => {
            preview.hidden = true;
            preview.innerHTML = "";
          };
        }
      };
    });

    document.querySelectorAll("[data-copy-doc]").forEach((button) => {
      button.onclick = async () => {
        button.disabled = true;
        try {
          await copyIdeaDocumentText(button.dataset.copyDoc, button.dataset.copyLabel || "Document");
        } catch (error) {
          toast(error?.message || "Could not copy document");
        } finally {
          button.disabled = false;
        }
      };
    });

    $("documentForm").onsubmit = async (e) => {
      e.preventDefault();
      const submit = e.submitter;
      if (submit) submit.disabled = true;
      const form = e.target;
      const file = form.file.files?.[0];
      if (!file) {
        toast("Choose a file first");
        if (submit) submit.disabled = false;
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        toast("Document must be 5 MB or smaller");
        if (submit) submit.disabled = false;
        return;
      }
      try {
        const dataBase64 = await fileToBase64(file);
        await apiJson("/api/ideas/" + encodeURIComponent(idea.id) + "/documents", {
          method: "POST",
          body: {
            kind: form.kind.value,
            filename: file.name,
            contentType: file.type || "application/octet-stream",
            dataBase64,
          },
        });
        const payload = await fetchJson("/api/ideas/" + encodeURIComponent(idea.id) + "/documents");
        const items = Array.isArray(payload.items) ? payload.items : [];
        idea.documentCount = items.length;
        toast("File added");
        renderIdeaDocumentsModal(idea, items, selectedPlatform, targetDurationMinutes);
      } catch (error) {
        toast(error?.message || "Could not upload document");
        if (submit) submit.disabled = false;
      }
    };

    document.querySelectorAll("[data-google-doc]").forEach((button) => {
      button.onclick = async () => {
        const doc = documents.find((item) => String(item.id) === String(button.dataset.googleDoc));
        if (!doc) return;
        button.disabled = true;
        const original = button.textContent;
        button.textContent = "Creating…";
        try {
          const created = await uploadDocumentToGoogleDocs(idea, doc);
          const payload = await fetchJson("/api/ideas/" + encodeURIComponent(idea.id) + "/documents");
          const items = Array.isArray(payload.items) ? payload.items : [];
          idea.documentCount = items.length;
          toast("Google Doc ready");
          if (created?.webViewLink) window.open(created.webViewLink, "_blank", "noopener");
          renderIdeaDocumentsModal(idea, items, selectedPlatform, targetDurationMinutes);
        } catch (error) {
          toast(error?.message || "Could not create Google Doc");
          button.disabled = false;
          button.textContent = original;
        }
      };
    });

    document.querySelectorAll("[data-download-doc]").forEach((button) => {
      button.onclick = async () => {
        const doc = documents.find((item) => String(item.id) === String(button.dataset.downloadDoc));
        if (!doc) return;
        button.disabled = true;
        try {
          await downloadIdeaDocument(doc);
        } catch (error) {
          toast(error?.message || "Could not download document");
        } finally {
          button.disabled = false;
        }
      };
    });

    document.querySelectorAll("[data-delete-doc]").forEach((button) => {
      button.onclick = async () => {
        const doc = documents.find((item) => String(item.id) === String(button.dataset.deleteDoc));
        if (!doc) return;
        const confirmed = window.confirm("Delete this " + String(kinds[doc.kind] || "document").toLowerCase() + "?");
        if (!confirmed) return;
        button.disabled = true;
        try {
          await apiJson("/api/idea-documents/" + encodeURIComponent(button.dataset.deleteDoc), {
            method: "DELETE",
          });
          const payload = await fetchJson("/api/ideas/" + encodeURIComponent(idea.id) + "/documents");
          const items = Array.isArray(payload.items) ? payload.items : [];
          idea.documentCount = items.length;
          toast("Document removed");
          renderIdeaDocumentsModal(idea, items, selectedPlatform, targetDurationMinutes);
        } catch (error) {
          toast(error?.message || "Could not remove document");
          button.disabled = false;
        }
      };
    });
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

  async function deleteExperiment(exp) {
    if (!exp) return false;
    const code = "EXP-" + String(exp.id).padStart(3, "0");
    const confirmed = window.confirm(
      "Delete " + code + "?\n\nThis permanently removes this experiment, its recorded metrics, result, lesson, and decision. The source Idea will remain."
    );
    if (!confirmed) return false;

    try {
      await apiJson("/api/experiments/" + Number(exp.id), {
        method: "DELETE",
      });
      $("modal").hidden = true;
      state.workflowLoaded = false;
      await loadWorkflowData(true);
      toast(code + " deleted");
      navigate("/lab");
      return true;
    } catch (error) {
      toast(error?.message || "Could not delete experiment");
      return false;
    }
  }

  function openExperimentEditModal(exp) {
    if (!exp) return;
    const m = $("modal");
    const publishedDate = String(exp.publishedAt || "").slice(0, 10);
    const formats = ["Short", "Long-form", "Livestream"];
    if (exp.format && !formats.includes(exp.format)) formats.unshift(exp.format);

    m.hidden = false;
    m.innerHTML = `<div class="modal experiment-edit-modal">
      <div class="experiment-edit-head">
        <div>
          <h2 style="margin:0 0 6px;font-size:16px">Edit experiment</h2>
          <p class="meta" style="margin:0">EXP-${String(exp.id).padStart(3, "0")} · source idea #${exp.ideaId}</p>
        </div>
        <button class="btn ghost" type="button" id="cancelM">Close</button>
      </div>

      <form class="form experiment-edit-form" id="experimentEditForm">
        <div class="experiment-edit-grid">
          <label>Experiment name
            <input name="name" required value="${esc(exp.name || "")}" />
          </label>
          <label>Topic
            <input name="topic" value="${esc(exp.topic || "")}" />
          </label>
          <label>Format
            <select name="format">
              ${formats.map((value) => `<option value="${esc(value)}" ${value === exp.format ? "selected" : ""}>${esc(value)}</option>`).join("")}
            </select>
          </label>
          <label>Status
            <select name="status">
              <option ${exp.status === "Draft" ? "selected" : ""}>Draft</option>
              <option ${exp.status === "Ready" ? "selected" : ""}>Ready</option>
              <option ${exp.status === "Published" ? "selected" : ""}>Published</option>
            </select>
          </label>
          <label>Decision
            <select name="decision">
              <option value="UNDECIDED" ${exp.decision === "UNDECIDED" ? "selected" : ""}>Undecided</option>
              <option ${exp.decision === "GO" ? "selected" : ""}>GO</option>
              <option ${exp.decision === "TEST" ? "selected" : ""}>TEST</option>
              <option ${exp.decision === "HOLD" ? "selected" : ""}>HOLD</option>
            </select>
          </label>
          <label>Published date
            <input name="publishedAt" type="date" value="${esc(publishedDate)}" />
          </label>
        </div>

        <label>Hypothesis
          <textarea name="hypothesis" rows="3">${esc(exp.hypothesis || "")}</textarea>
        </label>

        <div class="experiment-edit-metrics">
          <label>24h views
            <input name="v24" type="number" min="0" value="${exp.v24 ?? ""}" />
          </label>
          <label>7d views
            <input name="v7" type="number" min="0" value="${exp.v7 ?? ""}" />
          </label>
          <label>Retention %
            <input name="retention" type="number" min="0" max="100" step="0.1" value="${exp.retention ?? ""}" />
          </label>
          <label>Subscriber gain
            <input name="subs" type="number" value="${exp.subs ?? ""}" />
          </label>
          <label>CTR %
            <input name="ctr" type="number" min="0" max="100" step="0.1" value="${exp.ctr ?? ""}" />
          </label>
        </div>

        <label>Result summary
          <textarea name="result" rows="2">${esc(exp.result || "")}</textarea>
        </label>
        <label>What did we learn?
          <textarea name="lesson" rows="3">${esc(exp.lesson || "")}</textarea>
        </label>
        <label>Next test
          <textarea name="next" rows="2">${esc(exp.next || "")}</textarea>
        </label>

        <div class="actions experiment-edit-actions">
          <button class="btn danger" type="button" id="deleteExperimentFromModal">Delete experiment</button>
          <span class="grow"></span>
          <button class="btn ghost" type="button" id="cancelExperimentEdit">Cancel</button>
          <button class="btn primary" type="submit">Save changes</button>
        </div>
      </form>
    </div>`;

    const close = () => (m.hidden = true);
    $("cancelM").onclick = close;
    $("cancelExperimentEdit").onclick = close;
    $("deleteExperimentFromModal").onclick = async (e) => {
      const button = e.currentTarget;
      button.disabled = true;
      const deleted = await deleteExperiment(exp);
      if (!deleted) button.disabled = false;
    };
    m.onclick = (e) => {
      if (e.target === m) close();
    };

    $("experimentEditForm").onsubmit = async (e) => {
      e.preventDefault();
      const submit = e.submitter;
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Saving…";
      }
      const fd = new FormData(e.target);
      const numberOrNull = (name) => {
        const raw = String(fd.get(name) ?? "").trim();
        return raw === "" ? null : Number(raw);
      };
      try {
        await apiJson("/api/experiments/" + Number(exp.id), {
          method: "PATCH",
          body: {
            name: String(fd.get("name") || "").trim(),
            topic: String(fd.get("topic") || "").trim(),
            format: String(fd.get("format") || "").trim(),
            hypothesis: String(fd.get("hypothesis") || "").trim(),
            status: String(fd.get("status") || "Draft"),
            decision: String(fd.get("decision") || "UNDECIDED"),
            publishedAt: String(fd.get("publishedAt") || "").trim() || null,
            v24: numberOrNull("v24"),
            v7: numberOrNull("v7"),
            retention: numberOrNull("retention"),
            subs: numberOrNull("subs"),
            ctr: numberOrNull("ctr"),
            result: String(fd.get("result") || "").trim(),
            lesson: String(fd.get("lesson") || "").trim(),
            next: String(fd.get("next") || "").trim(),
          },
        });
        m.hidden = true;
        state.workflowLoaded = false;
        await loadWorkflowData(true);
        toast("Experiment updated");
        render();
      } catch (error) {
        toast(error?.message || "Could not update experiment");
        if (submit) {
          submit.disabled = false;
          submit.textContent = "Save changes";
        }
      }
    };
  }

  const NAV = [
    ["Overview", null],
    ["Dashboard", "/", "dash"],
    ["Research", null],
    ["Discover", "/discover", "search"],
    ["Saved Research", "/saved", "bookmark"],
    ["Create", null],
    ["Ideas", "/ideas", "light"],
    ["Test", null],
    ["Experiments", "/lab", "flask"],
    ["My Videos", "/videos", "play"],
    ["Learn", null],
    ["Patterns", "/patterns", "grid"],
    ["Analytics", "/analytics", "chart"],
    ["System", null],
    ["Trust & Access", "/trust", "shield"],
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
          <img class="avatar" src="https://api.dicebear.com/7.x/avataaars/svg?seed=${state.workspaceIsOwner ? "Christina" : "CreatorTester"}" alt="Workspace avatar" />
          <div><div>${state.workspaceIsOwner ? "Christina" : "Private tester"}</div><small>${state.workspaceIsOwner ? "Owner workspace" : "Isolated alpha workspace"}</small></div>
        </div>
      </aside>
      <div class="main">
        <header class="top">
          <button class="btn menu-btn" id="menu">Menu</button>
          <h1>${title}</h1>
          <div class="grow"></div>
          <input class="search-mini" id="gs" placeholder="Search app…  ⌘K" />
          <span class="badge">${state.workspaceIsOwner ? "Owner workspace" : "Private tester workspace"}</span>
        </header>
        <div class="page">${body}</div>
      </div>
    </div>`;
  }

  function filteredVideos() {
    let list = (state.searched ? state.liveVideos : []).slice();
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

    const days = {
      "24h": 1,
      "3d": 3,
      "7d": 7,
      "30d": 30,
      "1y": 365,
      "any": 0,
    }[state.filters.time] ?? (state.discoverMode === "reference" ? 0 : 7);
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
        "&mode=" +
        encodeURIComponent(state.discoverMode) +
        "&max_results=25";
      const response = await fetch(url, { headers: workspaceHeaders() });
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
      return `<div class="empty"><h3>Loading real research data…</h3><p>The Dashboard reads from Christina Lab's persisted research history.</p></div>`;
    }

    const m = d.metrics || {};
    const opportunities = Array.isArray(d.topOpportunities) ? d.topOpportunities : [];
    const growth = Array.isArray(d.fastestActualGrowth) ? d.fastestActualGrowth : [];
    const mix = Array.isArray(d.contentMix) ? d.contentMix : [];
    const maturity = d.dataMaturity || {};
    const workflow = state.workflowSummary || {};
    const decisions = workflow.decisions || {};

    return `
      <div class="product-hero">
        <div>
          <div class="eyebrow">EVIDENCE-DRIVEN CREATOR WORKFLOW</div>
          <div class="product-title">Research what works. Create something original. Test it. Learn what works for you.</div>
          <p class="sub">Christina Lab connects public market signals with your own creator experiments so research and AI generation lead to measurable learning—not just more content.</p>
        </div>
      </div>

      <div class="creator-loop">
        <button class="creator-loop-step" data-go="/discover"><span>1</span><b>Research</b><small>Find real market signals</small></button>
        <button class="creator-loop-step" data-go="/ideas"><span>2</span><b>Create</b><small>Turn evidence into an original idea</small></button>
        <button class="creator-loop-step" data-go="/lab"><span>3</span><b>Test</b><small>Publish a measurable experiment</small></button>
        <button class="creator-loop-step" data-go="/analytics"><span>4</span><b>Learn</b><small>Compare market vs creator evidence</small></button>
      </div>

      <div class="section-label-row">
        <div>
          <div class="eyebrow">YOUR CREATOR LOOP</div>
          <h2>Your evidence</h2>
        </div>
        <p>These numbers come from what you explicitly saved, created and tested.</p>
      </div>
      <div class="metrics">
        <div class="metric"><label>Saved Research</label><div class="val num">${fmt(workflow.savedResearch || 0)}</div><div class="sec">references you chose to keep</div></div>
        <div class="metric"><label>Ideas</label><div class="val num">${fmt(workflow.ideas || 0)}</div><div class="sec">original concepts in your pipeline</div></div>
        <div class="metric"><label>Experiments</label><div class="val num">${fmt(workflow.experiments || 0)}</div><div class="sec">${fmt(workflow.publishedExperiments || 0)} published</div></div>
        <div class="metric"><label>GO / TEST / HOLD</label><div class="val num">${fmt(decisions.GO || 0)} · ${fmt(decisions.TEST || 0)} · ${fmt(decisions.HOLD || 0)}</div><div class="sec">decisions from real results</div></div>
      </div>

      <div class="section-label-row">
        <div>
          <div class="eyebrow">MARKET EVIDENCE</div>
          <h2>What this workspace is observing</h2>
        </div>
        <p>Public YouTube observations collected by this workspace help you spot opportunities. They are not your personal performance.</p>
      </div>
      <div class="metrics">
        <div class="metric"><label>Videos Observed Here</label><div class="val num">${fmt(m.videosTracked || 0)}</div><div class="sec">from this workspace's Discover searches</div></div>
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
    const topicSource = state.searched ? state.liveVideos : [];
    const topics = ["All", ...new Set(topicSource.map((v) => v.topic).filter(Boolean))];
    const option = (value, label) =>
      `<option value="${value}" ${state.filters.time === value ? "selected" : ""}>${label}</option>`;
    const referenceMode = state.discoverMode === "reference";
    const timeOptions = referenceMode
      ? [
          ["30d", "Last 30 days"],
          ["1y", "Last year"],
          ["any", "Any time"],
        ]
      : [
          ["24h", "Last 24 hours"],
          ["3d", "3 days"],
          ["7d", "7 days"],
          ["30d", "30 days"],
        ];

    return `
      <p class="sub">${referenceMode
        ? "Find proven videos to study for format, title, hook, pacing, and positioning — without limiting yourself to this week's uploads."
        : "Search real public YouTube data and compare velocity, engagement, and audience-normalized reach."}</p>
      <div class="filters" style="margin-bottom:10px">
        <button class="btn ${!referenceMode ? "primary" : "ghost"}" type="button" data-mode="trend">🔥 Trends</button>
        <button class="btn ${referenceMode ? "primary" : "ghost"}" type="button" data-mode="reference">🔎 References</button>
      </div>
      <form class="search-lg" id="ds">
        <input name="q" value="${esc(state.query)}" placeholder="${referenceMode ? "Describe the kind of video you want references for..." : "Search topics, keywords, or channels..."}" />
        <button class="btn primary" type="submit">${referenceMode ? "Find References" : "Search YouTube"}</button>
      </form>
      <div class="filters">
        <select id="ftime">
          ${timeOptions.map(([value, label]) => option(value, label)).join("")}
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
        ? `<div class="meta" style="margin:-4px 0 12px">${referenceMode
            ? "Reference mode ranks a relevance-first YouTube search using Christina Lab's existing explainable metrics. Use it to study precedents, not just this week's trends."
            : "Live YouTube Data · Historical same-age baselines are used when enough observations exist; otherwise Christina Lab clearly falls back to a provisional velocity estimate."}</div>`
        : ""}
      ${
        state.loading
          ? `<div class="card" style="padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`
          : state.apiError
          ? `<div class="empty"><h3>Couldn't load YouTube results</h3><p>${esc(state.apiError)}</p><button class="btn" id="retry">Retry</button></div>`
          : !state.searched
          ? `<div class="empty">
              <h3>${referenceMode ? "Find videos worth studying." : "Find your next content opportunity."}</h3>
              <p>${referenceMode
                ? "Search by the format or story you want to make — you do not need an exact topic match."
                : "Search real YouTube data by topic, niche, keyword, or channel."}</p>
              <div class="chips">${(referenceMode
                ? ["I built an app", "building an app from scratch", "coding project from scratch", "developer build vlog", "vibe coding an app", "build in public"]
                : ["AI tools", "coding projects", "trading mistakes", "trading signals", "build in public", "creator growth"])
                .map((s) => `<button class="chip" data-sug="${esc(s)}">${esc(s)}</button>`)
                .join("")}</div>
            </div>`
          : list.length === 0
          ? `<div class="empty"><h3>No YouTube videos found for this search.</h3><p>${referenceMode ? "Try describing the format more broadly, for example “I built an app” or “coding project from scratch”." : "Try a broader keyword or longer time range."}</p></div>`
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
      <p class="sub">Keep only references worth learning from. Add Why / Adapt / Angle, choose Short or Long-form, then generate an original idea from the evidence.</p>
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
              <div class="saved-agent-idea">
                <label>Content type
                  <select class="saved-agent-type" data-agent-type-for="${esc(v.videoId || v.id)}">
                    <option value="">Choose type…</option>
                    <option value="Short">Short</option>
                    <option value="Long-form">Long-form</option>
                  </select>
                </label>
                <button class="btn primary" data-act="agent-idea" data-id="${esc(v.videoId || v.id)}">Generate idea</button>
              </div>
              <div class="actions" style="margin-top:8px">
                <button class="btn" data-act="analyze" data-id="${esc(v.videoId || v.id)}">Open research</button>
                <button class="btn" data-act="idea" data-id="${esc(v.videoId || v.id)}">Manual idea</button>
                <button class="btn ghost" data-act="unsave" data-id="${esc(v.videoId || v.id)}">Remove</button>
              </div>
            </div>`).join("")}</div>`
        : `<div class="card"><table class="table"><thead><tr><th>Research</th><th>Opp</th><th>Outlier</th><th>Notes</th><th></th></tr></thead><tbody>
            ${items.map((v) => `<tr>
              <td><div class="t">${esc(v.title)}</div><div class="meta">${esc(v.channel)} · ${esc(v.topic || "Unspecified")}</div></td>
              <td class="num">${v.opportunity == null ? "—" : v.opportunity + "/100"}</td>
              <td class="outlier">${v.outlier == null ? "—" : Number(v.outlier).toFixed(1) + "×"}</td>
              <td>${[v.why, v.adapt, v.angle].filter(Boolean).length}/3 prompts</td>
              <td>
                <div class="saved-agent-table">
                  <select class="saved-agent-type" data-agent-type-for="${esc(v.videoId || v.id)}" aria-label="Content type">
                    <option value="">Type…</option>
                    <option value="Short">Short</option>
                    <option value="Long-form">Long-form</option>
                  </select>
                  <button class="btn primary" data-act="agent-idea" data-id="${esc(v.videoId || v.id)}">Generate idea</button>
                  <button class="btn" data-act="idea" data-id="${esc(v.videoId || v.id)}">Manual</button>
                  <button class="btn ghost" data-act="unsave" data-id="${esc(v.videoId || v.id)}">Remove</button>
                </div>
              </td>
            </tr>`).join("")}
          </tbody></table></div>`}
    `;
  }

  function creatorAgent() {
    if (!window.CL_CREATOR_AGENT) {
      return '<div class="empty"><h3>Creator Agent UI failed to load.</h3><p>Refresh the page and try again.</p></div>';
    }
    return window.CL_CREATOR_AGENT.render({
      configured: state.creatorAgentConfigured,
      provider: state.creatorAgentProvider,
      model: state.creatorAgentModel,
      providers: state.creatorAgentProviders,
    });
  }

  function ideas() {
    const gate = workflowGate();
    if (gate) return gate;
    const cols = ["Draft", "Ready", "Published"];
    return `
      <p class="sub">Original concepts built from research or your own direction. Use Documents to generate the script, production plan, AI Studio prompt and photo-reference brief, then turn the idea into an experiment.</p>
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
              <div class="meta">${esc(idea.topic || "Unspecified")} · ${esc(idea.type)} · ${esc(idea.priority)} priority${idea.sourceVideoId ? " · sourced from research" : ""} · ${Number(idea.documentCount || 0)} doc${Number(idea.documentCount || 0) === 1 ? "" : "s"}</div>
              <div class="actions" style="margin-top:8px">
                <button class="btn" data-docs="${idea.id}">Production Pack</button>
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
      <p class="sub">This is where an idea becomes evidence. Publish the test, record the real result, then choose GO / TEST / HOLD and let Christina Lab build your creator-specific playbook.</p>
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
          <thead><tr><th>Experiment</th><th>Topic</th><th>Status</th><th>24h</th><th>7d</th><th>Ret.</th><th>Subs</th><th>Decision</th><th></th></tr></thead>
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
              <td><button class="btn" type="button" data-edit-exp="${x.id}">Edit</button></td>
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
      <div class="experiment-page-head">
        <div>
          <p class="sub" style="margin-bottom:4px">EXP-${String(x.id).padStart(3, "0")} · ${esc(x.status)} · source idea ${idea ? esc(idea.title) : "#" + x.ideaId}</p>
          <h2 style="margin:0">${esc(x.name)}</h2>
          <div class="meta" style="margin-top:5px">${esc(x.topic || "Unspecified")} · ${esc(x.format || "")}</div>
        </div>
        <div class="actions experiment-page-actions">
          <button class="btn primary" type="button" data-edit-exp="${x.id}">Edit experiment</button>
          <button class="btn danger" type="button" data-delete-exp="${x.id}">Delete experiment</button>
        </div>
      </div>
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
        <div class="metric"><label>Videos Observed Here</label><div class="val num">${fmt(dataset.videosTracked || 0)}</div><div class="sec">this workspace's persisted research videos</div></div>
        <div class="metric"><label>Metric Snapshots</label><div class="val num">${fmt(dataset.snapshotsStored || 0)}</div><div class="sec">timestamped observations</div></div>
        <div class="metric"><label>Analyzed Search Results</label><div class="val num">${fmt(dataset.analyzedCandidates || 0)}</div><div class="sec">Discover candidates with stored scores</div></div>
        <div class="metric"><label>Measured Growth Histories</label><div class="val num">${fmt(dataset.growthPairs || 0)}</div><div class="sec">videos with 2+ snapshots</div></div>
      </div>

      <div class="grid2">
        <div class="card">
          <div class="card-h"><h2>Search Topic Signals</h2><p>Based only on this workspace's persisted Discover searches. More different queries = a more useful comparison.</p></div>
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
    const gate = workflowGate();
    if (gate) return gate;

    if (state.patternsLoading && !state.patternsData) {
      return `<div class="card" style="padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>`;
    }

    const summary = state.workflowSummary || {};
    const marketTopics = Array.isArray(state.patternsData?.topics) ? state.patternsData.topics : [];
    const creatorSignals = Array.isArray(state.learningSignals) ? state.learningSignals : [];
    const decisions = summary.decisions || {};

    return `
      <p class="sub">Keep market evidence and creator evidence separate. Public research tells you what may be worth testing; your own experiments tell you what actually works for you.</p>

      <div class="metrics">
        <div class="metric"><label>Saved Research</label><div class="val num">${fmt(summary.savedResearch || 0)}</div><div class="sec">real saved YouTube research</div></div>
        <div class="metric"><label>Experiments</label><div class="val num">${fmt(summary.experiments || 0)}</div><div class="sec">${fmt(summary.publishedExperiments || 0)} published</div></div>
        <div class="metric"><label>GO Decisions</label><div class="val num">${fmt(decisions.GO || 0)}</div><div class="sec">from recorded experiment results</div></div>
        <div class="metric"><label>Average 24h Views</label><div class="val num">${summary.average24hViews == null ? "—" : fmt(summary.average24hViews)}</div><div class="sec">only experiments with entered results</div></div>
      </div>

      <div class="grid2">
        <div class="card">
          <div class="card-h"><h2>Market Evidence</h2><p>What public research is showing by topic.</p></div>
          ${marketTopics.length
            ? marketTopics.map((row) => `<div class="rank">
                <span>${esc(row.topic)}</span>
                <span>${fmt(row.videos)} videos</span>
                <span>avg opp ${row.avgOpportunity == null ? "—" : Number(row.avgOpportunity).toFixed(1)}</span>
                <span>${row.medianOutlier == null ? "baseline pending" : Number(row.medianOutlier).toFixed(1) + "× median outlier"}</span>
              </div>`).join("")
            : `<div class="empty"><p>No market topic signals yet. Run real Discover searches to build this side of the comparison.</p><button class="btn primary" data-go="/discover">Open Discover</button></div>`}
        </div>

        <div class="card">
          <div class="card-h"><h2>Your Creator Evidence</h2><p>What your own recorded experiments currently support.</p></div>
          ${creatorSignals.length
            ? creatorSignals.map((row) => `<div class="rank">
                <span>${esc(row.topic)}</span>
                <span>${fmt(row.experiments)} experiment${Number(row.experiments) === 1 ? "" : "s"}</span>
                <span>GO ${fmt(row.GO || 0)} · TEST ${fmt(row.TEST || 0)} · HOLD ${fmt(row.HOLD || 0)}</span>
                <span>${row.avg24hViews == null ? "24h result pending" : "avg " + fmt(row.avg24hViews) + " views / 24h"}</span>
              </div>`).join("")
            : `<div class="empty"><p>No creator learning signal yet. Publish an experiment and record its real result to build Christina-specific evidence.</p><button class="btn primary" data-go="/lab">Open Experiments</button></div>`}
        </div>
      </div>`;
  }

  function watchlists() {
    return `
      <p class="sub">Watchlists are an experimental research utility and are not part of the primary Christina Lab workflow yet.</p>
      <div class="empty">
        <h3>No persisted watchlist items yet.</h3>
        <p>The old VibeFlow example channels and topic counters have been removed. When watchlist persistence is implemented, real saved items will appear here.</p>
        <button class="btn primary" data-go="/discover">Open Discover</button>
      </div>`;
  }

  function trustAccess() {
    const provider = state.creatorAgentConfigured
      ? esc((state.creatorAgentProvider || "AI") + (state.creatorAgentModel ? " · " + state.creatorAgentModel : ""))
      : "Not configured";
    return `
      <div class="trust-hero">
        <div class="eyebrow">PRIVATE ALPHA</div>
        <h2>You stay in control.</h2>
        <p>Christina Lab uses AI to help with research, ideas and production material. It does not publish to your social accounts, send messages, or browse your Google Drive.</p>
      </div>

      <div class="trust-grid">
        <div class="card trust-card">
          <h2>Workspace isolation</h2>
          <p><b>${state.workspaceIsOwner ? "Owner workspace" : "Private tester workspace"}</b></p>
          <p class="meta">Creator workflow data is scoped by an unguessable private-alpha workspace key. Saved research, Ideas, Production Packs, uploads and Experiments in this workspace are kept separate from other tester workspaces.</p>
          <p class="meta"><b>Alpha limitation:</b> this is invite-key isolation, not full account authentication yet. Anyone with a tester invite link can access that tester workspace, so treat the link like a password.</p>
          ${state.workspaceIsOwner ? `
            <div class="actions" style="justify-content:flex-start">
              <button class="btn primary" id="createTesterInvite">Create private tester link</button>
              <button class="btn" id="copyOwnerRecovery">Copy owner recovery link</button>
            </div>
            <p class="meta">Save your owner recovery link somewhere private. It is the key to your existing Christina Lab workspace if browser storage is cleared.</p>
          ` : '<p class="meta">This tester link cannot access the owner workspace or another tester\'s workspace.</p>'}
        </div>

        <div class="card trust-card">
          <h2>AI access</h2>
          <p class="meta">Current provider: <b>${provider}</b></p>
          <p>When you start an AI action, Christina Lab sends only the context needed for that generation. The first time you use each AI workflow, the app shows exactly what will be shared before continuing.</p>
          <div class="trust-list">
            <div>✓ Can generate ideas, scripts, plans and AI scene prompts</div>
            <div>✓ Can analyze research or transcripts you choose to use</div>
            <div>✕ Cannot publish to YouTube, TikTok or Instagram</div>
            <div>✕ Cannot send messages or change social accounts</div>
            <div>✕ Cannot independently execute actions without you starting the feature</div>
          </div>
        </div>

        <div class="card trust-card">
          <h2>Google Docs</h2>
          <p>Google Docs is optional. Christina Lab requests <code>drive.file</code>, which lets it create and work with files created through Christina Lab rather than granting access to your whole Drive.</p>
          <p class="meta">The Google access token is kept in browser memory for the session and is not stored in the Christina Lab database. Christina Lab stores the resulting Google Doc ID/link so it can show “Open Google Doc” later.</p>
        </div>

        <div class="card trust-card">
          <h2>What Christina Lab stores</h2>
          <p class="meta">Inside your private workspace:</p>
          <div class="trust-list">
            <div>• Saved Research and creator notes</div>
            <div>• Ideas and hypotheses</div>
            <div>• Generated Production Packs and uploaded idea files</div>
            <div>• Experiments, metrics, results, lessons and decisions</div>
            <div>• Google Doc IDs/links when you create a Google Doc</div>
          </div>
          <p class="meta">AI provider API keys and YouTube API keys stay server-side and are not exposed in the browser.</p>
        </div>
      </div>`;
  }

  function settings() {
    return `
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">General</h2>
        <p class="meta">Workspace name: Christina Lab · Language: English</p>
      </div>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">YouTube Data API</h2>
        <p class="meta">Status: ${state.youtubeConfigured ? "Configured on backend" : "Not configured"}</p>
        <p>${state.youtubeConfigured ? "Real Discover searches use the server-side YouTube Data API key." : "Add YOUTUBE_API_KEY on the backend to enable real YouTube research."}</p>
      </div>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">YouTube Creator Analytics</h2>
        <p class="meta">Status: Not connected</p>
        <p>Connect your own channel to automatically import experiment performance.</p>
        <button class="btn" type="button" disabled>Not connected yet</button>
      </div>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">Google Docs cloud upload</h2>
        <p class="meta">Status: ${googleDocsConfigured() ? "Configured · connect when you upload" : "Needs OAuth client ID"}</p>
        <p>Convert idea DOCX/TXT/Markdown attachments into editable Google Docs in your own Drive. Christina Lab requests only the <code>drive.file</code> scope, so it can access files it creates rather than your whole Drive.</p>
        ${googleDocsConfigured()
          ? `<button class="btn primary" id="googleConnect">Connect Google Drive</button>`
          : `<p class="meta">One-time setup: add <code>GOOGLE_OAUTH_CLIENT_ID</code> to the deployed service and authorize the live Christina Lab origin as a JavaScript origin.</p>`}
      </div>
      <div class="card" style="padding:14px;margin-bottom:12px">
        <h2 style="font-size:14px">AI assistance</h2>
        <p class="meta">Status: ${state.creatorAgentConfigured
          ? "Configured · " + esc(state.creatorAgentProvider || "AI") + " · " + esc(state.creatorAgentModel || "model ready")
          : "Not configured · default provider Gemini"}</p>
        <p>AI appears inside the creator workflow where it is useful: turning saved research into an idea, extracting short-worthy moments, and generating production packs. The evidence and final creative decisions stay with you.</p>
        ${state.creatorAgentConfigured
          ? '<div class="actions" style="justify-content:flex-start"><button class="btn" data-go="/saved">Use in Saved Research</button><button class="btn" data-go="/ideas">Use in Ideas</button><button class="btn ghost" data-go="/agent">Advanced source tools</button></div>'
          : '<p class="meta">For the free alpha: set <code>AI_PROVIDER=gemini</code> and add <code>GEMINI_API_KEY</code>. Optional fallbacks: Groq, OpenRouter, OpenAI, or a local OpenAI-compatible model.</p>'}
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
    if (!state.workspaceReady) {
      const message = state.workspaceError
        ? '<div class="workspace-gate"><div class="eyebrow">PRIVATE ALPHA</div><h2>Workspace access required</h2><p>' + esc(state.workspaceError) + '</p><p class="meta">Open the owner recovery link or a private tester invite link. Workspace links are secrets: anyone with the link can access that workspace during the alpha.</p></div>'
        : '<div class="workspace-gate"><div class="eyebrow">PRIVATE ALPHA</div><h2>Securing your workspace…</h2><p>Verifying private creator access before loading saved research, Ideas and Experiments.</p></div>';
      $("app").innerHTML = message;
      return;
    }
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
    } else if (path === "/agent") {
      title = "Advanced AI Workspace";
      body = creatorAgent();
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
    } else if (path === "/trust") {
      title = "Trust & Access";
      body = trustAccess();
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
        if (b.dataset.act === "agent-idea") {
          const select = document.querySelector('[data-agent-type-for="' + CSS.escape(id) + '"]');
          agentIdeaFromSaved(id, select ? select.value : "", b);
        }
      };
    });
    document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => navigate(b.dataset.go)));
    document.querySelectorAll("[data-sug]").forEach((b) => {
      b.onclick = () => runDiscoverSearch(b.dataset.sug);
    });
    document.querySelectorAll("[data-mode]").forEach((b) => {
      b.onclick = () => {
        const nextMode = b.dataset.mode === "reference" ? "reference" : "trend";
        if (nextMode === state.discoverMode) return;
        state.discoverMode = nextMode;
        state.filters.time = nextMode === "reference" ? "any" : "7d";
        state.filters.sort = "opp";
        state.apiError = "";
        if (state.query) runDiscoverSearch(state.query);
        else render();
      };
    });
    document.querySelectorAll("[data-view]").forEach((b) => {
      b.onclick = () => {
        state.savedView = b.dataset.view;
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
        state.filters = {
          time: state.discoverMode === "reference" ? "any" : "7d",
          type: "All",
          minViews: 0,
          sort: "opp",
          topic: "All",
        };
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
    if ((state.route.split("?")[0] || "/") === "/agent" && window.CL_CREATOR_AGENT) {
      window.CL_CREATOR_AGENT.bind({
        apiBase: API_BASE,
        rerender: render,
        toast,
        refreshWorkflow: async () => {
          state.workflowLoaded = false;
          await loadWorkflowData(true);
        },
      });
    }
    document.getElementById("newIdea")?.addEventListener("click", () => openIdeaModal(null));
    document.getElementById("newExperiment")?.addEventListener("click", () => openExperimentModal(null));
    document.querySelectorAll("[data-docs]").forEach((button) => {
      button.onclick = () => {
        const idea = state.ideas.find((item) => String(item.id) === String(button.dataset.docs));
        if (idea) openIdeaDocumentsModal(idea);
      };
    });
    document.querySelectorAll("[data-create-exp]").forEach((button) => {
      button.onclick = () => {
        const idea = state.ideas.find((item) => String(item.id) === String(button.dataset.createExp));
        if (idea) openExperimentModal(idea);
      };
    });
    document.querySelectorAll("[data-edit-exp]").forEach((button) => {
      button.onclick = () => {
        const exp = state.experiments.find((item) => String(item.id) === String(button.dataset.editExp));
        if (exp) openExperimentEditModal(exp);
      };
    });
    document.querySelectorAll("[data-delete-exp]").forEach((button) => {
      button.onclick = async () => {
        const exp = state.experiments.find((item) => String(item.id) === String(button.dataset.deleteExp));
        if (!exp) return;
        button.disabled = true;
        const deleted = await deleteExperiment(exp);
        if (!deleted) button.disabled = false;
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
    document.getElementById("createTesterInvite")?.addEventListener("click", async () => {
      const accessKey = randomWorkspaceKey();
      const link = workspaceLink(accessKey);
      try {
        await navigator.clipboard.writeText(link);
        toast("Private tester link copied");
      } catch (_) {
        window.prompt("Copy this private tester link. Treat it like a password:", link);
      }
    });
    document.getElementById("copyOwnerRecovery")?.addEventListener("click", async () => {
      const link = workspaceLink(state.workspaceAccessKey);
      try {
        await navigator.clipboard.writeText(link);
        toast("Owner recovery link copied");
      } catch (_) {
        window.prompt("Save this owner recovery link somewhere private:", link);
      }
    });
    document.getElementById("googleConnect")?.addEventListener("click", async () => {
      try {
        await ensureGoogleAccessToken();
        toast("Google Drive connected for this session");
        render();
      } catch (error) {
        toast(error?.message || "Could not connect Google Drive");
      }
    });
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
  (async () => {
    await loadPublicConfig();
    await bootstrapWorkspace();
    render();
    if (state.workspaceReady) {
      loadRouteData(state.route);
      const path = state.route.split("?")[0] || "/";
      if (path === "/settings" || path === "/agent" || path === "/trust") render();
    }
  })();
})();

/* Christina Lab Creator Agent UI */
(function () {
  const state = {
    loading: false,
    packageLoading: false,
    error: "",
    research: null,
    seed: null,
    result: null,
  };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function fmt(value) {
    const n = Number(value || 0);
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + "K";
    return String(n);
  }

  function defaultSeed() {
    return {
      project: "",
      goal: "Document my progress from code to career by showing what I build, learn, and test.",
      topic: "",
      repoUrl: "",
      contentType: "Long-form",
    };
  }

  function render(config) {
    const seed = state.seed || defaultSeed();
    const research = state.research;
    const result = state.result;
    const configured = Boolean(config && config.configured);
    const provider = String(config && config.provider || "gemini");
    const model = String(config && config.model || "");
    const sourceById = {};
    (research && research.sourceMaterials || []).forEach(function (source) {
      sourceById[String(source.id)] = source;
    });

    let html = "";
    html += '<div class="agent-hero card"><div>';
    html += '<span class="badge strong">Human chooses the angle</span>';
    html += '<h2 style="font-size:20px;margin:8px 0 6px">Research → choose → production package</h2>';
    html += '<p class="sub" style="margin:0">Give Christina Lab the seed. The agent studies reference videos, saved research, and an optional public GitHub repo. It proposes three directions first; it only writes the full package after you choose.</p>';
    html += '<div class="meta" style="margin-top:8px">AI: ' + esc(provider) + (model ? ' · ' + esc(model) : '') + ' · provider can be swapped without changing the workflow.</div>';
    html += '</div></div>';

    if (!configured) {
      html += '<div class="empty" style="margin-top:12px">';
      html += '<h3>Creator Agent needs one backend key.</h3>';
      html += '<p>For the free alpha, add <code>GEMINI_API_KEY</code> and keep <code>AI_PROVIDER=gemini</code>. Keys stay server-side and are never sent to the browser.</p>';
      html += '<button class="btn" data-go="/settings">Open Settings</button></div>';
    }

    html += '<div class="card" style="margin-top:12px;padding:14px">';
    html += '<h2 style="font-size:14px;margin-top:0">1 · Give it the seed</h2>';
    html += '<form class="form" id="agentResearchForm">';
    html += '<label>Project / topic<input name="project" required value="' + esc(seed.project) + '" placeholder="e.g. Weather App, Christina Lab, RiskDesk" /></label>';
    html += '<label>Goal<textarea name="goal" rows="2">' + esc(seed.goal) + '</textarea></label>';
    html += '<label>Search topic <span class="meta">optional — otherwise it uses the project name</span><input name="topic" value="' + esc(seed.topic) + '" placeholder="e.g. coding portfolio project" /></label>';
    html += '<label>Public GitHub repo <span class="meta">optional</span><input name="repoUrl" value="' + esc(seed.repoUrl) + '" placeholder="https://github.com/owner/repo" /></label>';
    html += '<label>Content type<select name="contentType">';
    html += '<option' + (seed.contentType === "Long-form" ? " selected" : "") + '>Long-form</option>';
    html += '<option' + (seed.contentType === "Short" ? " selected" : "") + '>Short</option>';
    html += '</select></label>';
    html += '<div class="actions"><button class="btn primary" type="submit"' + (!configured || state.loading ? " disabled" : "") + '>';
    html += state.loading ? "Researching…" : "Research & suggest 3 angles";
    html += '</button>';
    if (research) html += '<button class="btn ghost" type="button" id="agentReset">Start over</button>';
    html += '</div></form>';
    if (state.error) html += '<div class="meta agent-error">' + esc(state.error) + '</div>';
    html += '</div>';

    if (state.loading) {
      html += '<div class="card" style="margin-top:12px;padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div>';
      html += '<p class="meta">Searching reference videos, reading available project context, and comparing it with Christina Lab memory…</p></div>';
    }

    if (research) {
      html += '<div class="card" style="margin-top:12px;padding:14px">';
      html += '<div class="card-h"><h2>2 · What the agent found</h2><p>' + Number(research.youtubeCount || (research.sourceMaterials || []).length || 0) + ' YouTube references · ' + Number(research.savedResearchCount || 0) + ' saved research matches</p></div>';
      html += '<p>' + esc(research.summary) + '</p>';
      if (research.repoContext && research.repoContext.available) {
        html += '<div class="meta"><b>Repo:</b> ' + esc(research.repoContext.repository) + ' · ' + esc(research.repoContext.language || "language not detected") + ' · ' + (research.repoContext.files || []).length + ' files sampled</div>';
      } else {
        html += '<div class="meta"><b>Repo context:</b> ' + esc(research.repoContext && research.repoContext.reason || "Not provided") + '</div>';
      }
      html += '</div>';

      html += '<div class="card" style="margin-top:12px">';
      html += '<div class="card-h"><h2>Source material</h2><p>Study the pattern — do not copy the creator.</p></div>';
      if ((research.sourceMaterials || []).length) {
        research.sourceMaterials.forEach(function (source) {
          html += '<div class="agent-source"><div>';
          html += '<div class="t"><a href="' + esc(source.url) + '" target="_blank" rel="noopener">' + esc(source.title) + '</a></div>';
          html += '<div class="meta">' + esc(source.channel) + ' · ' + fmt(source.views) + ' views' + (source.opportunity == null ? "" : " · " + esc(source.opportunity) + "/100 opp") + '</div>';
          html += '</div><div><b>Study:</b> ' + esc(source.useFor || source.whyUseful) + '</div>';
          html += '<div class="meta"><b>Why:</b> ' + esc(source.whyUseful);
          if (source.caution) html += ' · <b>Caution:</b> ' + esc(source.caution);
          html += '</div></div>';
        });
      } else {
        html += '<div class="empty"><p>No strong reference source was selected. The agent can still work from repo and saved research evidence.</p></div>';
      }
      html += '</div>';

      html += '<div style="margin-top:12px"><div class="card-h"><h2>3 · Choose the direction</h2><p>Nothing becomes the production package until you choose.</p></div>';
      html += '<div class="grid3 agent-angle-grid">';
      (research.angles || []).forEach(function (angle) {
        const best = String(angle.id) === String(research.bestStartingAngleId || "");
        const sourceCount = (angle.sourceIds || []).filter(function (id) { return Boolean(sourceById[String(id)]); }).length;
        html += '<div class="card agent-angle' + (best ? " agent-angle-best" : "") + '" style="padding:14px">';
        html += '<div class="actions" style="justify-content:space-between"><span class="badge' + (best ? " strong" : "") + '">' + (best ? "Suggested start" : "Option") + '</span><span class="meta">' + sourceCount + ' source' + (sourceCount === 1 ? "" : "s") + '</span></div>';
        html += '<h3 style="margin:10px 0 6px">' + esc(angle.title) + '</h3>';
        html += '<div class="hook">' + esc(angle.hook) + '</div>';
        html += '<p style="font-size:13px">' + esc(angle.positioning) + '</p>';
        html += '<div class="meta"><b>Why it could work:</b> ' + esc(angle.whyThisCouldWork) + '</div>';
        html += '<div class="meta" style="margin-top:6px"><b>Your angle:</b> ' + esc(angle.whatMakesItYours) + '</div>';
        html += '<button class="btn primary" style="margin-top:12px;width:100%" data-agent-angle="' + esc(angle.id) + '"' + (state.packageLoading ? " disabled" : "") + '>';
        html += state.packageLoading ? "Building package…" : "Choose this & build package";
        html += '</button></div>';
      });
      html += '</div></div>';
    }

    if (state.packageLoading) {
      html += '<div class="card" style="margin-top:12px;padding:16px"><div class="skel"></div><div class="skel"></div><div class="skel"></div>';
      html += '<p class="meta">Writing the research brief, full script, and production blueprint from your approved angle…</p></div>';
    }

    if (result) {
      html += '<div class="card agent-result" style="margin-top:12px;padding:14px">';
      html += '<span class="badge strong">Package created</span>';
      html += '<h2 style="margin:8px 0 6px">' + esc(result.idea && result.idea.title || "Creator package") + '</h2>';
      html += '<p class="meta">Saved as a Draft idea with ' + (result.documents || []).length + ' attached production files · ' + esc(result.provider || provider) + ' · ' + esc(result.model || model) + '.</p>';
      if (result.videoBuilderReady) {
        html += '<div class="badge strong" style="margin-top:8px">Video Builder ready · scene manifest included</div>';
      }
      html += '<div class="grid2" style="margin-top:12px"><div><b>Thumbnail</b><p class="meta">' + esc(result.thumbnailConcept) + '</p></div>';
      html += '<div><b>CTA</b><p class="meta">' + esc(result.cta) + '</p></div></div>';
      html += '<div class="actions" style="margin-top:12px"><button class="btn primary" data-go="/ideas">Open Ideas</button>';
      (result.documents || []).forEach(function (doc) {
        html += '<a class="btn" href="/api/idea-documents/' + encodeURIComponent(doc.id) + '">' + esc(doc.filename) + '</a>';
      });
      html += '</div></div>';
    }

    return html;
  }

  async function apiJson(apiBase, path, options) {
    const config = Object.assign({}, options || {});
    if (config.body && typeof config.body !== "string") {
      config.headers = Object.assign({ "Content-Type": "application/json" }, config.headers || {});
      config.body = JSON.stringify(config.body);
    }
    const response = await fetch((apiBase || "") + path, config);
    if (!response.ok) {
      let message = "Creator Agent could not complete this request.";
      try {
        const payload = await response.json();
        if (payload.detail) message = payload.detail;
      } catch (_) {}
      throw new Error(message);
    }
    return response.json();
  }

  function bind(context) {
    const apiBase = context.apiBase || "";
    const rerender = context.rerender;
    const toast = context.toast || function () {};
    const refreshWorkflow = context.refreshWorkflow || async function () {};

    const form = document.getElementById("agentResearchForm");
    if (form) {
      form.onsubmit = async function (event) {
        event.preventDefault();
        const data = new FormData(form);
        state.seed = {
          project: String(data.get("project") || "").trim(),
          goal: String(data.get("goal") || "").trim(),
          topic: String(data.get("topic") || "").trim(),
          repoUrl: String(data.get("repoUrl") || "").trim(),
          contentType: String(data.get("contentType") || "Long-form"),
        };
        state.loading = true;
        state.error = "";
        state.research = null;
        state.result = null;
        rerender();
        try {
          state.research = await apiJson(apiBase, "/api/agent/research", {
            method: "POST",
            body: state.seed,
          });
        } catch (error) {
          state.error = error && error.message || "Creator Agent could not finish the research pass.";
        } finally {
          state.loading = false;
          rerender();
        }
      };
    }

    const reset = document.getElementById("agentReset");
    if (reset) reset.onclick = function () {
      state.research = null;
      state.result = null;
      state.error = "";
      rerender();
    };

    document.querySelectorAll("[data-agent-angle]").forEach(function (button) {
      button.onclick = async function () {
        if (!state.research || !state.seed) return;
        const angle = (state.research.angles || []).find(function (item) {
          return String(item.id) === String(button.dataset.agentAngle);
        });
        if (!angle) return;

        state.packageLoading = true;
        state.error = "";
        state.result = null;
        rerender();
        try {
          state.result = await apiJson(apiBase, "/api/agent/package", {
            method: "POST",
            body: Object.assign({}, state.seed, {
              angle: angle,
              sourceMaterials: state.research.sourceMaterials || [],
            }),
          });
          await refreshWorkflow();
          toast("Creator package saved to Ideas");
        } catch (error) {
          state.error = error && error.message || "Creator Agent could not build the production package.";
        } finally {
          state.packageLoading = false;
          rerender();
        }
      };
    });
  }

  window.CL_CREATOR_AGENT = {
    render: render,
    bind: bind,
  };
})();

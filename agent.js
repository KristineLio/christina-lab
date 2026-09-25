/* Christina Lab Creator Agent UI */
(function () {
  const state = {
    loading: false,
    packageLoading: false,
    error: "",
    research: null,
    seed: null,
    result: null,
    shortSourceId: "",
    shortTranscript: "",
    shortPlatform: "YouTube Shorts",
    shortDuration: 8,
    shortTranscriptLoading: false,
    shortTranscriptMeta: "",
    shortAnalyzing: false,
    shortGenerating: false,
    shortMoments: [],
    shortMomentId: "",
    shortPackage: null,
    shortReferenceName: "",
    shortReferenceDataUrl: "",
    shortError: "",
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

  function shortTime(value) {
    const total = Math.max(0, Number(value || 0));
    const minutes = Math.floor(total / 60);
    const seconds = Math.floor(total % 60);
    return minutes + ":" + String(seconds).padStart(2, "0");
  }

  function resetShortState(sourceId) {
    state.shortSourceId = String(sourceId || "");
    state.shortTranscript = "";
    state.shortPlatform = "YouTube Shorts";
    state.shortDuration = 8;
    state.shortTranscriptLoading = false;
    state.shortTranscriptMeta = "";
    state.shortAnalyzing = false;
    state.shortGenerating = false;
    state.shortMoments = [];
    state.shortMomentId = "";
    state.shortPackage = null;
    state.shortReferenceName = "";
    state.shortReferenceDataUrl = "";
    state.shortError = "";
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
          html += '</div><div class="actions agent-source-actions">';
          html += '<a class="btn ghost" href="' + esc(source.url) + '" target="_blank" rel="noopener">Open video</a>';
          html += '<button class="btn" type="button" data-agent-short-source="' + esc(source.id) + '">Source → Short</button>';
          html += '</div></div>';
        });
      } else {
        html += '<div class="empty"><p>No strong reference source was selected. The agent can still work from repo and saved research evidence.</p></div>';
      }
      html += '</div>';


      if (state.shortSourceId) {
        const shortSource = sourceById[String(state.shortSourceId)];
        if (shortSource) {
          const selectedMoment = (state.shortMoments || []).find(function (moment) {
            return String(moment.id) === String(state.shortMomentId);
          });

          html += '<div class="card agent-short-workspace" style="margin-top:12px;padding:14px">';
          html += '<div class="card-h agent-short-head"><div><span class="badge strong">Source → Short</span>';
          html += '<h2 style="margin:8px 0 4px">Turn one viral moment into an original AI short</h2>';
          html += '<p>Source: <b>' + esc(shortSource.title) + '</b> · ' + esc(shortSource.channel) + '</p></div>';
          html += '<button class="btn ghost" type="button" id="agentShortClose">Close</button></div>';

          html += '<form class="form agent-short-form" id="agentShortAnalyzeForm">';
          html += '<div class="agent-short-transcript-tools"><button class="btn" type="button" id="agentShortLoadTranscript"' + (state.shortTranscriptLoading ? ' disabled' : '') + '>' + (state.shortTranscriptLoading ? 'Loading transcript…' : 'Load YouTube transcript') + '</button>';
          html += '<span class="meta">' + esc(state.shortTranscriptMeta || 'If public captions are available, Christina Lab will timestamp them automatically. You can still paste a transcript manually.') + '</span></div>';
          html += '<label>Timestamped transcript<textarea name="transcript" rows="9" required placeholder="Paste the video transcript with timestamps, e.g. 00:43 ...">' + esc(state.shortTranscript) + '</textarea></label>';
          html += '<div class="grid2"><label>Target platform<select name="platform">';
          ["YouTube Shorts", "TikTok", "Instagram Reels"].forEach(function (platform) {
            html += '<option' + (state.shortPlatform === platform ? ' selected' : '') + '>' + esc(platform) + '</option>';
          });
          html += '</select></label><label>Generated video length<select name="duration">';
          [6, 8, 10, 12, 15].forEach(function (duration) {
            html += '<option value="' + duration + '"' + (Number(state.shortDuration) === duration ? ' selected' : '') + '>' + duration + ' seconds</option>';
          });
          html += '</select></label></div>';
          html += '<p class="meta">Christina Lab studies the source structure and meaning, not the creator\'s wording. Timestamped transcripts let it point you to the exact frame to capture.</p>';
          html += '<div class="actions"><button class="btn primary" type="submit"' + (state.shortAnalyzing ? ' disabled' : '') + '>' + (state.shortAnalyzing ? 'Finding moments…' : 'Find 3 strongest moments') + '</button></div>';
          html += '</form>';

          if (state.shortError) html += '<div class="meta agent-error">' + esc(state.shortError) + '</div>';

          if (state.shortAnalyzing) {
            html += '<div class="agent-short-loading"><div class="skel"></div><div class="skel"></div><p class="meta">Reading the transcript for reveals, open loops, mistakes, transformations and compact insights…</p></div>';
          }

          if ((state.shortMoments || []).length) {
            html += '<div class="agent-short-moments"><div class="card-h"><h2>Choose the moment</h2><p>Each option points to the frame Christina Lab wants you to use as the visual reference.</p></div>';
            html += '<div class="grid3">';
            state.shortMoments.forEach(function (moment) {
              const selected = String(moment.id) === String(state.shortMomentId);
              html += '<button type="button" class="card agent-short-moment' + (selected ? ' selected' : '') + '" data-agent-short-moment="' + esc(moment.id) + '">';
              html += '<span class="badge' + (selected ? ' strong' : '') + '">' + shortTime(moment.startSeconds) + '–' + shortTime(moment.endSeconds) + '</span>';
              html += '<h3>' + esc(moment.label) + '</h3>';
              html += '<p>' + esc(moment.sourceParaphrase) + '</p>';
              html += '<div class="meta"><b>Mechanism:</b> ' + esc(moment.mechanism) + '</div>';
              html += '<div class="meta" style="margin-top:6px"><b>Why:</b> ' + esc(moment.whyStrong) + '</div>';
              html += '<div class="agent-frame-time">Reference frame: ' + shortTime(moment.frameTimeSeconds) + '</div>';
              html += '</button>';
            });
            html += '</div></div>';
          }

          if (selectedMoment) {
            html += '<div class="agent-short-reference">';
            html += '<div><div class="card-h"><h2>Add the reference frame</h2><p>Take a screenshot from approximately <b>' + shortTime(selectedMoment.frameTimeSeconds) + '</b> in the source video.</p></div>';
            html += '<p class="meta">' + esc(selectedMoment.shortDirection) + '</p>';
            html += '<label class="btn agent-frame-upload">Choose reference image<input id="agentShortReference" type="file" accept="image/png,image/jpeg,image/webp" hidden /></label>';
            if (state.shortReferenceName) html += '<span class="meta" style="margin-left:8px">' + esc(state.shortReferenceName) + '</span>';
            html += '</div>';
            html += '<div class="agent-short-preview">';
            if (state.shortReferenceDataUrl) {
              html += '<img src="' + esc(state.shortReferenceDataUrl) + '" alt="Reference frame preview" />';
            } else {
              html += '<div class="agent-short-preview-empty">Reference frame<br>' + shortTime(selectedMoment.frameTimeSeconds) + '</div>';
            }
            html += '</div></div>';
            html += '<div class="actions" style="margin-top:12px"><button class="btn primary" type="button" id="agentShortGenerate"' + (state.shortGenerating ? ' disabled' : '') + '>' + (state.shortGenerating ? 'Building shorts…' : 'Generate AI Studio packages') + '</button></div>';
          }

          if (state.shortGenerating) {
            html += '<div class="agent-short-loading"><div class="skel"></div><div class="skel"></div><p class="meta">Writing three original short scripts, shot plans and paste-ready AI Studio prompts…</p></div>';
          }

          if (state.shortPackage && (state.shortPackage.variants || []).length) {
            html += '<div class="agent-short-results"><div class="card-h"><h2>AI Studio-ready packages</h2><p>Use the reference image above together with one prompt below.</p></div>';
            html += '<div class="grid3">';
            (state.shortPackage.variants || []).forEach(function (variant, index) {
              html += '<div class="card agent-short-variant">';
              html += '<span class="badge strong">' + esc(variant.name || ('Variant ' + (index + 1))) + '</span>';
              html += '<h3>' + esc(variant.hook) + '</h3>';
              html += '<div class="meta"><b>Voiceover</b></div><p>' + esc(variant.voiceover) + '</p>';
              html += '<div class="meta"><b>On-screen text</b></div><div class="hook">' + esc(variant.onScreenText) + '</div>';
              html += '<div class="meta" style="margin-top:8px"><b>Shot plan</b></div>';
              html += '<ol class="agent-shot-list">';
              (variant.shotPlan || []).forEach(function (shot) {
                html += '<li><b>' + Number(shot.start || 0).toFixed(1) + '–' + Number(shot.end || 0).toFixed(1) + 's</b> · ' + esc(shot.visual) + ' — ' + esc(shot.action) + '</li>';
              });
              html += '</ol>';
              html += '<div class="actions"><button class="btn primary" type="button" data-agent-short-copy="' + index + '">Copy AI Studio prompt</button>';
              html += '<button class="btn" type="button" data-agent-short-copy-script="' + index + '">Copy script</button></div>';
              html += '</div>';
            });
            html += '</div>';
            html += '<p class="meta" style="margin-top:10px">Generated with ' + esc(state.shortPackage.provider || provider) + (state.shortPackage.model ? ' · ' + esc(state.shortPackage.model) : '') + '. The prompt treats the image as visual reference, not permission to clone the source creator.</p>';
            html += '</div>';
          }

          html += '</div>';
        }
      }

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
    config.headers = Object.assign({}, config.headers || {});
    if (window.CL_WORKSPACE_ID) {
      config.headers["X-Christina-Workspace"] = window.CL_WORKSPACE_ID;
    }
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
        if (window.CL_CONFIRM_AI_SHARE && !window.CL_CONFIRM_AI_SHARE(
          "advanced-research",
          "Your project name, goal, topic, optional public GitHub repo URL, selected content type, matching saved research, and public YouTube research signals will be sent for this research pass."
        )) return;
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
      resetShortState("");
      rerender();
    };

    document.querySelectorAll("[data-agent-short-source]").forEach(function (button) {
      button.onclick = function () {
        resetShortState(button.dataset.agentShortSource);
        rerender();
      };
    });

    const shortClose = document.getElementById("agentShortClose");
    if (shortClose) shortClose.onclick = function () {
      resetShortState("");
      rerender();
    };

    const shortTranscriptButton = document.getElementById("agentShortLoadTranscript");
    if (shortTranscriptButton) {
      shortTranscriptButton.onclick = async function () {
        if (!state.research || !state.shortSourceId) return;
        const source = (state.research.sourceMaterials || []).find(function (item) {
          return String(item.id) === String(state.shortSourceId);
        });
        if (!source || !source.id) return;

        state.shortTranscriptLoading = true;
        state.shortError = "";
        state.shortTranscriptMeta = "Requesting public captions from YouTube…";
        rerender();
        try {
          const response = await apiJson(apiBase, "/api/agent/shorts/transcript/" + encodeURIComponent(source.id));
          state.shortTranscript = String(response.transcript || "");
          state.shortTranscriptMeta = (response.language || response.languageCode || "Transcript") +
            " · " + Number(response.snippetCount || 0) + " caption lines" +
            (response.isGenerated ? " · auto-generated captions" : "");
        } catch (error) {
          state.shortError = error && error.message || "Public captions could not be loaded. Paste the timestamped transcript manually.";
          state.shortTranscriptMeta = "Automatic transcript unavailable — manual paste still works.";
        } finally {
          state.shortTranscriptLoading = false;
          rerender();
        }
      };
    }

    const shortForm = document.getElementById("agentShortAnalyzeForm");
    if (shortForm) {
      shortForm.onsubmit = async function (event) {
        event.preventDefault();
        if (!state.research || !state.shortSourceId) return;
        const source = (state.research.sourceMaterials || []).find(function (item) {
          return String(item.id) === String(state.shortSourceId);
        });
        if (!source) return;

        const data = new FormData(shortForm);
        state.shortTranscript = String(data.get("transcript") || "").trim();
        state.shortPlatform = String(data.get("platform") || "YouTube Shorts");
        state.shortDuration = Number(data.get("duration") || 8);
        state.shortAnalyzing = true;
        state.shortError = "";
        state.shortMoments = [];
        state.shortMomentId = "";
        state.shortPackage = null;
        state.shortReferenceName = "";
        state.shortReferenceDataUrl = "";
        rerender();

        try {
          const response = await apiJson(apiBase, "/api/agent/shorts/analyze", {
            method: "POST",
            body: {
              source: source,
              transcript: state.shortTranscript,
              platform: state.shortPlatform,
            },
          });
          state.shortMoments = response.moments || [];
          state.shortMomentId = state.shortMoments[0] ? String(state.shortMoments[0].id) : "";
          if (!state.shortMoments.length) state.shortError = "No usable short moments were found in that transcript.";
        } catch (error) {
          state.shortError = error && error.message || "Christina Lab could not analyze that transcript.";
        } finally {
          state.shortAnalyzing = false;
          rerender();
        }
      };
    }

    document.querySelectorAll("[data-agent-short-moment]").forEach(function (button) {
      button.onclick = function () {
        state.shortMomentId = String(button.dataset.agentShortMoment || "");
        state.shortPackage = null;
        state.shortReferenceName = "";
        state.shortReferenceDataUrl = "";
        state.shortError = "";
        rerender();
      };
    });

    const referenceInput = document.getElementById("agentShortReference");
    if (referenceInput) {
      referenceInput.onchange = function () {
        const file = referenceInput.files && referenceInput.files[0];
        if (!file) return;
        if (!/^image\/(png|jpeg|webp)$/i.test(file.type || "")) {
          state.shortError = "Use a PNG, JPG or WebP reference frame.";
          rerender();
          return;
        }
        const reader = new FileReader();
        reader.onload = function () {
          state.shortReferenceName = file.name || "reference-frame";
          state.shortReferenceDataUrl = String(reader.result || "");
          state.shortError = "";
          rerender();
        };
        reader.onerror = function () {
          state.shortError = "Could not read that reference image.";
          rerender();
        };
        reader.readAsDataURL(file);
      };
    }

    const shortGenerate = document.getElementById("agentShortGenerate");
    if (shortGenerate) {
      shortGenerate.onclick = async function () {
        if (!state.research || !state.shortSourceId || !state.shortMomentId) return;
        const source = (state.research.sourceMaterials || []).find(function (item) {
          return String(item.id) === String(state.shortSourceId);
        });
        const moment = (state.shortMoments || []).find(function (item) {
          return String(item.id) === String(state.shortMomentId);
        });
        if (!source || !moment) return;

        state.shortGenerating = true;
        state.shortError = "";
        state.shortPackage = null;
        rerender();
        try {
          state.shortPackage = await apiJson(apiBase, "/api/agent/shorts/generate", {
            method: "POST",
            body: {
              source: source,
              transcript: state.shortTranscript,
              moment: moment,
              platform: state.shortPlatform,
              durationSeconds: Number(state.shortDuration || 8),
              hasReferenceFrame: Boolean(state.shortReferenceDataUrl),
            },
          });
        } catch (error) {
          state.shortError = error && error.message || "Christina Lab could not build the short package.";
        } finally {
          state.shortGenerating = false;
          rerender();
        }
      };
    }

    document.querySelectorAll("[data-agent-short-copy]").forEach(function (button) {
      button.onclick = async function () {
        const variant = state.shortPackage && (state.shortPackage.variants || [])[Number(button.dataset.agentShortCopy)];
        if (!variant) return;
        try {
          await navigator.clipboard.writeText(String(variant.aiStudioPrompt || ""));
          toast("AI Studio prompt copied");
        } catch (_) {
          toast("Could not copy the prompt");
        }
      };
    });

    document.querySelectorAll("[data-agent-short-copy-script]").forEach(function (button) {
      button.onclick = async function () {
        const variant = state.shortPackage && (state.shortPackage.variants || [])[Number(button.dataset.agentShortCopyScript)];
        if (!variant) return;
        const script = [variant.hook, variant.voiceover, variant.onScreenText].filter(Boolean).join("\n\n");
        try {
          await navigator.clipboard.writeText(script);
          toast("Short script copied");
        } catch (_) {
          toast("Could not copy the script");
        }
      };
    });

    document.querySelectorAll("[data-agent-angle]").forEach(function (button) {
      button.onclick = async function () {
        if (!state.research || !state.seed) return;
        const angle = (state.research.angles || []).find(function (item) {
          return String(item.id) === String(button.dataset.agentAngle);
        });
        if (!angle) return;

        if (window.CL_CONFIRM_AI_SHARE && !window.CL_CONFIRM_AI_SHARE(
          "advanced-package",
          "The chosen angle, project context, selected source materials, matching saved research, and public repo context will be sent to generate and save this creator package."
        )) return;
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

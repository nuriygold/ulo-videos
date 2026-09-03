"use strict";

const form = document.querySelector("#scene-form");
const resultPanel = document.querySelector("#result");
const errorPanel = document.querySelector("#error");
const specJson = document.querySelector("#spec-json");
const planSummary = document.querySelector("#plan-summary");
const downloadLink = document.querySelector("#download-link");
const submitButton = form.querySelector("button[type='submit']");

const IS_LOCAL = ["localhost", "127.0.0.1", "::1"].includes(location.hostname);

const RESOLVE = {
  ffmpegLocal:
    "Resolve: install FFmpeg (brew install ffmpeg), then restart this app's server and reload.",
  blenderLocal:
    "Resolve: install Blender (brew install --cask blender), then restart this app's server and reload.",
  deployed:
    "Resolve: this is the deployed copy — its server has no media tools. Run the app locally (PYTHONPATH=src python3 -m ulo_videos) to render with this machine's tools.",
  missingAsset:
    "Resolve: create the file(s) at the listed path(s) inside the project, then resubmit.",
  drawtext:
    "Resolve: this FFmpeg build lacks the drawtext filter — install a full build (brew reinstall ffmpeg) or render captions with a capable build.",
  planError:
    "Resolve: read the reason above — it names what the render host is missing.",
  submit: "Resolve: fix the issue named above, then submit again.",
  startServer:
    "Resolve: start the app's server (PYTHONPATH=src python3 -m ulo_videos), then try again.",
  localRenderer:
    "Resolve: start the local app (PYTHONPATH=src python3 -m ulo_videos) on this machine and reload — this panel will then report your machine's real toolchain.",
};

const LOCAL_PROBE_PORTS = [8000, 8080, 8777];

const DOWNLOADS = {
  ffmpeg: { url: "https://ffmpeg.org/download.html", label: "Download FFmpeg" },
  blender: { url: "https://www.blender.org/download/", label: "Download Blender" },
  python: { url: "https://www.python.org/downloads/", label: "Download Python" },
};

function buildPayload(formElement) {
  const payload = {};
  for (const field of formElement.elements) {
    if (!field.name) continue;
    const dot = field.name.indexOf(".");
    if (dot === -1) {
      payload[field.name] = field.value;
    } else {
      const group = field.name.slice(0, dot);
      payload[group] = payload[group] || {};
      payload[group][field.name.slice(dot + 1)] = field.value;
    }
  }
  return payload;
}

function resolutionLine(text, links) {
  const line = document.createElement("p");
  line.className = "resolution";
  line.textContent = text;
  for (const key of links || []) {
    const info = DOWNLOADS[key];
    if (!info) continue;
    line.append(" ");
    const anchor = document.createElement("a");
    anchor.className = "download-link";
    anchor.href = info.url;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.textContent = info.label;
    line.append(anchor);
  }
  return line;
}

function showError(message, resolution, links) {
  const messageLine = document.createElement("p");
  messageLine.textContent = message;
  errorPanel.replaceChildren(messageLine);
  if (resolution) errorPanel.append(resolutionLine(resolution, links));
  errorPanel.hidden = false;
}

function hideError() {
  errorPanel.hidden = true;
  errorPanel.replaceChildren();
}

function planLine(text, className) {
  const line = document.createElement("p");
  line.textContent = text;
  if (className) line.className = className;
  return line;
}

function renderPlan(plan, planError) {
  if (!plan) {
    planSummary.append(planLine(`Plan unavailable: ${planError || "unknown error"}`, "plan-missing"));
    if (planError && planError.includes("ffmpeg")) {
      planSummary.append(
        IS_LOCAL
          ? resolutionLine(RESOLVE.ffmpegLocal, ["ffmpeg"])
          : resolutionLine(RESOLVE.deployed, ["ffmpeg", "python"]),
      );
    } else {
      planSummary.append(resolutionLine(RESOLVE.planError));
    }
    return;
  }
  planSummary.append(planLine(`Plan status: ${plan.status}`, plan.status === "ready" ? "plan-ok" : "plan-missing"));
  const output = plan.output;
  planSummary.append(planLine(`Output: ${output.resolution[0]}x${output.resolution[1]} at ${output.fps} fps (${output.format})`));
  planSummary.append(planLine(`Command: ${plan.argv.join(" ")}`));
  if (plan.missing_assets.length) {
    const names = plan.missing_assets.map((entry) => entry.field).join(", ");
    planSummary.append(planLine(`Missing asset files: ${names}`, "plan-missing"));
    planSummary.append(resolutionLine(RESOLVE.missingAsset));
  }
  if (plan.captions.reason) {
    planSummary.append(planLine(`Captions: ${plan.captions.applied ? "burned in" : "not applied"} - ${plan.captions.reason}`));
    if (!plan.captions.applied && plan.captions.reason.includes("drawtext")) {
      planSummary.append(resolutionLine(RESOLVE.drawtext, ["ffmpeg"]));
    }
  }
}

function renderResult(body) {
  hideError();
  planSummary.replaceChildren();
  specJson.textContent = JSON.stringify(body.scene, null, 2);
  renderPlan(body.plan, body.plan_error);
  downloadLink.hidden = false;
  resultPanel.hidden = false;
}

function validToolReport(data) {
  return (
    !!data &&
    typeof data === "object" &&
    ["blender", "ffmpeg"].every(
      (name) => data[name] && typeof data[name].available === "boolean",
    )
  );
}

function probeLocalRenderer() {
  const attempts = LOCAL_PROBE_PORTS.map((port) =>
    fetch(`http://127.0.0.1:${port}/api/tools`, {
      signal: AbortSignal.timeout(1500),
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => (validToolReport(data) ? { port, report: data } : null))
      .catch(() => null),
  );
  return Promise.all(attempts).then((found) => found.find(Boolean) || null);
}

function toolItem(name, info, fixFor) {
  const item = document.createElement("li");
  const status = document.createElement("p");
  status.textContent = info.available
    ? `${name}: available (${info.path})`
    : `${name}: not installed on the machine running this app`;
  item.className = info.available ? "tool-ok" : "tool-missing";
  item.append(status);
  if (!info.available) item.append(fixFor(name));
  return item;
}

function toolRows(report, fixFor) {
  return Object.entries(report).map(([name, info]) => toolItem(name, info, fixFor));
}

function introItem(text, resolution) {
  const item = document.createElement("li");
  item.className = resolution ? "tool-missing" : "tool-ok";
  const line = document.createElement("p");
  line.textContent = text;
  item.append(line);
  if (resolution) item.append(resolution);
  return item;
}

function unreachableItem() {
  const item = document.createElement("li");
  const status = document.createElement("p");
  status.textContent = "Toolchain status unavailable; is the app's server running?";
  item.className = "tool-missing";
  item.append(status);
  item.append(resolutionLine(RESOLVE.startServer, ["python"]));
  return item;
}

const LOCAL_FIX = (name) =>
  resolutionLine(name === "blender" ? RESOLVE.blenderLocal : RESOLVE.ffmpegLocal, [name]);

const DEPLOYED_FIX = (name) => resolutionLine(RESOLVE.deployed, [name, "python"]);

function refreshToolStatus() {
  const list = document.querySelector("#tool-list");
  if (IS_LOCAL) {
    fetch("/api/tools")
      .then(async (response) => {
        if (!response.ok) throw new Error(`status ${response.status}`);
        list.replaceChildren(...toolRows(await response.json(), LOCAL_FIX));
      })
      .catch(() => list.replaceChildren(unreachableItem()));
    return;
  }
  probeLocalRenderer().then((found) => {
    if (found) {
      list.replaceChildren(
        introItem(
          `Detected the local renderer on 127.0.0.1:${found.port} — reporting this machine's real toolchain:`,
        ),
        ...toolRows(found.report, LOCAL_FIX),
      );
      return;
    }
    list.replaceChildren(
      introItem(
        "No local renderer detected on this machine (probed 127.0.0.1 ports 8000, 8080, 8777) — a web page cannot inspect installed programs by itself.",
        resolutionLine(RESOLVE.localRenderer, ["python"]),
      ),
    );
    fetch("/api/tools")
      .then(async (response) => {
        if (!response.ok) throw new Error(`status ${response.status}`);
        list.append(...toolRows(await response.json(), DEPLOYED_FIX));
      })
      .catch(() => list.append(unreachableItem()));
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitButton.disabled = true;
  try {
    const response = await fetch("/api/spec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload(form)),
    });
    const body = await response.json();
    if (!response.ok) {
      showError(
        body.error || `Request failed with status ${response.status}.`,
        RESOLVE.submit,
      );
      return;
    }
    renderResult(body);
  } catch {
    showError(
      "Could not reach the app's server; is it still running?",
      RESOLVE.startServer,
      ["python"],
    );
  } finally {
    submitButton.disabled = false;
  }
});

refreshToolStatus();
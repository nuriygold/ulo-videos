"use strict";

const form = document.querySelector("#scene-form");
const resultPanel = document.querySelector("#result");
const errorPanel = document.querySelector("#error");
const specJson = document.querySelector("#spec-json");
const planSummary = document.querySelector("#plan-summary");
const downloadLink = document.querySelector("#download-link");
const submitButton = form.querySelector("button[type='submit']");

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

function showError(message) {
  errorPanel.textContent = message;
  errorPanel.hidden = false;
}

function hideError() {
  errorPanel.hidden = true;
  errorPanel.textContent = "";
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
    return;
  }
  planSummary.append(planLine(`Plan status: ${plan.status}`, plan.status === "ready" ? "plan-ok" : "plan-missing"));
  const output = plan.output;
  planSummary.append(planLine(`Output: ${output.resolution[0]}x${output.resolution[1]} at ${output.fps} fps (${output.format})`));
  planSummary.append(planLine(`Command: ${plan.argv.join(" ")}`));
  if (plan.missing_assets.length) {
    const names = plan.missing_assets.map((entry) => entry.field).join(", ");
    planSummary.append(planLine(`Missing asset files: ${names}`, "plan-missing"));
  }
  if (plan.captions.reason) {
    planSummary.append(planLine(`Captions: ${plan.captions.applied ? "burned in" : "not applied"} - ${plan.captions.reason}`));
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

async function refreshToolStatus() {
  const list = document.querySelector("#tool-list");
  try {
    const response = await fetch("/api/tools");
    if (!response.ok) throw new Error(`status ${response.status}`);
    const report = await response.json();
    const items = Object.entries(report).map(([name, info]) => {
      const item = document.createElement("li");
      item.textContent = info.available ? `${name}: available (${info.path})` : `${name}: not installed`;
      item.className = info.available ? "tool-ok" : "tool-missing";
      return item;
    });
    list.replaceChildren(...items);
  } catch {
    const item = document.createElement("li");
    item.textContent = "Toolchain status unavailable; is the app's server running?";
    item.className = "tool-missing";
    list.replaceChildren(item);
  }
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
      showError(body.error || `Request failed with status ${response.status}.`);
      return;
    }
    renderResult(body);
  } catch {
    showError("Could not reach the app's server; is it still running?");
  } finally {
    submitButton.disabled = false;
  }
});

refreshToolStatus();

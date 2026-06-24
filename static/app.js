const form = document.querySelector("#summary-form");
const periodSelect = document.querySelector("#period");
const status = document.querySelector("#status");
const report = document.querySelector("#report");
const submitButton = form.querySelector("button");

const formatNumber = (value, suffix = "") => {
  if (value === null || value === undefined) return "No data";
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)}${suffix}`;
};

const formatDate = (value) => new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
}).format(new Date(value));

function renderFacts(statistics, units) {
  const facts = [
    ["Average temperature", formatNumber(statistics.temperature_mean, ` ${units.temperature}`)],
    ["Average humidity", formatNumber(statistics.humidity_mean, units.humidity)],
    ["Energy used", formatNumber(statistics.energy_kwh, ` ${units.energy}`)],
    ["Temperature coverage", formatNumber(statistics.temperature_coverage * 100, "%")],
  ];
  document.querySelector("#facts").replaceChildren(...facts.map(([label, value]) => {
    const card = document.createElement("article");
    card.className = "fact";
    const term = document.createElement("span");
    term.textContent = label;
    const measurement = document.createElement("strong");
    measurement.textContent = value;
    card.append(term, measurement);
    return card;
  }));
}

function renderEvents(events) {
  const list = document.querySelector("#events");
  const section = document.querySelector("#events-section");
  section.hidden = events.length === 0;
  list.replaceChildren(...events.map((event) => {
    const item = document.createElement("li");
    const title = event.kind.replaceAll("_", " ");
    item.innerHTML = `<strong></strong><span></span>`;
    item.querySelector("strong").textContent = title.charAt(0).toUpperCase() + title.slice(1);
    item.querySelector("span").textContent = `${formatNumber(Math.abs(event.change), ` ${event.unit}`)} · ${formatDate(event.start)}`;
    return item;
  }));
}

function renderWarnings(warnings) {
  const box = document.querySelector("#warnings");
  box.hidden = warnings.length === 0;
  document.querySelector("#warning-list").replaceChildren(...warnings.map((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitButton.disabled = true;
  report.hidden = true;
  status.className = "status loading";
  status.textContent = "Following the sensor trail…";

  try {
    const response = await fetch(`/api/summary?period=${encodeURIComponent(periodSelect.value)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "The investigation failed.");

    document.querySelector("#period-heading").textContent =
      `${formatDate(payload.period.start)} – ${formatDate(payload.period.end)}`;
    document.querySelector("#summary-text").textContent = payload.summary;
    renderFacts(payload.statistics, payload.units);
    renderEvents(payload.events);
    renderWarnings(payload.warnings);
    report.hidden = false;
    status.textContent = "";
  } catch (error) {
    status.className = "status error";
    status.textContent = error instanceof Error ? error.message : "The investigation failed.";
  } finally {
    submitButton.disabled = false;
  }
});

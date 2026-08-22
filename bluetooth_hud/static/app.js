"use strict";

const byId = (id) => document.getElementById(id);
const chart = byId("signalChart");
const chartContext = chart.getContext("2d");
const history = [];
const demoMode = new URLSearchParams(location.search).get("demo") === "1";

let websocket;
let reconnectTimer;
let heartbeatTimer;
let reconnectAttempts = 0;
let lastRssiAt = 0;
let lastSampleCount = -1;
let latestState = null;

const proximityLabels = {
  very_close: "Muito perto",
  close: "Perto",
  near: "Na área",
  far: "Longe",
  very_far: "Muito longe",
  unknown: "Aguardando sinal",
};

const eventLabels = {
  boot: "inicialização",
  rssi: "nova leitura de sinal",
  lan: "leitura da rede local",
  state: "estado atualizado",
  snapshot: "sincronização completa",
  "monitor-ready": "monitor conectado",
  "monitor-error": "falha no monitor",
};

function formatClock() {
  byId("clock").textContent = new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date());
}

function formatMediaTime(milliseconds) {
  if (milliseconds == null) return "--:--";
  const seconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatDbm(value, digits = 0) {
  return value == null ? "--" : `${Number(value).toFixed(digits)} dBm`;
}

function setText(id, value) { byId(id).textContent = value; }

function setConnectionState(state) {
  const badge = byId("socketStatus");
  badge.className = `connection-badge is-${state}`;
  badge.querySelector("span").textContent = state === "online" ? "Tempo real" : state === "demo" ? "Demonstração" : "Reconectando";
}

function showNotice(message) {
  setText("noticeText", message || "O serviço Bluetooth não respondeu. Confira o BlueZ e o dispositivo configurado.");
  byId("notice").hidden = false;
}

function hideNotice() { byId("notice").hidden = true; }

function signalToDistancePercent(rssi) {
  const clamped = Math.max(-95, Math.min(-45, rssi ?? -95));
  return ((-clamped - 45) / 50) * 100;
}

function seedHistory(values) {
  if (history.length || !Array.isArray(values)) return;
  history.push(...values.filter(Number.isFinite).slice(-80));
}

function appendHistory(value, sampleCount) {
  if (!Number.isFinite(value) || sampleCount === lastSampleCount) return;
  lastSampleCount = sampleCount;
  history.push(value);
  if (history.length > 80) history.shift();
  drawChart();
}

function drawChart() {
  const rect = chart.getBoundingClientRect();
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.round(rect.width * scale));
  const height = Math.max(1, Math.round(rect.height * scale));
  if (chart.width !== width || chart.height !== height) {
    chart.width = width;
    chart.height = height;
  }
  chartContext.clearRect(0, 0, width, height);
  byId("chartEmpty").hidden = history.length > 1;
  if (history.length < 2) return;

  const padLeft = 35 * scale;
  const padTop = 9 * scale;
  const padBottom = 7 * scale;
  const usableWidth = width - padLeft;
  const usableHeight = height - padTop - padBottom;
  const points = history.map((value, index) => ({
    x: padLeft + (index / Math.max(history.length - 1, 1)) * usableWidth,
    y: padTop + ((Math.max(-95, Math.min(-45, value)) + 45) / -50) * usableHeight,
  }));

  const fill = chartContext.createLinearGradient(0, 0, 0, height);
  fill.addColorStop(0, "rgba(142, 240, 189, .28)");
  fill.addColorStop(1, "rgba(142, 240, 189, 0)");
  chartContext.beginPath();
  chartContext.moveTo(points[0].x, height);
  points.forEach((point) => chartContext.lineTo(point.x, point.y));
  chartContext.lineTo(points.at(-1).x, height);
  chartContext.closePath();
  chartContext.fillStyle = fill;
  chartContext.fill();

  chartContext.beginPath();
  points.forEach((point, index) => index ? chartContext.lineTo(point.x, point.y) : chartContext.moveTo(point.x, point.y));
  chartContext.strokeStyle = "#9af4c4";
  chartContext.lineWidth = 1.6 * scale;
  chartContext.lineJoin = "round";
  chartContext.stroke();

  const current = points.at(-1);
  chartContext.beginPath();
  chartContext.arc(current.x, current.y, 3.2 * scale, 0, Math.PI * 2);
  chartContext.fillStyle = "#c1ffdd";
  chartContext.shadowColor = "#8ef0bd";
  chartContext.shadowBlur = 10 * scale;
  chartContext.fill();
  chartContext.shadowBlur = 0;
}

function renderConfidence(data, bluetoothFresh, lanFresh) {
  const bluetoothConnected = Boolean(data.connected && bluetoothFresh);
  const lanConnected = Boolean(data.lan_present && lanFresh);
  let score = 8;
  if (bluetoothConnected) score += 60;
  else if (bluetoothFresh) score += 34;
  if (lanConnected) score += 30;
  if (data.paired && data.trusted) score += 2;
  score = Math.min(100, score);

  setText("confidenceScore", score);
  byId("scoreRing").style.setProperty("--score", `${score * 3.6}deg`);
  setText("confidenceLabel", score >= 80 ? "Alta" : score >= 45 ? "Moderada" : "Baixa");
  setText("confidenceDescription",
    bluetoothConnected && lanConnected
      ? "Bluetooth recente e presença na rede confirmam o dispositivo."
      : bluetoothFresh
        ? "A posição vem do Bluetooth; a rede local ainda não confirmou presença."
        : lanConnected
          ? "A rede confirma presença, mas o sinal Bluetooth está desatualizado."
          : "Aguardando sinais recentes do Bluetooth e da rede local."
  );
}

function render(data) {
  latestState = data;
  if (data.monitor_status === "ready") hideNotice();
  const now = Date.now() / 1000;
  const bluetoothAge = data.rssi_updated_at ? now - data.rssi_updated_at : Infinity;
  const lanAge = data.lan_updated_at ? now - data.lan_updated_at : Infinity;
  const bluetoothFresh = bluetoothAge < 3;
  const lanFresh = lanAge < 2;
  const signal = data.rssi_smooth ?? data.rssi;

  lastRssiAt = data.rssi_updated_at || lastRssiAt;
  setText("proximity", proximityLabels[data.proximity] || proximityLabels.unknown);
  setText("rssi", signal == null ? "--" : Math.round(signal));
  setText("raw", formatDbm(data.rssi));
  setText("median", formatDbm(data.rssi_median, 1));
  setText("filtered", formatDbm(data.rssi_smooth, 1));
  setText("samples", data.rssi_samples ?? 0);
  setText("sampleRate", data.rssi_rate_hz ? `${data.rssi_rate_hz.toFixed(1)} Hz` : "-- Hz");

  const trend = byId("trend");
  if (data.rssi_trend === "approaching") {
    trend.textContent = "↗ aproximando";
    trend.className = "trend-pill is-approaching";
  } else if (data.rssi_trend === "moving_away") {
    trend.textContent = "↘ afastando";
    trend.className = "trend-pill is-away";
  } else {
    trend.textContent = "→ estável";
    trend.className = "trend-pill is-stable";
  }

  const distancePercent = signalToDistancePercent(signal);
  const meter = byId("proximityMeter");
  const marker = byId("proximityMarker");
  marker.style.left = `${3 + distancePercent * .94}%`;
  marker.classList.toggle("is-stale", !bluetoothFresh);
  meter.setAttribute("aria-valuenow", String(Math.round(distancePercent)));
  meter.setAttribute("aria-valuetext", proximityLabels[data.proximity] || proximityLabels.unknown);
  setText("markerLabel", (data.name || "dispositivo").split(" ")[0]);

  seedHistory(data.rssi_filtered_recent);
  appendHistory(signal, data.rssi_samples ?? 0);
  setText("deviceName", data.name || "Dispositivo desconhecido");
  setText("address", data.address || "--");
  setText("battery", data.battery == null ? "--%" : `${data.battery}%`);
  byId("batteryBar").style.width = `${Math.max(0, Math.min(100, data.battery ?? 0))}%`;
  setText("connected", data.connected ? "Conectado" : "Desconectado");
  byId("connected").className = `status-value ${data.connected ? "is-on" : "is-off"}`;
  setText("paired", data.paired ? "Sim" : "Não");
  setText("trusted", data.trusted ? "Sim" : "Não");
  setText("source", (data.rssi_source || "--").toUpperCase());

  setText("btSensor", bluetoothFresh ? "Sinal recente" : "Sem sinal recente");
  setText("btDetail", bluetoothFresh ? `${formatDbm(signal)} · ${data.rssi_source?.toUpperCase() || "D-Bus"}` : "Aguardando RSSI");
  byId("btLed").className = `sensor-led ${bluetoothFresh ? "is-on" : "is-off"}`;

  const lanAvailable = Boolean(data.lan_present && lanFresh);
  setText("lanSensor", lanAvailable ? "Presença confirmada" : "Não detectado");
  setText("lanDetail", data.lan_target_ip ? `${data.lan_target_ip}${data.lan_rtt_ms == null ? "" : ` · ${data.lan_rtt_ms.toFixed(1)} ms`}` : "Nenhum alvo definido");
  byId("lanLed").className = `sensor-led ${lanAvailable ? "is-on" : data.lan_target_ip ? "is-warn" : "is-off"}`;

  const playerStatus = data.player_status || "stopped";
  setText("player", data.player_status ? playerStatus === "playing" ? "Reproduzindo" : playerStatus === "paused" ? "Pausado" : "Parado" : "Nenhum player");
  setText("mediaIcon", playerStatus === "playing" ? "▶" : playerStatus === "paused" ? "Ⅱ" : "■");
  setText("position", formatMediaTime(data.player_position_ms));
  setText("lastEvent", `Último evento: ${eventLabels[data.last_event] || data.last_event || "--"}`);
  renderConfidence(data, bluetoothFresh, lanFresh);
  updateFreshness();
}

function updateFreshness() {
  const element = byId("freshness");
  if (!lastRssiAt) {
    element.textContent = "sem amostras";
    element.className = "freshness is-stale";
    return;
  }
  const age = Math.max(0, Date.now() / 1000 - lastRssiAt);
  if (age < 1) {
    element.textContent = "ao vivo";
    element.className = "freshness is-live";
  } else if (age < 3) {
    element.textContent = `${age.toFixed(1)}s atrás`;
    element.className = "freshness is-recent";
  } else {
    element.textContent = `${Math.round(age)}s atrás`;
    element.className = "freshness is-stale";
  }
  if (latestState) {
    const lanFresh = latestState.lan_updated_at ? Date.now() / 1000 - latestState.lan_updated_at < 2 : false;
    renderConfidence(latestState, age < 3, lanFresh);
  }
}

function connect() {
  clearTimeout(reconnectTimer);
  clearInterval(heartbeatTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  websocket = new WebSocket(`${protocol}//${location.host}/ws`);
  websocket.addEventListener("open", () => {
    reconnectAttempts = 0;
    setConnectionState("online");
    hideNotice();
    heartbeatTimer = window.setInterval(() => {
      if (websocket.readyState === WebSocket.OPEN) websocket.send("ping");
    }, 15000);
  });
  websocket.addEventListener("message", (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "telemetry") render(message.data);
    if (message.type === "error") showNotice(message.message);
  });
  websocket.addEventListener("close", () => {
    clearInterval(heartbeatTimer);
    setConnectionState("offline");
    reconnectAttempts += 1;
    const delay = Math.min(10000, 600 * (2 ** Math.min(reconnectAttempts, 4))) + Math.random() * 350;
    reconnectTimer = window.setTimeout(connect, delay);
  });
  websocket.addEventListener("error", () => websocket.close());
}

function createDemoState(step) {
  const now = Date.now() / 1000;
  const phase = step / 8;
  const signal = Math.round(-67 + Math.sin(phase) * 9 + Math.sin(phase * .32) * 4);
  const previous = history.at(-1) ?? signal;
  const slope = signal - previous;
  return {
    name: "Galaxy A17", address: "EC:B5:50:••:••:9C", monitor_status: "ready", connected: true, paired: true, trusted: true, battery: 76,
    rssi: signal + Math.round(Math.sin(step) * 2), rssi_median: signal, rssi_smooth: signal + Math.sin(phase * 1.5),
    rssi_trend: slope > 1.1 ? "approaching" : slope < -1.1 ? "moving_away" : "stable", rssi_trend_slope: slope,
    rssi_samples: Math.max(1, step), rssi_updated_at: now, rssi_source: "dbus", rssi_rate_hz: 2,
    proximity: signal >= -62 ? "very_close" : signal >= -68 ? "close" : signal >= -75 ? "near" : signal >= -82 ? "far" : "very_far",
    rssi_recent: history.slice(-20), rssi_filtered_recent: history.slice(-20),
    lan_target_ip: "192.168.1.42", lan_present: true, lan_rtt_ms: 3.2 + Math.sin(phase) * .8, lan_rate_hz: 2,
    lan_updated_at: now, lan_target_mode: "configured", lan_candidates: [],
    player_status: "playing", player_position_ms: 98000 + step * 500, last_event: "rssi", updated_at: now,
  };
}

function startDemo() {
  setConnectionState("demo");
  byId("demoMark").hidden = false;
  let step = 1;
  for (; step < 28; step += 1) render(createDemoState(step));
  window.setInterval(() => render(createDemoState(step++)), 500);
}

window.addEventListener("resize", drawChart);
document.addEventListener("visibilitychange", () => {
  if (!demoMode && document.visibilityState === "visible" && (!websocket || websocket.readyState === WebSocket.CLOSED)) connect();
});

formatClock();
window.setInterval(formatClock, 1000);
window.setInterval(updateFreshness, 250);
demoMode ? startDemo() : connect();

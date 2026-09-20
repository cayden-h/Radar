/* The browser surface.
 *
 * It exists to demonstrate one property: the backend is shared. A button here
 * does exactly what the same button does on the phone and the watch, and all
 * three see the result, because every one of them goes through
 * HubRuntime.emit().
 *
 * The camera rule this page obeys: a frame that is not current is never drawn
 * as if it were. It is dimmed and captioned, or replaced by the unreachable
 * state. A frozen picture of an empty room is the most dangerous thing this
 * system can display.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const api = (path) => new URL(path, window.location.origin).toString();

let activeIncidentId = null;
let cameraAttached = false;

function addEvent(kind, text, refusal = false) {
  const li = document.createElement("li");
  if (refusal) li.className = "refusal";
  const label = document.createElement("div");
  label.className = "kind";
  label.textContent = `${kind} · ${new Date().toLocaleTimeString()}`;
  const body = document.createElement("div");
  body.textContent = text;
  li.append(label, body);
  $("events").prepend(li);
}

/* Attaching the MJPEG stream is separate from rendering status, because an
 * <img> whose src is reassigned tears down and rebuilds the connection. It is
 * attached once and left alone. */
function attachCamera() {
  if (cameraAttached) return;
  cameraAttached = true;
  const img = $("camera");
  img.src = api(`/v1/camera/live?t=${Date.now()}`);
  img.hidden = false;
}

/* Registered once, not per attach.
 *
 * The stream ending means the backend stopped sending parts, which means
 * frames stopped arriving. Mark it detached so the next poll can re-attach,
 * but **leave the frame on screen**: it is still the last thing the camera
 * saw, the overlay already says so, and hiding it produced a flicker on
 * exactly the screen that is supposed to communicate a failure calmly. */
$("camera").addEventListener("error", () => {
  cameraAttached = false;
});

function renderCamera(status) {
  const img = $("camera");
  const overlay = $("cameraOverlay");
  $("cameraStatus").textContent = status.detail || "";

  if (status.live) {
    attachCamera();
    img.classList.remove("stale");
    overlay.hidden = true;
    return;
  }

  if (!status.frames_received) {
    img.hidden = true;
    overlay.hidden = false;
    overlay.textContent = status.linked
      ? "Camera connected but no frames have arrived yet."
      : "No camera. The edge box has not connected.";
    return;
  }

  // There is a frame, but it is not current. Show it dimmed, and say so. It is
  // a true statement about the last thing the camera saw; what would be false
  // is presenting it as the room right now.
  attachCamera();
  img.classList.add("stale");
  overlay.hidden = false;
  const age = status.last_frame_age_s;
  overlay.textContent =
    "Camera unreachable. This is the last frame seen" +
    (age ? `, ${age.toFixed(0)}s ago.` : ".");
}

function renderShield(payload) {
  const el = $("shield");
  el.className = "shield";

  if (payload.refused) {
    el.classList.add("refused");
    el.textContent =
      "Shield: refused. Something asked to open the camera and could not " +
      `prove it was allowed to (${payload.refusal_reason}).`;
    return;
  }

  /* Not a refusal, and not a status update either. Nobody refused anything;
   * the shutter went quiet, so whether the camera is covered is genuinely not
   * known. That is the one shield state a reader must not skim past, so it
   * gets the same weight as a refusal and keeps its reason. */
  if (payload.position === "unknown") {
    el.classList.add("refused");
    el.textContent =
      "Shield: position unknown. The shutter did not answer" +
      (payload.refusal_reason ? ` (${payload.refusal_reason})` : "") +
      ", so whether the camera is covered is not known.";
    return;
  }

  if (payload.position === "open") el.classList.add("open");
  el.textContent =
    `Shield: ${payload.position} (${payload.position_basis}, ` +
    "the servo has no position feedback)";
}

async function refreshHub() {
  try {
    const res = await fetch(api("/v1/hub"));
    const hub = await res.json();
    $("mode").textContent = hub.mode;
    $("hub").textContent = `${hub.hub_name} · ${hub.site_address}`;
    renderCamera(hub.camera);
  } catch (err) {
    $("hub").textContent = "Hub unreachable.";
    $("cameraStatus").textContent = "";
  }
}

function connectStream() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${proto}//${window.location.host}/v1/stream`);

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data).payload;
    switch (payload.kind) {
      case "frame":
        // The MJPEG element carries the picture on this surface; this event is
        // for the watch. Used here only to keep the live label honest between
        // status polls.
        $("camera").classList.toggle("stale", !payload.live);
        break;
      case "narration":
        addEvent(`narration · ${payload.room}`, payload.text);
        break;
      case "occupancy":
        addEvent(
          `occupancy · ${payload.room}`,
          payload.person_present
            ? `${payload.people} person(s) visible`
            : "nobody visible"
        );
        break;
      case "notice":
        addEvent(
          payload.notice.dismissed ? "notice cleared" : "notice",
          `${payload.notice.title}: ${payload.notice.body}`
        );
        break;
      case "incident":
        activeIncidentId = payload.incident.incident_id;
        addEvent("incident", `${payload.phase}: ${payload.incident.incident_id}`);
        break;
      case "shield":
        renderShield(payload);
        addEvent(
          "shield",
          payload.refused
            ? `REFUSED: ${payload.refusal_reason}`
            : payload.position === "unknown"
              ? `POSITION UNKNOWN: ${payload.refusal_reason || "the shutter did not answer"}`
              : `${payload.position} (${payload.position_basis})`,
          payload.refused || payload.position === "unknown"
        );
        break;
      case "verification":
        addEvent(
          "verification",
          `${payload.result.decision}: ${payload.result.detail || ""}`,
          payload.result.decision === "DISCARDED"
        );
        break;
      case "transcript":
        addEvent(`transcript · ${payload.line.speaker}`, payload.line.text);
        break;
      case "context":
        addEvent("context", payload.note.text);
        break;
      case "hello":
        addEvent("connected", `${payload.hub_name} (${payload.mode})`);
        activeIncidentId = payload.active_incident_id;
        break;
      default:
        break;
    }
  });

  socket.addEventListener("close", () => {
    addEvent("disconnected", "Stream closed. Retrying in 2s.");
    setTimeout(connectStream, 2000);
  });
}

async function post(path, body) {
  const res = await fetch(api(path), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = JSON.parse(detail).detail || detail;
    } catch (err) {
      /* not JSON, use the raw text */
    }
    addEvent("error", `${path} failed: ${res.status} ${detail}`, true);
    return null;
  }
  return res.json();
}

/* Hold to confirm, 1.5s, same as the phone and the watch.
 *
 * `app/CLAUDE.md` singles this control out: "An accidental tap calls 911. A
 * pocket-dial to emergency services is a real harm, not an inconvenience." A
 * browser left open on a desk is the surface most likely to be clicked by
 * somebody walking past, so it gets the same gesture rather than less.
 *
 * Hold rather than a confirm dialog, for the reason the phone uses: a dialog
 * makes you find a second target, and it can be dismissed by accident too. A
 * hold gives continuous feedback and release-to-cancel. */
const HOLD_MS = 1500;

function holdToConfirm(button, action) {
  let timer = null;
  let started = 0;

  const paint = () => {
    if (!timer) return;
    const progress = Math.min(1, (performance.now() - started) / HOLD_MS);
    button.style.setProperty("--hold", `${progress * 100}%`);
    requestAnimationFrame(paint);
  };

  const begin = (event) => {
    event.preventDefault();
    if (timer) return;
    started = performance.now();
    button.classList.add("holding");
    timer = setTimeout(() => {
      cancel();
      action();
    }, HOLD_MS);
    requestAnimationFrame(paint);
  };

  const cancel = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    button.classList.remove("holding");
    button.style.setProperty("--hold", "0%");
  };

  button.addEventListener("pointerdown", begin);
  button.addEventListener("pointerup", cancel);
  button.addEventListener("pointerleave", cancel);
  button.addEventListener("pointercancel", cancel);
  // Keyboard reach: space or enter on a focused button fires click, which
  // would bypass the hold entirely. Swallow it and say why.
  button.addEventListener("click", (event) => event.preventDefault());
}

holdToConfirm($("startIncident"), async () => {
  const ack = await post("/v1/incident", { incident_type: "burglary" });
  if (ack) activeIncidentId = ack.incident_id;
});

$("openShutter").addEventListener("click", () =>
  post("/v1/shutter", { action: "open", reason: "opened from the web console" })
);
$("closeShutter").addEventListener("click", () =>
  post("/v1/shutter", { action: "close", reason: "closed from the web console" })
);

$("contextForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("contextText").value.trim();
  if (!text) return;
  if (!activeIncidentId) {
    addEvent("error", "No active incident to attach context to.", true);
    return;
  }
  const note = await post(`/v1/incident/${activeIncidentId}/context`, { text });
  if (note) $("contextText").value = "";
});

refreshHub();
setInterval(refreshHub, 3000);
connectStream();

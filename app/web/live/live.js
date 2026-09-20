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
  // If the stream ends, the backend stopped sending parts, which means frames
  // stopped arriving. Detach so the next status poll can re-attach rather than
  // leaving the last part painted forever.
  img.addEventListener("error", () => {
    cameraAttached = false;
    img.hidden = true;
  });
}

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
            : `${payload.position} (${payload.position_basis})`,
          payload.refused
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

$("startIncident").addEventListener("click", async () => {
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

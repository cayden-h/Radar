/* Hawk Eye replay console.
 *
 * Vanilla, no build, no CDN. Two entry points: HawkEye.index() draws the list
 * of records, HawkEye.record() draws one of them.
 *
 * Two decisions worth knowing before reading:
 *
 * 1. While a record is open the page POLLS `?since_seq=N` once a second rather
 *    than joining the websocket. A log a human reads does not need sub-second
 *    latency, and one channel is one thing to debug. The map here therefore
 *    trails the phone by up to a second, which is correct: this is the record,
 *    not a second live dashboard.
 *
 * 2. The chain is verified IN THIS BROWSER, over the record as served. A server
 *    that will lie about a record will also lie about having checked it, so the
 *    check that matters is the one the reader can run themselves.
 */

const HawkEye = (() => {
  const API = "/v1";

  // ------------------------------------------------------------------ helpers

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  async function getText(path) {
    const res = await fetch(path, { headers: { accept: "application/json" } });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`);
    return res.text();
  }

  async function getJSON(path) {
    return JSON.parse(await getText(path));
  }

  const clock = (iso) => {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour12: false }) + "." +
      String(d.getMilliseconds()).padStart(3, "0");
  };

  const stamp = (iso) => new Date(iso).toLocaleString([], { hour12: false });

  function duration(seconds) {
    const s = Math.max(0, Math.round(seconds));
    const m = Math.floor(s / 60);
    return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
  }

  function fail(message) {
    document.body.innerHTML = "";
    const box = el("div", "empty");
    box.append(el("h2", null, "Could not load the record"), el("p", null, message));
    const hint = el("p", "hint", "Is the hub running? ");
    hint.append(el("code", null, "cd app/backend && ./scripts/demo.sh"));
    box.append(hint);
    document.body.append(box);
  }

  // --------------------------------------------------------------- the index

  async function index() {
    let data;
    try {
      data = await getJSON(`${API}/replay`);
    } catch (err) {
      return fail(String(err));
    }

    $("hubline").textContent =
      `${data.hub_name} · ${data.mode} · ${data.caller_ansname}`;
    $("topmeta").append(
      el("span", "stamp", `${data.records.length} record${data.records.length === 1 ? "" : "s"}`)
    );

    drawArchive(data.archive);

    if (!data.records.length) {
      $("empty").hidden = false;
      return;
    }

    const host = $("records");
    for (const r of data.records) {
      const card = el("a", "card");
      card.href = `record.html?incident=${encodeURIComponent(r.incident_id)}`;

      const type = el("div", `type ${r.incident_type}`, r.incident_type);
      // Only the archived rows are labelled. A row this hub is currently
      // holding is the unremarkable case and does not need a badge saying so;
      // a row read back out of storage was written by a process that is gone,
      // and that is a different claim.
      if (r.source === "archive") {
        const badge = el("span", "src", "archived");
        badge.title =
          "Read back from the replay archive. This hub did not record it in " +
          "this run; it was written by an earlier one and stored.";
        type.append(badge);
      }
      card.append(type);
      card.append(el("div", "when", stamp(r.opened_at)));
      card.append(el("div", "addr", r.address));

      const dl = el("dl");
      const stat = (label, value, bad) => {
        // Each pair wrapped, because a three-column grid fed a flat run of
        // dt/dd fills row-major and pairs them with the wrong neighbour.
        const cell = el("div");
        cell.append(el("dt", null, label), el("dd", bad ? "bad" : null, value));
        dl.append(cell);
      };
      stat("Entries", String(r.entries));
      stat("Duration", duration(r.duration_s));
      // Discards are shown on the index deliberately. What the system refused to
      // repeat to a dispatcher is the interesting number, not the total.
      stat("Discarded", String(r.discarded), r.discarded > 0);
      card.append(dl);

      const state = el("div", "root");
      state.textContent = r.sealed
        ? `sealed · root ${(r.root_hash || "").slice(0, 24)}…`
        : "RECORDING · not yet sealed";
      card.append(state);
      host.append(card);
    }
  }

  /* Whether sealed records are outliving this process.
   *
   * Drawn on every load rather than only when something is wrong. A page that
   * only speaks up on failure teaches the reader that silence means healthy,
   * and silence here is also what a page that forgot to check looks like.
   */
  function drawArchive(status) {
    const host = $("archive");
    if (!host || !status) return;

    let cls = "off";
    let tag = "no archive";
    if (status.configured && status.connected) {
      cls = "ok";
      tag = status.backend;
    } else if (status.configured) {
      cls = "warn";
      tag = "archive down";
    }

    host.className = `archive ${cls}`;
    host.replaceChildren(el("span", "tag", tag), el("span", null, status.detail));
    host.hidden = false;
  }

  // -------------------------------------------------------------- the record

  const PRESENCE_COLOR = {
    confirmed_still: "#ff5f6d",
    confirmed_moving: "#46d19b",
    unconfirmed: "#66748a",
    unknown: "#66748a",
  };
  const UNEXPECTED = "#a986ff";

  function record() {
    const params = new URLSearchParams(location.search);
    const incidentId = params.get("incident");
    if (!incidentId) return fail("No incident id in the URL.");

    const state = {
      incidentId,
      entries: [],
      rawEntries: [],
      frames: [],
      floorplan: null,
      sealed: false,
      rootHash: null,
      callerAnsname: null,
      address: null,
      cursor: 0,
      playing: false,
      hidden: new Set(),
      timer: null,
      poll: null,
    };

    $("export").href = `${API}/incident/${encodeURIComponent(incidentId)}/replay/export`;
    $("printbtn").addEventListener("click", () => window.print());
    $("verify").addEventListener("click", () => verifyInBrowser(state));
    $("slider").addEventListener("input", (e) => {
      stopPlayback(state);
      showFrame(state, Number(e.target.value));
    });
    $("play").addEventListener("click", () => togglePlayback(state));

    tail(state);
  }

  async function tail(state) {
    let page, raw;
    try {
      // Read the response once as text, then twice from that text: normally for
      // the UI, and number-literal-preserving for the chain check. Fetching it
      // twice would let the two copies differ, which is the one thing a
      // verifier must not allow.
      const body = await getText(
        `${API}/incident/${encodeURIComponent(state.incidentId)}/replay` +
        `?since_seq=${state.entries.length}`
      );
      page = JSON.parse(body);
      raw = parseKeepingNumbers(body);
    } catch (err) {
      if (!state.entries.length) return fail(String(err));
      return; // A transient failure mid-poll. The next tick retries.
    }
    state.rawEntries.push(...raw.entries);

    const wasEmpty = state.entries.length === 0;
    const atEnd = state.cursor >= state.frames.length - 1;

    state.sealed = page.sealed;
    state.rootHash = page.root_hash;
    state.callerAnsname = page.caller_ansname;
    state.address = page.site_address;
    state.sealedAt = page.sealed_at;

    for (const entry of page.entries) {
      state.entries.push(entry);
      if (entry.kind === "frame") {
        if (!state.floorplan && entry.detail.floorplan) {
          state.floorplan = entry.detail.floorplan;
          drawPlan(state.floorplan);
        }
        state.frames.push(entry);
      }
      appendEntry(state, entry);
    }

    if (wasEmpty) buildFilters(state);
    header(state);
    chainFacts(state);

    if (page.entries.length) {
      $("slider").max = String(Math.max(0, state.frames.length - 1));
      drawRF(state);
      // Follow the live edge while recording, but never yank the scrubber out
      // from under someone who has dragged it back to look at something.
      if (atEnd || wasEmpty) showFrame(state, state.frames.length - 1);
    }

    if (!state.sealed) {
      state.poll = setTimeout(() => tail(state), 1000);
    } else if (state.poll) {
      clearTimeout(state.poll);
      state.poll = null;
    }
  }

  function header(state) {
    const kind = state.entries[0] && state.entries[0].detail.incident
      ? state.entries[0].detail.incident.incident_type
      : "incident";
    $("title").textContent = `${kind[0].toUpperCase()}${kind.slice(1)} · ${state.incidentId}`;
    document.title = `Hawk Eye · ${state.incidentId}`;
    $("subtitle").textContent = `${state.address} · ${state.callerAnsname}`;
    $("livebadge").hidden = state.sealed;
    $("sealbadge").hidden = !state.sealed;
  }

  // ------------------------------------------------------------------ the log

  const KINDS = ["lifecycle", "incident", "verification", "transcript", "instruction", "context", "notice", "frame"];

  function buildFilters(state) {
    const host = $("filters");
    host.innerHTML = "";
    for (const kind of KINDS) {
      const btn = el("button", "on", kind);
      btn.type = "button";
      btn.addEventListener("click", () => {
        if (state.hidden.has(kind)) {
          state.hidden.delete(kind);
          btn.classList.add("on");
        } else {
          state.hidden.add(kind);
          btn.classList.remove("on");
        }
        applyFilter(state);
      });
      host.append(btn);
    }
    // Frames are the bulk of a record and the least interesting line by line,
    // so the log starts without them. The map is where a frame is legible.
    state.hidden.add("frame");
    host.lastChild.classList.remove("on");
    applyFilter(state);
  }

  function applyFilter(state) {
    for (const node of $("entries").children) {
      node.hidden = state.hidden.has(node.dataset.kind);
    }
  }

  function appendEntry(state, entry) {
    const li = el("li", "entry");
    li.dataset.kind = entry.kind;
    li.dataset.seq = String(entry.seq);
    const discarded = entry.kind === "verification" && entry.detail.decision === "DISCARDED";
    if (discarded) li.dataset.discarded = "1";

    li.append(el("div", "seq", String(entry.seq)));

    const body = el("div");
    const head = el("div", "head");
    head.append(el("span", "kind", entry.kind));
    if (entry.actor) head.append(el("span", "actor", entry.actor));
    head.append(el("span", "time", clock(entry.at)));
    body.append(head);
    body.append(el("div", "summary", entry.summary));

    let open = null;
    li.addEventListener("click", () => {
      if (open) {
        open.remove();
        open = null;
      } else {
        open = el("pre", "detail", JSON.stringify(entry.detail, null, 2));
        body.append(open);
      }
      if (entry.kind === "frame") {
        const idx = state.frames.findIndex((f) => f.seq === entry.seq);
        if (idx >= 0) {
          stopPlayback(state);
          showFrame(state, idx);
        }
      }
    });

    li.append(body);
    li.hidden = state.hidden.has(entry.kind);
    $("entries").append(li);

    const list = $("entries");
    const nearBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 120;
    if (nearBottom) list.scrollTop = list.scrollHeight;
  }

  // ------------------------------------------------------------------ the map

  function drawPlan(plan) {
    const svg = $("plan");
    svg.setAttribute("viewBox", `-1 -1 ${plan.width_m * 10 + 2} ${plan.depth_m * 10 + 2}`);
    svg.innerHTML = "";
    const ns = "http://www.w3.org/2000/svg";

    for (const room of plan.rooms) {
      const poly = document.createElementNS(ns, "polygon");
      poly.setAttribute("class", "room");
      poly.setAttribute("points", room.polygon.map(([x, y]) => `${x * 10},${y * 10}`).join(" "));
      svg.append(poly);

      // Room names go at the top of the room, not at its centroid. Presences
      // sit near the centroid, so a label there collides with whoever is
      // standing in that room - and the room the intruder is in is exactly the
      // one you least want obscured.
      const cx = room.polygon.reduce((a, p) => a + p[0], 0) / room.polygon.length * 10;
      const cy = Math.min(...room.polygon.map((p) => p[1])) * 10 + 3.2;
      const label = document.createElementNS(ns, "text");
      label.setAttribute("class", "roomlabel");
      label.setAttribute("x", String(cx));
      label.setAttribute("y", String(cy));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", "2.4");
      label.setAttribute("fill", "#59667a");
      label.textContent = room.name;
      svg.append(label);
    }

    const layer = document.createElementNS(ns, "g");
    layer.setAttribute("id", "presences");
    svg.append(layer);

    legend();
  }

  function legend() {
    const host = $("legend");
    if (host.childElementCount) return;
    const rows = [
      ["Still, breathing", PRESENCE_COLOR.confirmed_still],
      ["Moving, breathing", PRESENCE_COLOR.confirmed_moving],
      ["No respiration signature", PRESENCE_COLOR.unconfirmed],
      ["Not accounted for", UNEXPECTED],
    ];
    for (const [text, color] of rows) {
      const span = el("span");
      const dot = el("i");
      dot.style.background = color;
      span.append(dot, document.createTextNode(text));
      host.append(span);
    }
  }

  function showFrame(state, index) {
    if (!state.frames.length) return;
    const idx = Math.max(0, Math.min(index, state.frames.length - 1));
    state.cursor = idx;
    const frame = state.frames[idx];

    $("slider").value = String(idx);
    $("frameidx").textContent = `${idx + 1} / ${state.frames.length}`;
    $("framestamp").textContent = clock(frame.at);

    const layer = $("presences");
    if (!layer) return;
    layer.innerHTML = "";
    const ns = "http://www.w3.org/2000/svg";

    for (const p of frame.detail.presences) {
      const x = p.x * 10;
      const y = p.y * 10;
      const unexpected = p.expected === false;
      const color = unexpected ? UNEXPECTED : (PRESENCE_COLOR[p.state] || PRESENCE_COLOR.unknown);

      // A long lie is the clinical variable this project exists for, so it gets
      // the loudest mark on the map and it grows with the time on the floor.
      if (p.still_down_s) {
        const halo = document.createElementNS(ns, "circle");
        halo.setAttribute("cx", String(x));
        halo.setAttribute("cy", String(y));
        halo.setAttribute("r", String(Math.min(9, 3.4 + p.still_down_s / 14)));
        halo.setAttribute("fill", color);
        halo.setAttribute("opacity", "0.16");
        layer.append(halo);
      }

      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", String(x));
      dot.setAttribute("cy", String(y));
      dot.setAttribute("r", p.state.startsWith("confirmed") ? "2.3" : "1.7");
      dot.setAttribute("fill", color);
      // Confidence rendered as coherence rather than as a number floating in
      // space: a presence the system is unsure of looks unsure.
      dot.setAttribute("opacity", String(0.35 + 0.65 * (p.confidence || 0)));
      layer.append(dot);

      const tag = document.createElementNS(ns, "text");
      tag.setAttribute("x", String(x));
      tag.setAttribute("y", String(y - 3.6));
      tag.setAttribute("text-anchor", "middle");
      tag.setAttribute("font-size", "2.3");
      tag.setAttribute("fill", color);
      tag.textContent = p.still_down_s
        ? `${p.presence_id} · down ${Math.round(p.still_down_s)}s`
        : p.presence_id;
      layer.append(tag);
    }

    rfCursor(state, idx);
    highlightEntry(frame.seq);
  }

  function highlightEntry(seq) {
    for (const node of $("entries").children) {
      node.classList.toggle("on", node.dataset.seq === String(seq));
    }
  }

  function togglePlayback(state) {
    if (state.playing) return stopPlayback(state);
    if (state.cursor >= state.frames.length - 1) state.cursor = -1;
    state.playing = true;
    $("play").textContent = "❚❚";
    state.timer = setInterval(() => {
      if (state.cursor >= state.frames.length - 1) return stopPlayback(state);
      showFrame(state, state.cursor + 1);
    }, 220);
  }

  function stopPlayback(state) {
    state.playing = false;
    $("play").textContent = "▶";
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }

  // ------------------------------------------------------------------ the RF

  /* Two strips, not one chart.
   *
   * Capture rate is in hertz and respiration is in breaths per minute. Drawing
   * 137 Hz and 16 bpm against one axis squashes the respiration traces into a
   * flat line at the bottom and invites a reader to compare two quantities that
   * have nothing to do with each other. Each gets its own scale. */
  function drawRF(state) {
    if (!state.frames.length) return;
    const W = 800, H = 88, pad = 9;
    const px = (i) => pad + (i / Math.max(1, state.frames.length - 1)) * (W - pad * 2);
    state.rfpx = px;

    drawRate(state, W, H, pad, px);
    drawResp(state, W, H, pad, px);
  }

  const NS = "http://www.w3.org/2000/svg";

  function svgEl(parent, tag, attrs, text) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (text !== undefined) node.textContent = text;
    parent.append(node);
    return node;
  }

  function trace(svg, values, px, py, color, width) {
    const pts = [];
    values.forEach((v, i) => {
      if (typeof v === "number") pts.push(`${pts.length ? "L" : "M"}${px(i)},${py(v)}`);
    });
    if (pts.length) {
      svgEl(svg, "path", { d: pts.join(" "), fill: "none", stroke: color, "stroke-width": width });
    }
  }

  function cursorLine(svg, id, H, pad) {
    svgEl(svg, "line", {
      id, y1: pad, y2: H - pad, x1: pad, x2: pad,
      stroke: "#e6ebf2", opacity: 0.45,
    });
  }

  function drawRate(state, W, H, pad, px) {
    const svg = $("rfrate");
    svg.innerHTML = "";
    const rates = state.frames.map((f) => f.detail.rf.frame_rate_hz);
    const floor = state.frames[0].detail.rf.min_useful_frame_rate_hz || 0;
    const known = rates.filter((r) => typeof r === "number");
    const top = Math.max(floor, ...(known.length ? known : [1])) * 1.2 || 1;
    const py = (v) => H - pad - (v / top) * (H - pad * 2);

    // The band below the minimum useful capture rate. Without a traffic
    // generator a real capture sits down here at roughly 10 Hz, resolving
    // breathing barely and a fall transient not at all, while every component
    // still reports healthy. It is the quiet failure, so it goes on the record.
    if (floor) {
      svgEl(svg, "rect", {
        x: pad, y: py(floor), width: W - pad * 2,
        height: Math.max(0, H - pad - py(floor)),
        fill: "#ff5f6d", opacity: 0.06,
      });
      svgEl(svg, "line", {
        x1: pad, x2: W - pad, y1: py(floor), y2: py(floor),
        stroke: "#ff5f6d", "stroke-dasharray": "4 4", opacity: 0.45,
      });
      svgEl(svg, "text", {
        x: pad + 5, y: py(floor) + 12, "font-size": 10, fill: "#ff5f6d", opacity: 0.85,
      }, `below ${floor} Hz: not enough frames to resolve a fall`);
    }

    trace(svg, rates, px, py, "#4da3ff", 1.6);
    cursorLine(svg, "rfcursor-rate", H, pad);
  }

  function drawResp(state, W, H, pad, px) {
    const svg = $("rfresp");
    svg.innerHTML = "";

    const ids = new Set();
    state.frames.forEach((f) => f.detail.rf.respiration.forEach((r) => ids.add(r.presence_id)));
    // RuView's stated range. A value outside it is reported as null rather than
    // as a number, so the axis is the range and not the data's own extent.
    const lo = 6, hi = 30;
    const py = (v) => H - pad - ((v - lo) / (hi - lo)) * (H - pad * 2);

    for (const bpm of [10, 20, 30]) {
      svgEl(svg, "line", {
        x1: pad, x2: W - pad, y1: py(bpm), y2: py(bpm),
        stroke: "#222a37", "stroke-width": 1,
      });
      svgEl(svg, "text", { x: 2, y: py(bpm) - 2, "font-size": 9, fill: "#3f4a5c" }, `${bpm}`);
    }

    const palette = ["#46d19b", "#a986ff", "#f2b155", "#ff8fa0"];
    [...ids].forEach((id, n) => {
      const series = state.frames.map((f) => {
        const hit = f.detail.rf.respiration.find((r) => r.presence_id === id);
        return hit ? hit.breathing_bpm : null;
      });
      const color = palette[n % palette.length];
      trace(svg, series, px, py, color, 1.4);

      // A presence with no respiration signature has no line to draw, and a gap
      // in a chart reads as missing data rather than as a finding. Say it.
      if (!series.some((v) => typeof v === "number")) {
        svgEl(svg, "text", {
          x: pad + 5, y: H - pad - 4 - n * 11, "font-size": 9, fill: color, opacity: 0.8,
        }, `${id}: no respiration signature`);
      }
    });

    cursorLine(svg, "rfcursor-resp", H, pad);
  }

  function rfCursor(state, idx) {
    if (!state.rfpx) return;
    const x = String(state.rfpx(idx));
    for (const id of ["rfcursor-rate", "rfcursor-resp"]) {
      const line = document.getElementById(id);
      if (line) {
        line.setAttribute("x1", x);
        line.setAttribute("x2", x);
      }
    }

    const rf = state.frames[idx].detail.rf;
    const host = $("rfmeta");
    host.innerHTML = "";
    const cell = (label, value, cls) => {
      const box = el("div");
      box.append(el("dt", null, label), el("dd", cls, value));
      host.append(box);
    };
    const degraded = typeof rf.frame_rate_hz === "number" &&
      typeof rf.min_useful_frame_rate_hz === "number" &&
      rf.frame_rate_hz < rf.min_useful_frame_rate_hz;
    cell("Capture rate", rf.frame_rate_hz == null ? "unknown" : `${rf.frame_rate_hz} Hz`, degraded ? "warn" : null);
    cell("Baseline", rf.baseline_healthy ? `${Math.round(rf.baseline_age_s)}s, healthy` : "UNHEALTHY", rf.baseline_healthy ? null : "warn");
    cell("Source", rf.source || "unknown", rf.simulated ? "sim" : null);
    cell("Raw CSI", "not recorded");
    for (const r of rf.respiration) {
      cell(r.presence_id, r.breathing_bpm == null ? r.respiration : `${r.breathing_bpm} bpm`);
    }
  }

  // --------------------------------------------------------------- the chain

  function chainFacts(state) {
    const kv = $("chainkv");
    kv.innerHTML = "";
    const row = (k, v) => {
      kv.append(el("dt", null, k), el("dd", null, v));
    };
    row("Entries", String(state.entries.length));
    row("Root hash", state.rootHash || "(none yet)");
    row("Algorithm", "sha256 over canonical JSON");
    row("Sealed", state.sealed ? stamp(state.sealedAt) : "not yet");
    row("SCITT receipt", "none - not submitted to a transparency log");
  }

  /* The same canonical form the server hashes, recomputed from the bytes it
   * served rather than from parsed JavaScript values.
   *
   * Parsing first and re-serializing does not work, and the way it fails is
   * quiet. `JSON.stringify` writes the float 1.0 as `1`, where Python writes
   * `1.0`; it leaves non-ASCII characters as themselves, where Python's default
   * `ensure_ascii` writes `\uXXXX`. Either difference changes the hash of an
   * entry nobody touched, and the console would then accuse an intact record of
   * having been altered. So this walks the raw text, keeps every number literal
   * exactly as it arrived, and re-emits strings by Python's escaping rules.
   *
   * It must agree byte for byte with `hawkeye_backend/replay/chain.py` and with
   * the `verify.py` shipped in the export. `test_the_shipped_verifier_agrees_
   * with_the_server` holds the Python halves together; this one is held by
   * running it, which is what the button does. */

  class RawNumber {
    constructor(literal) { this.literal = literal; }
  }

  /* JSON.parse, except numbers keep their source literal. Small enough to read,
   * which matters: a verifier nobody can audit verifies nothing. */
  function parseKeepingNumbers(text) {
    let i = 0;

    const ws = () => { while (i < text.length && " \t\n\r".includes(text[i])) i++; };
    const expect = (ch) => {
      if (text[i] !== ch) throw new SyntaxError(`expected ${ch} at ${i}`);
      i++;
    };

    function value() {
      ws();
      const ch = text[i];
      if (ch === "{") return object();
      if (ch === "[") return array();
      if (ch === '"') return string();
      if (text.startsWith("true", i)) { i += 4; return true; }
      if (text.startsWith("false", i)) { i += 5; return false; }
      if (text.startsWith("null", i)) { i += 4; return null; }
      return number();
    }

    function object() {
      expect("{");
      const out = {};
      ws();
      if (text[i] === "}") { i++; return out; }
      for (;;) {
        ws();
        const key = string();
        ws();
        expect(":");
        out[key] = value();
        ws();
        if (text[i] === ",") { i++; continue; }
        expect("}");
        return out;
      }
    }

    function array() {
      expect("[");
      const out = [];
      ws();
      if (text[i] === "]") { i++; return out; }
      for (;;) {
        out.push(value());
        ws();
        if (text[i] === ",") { i++; continue; }
        expect("]");
        return out;
      }
    }

    function string() {
      expect('"');
      let out = "";
      for (;;) {
        const ch = text[i++];
        if (ch === '"') return out;
        if (ch !== "\\") { out += ch; continue; }
        const esc = text[i++];
        if (esc === "u") {
          out += String.fromCharCode(parseInt(text.slice(i, i + 4), 16));
          i += 4;
        } else {
          out += { b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" }[esc] ?? esc;
        }
      }
    }

    function number() {
      const start = i;
      while (i < text.length && "-+.eE0123456789".includes(text[i])) i++;
      if (i === start) throw new SyntaxError(`bad value at ${i}`);
      return new RawNumber(text.slice(start, i));
    }

    const out = value();
    ws();
    return out;
  }

  /* Python's json string escaping with ensure_ascii on: the two-character
   * escapes, \u00XX for the remaining control characters, and \uXXXX for
   * everything above ASCII, surrogate pairs included. */
  function pyString(value) {
    let out = '"';
    for (const ch of value) {
      const code = ch.codePointAt(0);
      if (ch === '"') out += '\\"';
      else if (ch === "\\") out += "\\\\";
      else if (ch === "\n") out += "\\n";
      else if (ch === "\r") out += "\\r";
      else if (ch === "\t") out += "\\t";
      else if (ch === "\b") out += "\\b";
      else if (ch === "\f") out += "\\f";
      else if (code < 0x20) out += "\\u" + code.toString(16).padStart(4, "0");
      else if (code < 0x7f) out += ch;
      else {
        // Above ASCII: one \uXXXX per UTF-16 code unit, so astral characters
        // become the surrogate pair Python writes.
        for (let n = 0; n < ch.length; n++) {
          out += "\\u" + ch.charCodeAt(n).toString(16).padStart(4, "0");
        }
      }
    }
    return out + '"';
  }

  function canonical(value) {
    if (value instanceof RawNumber) return value.literal;
    if (value === null) return "null";
    if (typeof value === "boolean") return value ? "true" : "false";
    if (typeof value === "string") return pyString(value);
    if (typeof value === "number") return String(value); // only from our own code
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    const keys = Object.keys(value).sort();
    return "{" + keys.map((k) => pyString(k) + ":" + canonical(value[k])).join(",") + "}";
  }

  async function sha256(text) {
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function verifyInBrowser(state) {
    const verdict = $("verdict");
    verdict.className = "verdict idle";
    verdict.textContent = "Recomputing…";

    let prev = null;
    for (const entry of state.rawEntries) {
      // Rebuilt in the server's shape: `actor` is chained only when it is not
      // null, so an entry written without one hashes as it did before the
      // recorder tracked actors at all.
      const body = { seq: entry.seq, kind: entry.kind, summary: entry.summary, detail: entry.detail };
      if (entry.actor !== null && entry.actor !== undefined) body.actor = entry.actor;

      const seq = Number(entry.seq.literal);
      if ((entry.prev_hash ?? null) !== prev) {
        return bad(verdict, seq, `entry ${seq} does not follow entry ${seq - 1}`);
      }
      const computed = await sha256(canonical({ prev, entry: body }));
      if (computed !== entry.entry_hash) {
        return bad(verdict, seq, `entry ${seq} has been altered since it was written`);
      }
      prev = entry.entry_hash;
    }

    verdict.className = "verdict ok";
    verdict.textContent =
      `INTACT — ${state.rawEntries.length} entries, chain complete to ${(prev || "").slice(0, 24)}…\n` +
      `Recomputed in this browser. No entry has been edited, reordered, inserted or removed.`;
    for (const node of $("entries").children) node.classList.remove("bad");
  }

  function bad(verdict, seq, message) {
    verdict.className = "verdict bad";
    verdict.textContent = `ALTERED — ${message}`;
    for (const node of $("entries").children) {
      node.classList.toggle("bad", node.dataset.seq === String(seq));
    }
  }

  // Exposed for tests/test_replay_console_js.py, which runs this file under
  // node and checks its canonical form against the Python one. That test is the
  // only thing keeping three independent implementations of one hash in step,
  // and the disagreement it catches looks exactly like tampering.
  return { index, record, _canonical: { canonical, parseKeepingNumbers, pyString } };
})();

// A classic script's top-level `const` is script-scoped, not a window property.
// Published deliberately so the verifier can be driven from devtools: pointing
// it at a record you have doctored yourself is the only way to satisfy yourself
// that it reports ALTERED, and a check nobody has seen fail is not a check.
// Guarded because tests/test_replay_console_js.py evaluates this file under
// node, where there is no window and an unguarded assignment throws.
if (typeof window !== "undefined") window.HawkEye = HawkEye;

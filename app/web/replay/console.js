/* Hawk Eye replay console.
 *
 * Vanilla, no build, no CDN.
 *
 * This used to hold a second page: an interior floorplan replay, an entry
 * log, an RF strip and an in-browser hash-chain verifier, all keyed to one
 * incident. That page and its data model were pre-pivot (respiration,
 * `fire`/`burglary` incident types) and were removed in the pivot to a
 * single video-segments table. If the hash-chain / tamper-evidence UI comes
 * back, it belongs on whatever page next holds a full incident record; it
 * is not reconstructed here.
 *
 * This page has one job: list the video segments `vision/` writes.
 *
 * IMPORTANT: there is no backend endpoint for this yet. `vision/` writes
 * rotating, hashed mp4 segments to disk, but nothing in `app/backend`
 * exposes them over the API. The rows below are sample data shaped like
 * what that endpoint would return, not a live read. The page says so in
 * its own markup (`.mockcaution` in index.html) rather than only here,
 * because the honesty rule is that a limit lives in the data, not just in
 * a comment nobody reading the rendered page will ever see.
 */

const HawkEye = (() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const stamp = (iso) => new Date(iso).toLocaleString([], { hour12: false });

  function duration(seconds) {
    const s = Math.max(0, Math.round(seconds));
    const m = Math.floor(s / 60);
    return m ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`;
  }

  // Sample rows only — see the file header. Shaped like a plausible
  // `GET /v1/replay/segments` response: one row per rotating mp4 `vision/`
  // closes and hashes, scoped to the one room a fixed camera can see, per
  // the honesty rule in root CLAUDE.md.
  const SAMPLE_SEGMENTS = [
    {
      file: "inc-0001_living-room_04-22-09.mp4",
      incident_id: "inc-0001",
      room: "living_room",
      recorded_at: "2026-09-20T04:22:09Z",
      duration_s: 24,
      size_bytes: 18_874_368,
      sha256: "9f1c2a7e30bde104f6a7c1b9e2d5f8a3c0b6d9e2f4a7b1c8d3e6f9a2b5c8d1e4",
      status: "sealed",
    },
    {
      file: "inc-0001_living-room_04-22-33.mp4",
      incident_id: "inc-0001",
      room: "living_room",
      recorded_at: "2026-09-20T04:22:33Z",
      duration_s: 24,
      size_bytes: 19_301_120,
      sha256: "4d77c0e91a6b3f8d2c5a9e1b7f0d4a8c3e6b9f2d5a8c1e4b7f0a3d6c9e2b5f8a",
      status: "sealed",
    },
    {
      file: "inc-0001_living-room_04-22-58.mp4",
      incident_id: "inc-0001",
      room: "living_room",
      recorded_at: "2026-09-20T04:22:58Z",
      duration_s: 11,
      size_bytes: 8_912_896,
      sha256: "1b6e9c4f7a2d5b8e1c4f7a0d3b6e9c2f5a8d1b4e7c0f3a6d9b2e5c8f1a4d7b0e",
      status: "unsealed",
    },
  ];

  async function index() {
    $("topmeta").append(
      el(
        "span",
        "stamp",
        `${SAMPLE_SEGMENTS.length} segment${SAMPLE_SEGMENTS.length === 1 ? "" : "s"}`
      )
    );

    const host = $("rows");
    for (const seg of SAMPLE_SEGMENTS) {
      const row = el("tr");
      row.append(cell(seg.file, "file"));
      row.append(cell(seg.incident_id, "mono"));
      row.append(cell(seg.room.replace(/_/g, " ")));
      row.append(cell(stamp(seg.recorded_at), "mono"));
      row.append(cell(duration(seg.duration_s), "mono"));
      row.append(cell(formatBytes(seg.size_bytes), "mono"));

      const hash = cell(`${seg.sha256.slice(0, 16)}…`, "mono hash");
      hash.title = seg.sha256;
      row.append(hash);

      const status = el("td");
      status.append(el("span", `status ${seg.status}`, seg.status));
      row.append(status);

      host.append(row);
    }
  }

  function cell(text, cls) {
    return el("td", cls, text);
  }

  function formatBytes(bytes) {
    const mb = bytes / (1024 * 1024);
    return `${mb.toFixed(1)} MB`;
  }

  return { index };
})();

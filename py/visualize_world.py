#!/usr/bin/env python3
"""Serve an interactive browser visualization for generated_world.json.

The visualizer is deliberately separate from the generator:
- world_generator.py creates and validates data,
- visualize_world.py reads that JSON and serves a lightweight canvas UI.

There is no simulation loop here. The browser only inspects the generated state.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_WORLD_PATH = "generated_world.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Emergent Supply Chain World Viewer</title>
  <style>
    :root {
      --panel-bg: rgba(255, 255, 255, 0.94);
      --panel-border: #d0d7de;
      --text: #1f2328;
      --muted: #59636e;
      --accent: #0969da;
    }

    html,
    body {
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f8fa;
    }

    canvas {
      display: block;
      width: 100vw;
      height: 100vh;
      cursor: grab;
    }

    canvas.dragging {
      cursor: grabbing;
    }

    .panel {
      position: fixed;
      z-index: 3;
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      box-shadow: 0 8px 28px rgba(27, 31, 36, 0.12);
      backdrop-filter: blur(8px);
    }

    #topbar {
      top: 16px;
      left: 16px;
      right: 16px;
      min-height: 44px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 10px 12px;
      border-radius: 8px;
    }

    #title {
      font-size: 14px;
      font-weight: 700;
      white-space: nowrap;
    }

    #summary {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    #controls {
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }

    button {
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      padding: 6px 9px;
      font: inherit;
      font-size: 12px;
      cursor: pointer;
    }

    button:hover {
      border-color: var(--accent);
    }

    #legend {
      left: 16px;
      bottom: 16px;
      width: 220px;
      max-height: calc(100vh - 120px);
      overflow: auto;
      padding: 12px;
      border-radius: 8px;
    }

    #legend h2,
    #details h2 {
      margin: 0 0 10px;
      font-size: 13px;
    }

    .legend-row {
      display: grid;
      grid-template-columns: 16px 1fr;
      align-items: center;
      gap: 8px;
      margin: 7px 0;
      color: var(--muted);
      font-size: 12px;
    }

    .swatch {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      border: 1px solid rgba(0, 0, 0, 0.2);
    }

    #details {
      right: 16px;
      bottom: 16px;
      width: 290px;
      min-height: 116px;
      padding: 12px;
      border-radius: 8px;
      font-size: 12px;
    }

    .detail-row {
      display: grid;
      grid-template-columns: 82px 1fr;
      gap: 8px;
      margin: 6px 0;
    }

    .detail-key {
      color: var(--muted);
    }

    #tooltip {
      position: fixed;
      z-index: 4;
      display: none;
      pointer-events: none;
      max-width: 280px;
      padding: 8px 9px;
      border-radius: 7px;
      border: 1px solid var(--panel-border);
      background: rgba(255, 255, 255, 0.97);
      box-shadow: 0 8px 22px rgba(27, 31, 36, 0.14);
      font-size: 12px;
      line-height: 1.35;
    }

    #loading {
      position: fixed;
      inset: 0;
      z-index: 5;
      display: grid;
      place-items: center;
      background: #f6f8fa;
      color: var(--muted);
      font-size: 14px;
    }
  </style>
</head>
<body>
  <canvas id="world"></canvas>

  <div id="topbar" class="panel">
    <div>
      <div id="title">Emergent Supply Chain World</div>
      <div id="summary">Loading generated_world.json...</div>
    </div>
    <div id="controls">
      <button id="reset">Reset view</button>
      <button id="refresh">Reload JSON</button>
    </div>
  </div>

  <div id="legend" class="panel">
    <h2>Legend</h2>
    <div class="legend-row">
      <span class="swatch" style="background:#000000"></span>
      <span>agent</span>
    </div>
    <div class="legend-row">
      <span class="swatch" style="background:#0969da"></span>
      <span>machine</span>
    </div>
    <div id="resourceLegend"></div>
  </div>

  <div id="details" class="panel">
    <h2>Selected Node</h2>
    <div id="detailsBody">Hover or click an entity.</div>
  </div>

  <div id="tooltip"></div>
  <div id="loading">Loading world...</div>

  <script>
    const canvas = document.getElementById("world");
    const ctx = canvas.getContext("2d");
    const summary = document.getElementById("summary");
    const loading = document.getElementById("loading");
    const tooltip = document.getElementById("tooltip");
    const detailsBody = document.getElementById("detailsBody");
    const resourceLegend = document.getElementById("resourceLegend");
    const resetButton = document.getElementById("reset");
    const refreshButton = document.getElementById("refresh");

    // Fixed colors keep the same resource visually stable across reruns.
    const resourceColors = {
      iron_ore: "#b45309",
      copper_ore: "#ea580c",
      coal: "#24292f",
      stone: "#8c959f",
      crude_oil: "#581c87",
      water: "#2563eb",
      wood: "#15803d",
      uranium_ore: "#84cc16",
      fish: "#06b6d4",
    };
    const machineColor = "#0969da";

    const state = {
      world: null,
      scale: 1,
      offsetX: 0,
      offsetY: 0,
      minScale: 0.0001,
      maxScale: 8,
      dragging: false,
      dragStartX: 0,
      dragStartY: 0,
      dragOffsetX: 0,
      dragOffsetY: 0,
      hoverNode: null,
      selectedNode: null,
      needsDraw: false,
    };

    function resizeCanvas() {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (state.world) {
        fitWorldToScreen();
      }
      requestDraw();
    }

    function fitWorldToScreen() {
      const metadata = state.world.metadata;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const margin = 96;
      const scaleX = (width - margin * 2) / metadata.world_width;
      const scaleY = (height - margin * 2) / metadata.world_height;

      state.scale = Math.max(0.0001, Math.min(scaleX, scaleY));
      state.minScale = state.scale * 0.4;
      state.maxScale = state.scale * 800;
      state.offsetX = (width - metadata.world_width * state.scale) / 2;
      state.offsetY = (height - metadata.world_height * state.scale) / 2;
    }

    function formatAreaMultiplier(value) {
      if (Number.isInteger(value)) {
        return `${value}x area`;
      }
      return `${Number(value).toFixed(2)}x area`;
    }

    function worldToScreen(coordinate) {
      return {
        x: coordinate[0] * state.scale + state.offsetX,
        y: coordinate[1] * state.scale + state.offsetY,
      };
    }

    function screenToWorld(x, y) {
      return {
        x: (x - state.offsetX) / state.scale,
        y: (y - state.offsetY) / state.scale,
      };
    }

    function mapValues(collection) {
      return collection ? Object.values(collection) : [];
    }

    function worldAgents() {
      return mapValues(state.world.agents);
    }

    function worldDeposits() {
      return mapValues(state.world.deposits);
    }

    function worldMachines() {
      return mapValues(state.world.machines);
    }

    function requestDraw() {
      if (!state.needsDraw) {
        state.needsDraw = true;
        requestAnimationFrame(draw);
      }
    }

    function draw() {
      state.needsDraw = false;
      if (!state.world) return;

      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#f6f8fa";
      ctx.fillRect(0, 0, width, height);

      drawMapBounds();
      drawDeposits();
      drawMachines();
      drawAgents();
      drawHoverRing();
    }

    function drawMapBounds() {
      const metadata = state.world.metadata;

      ctx.save();
      ctx.strokeStyle = "#8c959f";
      ctx.lineWidth = 1;
      ctx.setLineDash([6, 6]);

      if (metadata.world_shape === "circle") {
        const center = worldToScreen(metadata.world_center);
        const radius = metadata.world_radius * state.scale;
        ctx.beginPath();
        ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
        ctx.stroke();
      } else {
        const x = state.offsetX;
        const y = state.offsetY;
        const width = metadata.world_width * state.scale;
        const height = metadata.world_height * state.scale;
        ctx.strokeRect(x, y, width, height);
      }

      ctx.restore();
    }

    function isVisible(point, radius) {
      return (
        point.x >= -radius &&
        point.x <= canvas.clientWidth + radius &&
        point.y >= -radius &&
        point.y <= canvas.clientHeight + radius
      );
    }

    function drawDeposits() {
      const radius = 3.2;
      ctx.globalAlpha = 0.86;
      for (const deposit of worldDeposits()) {
        const point = worldToScreen(deposit.coordinate);
        if (!isVisible(point, radius)) continue;

        ctx.beginPath();
        ctx.fillStyle = resourceColors[deposit.item] || "#6e7781";
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function drawMachines() {
      const radius = 4.4;
      ctx.save();
      ctx.strokeStyle = machineColor;
      ctx.fillStyle = "rgba(9, 105, 218, 0.18)";
      ctx.lineWidth = 1.5;

      for (const machine of worldMachines()) {
        const point = worldToScreen(machine.coordinate);
        if (!isVisible(point, radius)) continue;

        ctx.beginPath();
        ctx.rect(point.x - radius, point.y - radius, radius * 2, radius * 2);
        ctx.fill();
        ctx.stroke();
      }

      ctx.restore();
    }

    function drawAgents() {
      const radius = 1.8;
      ctx.fillStyle = "#000000";
      for (const agent of worldAgents()) {
        const point = worldToScreen(agent.coordinate);
        if (!isVisible(point, radius)) continue;

        ctx.beginPath();
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function drawHoverRing() {
      const node = state.hoverNode || state.selectedNode;
      if (!node) return;

      const point = worldToScreen(node.coordinate);
      ctx.save();
      ctx.strokeStyle = "#0969da";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(point.x, point.y, node.type === "agent" ? 6 : 7, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }

    function formatNode(node) {
      const rows = [
        ["id", node.id],
        ["type", node.type],
        ["coordinate", `[${node.coordinate[0]}, ${node.coordinate[1]}]`],
      ];

      if (node.type === "deposit") {
        rows.push(["item", node.item]);
        rows.push(["amount", node.amount.toLocaleString()]);
      }

      return rows;
    }

    function nodeToHtml(node) {
      return formatNode(node)
        .map(([key, value]) => (
          `<div class="detail-row"><span class="detail-key">${key}</span><span>${value}</span></div>`
        ))
        .join("");
    }

    function setDetails(node) {
      detailsBody.innerHTML = node ? nodeToHtml(node) : "Hover or click an entity.";
    }

    function setTooltip(node, mouseX, mouseY) {
      if (!node) {
        tooltip.style.display = "none";
        return;
      }

      tooltip.innerHTML = nodeToHtml(node);
      tooltip.style.display = "block";
      tooltip.style.left = `${Math.min(mouseX + 14, window.innerWidth - 310)}px`;
      tooltip.style.top = `${Math.min(mouseY + 14, window.innerHeight - 160)}px`;
    }

    function hitTest(mouseX, mouseY) {
      if (!state.world) return null;

      let best = null;
      let bestScore = Infinity;

      // Deposits are checked first because they are larger and colored.
      for (const deposit of worldDeposits()) {
        const point = worldToScreen(deposit.coordinate);
        const dx = point.x - mouseX;
        const dy = point.y - mouseY;
        const distanceSquared = dx * dx + dy * dy;
        const radius = 8;
        if (distanceSquared <= radius * radius) {
          const score = distanceSquared / (radius * radius);
          if (score < bestScore) {
            best = deposit;
            bestScore = score;
          }
        }
      }

      for (const machine of worldMachines()) {
        const point = worldToScreen(machine.coordinate);
        const dx = point.x - mouseX;
        const dy = point.y - mouseY;
        const distanceSquared = dx * dx + dy * dy;
        const radius = 7;
        if (distanceSquared <= radius * radius) {
          const score = distanceSquared / (radius * radius);
          if (score < bestScore) {
            best = machine;
            bestScore = score;
          }
        }
      }

      for (const agent of worldAgents()) {
        const point = worldToScreen(agent.coordinate);
        const dx = point.x - mouseX;
        const dy = point.y - mouseY;
        const distanceSquared = dx * dx + dy * dy;
        const radius = 6;
        if (distanceSquared <= radius * radius) {
          const score = distanceSquared / (radius * radius);
          if (score < bestScore) {
            best = agent;
            bestScore = score;
          }
        }
      }

      return best;
    }

    function handleWheel(event) {
      event.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;
      const before = screenToWorld(mouseX, mouseY);
      const zoomFactor = event.deltaY < 0 ? 1.18 : 0.85;

      state.scale = Math.max(
        state.minScale,
        Math.min(state.maxScale, state.scale * zoomFactor)
      );

      state.offsetX = mouseX - before.x * state.scale;
      state.offsetY = mouseY - before.y * state.scale;
      requestDraw();
    }

    function handleMouseDown(event) {
      state.dragging = true;
      state.dragStartX = event.clientX;
      state.dragStartY = event.clientY;
      state.dragOffsetX = state.offsetX;
      state.dragOffsetY = state.offsetY;
      canvas.classList.add("dragging");
    }

    function handleMouseMove(event) {
      const rect = canvas.getBoundingClientRect();
      const mouseX = event.clientX - rect.left;
      const mouseY = event.clientY - rect.top;

      if (state.dragging) {
        state.offsetX = state.dragOffsetX + event.clientX - state.dragStartX;
        state.offsetY = state.dragOffsetY + event.clientY - state.dragStartY;
        requestDraw();
        return;
      }

      const node = hitTest(mouseX, mouseY);
      if (node !== state.hoverNode) {
        state.hoverNode = node;
        requestDraw();
      }

      setTooltip(node, event.clientX, event.clientY);
      if (node && !state.selectedNode) {
        setDetails(node);
      }
    }

    function handleMouseUp() {
      state.dragging = false;
      canvas.classList.remove("dragging");
    }

    function handleClick(event) {
      if (state.dragging) return;
      const rect = canvas.getBoundingClientRect();
      const node = hitTest(event.clientX - rect.left, event.clientY - rect.top);
      state.selectedNode = node;
      setDetails(node);
      requestDraw();
    }

    function renderLegend(resourceTypes) {
      resourceLegend.innerHTML = resourceTypes
        .map((resource) => (
          `<div class="legend-row">
            <span class="swatch" style="background:${resourceColors[resource] || "#6e7781"}"></span>
            <span>${resource}</span>
          </div>`
        ))
        .join("");
    }

    async function loadWorld() {
      loading.style.display = "grid";
      state.hoverNode = null;
      state.selectedNode = null;
      setDetails(null);

      const response = await fetch("/world.json?cacheBust=" + Date.now());
      if (!response.ok) {
        throw new Error("Could not load generated_world.json");
      }

      state.world = await response.json();
      renderLegend(state.world.metadata.resource_types);
      const agentCount = worldAgents().length;
      const depositCount = worldDeposits().length;
      const machineCount = worldMachines().length;
      const shapeSummary = state.world.metadata.world_shape === "circle"
        ? `circle r ${state.world.metadata.world_radius.toLocaleString()}`
        : `${state.world.metadata.world_width} x ${state.world.metadata.world_height}`;
      summary.textContent = [
        `seed ${state.world.metadata.seed}`,
        shapeSummary,
        formatAreaMultiplier(state.world.metadata.area_multiplier || 1),
        `${agentCount.toLocaleString()} agents`,
        `${depositCount.toLocaleString()} deposits`,
        `${machineCount.toLocaleString()} machines`,
        `${state.world.metadata.total_resource_units.toLocaleString()} resource units`,
      ].join(" | ");

      fitWorldToScreen();
      loading.style.display = "none";
      requestDraw();
    }

    resetButton.addEventListener("click", () => {
      if (!state.world) return;
      fitWorldToScreen();
      requestDraw();
    });

    refreshButton.addEventListener("click", () => {
      loadWorld().catch((error) => {
        loading.textContent = error.message;
      });
    });

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    canvas.addEventListener("mousedown", handleMouseDown);
    canvas.addEventListener("mousemove", handleMouseMove);
    canvas.addEventListener("mouseup", handleMouseUp);
    canvas.addEventListener("mouseleave", () => {
      handleMouseUp();
      state.hoverNode = null;
      setTooltip(null);
      requestDraw();
    });
    canvas.addEventListener("click", handleClick);
    window.addEventListener("resize", resizeCanvas);

    resizeCanvas();
    loadWorld().catch((error) => {
      loading.textContent = error.message;
    });
  </script>
</body>
</html>
"""


def parse_args():
    """Parse server settings."""
    parser = argparse.ArgumentParser(
        description="Serve an interactive visualization for generated_world.json."
    )
    parser.add_argument("--world", default=DEFAULT_WORLD_PATH)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def load_world_bytes(world_path):
    """Read and lightly validate the JSON before serving it."""
    path = Path(world_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist. Run world_generator.py first."
        )

    # Parse once at startup so JSON errors fail fast, then serve the bytes.
    data = json.loads(path.read_text(encoding="utf-8"))
    required_keys = {"metadata", "agents", "deposits", "machines", "coordinates"}
    missing_keys = required_keys - set(data)
    if missing_keys:
        raise ValueError(f"World JSON is missing keys: {sorted(missing_keys)}")

    return path.read_bytes()


def make_handler(world_path):
    """Create a request handler bound to the selected JSON path."""

    class WorldViewerHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            if self.path == "/" or self.path.startswith("/?"):
                html_bytes = HTML_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return

            if self.path.startswith("/world.json"):
                try:
                    world_bytes = load_world_bytes(world_path)
                except Exception as error:
                    error_bytes = str(error).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(error_bytes)))
                    self.end_headers()
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(world_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return

            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                html_bytes = HTML_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html_bytes)
                return

            if self.path.startswith("/world.json"):
                try:
                    world_bytes = load_world_bytes(world_path)
                except Exception as error:
                    self.send_response(500)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(str(error).encode("utf-8"))
                    return

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(world_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(world_bytes)
                return

            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")

        def log_message(self, format_string, *args):
            """Keep terminal output quiet unless there is a real server error."""
            return

    return WorldViewerHandler


def start_server(host, port, world_path):
    """Start the HTTP server, trying nearby ports if the default is busy."""
    handler = make_handler(world_path)
    last_error = None

    for candidate_port in range(port, port + 50):
        try:
            server = ThreadingHTTPServer((host, candidate_port), handler)
            return server, candidate_port
        except OSError as error:
            last_error = error

    raise OSError(f"Could not bind to ports {port}-{port + 49}: {last_error}")


def main():
    args = parse_args()
    load_world_bytes(args.world)
    server, actual_port = start_server(args.host, args.port, args.world)

    print(f"Serving {args.world}", flush=True)
    print(f"Open http://{args.host}:{actual_port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

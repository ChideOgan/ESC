#!/usr/bin/env python3
"""Serve the ESC world dashboard.

The dashboard is intentionally still a Step 1 tool:
- it lists saved generated worlds,
- it can generate another static world from form settings,
- it renders the selected world on a canvas,

There is no simulation loop here. No agents move, mine, trade, message, price,
or act. The browser only manages and inspects generated world snapshots.
"""

import argparse
import json
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from world_generator import (
    build_world,
    save_world,
)


DEFAULT_INDEX_PATH = "worlds_index.json"
DEFAULT_WORLDS_DIR = "worlds"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

REQUIRED_WORLD_KEYS = {"metadata", "agents", "deposits", "machines", "coordinates"}
INDEX_LOCK = threading.RLock()


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ESC World Dashboard</title>
  <style>
    :root {
      --sidebar-width: 306px;
      --sidebar-collapsed-width: 66px;
      --sidebar-bg: rgba(255, 255, 255, 0.96);
      --sidebar-border: #d0d7de;
      --sidebar-hover: #f6f8fa;
      --sidebar-active: #eaf2ff;
      --sidebar-text: #1f2328;
      --sidebar-muted: #59636e;
      --panel-bg: rgba(255, 255, 255, 0.94);
      --panel-border: #d0d7de;
      --text: #1f2328;
      --muted: #59636e;
      --accent: #0969da;
      --danger: #b42318;
      --canvas-bg: #f6f8fa;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--canvas-bg);
    }

    button,
    input {
      font: inherit;
    }

    canvas {
      position: fixed;
      inset: 0;
      display: block;
      width: 100vw;
      height: 100vh;
      cursor: grab;
    }

    canvas.dragging {
      cursor: grabbing;
    }

    .sidebar {
      position: fixed;
      top: 14px;
      bottom: 14px;
      left: 14px;
      z-index: 8;
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      width: var(--sidebar-width);
      overflow: hidden;
      color: var(--sidebar-text);
      background: var(--sidebar-bg);
      border: 1px solid var(--sidebar-border);
      border-radius: 18px;
      box-shadow: 0 18px 55px rgba(27, 31, 36, 0.14);
      backdrop-filter: blur(14px);
      transition: width 170ms ease;
    }

    body.sidebar-collapsed .sidebar {
      width: var(--sidebar-collapsed-width);
    }

    .sidebar-top {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px;
    }

    .icon-button {
      display: inline-grid;
      place-items: center;
      width: 36px;
      height: 36px;
      min-width: 36px;
      padding: 0;
      color: #59636e;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 10px;
      cursor: pointer;
    }

    .icon-button:hover {
      background: var(--sidebar-hover);
      border-color: var(--sidebar-border);
    }

    .icon-button svg {
      width: 20px;
      height: 20px;
      stroke: currentColor;
    }

    #openCreate svg {
      width: 18px;
      height: 18px;
    }

    .sidebar-search-wrap {
      padding: 0 12px 12px;
    }

    .sidebar-search {
      position: relative;
    }

    .sidebar-search svg {
      position: absolute;
      top: 50%;
      left: 12px;
      width: 16px;
      height: 16px;
      color: #8c959f;
      transform: translateY(-50%);
    }

    #worldSearch {
      width: 100%;
      height: 38px;
      padding: 0 12px 0 36px;
      color: var(--sidebar-text);
      background: #ffffff;
      border: 1px solid var(--sidebar-border);
      border-radius: 10px;
      outline: none;
    }

    #worldSearch:focus {
      border-color: var(--accent);
    }

    #worldSearch::placeholder {
      color: #8c959f;
    }

    .world-list {
      min-height: 0;
      overflow-y: auto;
      padding: 0 8px 8px;
    }

    .world-row {
      display: grid;
      grid-template-columns: 1fr 30px;
      align-items: center;
      gap: 4px;
      min-height: 48px;
      margin: 2px 0;
      padding: 4px;
      border-radius: 12px;
    }

    .world-row:hover {
      background: var(--sidebar-hover);
    }

    .world-row.active {
      background: var(--sidebar-active);
    }

    .world-main {
      min-width: 0;
      padding: 6px 6px 6px 10px;
      color: inherit;
      text-align: left;
      background: transparent;
      border: 0;
      cursor: pointer;
    }

    .world-name,
    .world-meta {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .world-name {
      font-size: 13px;
      font-weight: 650;
    }

    .world-meta {
      margin-top: 3px;
      color: var(--sidebar-muted);
      font-size: 11px;
    }

    .world-more-icon {
      display: grid;
      place-items: center;
      width: 30px;
      height: 30px;
      color: #8c959f;
      pointer-events: none;
    }

    .world-more-icon svg {
      width: 16px;
      height: 16px;
      fill: currentColor;
    }

    .sidebar-footer {
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 56px;
      padding: 12px 16px;
      color: var(--sidebar-muted);
      background: rgba(246, 248, 250, 0.98);
      border-top: 1px solid var(--sidebar-border);
      font-weight: 700;
      letter-spacing: 0.02em;
    }

    .footer-world {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      color: #59636e;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 10px;
      cursor: default;
    }

    .footer-world svg {
      width: 20px;
      height: 20px;
      stroke: currentColor;
    }

    .world-empty {
      padding: 16px 12px;
      color: var(--sidebar-muted);
      font-size: 12px;
      line-height: 1.45;
    }

    body.sidebar-collapsed .sidebar {
      grid-template-rows: auto 1fr;
    }

    body.sidebar-collapsed .sidebar-search-wrap,
    body.sidebar-collapsed .world-list,
    body.sidebar-collapsed .sidebar-footer {
      display: none;
    }

    body.sidebar-collapsed .sidebar-top {
      flex-direction: column;
      padding: 12px;
    }

    body.sidebar-collapsed #collapseSidebar .collapse-expanded {
      display: none;
    }

    body:not(.sidebar-collapsed) #collapseSidebar .collapse-collapsed {
      display: none;
    }

    .topbar {
      position: fixed;
      top: 16px;
      right: 16px;
      left: calc(var(--sidebar-width) + 34px);
      z-index: 5;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 52px;
      padding: 10px 14px;
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      border-radius: 12px;
      box-shadow: 0 12px 30px rgba(27, 31, 36, 0.12);
      backdrop-filter: blur(10px);
      transition: left 170ms ease;
    }

    body.sidebar-collapsed .topbar {
      left: calc(var(--sidebar-collapsed-width) + 34px);
    }

    .title-stack {
      min-width: 0;
    }

    #title {
      overflow: hidden;
      font-size: 14px;
      font-weight: 750;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    #summary {
      margin-top: 2px;
      overflow: hidden;
      color: var(--muted);
      font-size: 12px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .top-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }

    .control-button,
    .primary-button {
      height: 34px;
      padding: 0 12px;
      border-radius: 8px;
      cursor: pointer;
    }

    .control-button {
      color: var(--muted);
      background: #ffffff;
      border: 1px solid var(--panel-border);
    }

    .control-button:hover {
      border-color: var(--accent);
    }

    .primary-button {
      color: #ffffff;
      background: var(--accent);
      border: 1px solid var(--accent);
      font-weight: 700;
    }

    .primary-button:disabled {
      cursor: not-allowed;
      opacity: 0.65;
    }

    .panel {
      position: fixed;
      z-index: 4;
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      box-shadow: 0 12px 30px rgba(27, 31, 36, 0.12);
      backdrop-filter: blur(10px);
    }

    #legend {
      right: 16px;
      bottom: 196px;
      width: 228px;
      max-height: calc(100vh - 300px);
      overflow: auto;
      padding: 12px;
      border-radius: 12px;
    }

    #details {
      right: 16px;
      bottom: 16px;
      width: 304px;
      min-height: 152px;
      padding: 12px;
      border-radius: 12px;
      font-size: 12px;
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
      border: 1px solid rgba(0, 0, 0, 0.2);
      border-radius: 50%;
    }

    .swatch.square {
      border-radius: 3px;
    }

    .swatch-icon {
      display: block;
      width: 13px;
      height: 13px;
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
      z-index: 10;
      display: none;
      max-width: 280px;
      padding: 8px 9px;
      pointer-events: none;
      background: rgba(255, 255, 255, 0.97);
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      box-shadow: 0 8px 22px rgba(27, 31, 36, 0.14);
      font-size: 12px;
      line-height: 1.35;
    }

    .loading {
      position: fixed;
      inset: 0;
      z-index: 3;
      display: none;
      place-items: center;
      color: var(--muted);
      background: rgba(246, 248, 250, 0.62);
      font-size: 14px;
    }

    .loading.visible {
      display: grid;
    }

    .create-panel {
      position: fixed;
      top: 84px;
      left: calc(var(--sidebar-width) + 34px);
      z-index: 7;
      display: none;
      width: min(460px, calc(100vw - var(--sidebar-width) - 64px));
      max-height: calc(100vh - 112px);
      overflow: auto;
      padding: 16px;
      background: rgba(255, 255, 255, 0.98);
      border: 1px solid var(--panel-border);
      border-radius: 14px;
      box-shadow: 0 22px 64px rgba(27, 31, 36, 0.2);
      transition: left 170ms ease;
    }

    body.sidebar-collapsed .create-panel {
      left: calc(var(--sidebar-collapsed-width) + 34px);
      width: min(460px, calc(100vw - var(--sidebar-collapsed-width) - 64px));
    }

    .create-panel.open {
      display: block;
    }

    .create-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }

    .create-header h2 {
      margin: 0;
      font-size: 16px;
    }

    .form-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }

    .field {
      display: grid;
      gap: 6px;
    }

    .field.full {
      grid-column: 1 / -1;
    }

    .field label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }

    .field input {
      width: 100%;
      height: 36px;
      padding: 0 10px;
      color: var(--text);
      background: #ffffff;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      outline: none;
    }

    .field input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(9, 105, 218, 0.12);
    }

    .form-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 16px;
    }

    #formStatus {
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
    }

    #formStatus.error {
      color: var(--danger);
    }

    @media (max-width: 900px) {
      :root {
        --sidebar-width: 276px;
      }

      .topbar {
        left: 16px;
        right: 16px;
        top: auto;
        bottom: 16px;
      }

      body.sidebar-collapsed .topbar {
        left: 16px;
      }

      #legend,
      #details {
        display: none;
      }

      .create-panel,
      body.sidebar-collapsed .create-panel {
        left: 16px;
        right: 16px;
        width: auto;
      }
    }
  </style>
</head>
<body>
  <canvas id="world"></canvas>

  <aside id="sidebar" class="sidebar" aria-label="World sidebar">
    <div class="sidebar-top">
      <button id="collapseSidebar" class="icon-button" type="button" aria-label="Collapse sidebar">
        <svg class="collapse-expanded" viewBox="0 0 24 24" fill="none" stroke-width="2">
          <rect x="3" y="4" width="18" height="16" rx="3"></rect>
          <path d="M9 4v16"></path>
          <path d="M6 9h1"></path>
          <path d="M6 12h1"></path>
          <path d="M6 15h1"></path>
        </svg>
        <svg class="collapse-collapsed" viewBox="0 0 24 24" fill="none" stroke-width="2">
          <rect x="3" y="4" width="18" height="16" rx="3"></rect>
          <path d="M15 4v16"></path>
          <path d="M8 9h1"></path>
          <path d="M8 12h1"></path>
          <path d="M8 15h1"></path>
        </svg>
      </button>
      <button id="openCreate" class="icon-button" type="button" aria-label="Create world">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
          <path d="M18.375 2.625a2.12 2.12 0 1 1 3 3L12.36 14.64a2 2 0 0 1-.85.5l-2.87.84a.5.5 0 0 1-.62-.62l.84-2.87a2 2 0 0 1 .5-.85Z"></path>
        </svg>
      </button>
    </div>

    <div class="sidebar-search-wrap">
      <div class="sidebar-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="7"></circle>
          <path d="m20 20-3.5-3.5"></path>
        </svg>
        <input id="worldSearch" type="search" placeholder="Search worlds or seeds" autocomplete="off" />
      </div>
    </div>

    <div id="worldList" class="world-list"></div>

    <div class="sidebar-footer">
      <span class="footer-world" aria-label="Worlds">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="9"></circle>
          <path d="M3.6 9h16.8"></path>
          <path d="M3.6 15h16.8"></path>
          <path d="M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9"></path>
          <path d="M12 3c-2.4 2.6-3.6 5.6-3.6 9s1.2 6.4 3.6 9"></path>
        </svg>
      </span>
    </div>
  </aside>

  <section id="createPanel" class="create-panel" aria-label="Create World">
    <div class="create-header">
      <h2>Create World</h2>
      <button id="closeCreate" class="icon-button" type="button" aria-label="Close create world panel" style="color:#59636e">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2">
          <path d="M18 6 6 18"></path>
          <path d="m6 6 12 12"></path>
        </svg>
      </button>
    </div>

    <form id="createWorldForm">
      <div class="form-grid">
        <div class="field full">
          <label for="displayNameInput">output / world name</label>
          <input id="displayNameInput" name="display_name" value="Seed 42" />
        </div>
        <div class="field">
          <label for="seedInput">seed</label>
          <input id="seedInput" name="seed" type="number" step="1" value="42" />
        </div>
        <div class="field">
          <label for="areaMultiplierInput">area_multiplier</label>
          <input id="areaMultiplierInput" name="area_multiplier" type="number" step="0.1" value="3" />
        </div>
        <div class="field">
          <label for="baseWidthInput">base_world_width</label>
          <input id="baseWidthInput" name="base_world_width" type="number" step="1" value="100000" />
        </div>
        <div class="field">
          <label for="baseHeightInput">base_world_height</label>
          <input id="baseHeightInput" name="base_world_height" type="number" step="1" value="100000" />
        </div>
        <div class="field">
          <label for="agentCountInput">agent_count</label>
          <input id="agentCountInput" name="agent_count" type="number" step="1" value="8200" />
        </div>
        <div class="field">
          <label for="depositCountInput">deposit_count</label>
          <input id="depositCountInput" name="deposit_count" type="number" step="1" value="10000" />
        </div>
        <div class="field full">
          <label for="totalUnitsInput">total_resource_units</label>
          <input id="totalUnitsInput" name="total_resource_units" type="number" step="1" value="10000000" />
        </div>
      </div>
      <div class="form-actions">
        <span id="formStatus"></span>
        <button id="generateWorld" class="primary-button" type="submit">Generate World</button>
      </div>
    </form>
  </section>

  <header class="topbar">
    <div class="title-stack">
      <div id="title">ESC World Dashboard</div>
      <div id="summary">Loading saved worlds...</div>
    </div>
    <div class="top-actions">
      <button id="reset" class="control-button" type="button">Reset view</button>
      <button id="refresh" class="control-button" type="button">Reload world</button>
    </div>
  </header>

  <div id="legend" class="panel">
    <h2>Legend</h2>
    <div class="legend-row">
      <span class="swatch" style="background:#111827"></span>
      <span>agent</span>
    </div>
    <div class="legend-row">
      <span class="swatch square" style="background:#ef4444"></span>
      <span>machine</span>
    </div>
    <div id="resourceLegend"></div>
  </div>

  <div id="details" class="panel">
    <h2>Selected Node</h2>
    <div id="detailsBody">Hover or click an entity.</div>
  </div>

  <div id="tooltip"></div>
  <div id="loading" class="loading">Loading world...</div>

  <script>
    const canvas = document.getElementById("world");
    const ctx = canvas.getContext("2d");
    const summary = document.getElementById("summary");
    const title = document.getElementById("title");
    const loading = document.getElementById("loading");
    const tooltip = document.getElementById("tooltip");
    const detailsBody = document.getElementById("detailsBody");
    const resourceLegend = document.getElementById("resourceLegend");
    const sidebar = document.getElementById("sidebar");
    const topbar = document.querySelector(".topbar");
    const legendPanel = document.getElementById("legend");
    const resetButton = document.getElementById("reset");
    const refreshButton = document.getElementById("refresh");
    const collapseButton = document.getElementById("collapseSidebar");
    const openCreateButton = document.getElementById("openCreate");
    const closeCreateButton = document.getElementById("closeCreate");
    const createPanel = document.getElementById("createPanel");
    const createWorldForm = document.getElementById("createWorldForm");
    const formStatus = document.getElementById("formStatus");
    const generateWorldButton = document.getElementById("generateWorld");
    const worldList = document.getElementById("worldList");
    const worldSearch = document.getElementById("worldSearch");

    const resourceColors = {
      iron_ore: "#9a5a2e",
      copper_ore: "#f97316",
      coal: "#4b5563",
      stone: "#a8a29e",
      crude_oil: "#7c3aed",
      water: "#2563eb",
      wood: "#15803d",
      uranium_ore: "#84cc16",
      fish: "#06b6d4",
    };
    const agentColor = "#111827";
    const machineColor = "#ef4444";

    const state = {
      world: null,
      worlds: [],
      selectedWorldId: null,
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
    window.dashboardState = state;

    function showLoading(message) {
      loading.textContent = message || "Loading world...";
      loading.classList.add("visible");
    }

    function hideLoading() {
      loading.classList.remove("visible");
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

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

    function fitViewport() {
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      const isDesktop = window.innerWidth > 900;

      if (!isDesktop) {
        return {
          left: 28,
          top: 28,
          width: Math.max(240, width - 56),
          height: Math.max(240, height - 120),
        };
      }

      const gap = 36;
      const sidebarRect = sidebar.getBoundingClientRect();
      const topbarRect = topbar.getBoundingClientRect();
      const legendRect = legendPanel.getBoundingClientRect();
      const rightPanelLeft = legendRect.width > 0 ? legendRect.left : width - 28;
      const left = sidebarRect.right + gap;
      const top = topbarRect.bottom + 28;
      const rightEdge = Math.max(left + 240, rightPanelLeft - gap);
      const bottomEdge = height - 28;

      return {
        left,
        top,
        width: Math.max(240, rightEdge - left),
        height: Math.max(240, bottomEdge - top),
      };
    }

    function fitWorldToScreen() {
      const metadata = state.world.metadata;
      const viewport = fitViewport();
      const scaleX = viewport.width / metadata.world_width;
      const scaleY = viewport.height / metadata.world_height;

      state.scale = Math.max(0.0001, Math.min(scaleX, scaleY));
      state.minScale = state.scale * 0.4;
      state.maxScale = state.scale * 800;
      state.offsetX =
        viewport.left + (viewport.width - metadata.world_width * state.scale) / 2;
      state.offsetY =
        viewport.top + (viewport.height - metadata.world_height * state.scale) / 2;
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

      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#f6f8fa";
      ctx.fillRect(0, 0, width, height);

      if (!state.world) return;

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

    function roundedPolygonPath(points, cornerRadius) {
      points.forEach((point, index) => {
        const previous = points[(index - 1 + points.length) % points.length];
        const next = points[(index + 1) % points.length];
        const previousVector = {
          x: previous.x - point.x,
          y: previous.y - point.y,
        };
        const nextVector = {
          x: next.x - point.x,
          y: next.y - point.y,
        };
        const previousLength = Math.hypot(previousVector.x, previousVector.y);
        const nextLength = Math.hypot(nextVector.x, nextVector.y);
        const distance = Math.min(cornerRadius, previousLength / 2, nextLength / 2);
        const start = {
          x: point.x + (previousVector.x / previousLength) * distance,
          y: point.y + (previousVector.y / previousLength) * distance,
        };
        const end = {
          x: point.x + (nextVector.x / nextLength) * distance,
          y: point.y + (nextVector.y / nextLength) * distance,
        };

        if (index === 0) {
          ctx.moveTo(start.x, start.y);
        } else {
          ctx.lineTo(start.x, start.y);
        }
        ctx.quadraticCurveTo(point.x, point.y, end.x, end.y);
      });
      ctx.closePath();
    }

    function roundedTrianglePath(point, radius, cornerRadius) {
      roundedPolygonPath(
        [
          { x: point.x, y: point.y - radius },
          { x: point.x + radius * 0.95, y: point.y + radius * 0.82 },
          { x: point.x - radius * 0.95, y: point.y + radius * 0.82 },
        ],
        cornerRadius,
      );
    }

    function roundedRectPath(x, y, width, height, radius) {
      const cornerRadius = Math.min(radius, width / 2, height / 2);
      ctx.moveTo(x + cornerRadius, y);
      ctx.lineTo(x + width - cornerRadius, y);
      ctx.quadraticCurveTo(x + width, y, x + width, y + cornerRadius);
      ctx.lineTo(x + width, y + height - cornerRadius);
      ctx.quadraticCurveTo(x + width, y + height, x + width - cornerRadius, y + height);
      ctx.lineTo(x + cornerRadius, y + height);
      ctx.quadraticCurveTo(x, y + height, x, y + height - cornerRadius);
      ctx.lineTo(x, y + cornerRadius);
      ctx.quadraticCurveTo(x, y, x + cornerRadius, y);
      ctx.closePath();
    }

    function drawDeposits() {
      const radius = 3.8;
      ctx.globalAlpha = 0.86;
      for (const deposit of worldDeposits()) {
        const point = worldToScreen(deposit.coordinate);
        if (!isVisible(point, radius)) continue;

        ctx.beginPath();
        ctx.fillStyle = resourceColors[deposit.item] || "#6e7781";
        roundedTrianglePath(point, radius, 1.2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function drawMachines() {
      const radius = 4.4;
      ctx.save();
      ctx.fillStyle = machineColor;

      for (const machine of worldMachines()) {
        const point = worldToScreen(machine.coordinate);
        if (!isVisible(point, radius)) continue;

        ctx.beginPath();
        roundedRectPath(point.x - radius, point.y - radius, radius * 2, radius * 2, 2);
        ctx.fill();
      }

      ctx.restore();
    }

    function drawAgents() {
      const radius = 1.8;
      ctx.fillStyle = agentColor;
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
      if (node.type === "deposit") {
        roundedTrianglePath(point, 8, 2.6);
      } else if (node.type === "machine") {
        roundedRectPath(point.x - 7, point.y - 7, 14, 14, 3);
      } else {
        ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
      }
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
          `<div class="detail-row"><span class="detail-key">${escapeHtml(key)}</span><span>${escapeHtml(value)}</span></div>`
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
      legendPanel.hidden = resourceTypes.length === 0;
      resourceLegend.innerHTML = resourceTypes
        .map((resource) => (
          `<div class="legend-row">
            <svg class="swatch-icon" viewBox="0 0 16 16" aria-hidden="true">
              <path fill="${resourceColors[resource] || "#6e7781"}" d="M8 1.4 Q8.7 1.4 9.1 2.1 L14.7 12.3 Q15.2 13.2 14.6 14 Q14.1 14.7 13.1 14.7 H2.9 Q1.9 14.7 1.4 14 Q0.8 13.2 1.3 12.3 L6.9 2.1 Q7.3 1.4 8 1.4 Z"></path>
            </svg>
            <span>${escapeHtml(resource)}</span>
          </div>`
        ))
        .join("");
    }

    function selectedWorldMeta() {
      return state.worlds.find((world) => world.id === state.selectedWorldId) || null;
    }

    function renderWorldList() {
      const query = worldSearch.value.trim().toLowerCase();
      const filteredWorlds = state.worlds.filter((world) => {
        const haystack = `${world.display_name} ${world.seed}`.toLowerCase();
        return haystack.includes(query);
      });

      if (!state.worlds.length) {
        worldList.innerHTML = "";
        return;
      }

      if (!filteredWorlds.length) {
        worldList.innerHTML = `<div class="world-empty">No worlds match this search.</div>`;
        return;
      }

      worldList.innerHTML = filteredWorlds
        .map((world) => {
          const active = world.id === state.selectedWorldId ? " active" : "";
          return `<div class="world-row${active}" data-world-id="${escapeHtml(world.id)}">
            <button class="world-main" type="button" data-action="select" data-world-id="${escapeHtml(world.id)}">
              <span class="world-name">${escapeHtml(world.display_name)}</span>
              <span class="world-meta">seed ${escapeHtml(world.seed)} · ${escapeHtml(world.created_at || "")}</span>
            </button>
            <span class="world-more-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <circle cx="6" cy="12" r="1.8"></circle>
                <circle cx="12" cy="12" r="1.8"></circle>
                <circle cx="18" cy="12" r="1.8"></circle>
              </svg>
            </span>
          </div>`;
        })
        .join("");
    }

    function renderWorldSummary() {
      if (!state.world) {
        title.textContent = "None";
        summary.textContent = "No world selected";
        return;
      }

      const meta = selectedWorldMeta();
      const metadata = state.world.metadata;
      const agentCount = worldAgents().length;
      const depositCount = worldDeposits().length;
      const machineCount = worldMachines().length;
      const shapeSummary = metadata.world_shape === "circle"
        ? `circle r ${metadata.world_radius.toLocaleString()}`
        : `${metadata.world_width} x ${metadata.world_height}`;

      title.textContent = meta ? meta.display_name : "Selected World";
      summary.textContent = [
        `seed ${metadata.seed}`,
        shapeSummary,
        formatAreaMultiplier(metadata.area_multiplier || 1),
        `${agentCount.toLocaleString()} agents`,
        `${depositCount.toLocaleString()} deposits`,
        `${machineCount.toLocaleString()} machines`,
        `${metadata.total_resource_units.toLocaleString()} resource units`,
      ].join(" | ");
    }

    async function apiJson(url, options = {}) {
      const response = await fetch(url, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(options.headers || {}),
        },
      });
      const text = await response.text();
      let data = null;
      if (text) {
        data = JSON.parse(text);
      }
      if (!response.ok) {
        throw new Error(data?.error || `Request failed: ${response.status}`);
      }
      return data;
    }

    async function loadWorldList({ selectCurrent = true } = {}) {
      const data = await apiJson("/api/worlds?cacheBust=" + Date.now());
      state.worlds = data.worlds || [];
      const selectedExists = state.worlds.some((world) => {
        return world.id === data.selected_world_id;
      });
      state.selectedWorldId = selectedExists
        ? data.selected_world_id
        : state.worlds[0]?.id || null;
      renderWorldList();

      if (selectCurrent && state.selectedWorldId) {
        await loadSelectedWorld(state.selectedWorldId);
      } else {
        state.world = null;
        renderLegend([]);
        renderWorldSummary();
        hideLoading();
        requestDraw();
        if (!state.worlds.length) {
          createPanel.classList.add("open");
        }
      }
    }

    async function loadSelectedWorld(worldId) {
      if (!worldId) {
        state.world = null;
        state.selectedWorldId = null;
        renderLegend([]);
        renderWorldSummary();
        hideLoading();
        requestDraw();
        return;
      }

      showLoading("Loading world...");
      state.hoverNode = null;
      state.selectedNode = null;
      setDetails(null);

      const response = await fetch(`/api/world?id=${encodeURIComponent(worldId)}&cacheBust=${Date.now()}`);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || "Could not load selected world");
      }

      state.world = await response.json();
      state.selectedWorldId = worldId;
      renderLegend(state.world.metadata.resource_types);
      renderWorldSummary();
      renderWorldList();
      fitWorldToScreen();
      hideLoading();
      requestDraw();
    }

    function numberField(formData, name) {
      const value = Number(formData.get(name));
      if (!Number.isFinite(value)) {
        throw new Error(`${name} must be a number`);
      }
      return value;
    }

    async function generateWorld(event) {
      event.preventDefault();
      formStatus.textContent = "";
      formStatus.classList.remove("error");
      generateWorldButton.disabled = true;
      generateWorldButton.textContent = "Generating...";

      try {
        const formData = new FormData(createWorldForm);
        const payload = {
          display_name: String(formData.get("display_name") || "").trim(),
          seed: Math.trunc(numberField(formData, "seed")),
          base_world_width: Math.trunc(numberField(formData, "base_world_width")),
          base_world_height: Math.trunc(numberField(formData, "base_world_height")),
          area_multiplier: numberField(formData, "area_multiplier"),
          agent_count: Math.trunc(numberField(formData, "agent_count")),
          deposit_count: Math.trunc(numberField(formData, "deposit_count")),
          total_resource_units: Math.trunc(numberField(formData, "total_resource_units")),
        };

        formStatus.textContent = "Generating world JSON...";
        const data = await apiJson("/api/worlds/generate", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        createPanel.classList.remove("open");
        await loadWorldList({ selectCurrent: false });
        await loadSelectedWorld(data.world.id);
      } catch (error) {
        formStatus.textContent = error.message;
        formStatus.classList.add("error");
      } finally {
        generateWorldButton.disabled = false;
        generateWorldButton.textContent = "Generate World";
      }
    }

    function updateWorldNameDefault() {
      const seed = document.getElementById("seedInput").value || "42";
      const nameInput = document.getElementById("displayNameInput");
      if (!nameInput.value.trim() || /^Seed \d+$/.test(nameInput.value.trim())) {
        nameInput.value = `Seed ${seed}`;
      }
    }

    collapseButton.addEventListener("click", () => {
      document.body.classList.toggle("sidebar-collapsed");
      window.setTimeout(resizeCanvas, 190);
    });

    openCreateButton.addEventListener("click", () => {
      createPanel.classList.toggle("open");
    });

    closeCreateButton.addEventListener("click", () => {
      createPanel.classList.remove("open");
    });

    worldSearch.addEventListener("input", renderWorldList);

    worldList.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-world-id]");
      if (!button) return;

      const worldId = button.dataset.worldId;
      const action = button.dataset.action;
      if (action === "select") {
        loadSelectedWorld(worldId).catch((error) => {
          showLoading(error.message);
        });
      }
    });

    createWorldForm.addEventListener("submit", generateWorld);
    document.getElementById("seedInput").addEventListener("input", updateWorldNameDefault);

    resetButton.addEventListener("click", () => {
      if (!state.world) return;
      fitWorldToScreen();
      requestDraw();
    });

    refreshButton.addEventListener("click", () => {
      if (!state.selectedWorldId) {
        createPanel.classList.add("open");
        return;
      }
      loadSelectedWorld(state.selectedWorldId).catch((error) => {
        showLoading(error.message);
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
    showLoading("Loading saved worlds...");
    loadWorldList().catch((error) => {
      showLoading(error.message);
    });
  </script>
</body>
</html>
"""


def parse_args():
    """Parse server settings."""
    parser = argparse.ArgumentParser(
        description="Serve the ESC world dashboard and world management API."
    )
    parser.add_argument("--index", default=DEFAULT_INDEX_PATH)
    parser.add_argument("--worlds-dir", default=DEFAULT_WORLDS_DIR)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args()


def utc_now_iso():
    """Return a compact UTC timestamp for the index."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path):
    """Read JSON from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    """Write readable JSON to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def validate_world_file(path):
    """Read and lightly validate a world JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist. Run world_generator.py first.")

    data = read_json(path)
    missing_keys = REQUIRED_WORLD_KEYS - set(data)
    if missing_keys:
        raise ValueError(f"World JSON is missing keys: {sorted(missing_keys)}")

    return data


def path_for_index(index_path, file_path):
    """Resolve an index file_path relative to the index location."""
    path = Path(file_path)
    if path.is_absolute():
        return path
    return index_path.parent / path


def relative_to_index(index_path, file_path):
    """Store file paths relative to the index when possible."""
    path = Path(file_path)
    try:
        return str(path.resolve().relative_to(index_path.parent.resolve()))
    except ValueError:
        return str(path)


def normalize_index(index, index_path=None):
    """Keep the index shape predictable for the browser.

    When index_path is available, entries whose world files no longer exist are
    skipped. This lets the dashboard recover cleanly after generated files are
    removed.
    """
    if not isinstance(index, dict):
        index = {}

    worlds = index.get("worlds")
    if not isinstance(worlds, list):
        worlds = []

    normalized_worlds = []
    for world in worlds:
        if not isinstance(world, dict):
            continue
        if not world.get("id") or not world.get("file_path"):
            continue
        if index_path is not None:
            world_path = path_for_index(index_path, world["file_path"])
            if not world_path.exists():
                continue
        normalized_worlds.append(world)

    selected_world_id = index.get("selected_world_id")
    if selected_world_id not in {world["id"] for world in normalized_worlds}:
        selected_world_id = normalized_worlds[0]["id"] if normalized_worlds else None

    return {
        "selected_world_id": selected_world_id,
        "worlds": normalized_worlds,
    }


def ensure_index(index_path):
    """Create or normalize worlds_index.json."""
    with INDEX_LOCK:
        if index_path.exists():
            index = normalize_index(read_json(index_path), index_path)
        else:
            index = {"selected_world_id": None, "worlds": []}

        write_json(index_path, index)
        return index


def load_index(index_path):
    """Load the world index, creating it if needed."""
    return ensure_index(index_path)


def save_index(index_path, index):
    """Persist the normalized index."""
    write_json(index_path, normalize_index(index, index_path))


def find_world_entry(index, world_id):
    """Return the world index entry for an id."""
    for world in index["worlds"]:
        if world["id"] == world_id:
            return world
    raise KeyError(f"Unknown world id: {world_id}")


def selected_or_requested_world_id(index, requested_id):
    """Choose the requested world id, falling back to the selected id."""
    if requested_id:
        return requested_id
    if index["selected_world_id"]:
        return index["selected_world_id"]
    if index["worlds"]:
        return index["worlds"][0]["id"]
    raise KeyError("No worlds are available.")


def load_world_bytes(index_path, requested_id=None):
    """Load the selected world JSON bytes."""
    with INDEX_LOCK:
        index = load_index(index_path)
        world_id = selected_or_requested_world_id(index, requested_id)
        entry = find_world_entry(index, world_id)
        path = path_for_index(index_path, entry["file_path"])
        validate_world_file(path)
        return path.read_bytes()


def unique_display_name(index, requested_name, seed):
    """Return a display name that does not collide with existing worlds."""
    base_name = requested_name.strip() if requested_name else f"Seed {seed}"
    existing_names = {world.get("display_name", "") for world in index["worlds"]}
    if base_name not in existing_names:
        return base_name

    suffix = 2
    while f"{base_name} ({suffix})" in existing_names:
        suffix += 1
    return f"{base_name} ({suffix})"


def unique_world_id(seed):
    """Return a unique id suitable for a saved world file."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"world_seed_{seed}_{stamp}_{uuid.uuid4().hex[:8]}"


def int_setting(payload, key):
    """Read an integer setting from a request payload."""
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer.")
    try:
        value = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer.") from error
    return value


def float_setting(payload, key):
    """Read a floating point setting from a request payload."""
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        value = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a number.") from error
    return value


def generate_world_from_payload(index_path, worlds_dir, payload):
    """Generate a world, save it, and append it to the world index."""
    seed = int_setting(payload, "seed")
    base_world_width = int_setting(payload, "base_world_width")
    base_world_height = int_setting(payload, "base_world_height")
    area_multiplier = float_setting(payload, "area_multiplier")
    agent_count = int_setting(payload, "agent_count")
    deposit_count = int_setting(payload, "deposit_count")
    total_resource_units = int_setting(payload, "total_resource_units")

    world = build_world(
        seed=seed,
        base_world_width=base_world_width,
        base_world_height=base_world_height,
        area_multiplier=area_multiplier,
        agent_count=agent_count,
        deposit_count=deposit_count,
        total_resource_units=total_resource_units,
    )

    with INDEX_LOCK:
        index = load_index(index_path)
        world_id = unique_world_id(seed)
        output_path = worlds_dir / f"{world_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        save_world(world, output_path)

        entry = {
            "id": world_id,
            "display_name": unique_display_name(
                index,
                str(payload.get("display_name", "")),
                seed,
            ),
            "seed": seed,
            "file_path": relative_to_index(index_path, output_path),
            "created_at": utc_now_iso(),
        }
        index["worlds"].insert(0, entry)
        index["selected_world_id"] = world_id
        save_index(index_path, index)

    return entry


def public_index(index_path):
    """Return the index payload sent to the browser."""
    with INDEX_LOCK:
        index = load_index(index_path)
        return {
            "selected_world_id": index["selected_world_id"],
            "worlds": index["worlds"],
        }


def make_handler(index_path, worlds_dir):
    """Create a request handler bound to the selected dashboard paths."""

    class WorldDashboardHandler(BaseHTTPRequestHandler):
        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_bytes(status, body, "application/json; charset=utf-8")

        def send_text(self, status, message):
            self.send_bytes(
                status,
                str(message).encode("utf-8"),
                "text/plain; charset=utf-8",
            )

        def read_json_body(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def handle_request(self, include_body=True):
            parsed = urlparse(self.path)

            if parsed.path == "/":
                self.send_bytes(
                    200,
                    HTML_PAGE.encode("utf-8"),
                    "text/html; charset=utf-8",
                )
                return

            if parsed.path == "/api/worlds":
                self.send_json(200, public_index(index_path))
                return

            if parsed.path in {"/api/world", "/world.json"}:
                query = parse_qs(parsed.query)
                world_id = query.get("id", [None])[0]
                try:
                    world_bytes = load_world_bytes(index_path, world_id)
                except Exception as error:
                    self.send_text(404, error)
                    return

                self.send_bytes(200, world_bytes, "application/json; charset=utf-8")
                return

            self.send_text(404, "Not found")

        def do_HEAD(self):
            self.handle_request(include_body=False)

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            parsed = urlparse(self.path)

            try:
                payload = self.read_json_body()
                if parsed.path == "/api/worlds/generate":
                    entry = generate_world_from_payload(
                        index_path,
                        worlds_dir,
                        payload,
                    )
                    self.send_json(200, {"world": entry})
                    return

                self.send_text(404, "Not found")
            except Exception as error:
                self.send_json(400, {"error": str(error)})

        def log_message(self, format_string, *args):
            """Keep terminal output quiet unless there is a real server error."""
            return

    return WorldDashboardHandler


def start_server(host, port, index_path, worlds_dir):
    """Start the HTTP server, trying nearby ports if the default is busy."""
    handler = make_handler(index_path, worlds_dir)
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
    index_path = Path(args.index)
    worlds_dir = Path(args.worlds_dir)

    ensure_index(index_path)
    server, actual_port = start_server(
        args.host,
        args.port,
        index_path,
        worlds_dir,
    )

    print(f"Serving dashboard with {index_path}", flush=True)
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

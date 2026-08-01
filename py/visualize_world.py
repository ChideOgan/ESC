#!/usr/bin/env python3
"""Serve the ESC world dashboard.

The dashboard is intentionally still a Step 1 tool:
- it lists saved generated worlds,
- it can generate another static world from form settings,
- it renders the selected world on a canvas,
- it can run the one-agent brain lab in memory for one-agent worlds.

There is still no mining, trade, messaging, pricing, production, or economy
logic here. The only live mutation is the one-agent brain-lab movement loop.
"""

import argparse
import json
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from brain import (
    StaticTensorSequenceBrain,
    WorldEnvironment,
    apply_action,
    valid_actions_from_coordinate,
)
from world_generator import (
    build_world,
    coordinate_key,
    save_world,
)


DEFAULT_INDEX_PATH = "worlds_index.json"
DEFAULT_WORLDS_DIR = "worlds"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
FORECAST_BATCH_SIZE = 100
DEFAULT_FORECAST_PASS_PERCENT = 90.0
MAX_FORECAST_LEVEL = 100
DEFAULT_AUTO_INCREASE_BY = 1
DEFAULT_AUTO_INCREASE_PASSES = 100
MAX_AUTO_INCREASE_PASSES = 100_000

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

    .world-delete-button {
      display: grid;
      place-items: center;
      width: 30px;
      height: 30px;
      color: #8c959f;
      background: transparent;
      border: 0;
      border-radius: 8px;
      cursor: pointer;
    }

    .world-delete-button:hover {
      color: var(--danger);
      background: #fff1f0;
    }

    .world-delete-button svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
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

    .title-time {
      display: inline-block;
      margin-left: 6px;
      padding: 1px 5px;
      color: #0969da;
      background: #ddf4ff;
      border: 1px solid #b6e3ff;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 625;
    }

    #summary {
      margin-top: 6px;
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

    .brain-controls {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .icon-control-button {
      width: 34px;
      height: 34px;
      display: grid;
      place-items: center;
      padding: 0;
    }

    .icon-control-button svg {
      width: 16px;
      height: 16px;
      stroke-width: 2.2;
    }

    .icon-control-button.is-active {
      color: var(--accent);
      border-color: var(--accent);
      background: #eff6ff;
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

    #trainingInfo {
      right: 16px;
      top: 84px;
      width: 304px;
      height: 400px;
      min-height: 180px;
      padding: 14px;
      border-radius: 16px;
      display: flex;
      flex-direction: column;
    }

    #trainingInfo h2 {
      margin: 0 0 16px;
      font-size: 13px;
    }

    .training-level-control {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .level-stepper {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }

    .level-stepper button {
      display: grid;
      width: 24px;
      height: 24px;
      place-items: center;
      padding: 0;
      color: var(--muted);
      background: #ffffff;
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      cursor: pointer;
    }

    .level-stepper button:hover:not(:disabled) {
      color: var(--accent);
      border-color: var(--accent);
    }

    .level-stepper button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }

    .level-stepper svg {
      width: 14px;
      height: 14px;
      stroke-width: 2.25;
    }

    .level-stepper input {
      width: 46px;
      height: 24px;
      padding: 0 5px;
      color: var(--text);
      background: #ffffff;
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      font: inherit;
      font-variant-numeric: tabular-nums;
      text-align: center;
      appearance: textfield;
      -moz-appearance: textfield;
    }

    .level-stepper input::-webkit-inner-spin-button,
    .level-stepper input::-webkit-outer-spin-button {
      margin: 0;
      -webkit-appearance: none;
    }

    .level-stepper input:focus {
      outline: 2px solid rgba(9, 105, 218, 0.2);
      border-color: var(--accent);
    }

    .level-stepper input:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }

    .training-console-controls {
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }

    .console-setting {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .console-toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }

    .console-toggle input {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
    }

    .toggle-track {
      position: relative;
      width: 34px;
      height: 20px;
      flex: 0 0 auto;
      border: 1px solid var(--panel-border);
      border-radius: 999px;
      background: #d8dee4;
      cursor: pointer;
      transition: background 140ms ease, border-color 140ms ease;
    }

    .toggle-track::after {
      position: absolute;
      top: 3px;
      left: 3px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: #ffffff;
      content: "";
      transition: transform 140ms ease;
    }

    .console-toggle input:checked + .toggle-track {
      border-color: var(--accent);
      background: var(--accent);
    }

    .console-toggle input:checked + .toggle-track::after {
      transform: translateX(14px);
    }

    .console-toggle input:focus-visible + .toggle-track {
      outline: 2px solid rgba(9, 105, 218, 0.25);
      outline-offset: 2px;
    }

    .console-toggle input:disabled + .toggle-track {
      cursor: not-allowed;
      opacity: 0.55;
    }

    .auto-increase-settings {
      display: grid;
      grid-template-columns: auto 44px auto 54px auto;
      align-items: center;
      justify-content: center;
      column-gap: 8px;
      margin: 0 0 2px;
      min-height: 30px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }

    .auto-increase-number {
      width: 100%;
      height: 28px;
      padding: 0 5px;
      color: var(--text);
      background: #ffffff;
      border: 1px solid var(--panel-border);
      border-radius: 6px;
      font: inherit;
      font-variant-numeric: tabular-nums;
      text-align: center;
      appearance: textfield;
      -moz-appearance: textfield;
    }

    .auto-increase-number::-webkit-inner-spin-button,
    .auto-increase-number::-webkit-outer-spin-button {
      margin: 0;
      -webkit-appearance: none;
    }

    .auto-increase-number:focus {
      outline: 2px solid rgba(9, 105, 218, 0.2);
      border-color: var(--accent);
    }

    .auto-increase-number:disabled {
      cursor: not-allowed;
      color: #8c959f;
      background: #f6f8fa;
    }

    .training-metrics {
      display: grid;
      grid-template-columns: 1fr;
      margin-top: 12px;
      border-top: 1px solid var(--panel-border);
    }

    .metric-cell {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-width: 0;
      padding: 9px 0;
      border-bottom: 1px solid rgba(208, 215, 222, 0.7);
    }

    .metric-label {
      display: inline;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: none;
    }

    .metric-value {
      display: inline;
      margin-top: 0;
      overflow: hidden;
      color: var(--text);
      font-size: 13px;
      font-weight: 750;
      text-overflow: ellipsis;
      white-space: nowrap;
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

    .modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 12;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(27, 31, 36, 0.28);
    }

    .modal-backdrop[hidden] {
      display: none;
    }

    .confirm-dialog {
      width: min(360px, 100%);
      padding: 18px;
      background: #ffffff;
      border: 1px solid var(--panel-border);
      border-radius: 14px;
      box-shadow: 0 24px 70px rgba(27, 31, 36, 0.22);
    }

    .confirm-dialog h2 {
      margin: 0;
      font-size: 16px;
    }

    .confirm-dialog p {
      margin: 10px 0 18px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }

    .dialog-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
    }

    .dialog-button {
      height: 34px;
      padding: 0 13px;
      color: var(--muted);
      background: #ffffff;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      cursor: pointer;
      font-weight: 700;
    }

    .dialog-button:hover {
      border-color: var(--accent);
    }

    .dialog-button.confirm {
      color: #ffffff;
      background: var(--danger);
      border-color: var(--danger);
    }

    .dialog-button:disabled {
      cursor: not-allowed;
      opacity: 0.65;
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

      #trainingInfo,
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
          <label for="chaosLevelInput">chaos_level</label>
          <input
            id="chaosLevelInput"
            name="chaos_level"
            type="number"
            min="0"
            max="1"
            step="0.05"
            value="0.5"
          />
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
      <div class="brain-controls" aria-label="Brain controls">
        <button id="playBrain" class="control-button icon-control-button" type="button" aria-label="Play brain">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <polygon points="6 4 20 12 6 20 6 4"></polygon>
          </svg>
        </button>
        <button id="pauseBrain" class="control-button icon-control-button" type="button" aria-label="Pause brain">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <rect x="6" y="4" width="4" height="16"></rect>
            <rect x="14" y="4" width="4" height="16"></rect>
          </svg>
        </button>
      </div>
      <button id="reset" class="control-button" type="button">Reset view</button>
      <button id="refresh" class="control-button" type="button">Reload world</button>
    </div>
  </header>

  <div id="trainingInfo" class="panel">
    <h2>Training Console</h2>
    <div class="training-level-control">
      <span>Forecast Length</span>
      <div class="level-stepper">
        <button id="decreaseForecastLevel" type="button" aria-label="Decrease forecast length" title="Decrease forecast length">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M5 12h14"></path></svg>
        </button>
        <input id="forecastLevelInput" type="number" min="1" max="100" step="1" value="1" inputmode="numeric" aria-label="Forecast length" />
        <button id="increaseForecastLevel" type="button" aria-label="Increase forecast length" title="Increase forecast length">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>
        </button>
      </div>
    </div>
    <div class="training-console-controls">
      <label class="console-setting" for="passGradeInput">
        <span>Pass Grade</span>
        <span class="level-stepper">
          <button id="decreasePassGrade" type="button" aria-label="Decrease pass grade" title="Decrease pass grade">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M5 12h14"></path></svg>
          </button>
          <input id="passGradeInput" type="number" min="0" max="100" step="1" value="90" inputmode="numeric" aria-label="Pass Grade" />
          <button id="increasePassGrade" type="button" aria-label="Increase pass grade" title="Increase pass grade">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>
          </button>
        </span>
      </label>
      <label class="console-toggle" for="autoIncreaseLevelInput">
        <span>Auto Increase Length</span>
        <input id="autoIncreaseLevelInput" type="checkbox" role="switch" />
        <span class="toggle-track" aria-hidden="true"></span>
      </label>
      <div class="auto-increase-settings" aria-label="Auto increase length settings">
        <span>Increase</span>
        <input id="autoIncreaseByInput" class="auto-increase-number" type="number" min="1" max="100" step="1" value="1" inputmode="numeric" aria-label="Increase length by" disabled />
        <span>every</span>
        <input id="autoIncreasePassesInput" class="auto-increase-number" type="number" min="1" max="100000" step="1" value="100" inputmode="numeric" aria-label="Consecutive passing batches required" disabled />
        <span>passes</span>
      </div>
    </div>
    <div id="trainingMetrics" class="training-metrics"></div>
  </div>

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

  <div id="deleteDialog" class="modal-backdrop" hidden>
    <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="deleteDialogTitle">
      <h2 id="deleteDialogTitle">Delete World</h2>
      <p id="deleteDialogMessage">Delete this generated world?</p>
      <div class="dialog-actions">
        <button id="cancelDelete" class="dialog-button" type="button">Cancel</button>
        <button id="confirmDelete" class="dialog-button confirm" type="button">Confirm</button>
      </div>
    </section>
  </div>

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
    const trainingInfoPanel = document.getElementById("trainingInfo");
    const legendPanel = document.getElementById("legend");
    const detailsPanel = document.getElementById("details");
    const trainingMetrics = document.getElementById("trainingMetrics");
    const decreaseForecastLevelButton = document.getElementById("decreaseForecastLevel");
    const increaseForecastLevelButton = document.getElementById("increaseForecastLevel");
    const forecastLevelInput = document.getElementById("forecastLevelInput");
    const decreasePassGradeButton = document.getElementById("decreasePassGrade");
    const increasePassGradeButton = document.getElementById("increasePassGrade");
    const passGradeInput = document.getElementById("passGradeInput");
    const autoIncreaseLevelInput = document.getElementById("autoIncreaseLevelInput");
    const autoIncreaseByInput = document.getElementById("autoIncreaseByInput");
    const autoIncreasePassesInput = document.getElementById("autoIncreasePassesInput");
    const resetButton = document.getElementById("reset");
    const refreshButton = document.getElementById("refresh");
    const playBrainButton = document.getElementById("playBrain");
    const pauseBrainButton = document.getElementById("pauseBrain");
    const collapseButton = document.getElementById("collapseSidebar");
    const openCreateButton = document.getElementById("openCreate");
    const closeCreateButton = document.getElementById("closeCreate");
    const createPanel = document.getElementById("createPanel");
    const createWorldForm = document.getElementById("createWorldForm");
    const formStatus = document.getElementById("formStatus");
    const generateWorldButton = document.getElementById("generateWorld");
    const seedInput = document.getElementById("seedInput");
    const displayNameInput = document.getElementById("displayNameInput");
    const worldList = document.getElementById("worldList");
    const worldSearch = document.getElementById("worldSearch");
    const deleteDialog = document.getElementById("deleteDialog");
    const deleteDialogMessage = document.getElementById("deleteDialogMessage");
    const cancelDeleteButton = document.getElementById("cancelDelete");
    const confirmDeleteButton = document.getElementById("confirmDelete");

    const resourceColors = {
      iron_ore: "#9a5a2e",
      copper_ore: "#f97316",
      coal: "#facc15",
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
      followedAgentId: null,
      pendingDeleteWorldId: null,
      brainActive: false,
      brainRunning: false,
      brainBusy: false,
      brainStream: null,
      brainStreamWorldId: null,
      brainIterations: 0,
      trainingTimeMs: 0,
      trainingStartedAt: null,
      trainingTimer: null,
      forecastLevel: 1,
      pathTrials: 0,
      completedBatches: 0,
      batchSize: 100,
      batchPathsCompleted: 0,
      batchStepCorrect: [0],
      batchStepTotal: [0],
      lastGrade: null,
      lastStepAccuracies: [],
      passThresholdPercent: 90,
      targetReached: false,
      autoIncreaseLevel: false,
      autoIncreaseBy: 1,
      autoIncreasePasses: 100,
      consecutivePassingBatches: 0,
      brainStepSize: null,
      brainStepsPerTick: 1,
      brainServerIntervalMs: 10,
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

    function layoutRightPanels() {
      if (window.innerWidth <= 900 || legendPanel.hidden) {
        trainingInfoPanel.style.top = "";
        trainingInfoPanel.style.height = "";
        return;
      }

      const topbarRect = topbar.getBoundingClientRect();
      const legendRect = legendPanel.getBoundingClientRect();
      const detailsRect = detailsPanel.getBoundingClientRect();
      if (!topbarRect.height || !legendRect.height || !detailsRect.height) return;

      const sharedGap = Math.max(16, detailsRect.top - legendRect.bottom);
      const targetTop = Math.round(topbarRect.bottom + sharedGap);
      const targetHeight = Math.floor(legendRect.top - targetTop - sharedGap);

      trainingInfoPanel.style.top = `${targetTop}px`;
      trainingInfoPanel.style.height = `${Math.max(180, targetHeight)}px`;
    }

    function resizeCanvas() {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      layoutRightPanels();
      if (state.world) {
        if (state.followedAgentId) {
          followSelectedAgent();
        } else {
          fitWorldToScreen();
        }
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
      const rightPanels = [trainingInfoPanel, legendPanel]
        .map((panel) => panel.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0);
      const rightPanelLeft = rightPanels.length
        ? Math.min(...rightPanels.map((rect) => rect.left))
        : width - 28;
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
      // At the closest zoom, one world coordinate needs enough screen space
      // for a readable label. This makes the surface tile size reach 1 by 1,
      // where the displayed average is necessarily the exact integer value.
      state.maxScale = Math.max(state.scale * 800, 60);
      state.offsetX =
        viewport.left + (viewport.width - metadata.world_width * state.scale) / 2;
      state.offsetY =
        viewport.top + (viewport.height - metadata.world_height * state.scale) / 2;
    }

    function formatChaosLevel(value) {
      return `chaos ${Number(value ?? 0.5).toFixed(2)}`;
    }

    function formatTrainingTime(milliseconds) {
      let remaining = Math.max(0, Math.floor(Number(milliseconds) || 0));
      const days = Math.floor(remaining / 86400000);
      remaining %= 86400000;
      const hours = Math.floor(remaining / 3600000);
      remaining %= 3600000;
      const minutes = Math.floor(remaining / 60000);
      remaining %= 60000;
      const seconds = Math.floor(remaining / 1000);
      const ms = remaining % 1000;

      return `${days}d - ${String(hours).padStart(2, "0")}h - ${String(minutes).padStart(2, "0")}m - ${String(seconds).padStart(2, "0")}s - ${String(ms).padStart(3, "0")}ms`;
    }

    function currentTrainingTimeMs() {
      const baseTime = Math.max(0, Number(state.trainingTimeMs) || 0);
      if (!state.brainRunning || state.trainingStartedAt === null) {
        return baseTime;
      }
      return baseTime + Math.max(0, Date.now() - state.trainingStartedAt);
    }

    function clampPassThreshold(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return state.passThresholdPercent;
      return Math.max(0, Math.min(100, Math.round(number * 10) / 10));
    }

    function clampForecastLevel(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return state.forecastLevel;
      return Math.max(1, Math.min(100, Math.floor(number)));
    }

    function clampAutoIncreaseBy(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return state.autoIncreaseBy;
      return Math.max(1, Math.min(100, Math.floor(number)));
    }

    function clampAutoIncreasePasses(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return state.autoIncreasePasses;
      return Math.max(1, Math.min(100000, Math.floor(number)));
    }

    function syncTrainingInputs() {
      if (document.activeElement !== forecastLevelInput) {
        forecastLevelInput.value = String(state.forecastLevel);
      }
      if (document.activeElement !== passGradeInput) {
        passGradeInput.value = String(state.passThresholdPercent);
      }
      if (document.activeElement !== autoIncreaseByInput) {
        autoIncreaseByInput.value = String(state.autoIncreaseBy);
      }
      if (document.activeElement !== autoIncreasePassesInput) {
        autoIncreasePassesInput.value = String(state.autoIncreasePasses);
      }
      autoIncreaseLevelInput.checked = state.autoIncreaseLevel;
    }

    function renderTrainingInfo() {
      const hasGrade = Number.isFinite(state.lastGrade);
      const grade = hasGrade ? `${state.lastGrade.toFixed(1)}%` : "n/a";

      syncTrainingInputs();
      trainingMetrics.innerHTML = [
        ["Batch", `${state.batchPathsCompleted}/${state.batchSize}`],
        ["Grade", grade],
      ]
        .map(([label, value]) => `<div class="metric-cell">
          <span class="metric-label">${escapeHtml(label)}</span>
          <span class="metric-value">${escapeHtml(value)}</span>
        </div>`)
        .join("");
      layoutRightPanels();
    }

    function startTrainingTimer() {
      if (state.trainingTimer) return;

      const tick = () => {
        if (!state.trainingTimer) return;
        renderWorldSummary();
        renderTrainingInfo();
        state.trainingTimer = requestAnimationFrame(tick);
      };

      state.trainingTimer = requestAnimationFrame(tick);
    }

    function stopTrainingTimer() {
      if (!state.trainingTimer) return;
      cancelAnimationFrame(state.trainingTimer);
      state.trainingTimer = null;
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

    function defaultBrainStepSize() {
      return 1;
    }

    function stopFollowingAgent() {
      state.followedAgentId = null;
    }

    function centerCoordinateInViewport(coordinate) {
      const viewport = fitViewport();
      const centerX = viewport.left + (viewport.width / 2);
      const centerY = viewport.top + (viewport.height / 2);
      state.offsetX = centerX - (coordinate[0] * state.scale);
      state.offsetY = centerY - (coordinate[1] * state.scale);
    }

    function startFollowingAgent(agent) {
      if (!agent || agent.type !== "agent") return;

      state.followedAgentId = agent.id;
      state.scale = state.maxScale;
      centerCoordinateInViewport(agent.coordinate);
    }

    function followSelectedAgent() {
      if (!state.followedAgentId || !state.world) return;

      const agent = state.world.agents?.[state.followedAgentId];
      if (!agent) {
        stopFollowingAgent();
        return;
      }

      centerCoordinateInViewport(agent.coordinate);
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

      drawSurfaceAverages();
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

    function deterministicHash(seed, x, y, salt = 0) {
      // This mirrors world_generator.deterministic_hash(), including its
      // unsigned 32-bit integer behavior, so the canvas never needs to store
      // or request a surface value for a coordinate.
      let value = (
        Math.imul(Number(seed), 374761393) +
        Math.imul(x, 668265263) +
        Math.imul(y, 2147483647) +
        Math.imul(salt, 1274126177)
      ) >>> 0;
      value ^= value >>> 13;
      value = Math.imul(value, 1274126177) >>> 0;
      value ^= value >>> 16;
      return value >>> 0;
    }

    function deterministicUnitNoise(seed, x, y, salt = 0) {
      return deterministicHash(seed, x, y, salt) / 0xffffffff;
    }

    function smoothstep(value) {
      return value * value * (3 - (2 * value));
    }

    function lerp(start, end, amount) {
      return start + ((end - start) * amount);
    }

    function smoothNoise(seed, x, y, scale, salt = 0) {
      const scaledX = x / scale;
      const scaledY = y / scale;
      const x0 = Math.floor(scaledX);
      const y0 = Math.floor(scaledY);
      const x1 = x0 + 1;
      const y1 = y0 + 1;
      const tx = smoothstep(scaledX - x0);
      const ty = smoothstep(scaledY - y0);
      const top = lerp(
        deterministicUnitNoise(seed, x0, y0, salt),
        deterministicUnitNoise(seed, x1, y0, salt),
        tx,
      );
      const bottom = lerp(
        deterministicUnitNoise(seed, x0, y1, salt),
        deterministicUnitNoise(seed, x1, y1, salt),
        tx,
      );
      return lerp(top, bottom, ty);
    }

    function surfaceCodeAtCoordinate(metadata, x, y) {
      const chaosLevel = Number(metadata.chaos_level ?? 0.5);
      const broad = smoothNoise(metadata.seed, x, y, 8192, 11);
      const medium = smoothNoise(metadata.seed, x, y, 1024, 23);
      const structuredValue = (0.65 * broad) + (0.35 * medium);
      const chaoticValue = deterministicUnitNoise(metadata.seed, x, y, 97);
      const value = ((1 - chaosLevel) * structuredValue) + (chaosLevel * chaoticValue);
      return Math.min(Number(metadata.surface_code_count ?? 10) - 1, Math.floor(value * Number(metadata.surface_code_count ?? 10)));
    }

    function isInsideWorld(metadata, x, y) {
      if (metadata.world_shape !== "circle") {
        return x >= 0 && x < metadata.world_width && y >= 0 && y < metadata.world_height;
      }

      const [centerX, centerY] = metadata.world_center;
      const dx = x - centerX;
      const dy = y - centerY;
      return (dx * dx) + (dy * dy) <= metadata.world_radius * metadata.world_radius;
    }

    function niceSampleStep(targetStep) {
      const exponent = Math.floor(Math.log10(Math.max(1, targetStep)));
      const magnitude = 10 ** exponent;
      const normalized = targetStep / magnitude;
      const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
      return Math.max(1, Math.round(multiplier * magnitude));
    }

    function averageSurfaceCodeInTile(metadata, startX, startY, endX, endY) {
      const width = endX - startX;
      const height = endY - startY;
      const samplesX = Math.min(5, width);
      const samplesY = Math.min(5, height);
      let total = 0;
      let count = 0;
      let totalX = 0;
      let totalY = 0;

      // A fixed, evenly distributed sample keeps large world tiles cheap to
      // render. When a tile is 5 by 5 coordinates or smaller, every cell is
      // included and the displayed average is exact.
      for (let sampleX = 0; sampleX < samplesX; sampleX += 1) {
        const x = Math.min(
          endX - 1,
          Math.floor(startX + (((sampleX + 0.5) * width) / samplesX)),
        );
        for (let sampleY = 0; sampleY < samplesY; sampleY += 1) {
          const y = Math.min(
            endY - 1,
            Math.floor(startY + (((sampleY + 0.5) * height) / samplesY)),
          );
          if (!isInsideWorld(metadata, x, y)) continue;
          total += surfaceCodeAtCoordinate(metadata, x, y);
          count += 1;
          totalX += x;
          totalY += y;
        }
      }

      return count === 0
        ? null
        : {
            value: total / count,
            centerX: totalX / count,
            centerY: totalY / count,
          };
    }

    function formatSurfaceAverage(average, width, height) {
      return width === 1 && height === 1
        ? String(Math.round(average))
        : average.toFixed(1);
    }

    function insetLabelPoint(metadata, x, y, paddingPixels = 28) {
      if (metadata.world_shape !== "circle") return [x, y];

      const [centerX, centerY] = metadata.world_center;
      const dx = x - centerX;
      const dy = y - centerY;
      const distance = Math.hypot(dx, dy);
      const insetRadius = Math.max(
        0,
        metadata.world_radius - (paddingPixels / state.scale),
      );

      if (distance <= insetRadius || distance === 0) return [x, y];

      const scale = insetRadius / distance;
      return [centerX + (dx * scale), centerY + (dy * scale)];
    }

    function drawSurfaceAverages() {
      const metadata = state.world.metadata;
      const topLeft = screenToWorld(0, 0);
      const bottomRight = screenToWorld(canvas.clientWidth, canvas.clientHeight);
      const minX = Math.max(0, Math.floor(Math.min(topLeft.x, bottomRight.x)));
      const maxX = Math.min(metadata.world_width - 1, Math.ceil(Math.max(topLeft.x, bottomRight.x)));
      const minY = Math.max(0, Math.floor(Math.min(topLeft.y, bottomRight.y)));
      const maxY = Math.min(metadata.world_height - 1, Math.ceil(Math.max(topLeft.y, bottomRight.y)));
      const sampleStep = niceSampleStep(54 / state.scale);
      const startX = Math.floor(minX / sampleStep) * sampleStep;
      const startY = Math.floor(minY / sampleStep) * sampleStep;

      ctx.save();
      ctx.fillStyle = "#6e7781";
      ctx.globalAlpha = 0.62;
      ctx.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (let x = startX; x <= maxX; x += sampleStep) {
        for (let y = startY; y <= maxY; y += sampleStep) {
          const endX = Math.min(x + sampleStep, metadata.world_width);
          const endY = Math.min(y + sampleStep, metadata.world_height);
          const tileAverage = averageSurfaceCodeInTile(metadata, x, y, endX, endY);
          if (tileAverage === null) continue;

          const labelCoordinate = insetLabelPoint(
            metadata,
            tileAverage.centerX,
            tileAverage.centerY,
          );
          const point = worldToScreen(labelCoordinate);
          ctx.fillText(
            formatSurfaceAverage(tileAverage.value, endX - x, endY - y),
            point.x,
            point.y,
          );
        }
      }

      ctx.restore();
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
      stopFollowingAgent();
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
        if (
          event.clientX !== state.dragStartX
          || event.clientY !== state.dragStartY
        ) {
          stopFollowingAgent();
        }
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
      if (node?.type === "agent") {
        startFollowingAgent(node);
      } else {
        stopFollowingAgent();
      }
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
      layoutRightPanels();
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
            <button class="world-delete-button" type="button" data-action="delete" data-world-id="${escapeHtml(world.id)}" aria-label="Delete ${escapeHtml(world.display_name)}">
              <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 6h18"></path>
                <path d="M8 6V4h8v2"></path>
                <path d="M19 6 18 20H6L5 6"></path>
                <path d="M10 11v5"></path>
                <path d="M14 11v5"></path>
              </svg>
            </button>
          </div>`;
        })
        .join("");
    }

    function renderWorldSummary() {
      if (!state.world) {
        title.textContent = "None";
        summary.textContent = "No world selected";
        renderTrainingInfo();
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

      const displayName = meta ? meta.display_name : "Selected World";
      title.innerHTML = `${escapeHtml(displayName)} -<span class="title-time">${escapeHtml(formatTrainingTime(currentTrainingTimeMs()))}</span>`;
      summary.textContent = [
        `seed ${metadata.seed}`,
        shapeSummary,
        formatChaosLevel(metadata.chaos_level),
        `${agentCount.toLocaleString()} agents`,
        `${depositCount.toLocaleString()} deposits`,
        `${machineCount.toLocaleString()} machines`,
        `${metadata.total_resource_units.toLocaleString()} resource units`,
      ].join(" | ");
    }

    function renderBrainStatus() {
      const hasWorld = Boolean(state.selectedWorldId);
      playBrainButton.disabled = !hasWorld;
      pauseBrainButton.disabled = !hasWorld;
      decreaseForecastLevelButton.disabled = !hasWorld || state.brainRunning || state.forecastLevel <= 1;
      increaseForecastLevelButton.disabled = !hasWorld || state.brainRunning;
      forecastLevelInput.disabled = !hasWorld || state.brainRunning;
      passGradeInput.disabled = !hasWorld;
      decreasePassGradeButton.disabled = !hasWorld || state.passThresholdPercent <= 0;
      increasePassGradeButton.disabled = !hasWorld || state.passThresholdPercent >= 100;
      autoIncreaseLevelInput.disabled = !hasWorld;
      autoIncreaseByInput.disabled = !hasWorld || !state.autoIncreaseLevel;
      autoIncreasePassesInput.disabled = !hasWorld || !state.autoIncreaseLevel;
      playBrainButton.classList.toggle("is-active", state.brainRunning);
      pauseBrainButton.classList.toggle("is-active", hasWorld && !state.brainRunning);
    }

    function setBrainState(brain) {
      state.brainActive = Boolean(brain?.active);
      state.brainIterations = brain?.iterations || 0;
      if (Number.isFinite(Number(brain?.training_time_ms))) {
        state.trainingTimeMs = Math.max(0, Math.floor(Number(brain.training_time_ms)));
        const meta = selectedWorldMeta();
        if (meta) {
          meta.training_time_ms = state.trainingTimeMs;
        }
      } else {
        const meta = selectedWorldMeta();
        state.trainingTimeMs = Math.max(
          0,
          Math.floor(Number(meta?.training_time_ms) || 0),
        );
      }
      state.brainRunning = Boolean(brain?.running);
      state.trainingStartedAt = state.brainRunning ? Date.now() : null;
      state.forecastLevel = Math.max(1, Math.floor(Number(brain?.forecast_level) || 1));
      state.pathTrials = Math.max(
        0,
        Math.floor(Number(brain?.path_trials) || 0),
      );
      state.completedBatches = Math.max(
        0,
        Math.floor(Number(brain?.completed_batches) || 0),
      );
      state.batchSize = Math.max(1, Math.floor(Number(brain?.batch_size) || 100));
      state.batchPathsCompleted = Math.max(
        0,
        Math.floor(Number(brain?.batch_paths_completed) || 0),
      );
      state.batchStepCorrect = Array.isArray(brain?.batch_step_correct)
        ? brain.batch_step_correct
        : [0];
      state.batchStepTotal = Array.isArray(brain?.batch_step_total)
        ? brain.batch_step_total
        : [0];
      state.lastGrade = Number.isFinite(Number(brain?.last_grade))
        ? Number(brain.last_grade)
        : null;
      state.lastStepAccuracies = Array.isArray(brain?.last_step_accuracies)
        ? brain.last_step_accuracies
        : [];
      state.passThresholdPercent = Number.isFinite(Number(brain?.pass_threshold_percent))
        ? Number(brain.pass_threshold_percent)
        : 90;
      state.targetReached = Boolean(brain?.target_reached);
      state.autoIncreaseLevel = Boolean(brain?.auto_increase_level);
      state.autoIncreaseBy = Math.max(
        1,
        Math.floor(Number(brain?.auto_increase_by) || 1),
      );
      state.autoIncreasePasses = Math.max(
        1,
        Math.floor(Number(brain?.auto_increase_passes) || 100),
      );
      state.consecutivePassingBatches = Math.max(
        0,
        Math.floor(Number(brain?.consecutive_passing_batches) || 0),
      );
      if (Number.isFinite(Number(brain?.step_size))) {
        state.brainStepSize = Math.max(1, Math.floor(Number(brain.step_size)));
      }
      renderBrainStatus();
      renderWorldSummary();
      renderTrainingInfo();

      if (state.brainRunning) {
        startTrainingTimer();
        openBrainStream();
      } else {
        stopTrainingTimer();
        closeBrainStream();
      }
    }

    function openBrainStream() {
      if (!state.selectedWorldId) return;
      if (
        state.brainStream
        && state.brainStreamWorldId === state.selectedWorldId
      ) {
        return;
      }

      closeBrainStream();
      const url = `/api/brain/stream?id=${encodeURIComponent(state.selectedWorldId)}&cacheBust=${Date.now()}`;
      state.brainStream = new EventSource(url);
      state.brainStreamWorldId = state.selectedWorldId;

      state.brainStream.onmessage = (event) => {
        const data = JSON.parse(event.data);
        applyBrainStreamUpdate(data);
      };

      state.brainStream.onerror = () => {
        // EventSource will retry automatically. Keep the old frame visible.
      };
    }

    function closeBrainStream() {
      if (state.brainStream) {
        state.brainStream.close();
        state.brainStream = null;
        state.brainStreamWorldId = null;
      }
    }

    function applyBrainStreamUpdate(data) {
      if (data.agent && state.world?.agents?.[data.agent.id]) {
        state.world.agents[data.agent.id].coordinate = data.agent.coordinate;
      }

      setBrainState(data.brain);
      refreshSelectedNodeFromWorld();
      followSelectedAgent();
      requestDraw();
    }

    function refreshSelectedNodeFromWorld() {
      if (!state.selectedNode || !state.world) return;

      const selected = state.selectedNode;
      let updated = null;
      if (selected.type === "agent") {
        updated = state.world.agents[selected.id] || null;
      } else if (selected.type === "deposit") {
        updated = state.world.deposits[selected.id] || null;
      } else if (selected.type === "machine") {
        updated = state.world.machines[selected.id] || null;
      }

      state.selectedNode = updated;
      setDetails(updated);
    }

    async function loadBrainState(worldId) {
      if (!worldId) {
        setBrainState({ iterations: 0 });
        return;
      }

      const data = await apiJson(`/api/brain/state?id=${encodeURIComponent(worldId)}&cacheBust=${Date.now()}`);
      setBrainState(data.brain);
      if (data.world) {
        state.world = data.world;
        refreshSelectedNodeFromWorld();
        requestDraw();
      }
    }

    async function startBrainLoop() {
      if (!state.selectedWorldId) return;

      const data = await apiJson("/api/brain/play", {
        method: "POST",
        body: JSON.stringify({
          world_id: state.selectedWorldId,
          step_size: state.brainStepSize || defaultBrainStepSize(),
          steps_per_tick: state.brainStepsPerTick,
          interval_ms: state.brainServerIntervalMs,
          pass_threshold_percent: state.passThresholdPercent,
          auto_increase_level: state.autoIncreaseLevel,
          auto_increase_by: state.autoIncreaseBy,
          auto_increase_passes: state.autoIncreasePasses,
        }),
      });

      state.world = data.world;
      setBrainState(data.brain);
      refreshSelectedNodeFromWorld();
      requestDraw();
    }

    async function pauseBrainLoop() {
      if (!state.selectedWorldId) return;

      const data = await apiJson("/api/brain/pause", {
        method: "POST",
        body: JSON.stringify({
          world_id: state.selectedWorldId,
        }),
      });

      if (data.world) {
        state.world = data.world;
      }
      setBrainState(data.brain);
      refreshSelectedNodeFromWorld();
      requestDraw();
    }

    async function resetBrainLabWorld() {
      if (!state.selectedWorldId) return;
      closeBrainStream();

      const data = await apiJson("/api/brain/reset", {
        method: "POST",
        body: JSON.stringify({
          world_id: state.selectedWorldId,
          step_size: state.brainStepSize || defaultBrainStepSize(),
          steps: state.brainStepsPerTick,
          pass_threshold_percent: state.passThresholdPercent,
          auto_increase_level: state.autoIncreaseLevel,
          auto_increase_by: state.autoIncreaseBy,
          auto_increase_passes: state.autoIncreasePasses,
        }),
      });

      state.world = data.world;
      setBrainState(data.brain);
      refreshSelectedNodeFromWorld();
      fitWorldToScreen();
      hideLoading();
      requestDraw();
    }

    async function setForecastLevel(level) {
      if (!state.selectedWorldId || state.brainRunning) return;

      const nextLevel = clampForecastLevel(level);
      const data = await apiJson("/api/brain/level", {
        method: "POST",
        body: JSON.stringify({
          world_id: state.selectedWorldId,
          forecast_level: nextLevel,
          step_size: state.brainStepSize || defaultBrainStepSize(),
          steps_per_tick: state.brainStepsPerTick,
          interval_ms: state.brainServerIntervalMs,
          pass_threshold_percent: state.passThresholdPercent,
          auto_increase_level: state.autoIncreaseLevel,
          auto_increase_by: state.autoIncreaseBy,
          auto_increase_passes: state.autoIncreasePasses,
        }),
      });

      if (data.world) {
        state.world = data.world;
      }
      setBrainState(data.brain);
      refreshSelectedNodeFromWorld();
      requestDraw();
    }

    async function changeForecastLevel(delta) {
      return setForecastLevel(state.forecastLevel + delta);
    }

    async function setPassGrade(grade) {
      state.passThresholdPercent = clampPassThreshold(grade);
      syncTrainingInputs();
      renderBrainStatus();
      renderTrainingInfo();
      await updateBrainSettings();
    }

    async function changePassGrade(delta) {
      return setPassGrade(state.passThresholdPercent + delta);
    }

    async function setAutoIncreaseBy(value) {
      state.autoIncreaseBy = clampAutoIncreaseBy(value);
      syncTrainingInputs();
      renderTrainingInfo();
      await updateBrainSettings();
    }

    async function setAutoIncreasePasses(value) {
      state.autoIncreasePasses = clampAutoIncreasePasses(value);
      syncTrainingInputs();
      renderTrainingInfo();
      await updateBrainSettings();
    }

    async function updateBrainSettings() {
      if (!state.selectedWorldId) return;
      if (!state.brainActive) {
        renderBrainStatus();
        renderWorldSummary();
        renderTrainingInfo();
        return;
      }

      const data = await apiJson("/api/brain/settings", {
        method: "POST",
        body: JSON.stringify({
          world_id: state.selectedWorldId,
          step_size: state.brainStepSize || defaultBrainStepSize(),
          steps_per_tick: state.brainStepsPerTick,
          interval_ms: state.brainServerIntervalMs,
          pass_threshold_percent: state.passThresholdPercent,
          auto_increase_level: state.autoIncreaseLevel,
          auto_increase_by: state.autoIncreaseBy,
          auto_increase_passes: state.autoIncreasePasses,
        }),
      });

      if (data.world) {
        state.world = data.world;
      }
      setBrainState(data.brain);
      refreshSelectedNodeFromWorld();
      requestDraw();
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
        setBrainState({ iterations: 0 });
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
      closeBrainStream();
      if (!worldId) {
        state.world = null;
        state.selectedWorldId = null;
        setBrainState({ iterations: 0 });
        renderLegend([]);
        renderWorldSummary();
        hideLoading();
        requestDraw();
        return;
      }

      showLoading("Loading world...");
      state.hoverNode = null;
      state.selectedNode = null;
      stopFollowingAgent();
      setDetails(null);

      const response = await fetch(`/api/world?id=${encodeURIComponent(worldId)}&cacheBust=${Date.now()}`);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || "Could not load selected world");
      }

      state.world = await response.json();
      state.selectedWorldId = worldId;
      state.brainStepSize = null;
      renderLegend(state.world.metadata.resource_types);
      renderWorldSummary();
      renderWorldList();
      await loadBrainState(worldId);
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
          chaos_level: numberField(formData, "chaos_level"),
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
      const seed = seedInput.value || "42";
      if (!displayNameInput.value.trim() || /^Seed \d+$/.test(displayNameInput.value.trim())) {
        displayNameInput.value = `Seed ${seed}`;
      }
    }

    function openDeleteDialog(worldId) {
      const world = state.worlds.find((item) => item.id === worldId);
      state.pendingDeleteWorldId = worldId;
      deleteDialogMessage.textContent = world
        ? `Delete "${world.display_name}"? This removes it from the sidebar and deletes its saved JSON file.`
        : "Delete this generated world?";
      confirmDeleteButton.disabled = false;
      confirmDeleteButton.textContent = "Confirm";
      deleteDialog.hidden = false;
      confirmDeleteButton.focus();
    }

    function closeDeleteDialog() {
      state.pendingDeleteWorldId = null;
      deleteDialog.hidden = true;
    }

    async function confirmDeleteWorld() {
      const worldId = state.pendingDeleteWorldId;
      if (!worldId) return;

      confirmDeleteButton.disabled = true;
      confirmDeleteButton.textContent = "Deleting...";

      try {
        await apiJson(`/api/world?id=${encodeURIComponent(worldId)}`, {
          method: "DELETE",
        });
        closeDeleteDialog();
        await loadWorldList();
      } catch (error) {
        deleteDialogMessage.textContent = error.message;
        confirmDeleteButton.disabled = false;
        confirmDeleteButton.textContent = "Confirm";
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
      } else if (action === "delete") {
        openDeleteDialog(worldId);
      }
    });

    createWorldForm.addEventListener("submit", generateWorld);
    seedInput.addEventListener("input", updateWorldNameDefault);
    playBrainButton.addEventListener("click", () => {
      startBrainLoop().catch((error) => {
        showLoading(error.message);
      });
    });
    pauseBrainButton.addEventListener("click", () => {
      pauseBrainLoop().catch((error) => {
        showLoading(error.message);
      });
    });
    decreaseForecastLevelButton.addEventListener("click", () => {
      changeForecastLevel(-1).catch((error) => {
        showLoading(error.message);
      });
    });
    increaseForecastLevelButton.addEventListener("click", () => {
      changeForecastLevel(1).catch((error) => {
        showLoading(error.message);
      });
    });
    decreasePassGradeButton.addEventListener("click", () => {
      changePassGrade(-1).catch((error) => {
        showLoading(error.message);
      });
    });
    increasePassGradeButton.addEventListener("click", () => {
      changePassGrade(1).catch((error) => {
        showLoading(error.message);
      });
    });
    forecastLevelInput.addEventListener("change", () => {
      setForecastLevel(forecastLevelInput.value).catch((error) => {
        showLoading(error.message);
      });
    });
    passGradeInput.addEventListener("input", () => {
      state.passThresholdPercent = clampPassThreshold(passGradeInput.value);
      renderTrainingInfo();
    });
    passGradeInput.addEventListener("change", () => {
      setPassGrade(passGradeInput.value).catch((error) => {
        showLoading(error.message);
      });
    });
    autoIncreaseLevelInput.addEventListener("change", () => {
      state.autoIncreaseLevel = autoIncreaseLevelInput.checked;
      syncTrainingInputs();
      renderBrainStatus();
      renderTrainingInfo();
      updateBrainSettings().catch((error) => {
        showLoading(error.message);
      });
    });
    autoIncreaseByInput.addEventListener("change", () => {
      setAutoIncreaseBy(autoIncreaseByInput.value).catch((error) => {
        showLoading(error.message);
      });
    });
    autoIncreasePassesInput.addEventListener("change", () => {
      setAutoIncreasePasses(autoIncreasePassesInput.value).catch((error) => {
        showLoading(error.message);
      });
    });
    cancelDeleteButton.addEventListener("click", closeDeleteDialog);
    confirmDeleteButton.addEventListener("click", confirmDeleteWorld);
    deleteDialog.addEventListener("click", (event) => {
      if (event.target === deleteDialog) {
        closeDeleteDialog();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !deleteDialog.hidden) {
        closeDeleteDialog();
      }
    });

    resetButton.addEventListener("click", () => {
      if (!state.world) return;
      stopFollowingAgent();
      fitWorldToScreen();
      requestDraw();
    });

    refreshButton.addEventListener("click", () => {
      closeBrainStream();
      if (!state.selectedWorldId) {
        createPanel.classList.add("open");
        return;
      }
      resetBrainLabWorld().catch((error) => {
        loadSelectedWorld(state.selectedWorldId).catch(() => {
          showLoading(error.message);
        });
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

    renderBrainStatus();
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

        normalized_world = dict(world)
        try:
            training_time_ms = int(normalized_world.get("training_time_ms", 0))
        except (TypeError, ValueError):
            training_time_ms = 0
        normalized_world["training_time_ms"] = max(0, training_time_ms)
        normalized_worlds.append(normalized_world)

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


def world_training_time_ms(index_path, world_id):
    """Return persisted cumulative training time for one world."""
    with INDEX_LOCK:
        index = load_index(index_path)
        entry = find_world_entry(index, world_id)
        return int(entry.get("training_time_ms", 0))


def add_world_training_time_ms(index_path, world_id, elapsed_ms):
    """Add elapsed training time to one world and persist the index."""
    with INDEX_LOCK:
        index = load_index(index_path)
        entry = find_world_entry(index, world_id)
        current_ms = int(entry.get("training_time_ms", 0))
        entry["training_time_ms"] = max(0, current_ms + max(0, int(elapsed_ms)))
        save_index(index_path, index)
        return entry["training_time_ms"]


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


def load_world_object(index_path, requested_id=None):
    """Load the selected/requested world JSON object and its id."""
    with INDEX_LOCK:
        index = load_index(index_path)
        world_id = selected_or_requested_world_id(index, requested_id)
        entry = find_world_entry(index, world_id)
        path = path_for_index(index_path, entry["file_path"])
        return world_id, validate_world_file(path)


def clamp_percent(value, default=DEFAULT_FORECAST_PASS_PERCENT):
    """Return a dashboard percentage setting constrained to 0 through 100."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default

    if number != number:
        number = default

    return max(0.0, min(100.0, number))


def boolean_setting(value, default=False):
    """Read a JSON boolean without treating the string 'false' as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def positive_integer_setting(value, default, maximum):
    """Read a bounded positive integer from a dashboard setting."""
    try:
        if isinstance(value, bool):
            raise TypeError
        number = int(value)
    except (TypeError, ValueError):
        number = default

    return max(1, min(maximum, number))


class BrainLabRuntime:
    """In-memory one-agent live brain run for one selected world."""

    def __init__(
        self,
        world_id,
        world,
        step_size=1,
        feature_pairs=96,
        learning_rate=0.03,
        epsilon=0.15,
        steps_per_tick=1,
        loop_interval_seconds=0.01,
        training_time_ms=0,
        pass_threshold_percent=DEFAULT_FORECAST_PASS_PERCENT,
        auto_increase_level=False,
        auto_increase_by=DEFAULT_AUTO_INCREASE_BY,
        auto_increase_passes=DEFAULT_AUTO_INCREASE_PASSES,
    ):
        self.world_id = world_id
        self.world = world
        self.step_size = step_size
        self.steps_per_tick = steps_per_tick
        self.loop_interval_seconds = loop_interval_seconds
        self.pass_threshold_percent = clamp_percent(pass_threshold_percent)
        self.auto_increase_level = boolean_setting(auto_increase_level)
        self.auto_increase_by = positive_integer_setting(
            auto_increase_by,
            DEFAULT_AUTO_INCREASE_BY,
            MAX_FORECAST_LEVEL,
        )
        self.auto_increase_passes = positive_integer_setting(
            auto_increase_passes,
            DEFAULT_AUTO_INCREASE_PASSES,
            MAX_AUTO_INCREASE_PASSES,
        )
        self.running = False
        self.runner_thread = None
        self.training_time_ms = max(0, int(training_time_ms))
        self.training_started_at = None
        self.env = WorldEnvironment(world)
        self.rng = random.Random(world["metadata"].get("seed", 1))
        self.brain = StaticTensorSequenceBrain()
        self.iterations = 0
        self.forecast_level = 1
        self.path_trials = 0
        self.completed_batches = 0
        self.batch_paths_completed = 0
        self.batch_step_correct = [0]
        self.batch_step_total = [0]
        self.batch_path_keys = set()
        self.last_grade = None
        self.last_step_accuracies = []
        self.target_reached = False
        self.consecutive_passing_batches = 0
        self.unique_coordinates_seen = {coordinate_key(self.env.coordinate)}
        self.deposit_ids_seen = set()
        self.last_action = None
        self.last_prediction_error = None
        self.last_event = None

        initial_observation = self.env.observe()
        initial_deposit = initial_observation["cell"]["deposit_id"]
        if initial_deposit:
            self.deposit_ids_seen.add(initial_deposit)

    def start_training_timer(self):
        """Start counting wall-clock training time for this runtime."""
        if self.training_started_at is None:
            self.training_started_at = time.monotonic()

    def current_training_time_ms(self):
        """Return persisted time plus the current unpaused run."""
        if self.training_started_at is None:
            return self.training_time_ms
        elapsed_ms = int((time.monotonic() - self.training_started_at) * 1000)
        return self.training_time_ms + max(0, elapsed_ms)

    def pause_training_timer(self):
        """Stop counting wall-clock time and return the elapsed increment."""
        if self.training_started_at is None:
            return 0

        elapsed_ms = int((time.monotonic() - self.training_started_at) * 1000)
        elapsed_ms = max(0, elapsed_ms)
        self.training_time_ms += elapsed_ms
        self.training_started_at = None
        return elapsed_ms

    def set_forecast_level(self, level):
        """Select a path horizon and discard only its in-progress batch."""
        if self.running:
            raise RuntimeError("Pause training before changing the forecast level.")

        self.forecast_level = max(1, min(MAX_FORECAST_LEVEL, int(level)))
        self.consecutive_passing_batches = 0
        self._start_new_batch(clear_grade=True)

    def _start_new_batch(self, clear_grade=False):
        """Prepare 100 fresh path trials without resetting the agent or brain."""
        self.batch_paths_completed = 0
        self.batch_step_correct = [0] * self.forecast_level
        self.batch_step_total = [0] * self.forecast_level
        self.batch_path_keys = set()
        self.target_reached = False
        if clear_grade:
            self.last_grade = None
            self.last_step_accuracies = []

    def apply_settings(self, options=None):
        """Update live-tunable runtime settings without resetting the world."""
        options = options or {}

        if "step_size" in options:
            self.step_size = max(1, int(options["step_size"]))
        if "steps_per_tick" in options or "steps" in options:
            self.steps_per_tick = max(
                1,
                min(
                    250,
                    int(options.get("steps_per_tick", options.get("steps", 1))),
                ),
            )
        if "interval_ms" in options:
            self.loop_interval_seconds = max(
                0.001,
                float(options["interval_ms"]) / 1000.0,
            )
        if "pass_threshold_percent" in options:
            next_pass_threshold_percent = clamp_percent(
                options["pass_threshold_percent"],
                self.pass_threshold_percent,
            )
            if next_pass_threshold_percent != self.pass_threshold_percent:
                self.consecutive_passing_batches = 0
            self.pass_threshold_percent = next_pass_threshold_percent
            if self.last_step_accuracies:
                self.target_reached = all(
                    accuracy >= self.pass_threshold_percent
                    for accuracy in self.last_step_accuracies
                )
        if "auto_increase_level" in options:
            next_auto_increase_level = boolean_setting(
                options["auto_increase_level"],
                self.auto_increase_level,
            )
            if next_auto_increase_level != self.auto_increase_level:
                self.consecutive_passing_batches = 0
            self.auto_increase_level = next_auto_increase_level
        if "auto_increase_by" in options:
            next_auto_increase_by = positive_integer_setting(
                options["auto_increase_by"],
                self.auto_increase_by,
                MAX_FORECAST_LEVEL,
            )
            if next_auto_increase_by != self.auto_increase_by:
                self.consecutive_passing_batches = 0
            self.auto_increase_by = next_auto_increase_by
        if "auto_increase_passes" in options:
            next_auto_increase_passes = positive_integer_setting(
                options["auto_increase_passes"],
                self.auto_increase_passes,
                MAX_AUTO_INCREASE_PASSES,
            )
            if next_auto_increase_passes != self.auto_increase_passes:
                self.consecutive_passing_batches = 0
            self.auto_increase_passes = next_auto_increase_passes

    def _generate_actions(self):
        """Create one complete legal path before any movement is executed.

        Levels below four have fewer than 100 possible action vectors, so the
        runtime permits repeated vectors there. They are still separate trials
        because the agent reaches them from different physical coordinates.
        """
        can_require_unique_paths = 4**self.forecast_level >= FORECAST_BATCH_SIZE

        for _ in range(32):
            cursor = self.env.coordinate
            actions = []
            for _step in range(self.forecast_level):
                valid_actions = valid_actions_from_coordinate(
                    cursor,
                    self.env.metadata,
                    self.step_size,
                )
                if not valid_actions:
                    break
                action = self.rng.choice(valid_actions)
                actions.append(action)
                cursor = apply_action(cursor, action, self.step_size)

            if len(actions) != self.forecast_level:
                raise RuntimeError("Could not create a complete legal forecast path.")

            path_key = tuple(actions)
            if not can_require_unique_paths or path_key not in self.batch_path_keys:
                self.batch_path_keys.add(path_key)
                return actions

        # A path is always usable even if random retries happened to collide.
        self.batch_path_keys.add(tuple(actions))
        return actions

    def _finish_batch_if_ready(self):
        """Grade a completed 100-path batch and retain only its summary."""
        if self.batch_paths_completed < FORECAST_BATCH_SIZE:
            return False

        step_accuracies = [
            (correct / total) * 100 if total else 0.0
            for correct, total in zip(self.batch_step_correct, self.batch_step_total)
        ]
        self.last_step_accuracies = step_accuracies
        # The grade is the weakest position in the path. Passing therefore
        # means every step position, not only an average, reached the target.
        self.last_grade = min(step_accuracies, default=0.0)
        self.completed_batches += 1
        batch_passed = all(
            accuracy >= self.pass_threshold_percent for accuracy in step_accuracies
        )
        self.target_reached = batch_passed

        if (
            batch_passed
            and self.auto_increase_level
            and self.forecast_level < MAX_FORECAST_LEVEL
        ):
            self.consecutive_passing_batches += 1
            if self.consecutive_passing_batches >= self.auto_increase_passes:
                self.forecast_level = min(
                    MAX_FORECAST_LEVEL,
                    self.forecast_level + self.auto_increase_by,
                )
                self.consecutive_passing_batches = 0
            self._start_new_batch(clear_grade=False)
        elif batch_passed:
            # The background manager notices this and persists elapsed time.
            self.running = False
        else:
            self.consecutive_passing_batches = 0
            self._start_new_batch(clear_grade=False)

        return batch_passed

    def step_once(self):
        """Forecast and execute one full blind path trial at the chosen level."""
        actions = self._generate_actions()
        # All guesses are prepared before movement reveals even the first cell.
        predictions = self.brain.predict_path(actions)

        for step_number, (action, prediction) in enumerate(
            zip(actions, predictions),
            start=1,
        ):
            before = self.env.coordinate
            self.env.move(action, self.step_size)
            observation = self.env.observe(last_action=action)
            actual_surface = observation["cell"]["surface_code"]
            correct = prediction["predicted_surface"] == actual_surface

            self.iterations += 1
            self.batch_step_total[step_number - 1] += 1
            if correct:
                self.batch_step_correct[step_number - 1] += 1

            self.unique_coordinates_seen.add(coordinate_key(self.env.coordinate))
            deposit_id = observation["cell"]["deposit_id"]
            if deposit_id:
                self.deposit_ids_seen.add(deposit_id)

            step_record = {
                "step": step_number,
                "iteration": self.iterations,
                "from": before,
                "to": self.env.coordinate,
                "action": action,
                "action_code": prediction["action_code"],
                "predicted_surface": prediction["predicted_surface"],
                "actual_surface": actual_surface,
                "correct": correct,
                "brain_number": prediction["brain_number"],
                "state_size_before": prediction["state_size_before"],
                "state_size_after": prediction["state_size_after"],
            }
            self.last_action = action
            self.last_prediction_error = 0.0 if correct else 1.0
            self.last_event = step_record

        self.path_trials += 1
        self.batch_paths_completed += 1
        return self._finish_batch_if_ready()

    def step(self, count):
        """Advance the runtime count iterations."""
        for _ in range(count):
            self.step_once()
        return self.payload(include_world=True)

    def brain_payload(self):
        """Return visible brain status for the dashboard."""
        return {
            "active": True,
            "running": self.running,
            "world_id": self.world_id,
            "agent_id": self.env.agent_id,
            "iterations": self.iterations,
            "training_time_ms": self.current_training_time_ms(),
            "forecast_level": self.forecast_level,
            "path_trials": self.path_trials,
            "completed_batches": self.completed_batches,
            "batch_size": FORECAST_BATCH_SIZE,
            "batch_paths_completed": self.batch_paths_completed,
            "batch_step_correct": self.batch_step_correct,
            "batch_step_total": self.batch_step_total,
            "last_grade": self.last_grade,
            "last_step_accuracies": self.last_step_accuracies,
            "pass_threshold_percent": self.pass_threshold_percent,
            "auto_increase_level": self.auto_increase_level,
            "auto_increase_by": self.auto_increase_by,
            "auto_increase_passes": self.auto_increase_passes,
            "consecutive_passing_batches": self.consecutive_passing_batches,
            "target_reached": self.target_reached,
            "coordinate": self.env.coordinate,
            "step_size": self.step_size,
            "steps_per_tick": self.steps_per_tick,
            "loop_interval_ms": round(self.loop_interval_seconds * 1000, 3),
            "last_action": self.last_action,
            "last_prediction_error": self.last_prediction_error,
            "unique_coordinates_seen": len(self.unique_coordinates_seen),
            "deposits_seen": len(self.deposit_ids_seen),
            "last_event": self.last_event,
        }

    def payload(self, include_world=False):
        """Return dashboard payload."""
        payload = {"brain": self.brain_payload()}
        if include_world:
            payload["world"] = self.world
        return payload


def inactive_brain_payload(world_id, training_time_ms):
    """Return dashboard defaults before a runtime has been created."""
    return {
        "active": False,
        "running": False,
        "world_id": world_id,
        "iterations": 0,
        "training_time_ms": training_time_ms,
        "forecast_level": 1,
        "path_trials": 0,
        "completed_batches": 0,
        "batch_size": FORECAST_BATCH_SIZE,
        "batch_paths_completed": 0,
        "batch_step_correct": [0],
        "batch_step_total": [0],
        "last_grade": None,
        "last_step_accuracies": [],
        "pass_threshold_percent": DEFAULT_FORECAST_PASS_PERCENT,
        "auto_increase_level": False,
        "auto_increase_by": DEFAULT_AUTO_INCREASE_BY,
        "auto_increase_passes": DEFAULT_AUTO_INCREASE_PASSES,
        "consecutive_passing_batches": 0,
        "target_reached": False,
    }


class BrainLabManager:
    """Manage live in-memory brain runtimes by world id."""

    def __init__(self, index_path):
        self.index_path = index_path
        self.lock = threading.RLock()
        self.runtimes = {}

    def reset(self, world_id=None, options=None):
        """Create a fresh runtime for a selected world."""
        options = options or {}
        with self.lock:
            selected_world_id, world = load_world_object(self.index_path, world_id)
            previous_runtime = self.runtimes.get(selected_world_id)
            if previous_runtime is not None:
                elapsed_ms = previous_runtime.pause_training_timer()
                if elapsed_ms:
                    previous_runtime.training_time_ms = add_world_training_time_ms(
                        self.index_path,
                        selected_world_id,
                        elapsed_ms,
                    )
                previous_runtime.running = False

            runtime = BrainLabRuntime(
                selected_world_id,
                world,
                step_size=max(1, int(options.get("step_size", 1))),
                feature_pairs=max(1, int(options.get("features", 96))),
                learning_rate=float(options.get("learning_rate", 0.03)),
                epsilon=float(options.get("epsilon", 0.15)),
                steps_per_tick=max(
                    1,
                    min(
                        250,
                        int(options.get("steps_per_tick", options.get("steps", 1))),
                    ),
                ),
                loop_interval_seconds=max(
                    0.001,
                    float(options.get("interval_ms", 10)) / 1000.0,
                ),
                training_time_ms=world_training_time_ms(
                    self.index_path,
                    selected_world_id,
                ),
                pass_threshold_percent=options.get(
                    "pass_threshold_percent",
                    DEFAULT_FORECAST_PASS_PERCENT,
                ),
                auto_increase_level=options.get("auto_increase_level", False),
                auto_increase_by=options.get(
                    "auto_increase_by",
                    DEFAULT_AUTO_INCREASE_BY,
                ),
                auto_increase_passes=options.get(
                    "auto_increase_passes",
                    DEFAULT_AUTO_INCREASE_PASSES,
                ),
            )
            self.runtimes[selected_world_id] = runtime
            return runtime

    def get(self, world_id=None):
        """Return a runtime if one exists."""
        selected_world_id, _world = load_world_object(self.index_path, world_id)
        return self.runtimes.get(selected_world_id)

    def ensure(self, world_id=None, options=None):
        """Return existing runtime or create one."""
        with self.lock:
            selected_world_id, _world = load_world_object(self.index_path, world_id)
            runtime = self.runtimes.get(selected_world_id)
            if runtime is None:
                runtime = self.reset(selected_world_id, options)
            return runtime

    def state(self, world_id=None):
        """Return visible lab state without creating a runtime."""
        with self.lock:
            selected_world_id, _world = load_world_object(self.index_path, world_id)
            runtime = self.runtimes.get(selected_world_id)
            if runtime is None:
                return {"brain": inactive_brain_payload(
                    selected_world_id,
                    world_training_time_ms(self.index_path, selected_world_id),
                )}
            return runtime.payload(include_world=True)

    def resolve_world_id(self, world_id=None):
        """Return the concrete selected/requested world id."""
        selected_world_id, _world = load_world_object(self.index_path, world_id)
        return selected_world_id

    def stream_state(self, world_id):
        """Return a small payload for frequent live UI updates."""
        with self.lock:
            runtime = self.runtimes.get(world_id)
            if runtime is None:
                return {"brain": inactive_brain_payload(
                    world_id,
                    world_training_time_ms(self.index_path, world_id),
                )}

            brain = runtime.brain_payload()
            return {
                "brain": brain,
                "agent": {
                    "id": brain["agent_id"],
                    "coordinate": brain["coordinate"],
                },
            }

    def step(self, world_id=None, steps=1, options=None):
        """Run several brain iterations and return updated state."""
        with self.lock:
            runtime = self.ensure(world_id, options)
            step_count = max(1, min(250, int(steps)))
            return runtime.step(step_count)

    def set_forecast_level(self, world_id=None, level=1, options=None):
        """Set the selected path horizon while the runtime is paused."""
        with self.lock:
            runtime = self.ensure(world_id, options)
            runtime.set_forecast_level(level)
            runtime.apply_settings(options)
            return runtime.payload(include_world=True)

    def play(self, world_id=None, options=None):
        """Start the server-side background brain loop."""
        options = options or {}
        with self.lock:
            runtime = self.ensure(world_id, options)
            runtime.apply_settings(options)

            runtime.start_training_timer()
            runtime.running = True

            if (
                runtime.runner_thread is None
                or not runtime.runner_thread.is_alive()
            ):
                runtime.runner_thread = threading.Thread(
                    target=self._run_loop,
                    args=(runtime.world_id,),
                    daemon=True,
                )
                runtime.runner_thread.start()

            return runtime.payload(include_world=True)

    def pause(self, world_id=None):
        """Pause the server-side background brain loop."""
        with self.lock:
            runtime = self.get(world_id)
            if runtime is None:
                return self.state(world_id)
            elapsed_ms = runtime.pause_training_timer()
            if elapsed_ms:
                runtime.training_time_ms = add_world_training_time_ms(
                    self.index_path,
                    runtime.world_id,
                    elapsed_ms,
                )
            runtime.running = False
            return runtime.payload(include_world=True)

    def update_settings(self, world_id=None, options=None):
        """Update live console settings without starting or resetting training."""
        with self.lock:
            runtime = self.get(world_id)
            if runtime is None:
                return self.state(world_id)
            runtime.apply_settings(options)
            return runtime.payload(include_world=True)

    def _run_loop(self, world_id):
        """Run one runtime until it is paused, reset, deleted, or server exits."""
        while True:
            with self.lock:
                runtime = self.runtimes.get(world_id)
                if runtime is None or not runtime.running:
                    return

                step_count = runtime.steps_per_tick
                sleep_seconds = runtime.loop_interval_seconds
                for _ in range(step_count):
                    runtime.step_once()
                    if not runtime.running:
                        elapsed_ms = runtime.pause_training_timer()
                        if elapsed_ms:
                            runtime.training_time_ms = add_world_training_time_ms(
                                self.index_path,
                                runtime.world_id,
                                elapsed_ms,
                            )
                        return

            time.sleep(sleep_seconds)

    def clear(self, world_id):
        """Drop one runtime."""
        with self.lock:
            runtime = self.runtimes.get(world_id)
            if runtime is not None:
                runtime.running = False
            self.runtimes.pop(world_id, None)


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
    chaos_level = float_setting(payload, "chaos_level")
    agent_count = int_setting(payload, "agent_count")
    deposit_count = int_setting(payload, "deposit_count")
    total_resource_units = int_setting(payload, "total_resource_units")

    world = build_world(
        seed=seed,
        base_world_width=base_world_width,
        base_world_height=base_world_height,
        chaos_level=chaos_level,
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
            "training_time_ms": 0,
        }
        index["worlds"].insert(0, entry)
        index["selected_world_id"] = world_id
        save_index(index_path, index)

    return entry


def delete_world_from_index(index_path, worlds_dir, world_id):
    """Delete one saved world file and remove it from the dashboard index."""
    if not world_id:
        raise ValueError("Missing world id.")

    with INDEX_LOCK:
        index = load_index(index_path)
        entry = find_world_entry(index, world_id)
        world_path = path_for_index(index_path, entry["file_path"])
        deleted_file = False

        if world_path.exists():
            try:
                world_path.resolve().relative_to(worlds_dir.resolve())
            except ValueError as error:
                raise ValueError(
                    "Refusing to delete a world file outside the worlds directory."
                ) from error

            world_path.unlink()
            deleted_file = True

        index["worlds"] = [
            world for world in index["worlds"] if world["id"] != world_id
        ]
        if index["selected_world_id"] == world_id:
            index["selected_world_id"] = (
                index["worlds"][0]["id"] if index["worlds"] else None
            )

        save_index(index_path, index)
        index = load_index(index_path)

    return {
        "deleted_world_id": world_id,
        "deleted_file": deleted_file,
        "selected_world_id": index["selected_world_id"],
        "worlds": index["worlds"],
    }


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
    brain_lab = BrainLabManager(index_path)

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

        def send_brain_stream(self, world_id):
            """Send live brain updates as a Server-Sent Events stream."""
            try:
                stream_world_id = brain_lab.resolve_world_id(world_id)
            except Exception as error:
                self.send_json(400, {"error": str(error)})
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                while True:
                    payload = brain_lab.stream_state(stream_world_id)
                    message = f"data: {json.dumps(payload)}\n\n"
                    self.wfile.write(message.encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                return

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

            if parsed.path == "/api/brain/state":
                query = parse_qs(parsed.query)
                world_id = query.get("id", [None])[0]
                try:
                    self.send_json(200, brain_lab.state(world_id))
                except Exception as error:
                    self.send_json(400, {"error": str(error)})
                return

            if parsed.path == "/api/brain/stream":
                query = parse_qs(parsed.query)
                world_id = query.get("id", [None])[0]
                self.send_brain_stream(world_id)
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

                if parsed.path == "/api/brain/reset":
                    runtime = brain_lab.reset(payload.get("world_id"), payload)
                    self.send_json(200, runtime.payload(include_world=True))
                    return

                if parsed.path == "/api/brain/play":
                    self.send_json(
                        200,
                        brain_lab.play(payload.get("world_id"), payload),
                    )
                    return

                if parsed.path == "/api/brain/pause":
                    self.send_json(
                        200,
                        brain_lab.pause(payload.get("world_id")),
                    )
                    return

                if parsed.path == "/api/brain/settings":
                    self.send_json(
                        200,
                        brain_lab.update_settings(
                            payload.get("world_id"),
                            payload,
                        ),
                    )
                    return

                if parsed.path == "/api/brain/step":
                    self.send_json(
                        200,
                        brain_lab.step(
                            payload.get("world_id"),
                            payload.get("steps", 1),
                            payload,
                        ),
                    )
                    return

                if parsed.path == "/api/brain/level":
                    self.send_json(
                        200,
                        brain_lab.set_forecast_level(
                            payload.get("world_id"),
                            payload.get("forecast_level", 1),
                            payload,
                        ),
                    )
                    return

                self.send_text(404, "Not found")
            except Exception as error:
                self.send_json(400, {"error": str(error)})

        def do_DELETE(self):
            parsed = urlparse(self.path)

            try:
                if parsed.path == "/api/world":
                    query = parse_qs(parsed.query)
                    world_id = query.get("id", [None])[0]
                    self.send_json(
                        200,
                        delete_world_from_index(index_path, worlds_dir, world_id),
                    )
                    brain_lab.clear(world_id)
                    return

                self.send_text(404, "Not found")
            except KeyError as error:
                self.send_json(404, {"error": str(error)})
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

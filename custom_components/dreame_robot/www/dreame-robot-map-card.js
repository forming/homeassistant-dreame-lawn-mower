/**
 * Dreame Robot interactive map card.
 *
 * Draws the map served by the integration and turns taps into Home Assistant
 * service calls. Copy this file to /config/www/dreame-robot-map-card.js,
 * register it as a Lovelace resource, then add to any view:
 *
 *   type: custom:dreame-robot-map
 *   entity: lawn_mower.back_garden_mower
 *
 * Optional config: title (string), refresh_interval (seconds, default 3).
 */

const DOMAIN = "dreame_robot";
const SVG_NS = "http://www.w3.org/2000/svg";

const COLORS = {
  lawn: "#3a7a4a",
  lawnEdge: "#8cd69e",
  forbidden: "rgba(138, 36, 36, 0.82)",
  forbiddenEdge: "#e26a6a",
  spot: "rgba(86, 132, 214, 0.35)",
  spotEdge: "#8cb4f6",
  contour: "#eca854",
  path: "#e8ce78",
  trail: "rgba(250, 240, 150, 0.75)",
  robot: "#fafafa",
  robotRing: "#1e2420",
};

const STYLES = `
  :host { display: block; }
  ha-card { padding: 12px 16px 16px; }
  .header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .title { font-size: 1.15rem; font-weight: 500; }
  .meta { display: flex; gap: 6px; flex-wrap: wrap; }
  .pill { font-size: 0.8rem; padding: 2px 8px; border-radius: 10px;
          background: var(--secondary-background-color); }
  .pill.warn { background: var(--error-color); color: var(--text-primary-color); }
  .map { margin: 8px 0; }
  .canvas { width: 100%; height: auto; display: block; }
  .canvas .shape { cursor: pointer; }
  .canvas .shape:hover { filter: brightness(1.3); }
  .label { fill: #f5faf6; font-size: 22px; font-weight: 600; pointer-events: none;
           paint-order: stroke; stroke: rgba(0, 0, 0, 0.45); stroke-width: 5px; }
  .placeholder { padding: 32px 8px; text-align: center; opacity: 0.7; }
  .selected { font-size: 0.9rem; opacity: 0.8; margin-bottom: 6px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  button.action { background: var(--secondary-background-color); color: inherit;
                  border: none; border-radius: 18px; padding: 7px 13px; cursor: pointer;
                  font: inherit; font-size: 0.85rem; white-space: nowrap; }
  button.action:hover { filter: brightness(1.2); }
  button.primary { background: var(--primary-color); color: var(--text-primary-color); }
`;

class DreameRobotMap extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._error = null;
    this._selected = null;
    this._timer = null;
  }

  setConfig(config) {
    this._config = config || {};
    if (!this._config.entity && !this._config.entry_id) {
      throw new Error("dreame-robot-map requires an 'entity' or 'entry_id'");
    }
    if (!this._timer) {
      this._timer = setInterval(() => this._fetch(), (this._config.refresh_interval || 3) * 1000);
      this._render();
    }
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._fetch();
    }
    this._renderStatus();
  }

  getCardSize() {
    return 6;
  }

  disconnectedCallback() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  get _mower() {
    const id = this._config && this._config.entity;
    return id && this._hass ? this._hass.states[id] : null;
  }

  get _entryId() {
    const mower = this._mower;
    const fromEntity = mower && mower.attributes && mower.attributes.entry_id;
    return this._config.entry_id || fromEntity || null;
  }

  async _fetch() {
    const entryId = this._entryId;
    if (!entryId || !this._hass) {
      return;
    }
    try {
      this._data = await this._hass.callApi("GET", `api/${DOMAIN}/${entryId}/map.json`);
      this._error = null;
    } catch (err) {
      // A missing map is a normal state, not an error worth shouting about.
      this._error = (err && err.message) || String(err);
    }
    this._renderMap();
    this._renderStatus();
  }

  async _mowerCommand(action) {
    const mower = this._mower;
    if (!this._hass || !mower) {
      return;
    }
    await this._hass.callService("lawn_mower", action, { entity_id: mower.entity_id }, {});
  }

  async _service(name, data) {
    if (!this._hass || !this._mower) {
      return;
    }
    await this._hass.callService(DOMAIN, name, data, {});
    await this._fetch();
  }

  // -- rendering -----------------------------------------------------------

  _render() {
    if (!this.shadowRoot) {
      return;
    }
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="header">
          <div class="title"></div>
          <div class="meta"></div>
        </div>
        <div class="map"></div>
        <div class="selected"></div>
        <div class="row"></div>
      </ha-card>`;
    this.shadowRoot.querySelector(".title").textContent =
      (this._config && this._config.title) || "Dreame mower";
    this._renderMap();
    this._renderActions();
    this._renderStatus();
  }

  _el(name, className) {
    const node = document.createElement(name);
    if (className) {
      node.className = className;
    }
    return node;
  }

  _svg(name, attrs) {
    const node = document.createElementNS(SVG_NS, name);
    for (const key of Object.keys(attrs)) {
      node.setAttribute(key, attrs[key]);
    }
    return node;
  }

  _points(pts) {
    return pts.map((p) => `${p[0]},${p[1]}`).join(" ");
  }

  _renderMap() {
    const host = this.shadowRoot && this.shadowRoot.querySelector(".map");
    if (!host) {
      return;
    }
    const data = this._data;
    if (!data) {
      host.textContent = this._error || "Waiting for the mower map…";
      host.className = "map placeholder";
      return;
    }
    if (!data.available || !data.canvas) {
      host.textContent = "No map stored on this mower yet.";
      host.className = "map placeholder";
      return;
    }
    host.className = "map";
    host.textContent = "";

    const svg = this._svg("svg", {
      viewBox: `0 0 ${data.canvas.width} ${data.canvas.height}`,
      preserveAspectRatio: "xMidYMid meet",
    });
    svg.setAttribute("class", "canvas");
    const put = (node) => svg.appendChild(node);

    // Drawn back to front: filled areas, then the lines that sit on top of
    // them, then labels, then the mower. Anything drawn earlier would be
    // painted over by the lawn zones.
    const groups = [
      ["zones", COLORS.lawn, COLORS.lawnEdge, "zone"],
      ["spots", COLORS.spot, COLORS.spotEdge, "spot"],
      // Forbidden areas are shown but not actionable: the device exposes no
      // no-go mowing task, so there is nothing sensible to send.
      ["forbidden", COLORS.forbidden, COLORS.forbiddenEdge, null],
    ];
    for (const [name, fill, edge, action] of groups) {
      for (const poly of data[name] || []) {
        const shape = this._svg("polygon", {
          points: this._points(poly.points),
          fill,
          stroke: edge,
          "stroke-width": 3,
        });
        shape.setAttribute("class", "shape");
        shape.addEventListener("click", (event) => {
          if (!action) {
            return;
          }
          event.stopPropagation();
          this._select({ action, name: poly.name, id: poly.id });
        });
        put(shape);
      }
    }

    for (const path of data.paths || []) {
      put(
        this._svg("polyline", {
          points: this._points(path.points),
          fill: "none",
          stroke: COLORS.path,
          "stroke-width": 3,
          "stroke-dasharray": "10 8",
        })
      );
    }
    for (const segment of data.trail || []) {
      put(
        this._svg("polyline", {
          points: this._points(segment),
          fill: "none",
          stroke: COLORS.trail,
          "stroke-width": 4,
          "stroke-linecap": "round",
          "stroke-linejoin": "round",
        })
      );
    }
    for (const contour of data.contours || []) {
      const shape = this._svg("polyline", {
        points: this._points(contour.points),
        fill: "none",
        stroke: COLORS.contour,
        "stroke-width": 4,
        "stroke-dasharray": "6 5",
      });
      shape.setAttribute("class", "shape");
      shape.addEventListener("click", (event) => {
        event.stopPropagation();
        this._select({ action: "edge", name: contour.name, pair: contourPair(contour) });
      });
      put(shape);
    }
    for (const point of data.points || []) {
      put(this._svg("circle", { cx: point[0], cy: point[1], r: 6, fill: "rgba(220,220,220,0.6)" }));
    }

    for (const name of ["zones", "spots", "forbidden"]) {
      for (const poly of data[name] || []) {
        put(this._label(poly));
      }
    }

    if (data.robot && data.robot.native) {
      const group = this._svg("g", { transform: robotTransform(data.robot) });
      group.appendChild(
        this._svg("polygon", {
          points: "0,-16 11,12 0,6 -11,12",
          fill: COLORS.robot,
          stroke: COLORS.robotRing,
          "stroke-width": 2,
        })
      );
      put(group);
    }

    svg.addEventListener("click", (event) => this._onCanvasClick(event, svg, data));
    host.appendChild(svg);
  }

  _select(selection) {
    /** Remember what the user tapped and refresh the action row. */
    this._selected = selection;
    this._renderActions();
  }

  _label(poly) {
    let x = 0;
    let y = 0;
    for (const p of poly.points) {
      x += p[0];
      y += p[1];
    }
    const text = this._svg("text", {
      x: x / poly.points.length,
      y: y / poly.points.length,
      "text-anchor": "middle",
      "dominant-baseline": "middle",
    });
    text.setAttribute("class", "label");
    text.textContent = poly.name;
    return text;
  }

  _onCanvasClick(event, svg, data) {
    const rect = svg.getBoundingClientRect();
    const scale = data.canvas.width / rect.width;
    const native = invert(data.projection, (event.clientX - rect.left) * scale, (event.clientY - rect.top) * scale);
    this._select({
      action: "point",
      name: `${Math.round(native[0])}, ${Math.round(native[1])}`,
      x: Math.round(native[0]),
      y: Math.round(native[1]),
    });
  }

  _renderActions() {
    const host = this.shadowRoot && this.shadowRoot.querySelector(".row");
    const caption = this.shadowRoot && this.shadowRoot.querySelector(".selected");
    if (!host || !caption) {
      return;
    }
    const selected = this._selected;
    caption.textContent = selected
      ? `Selected ${selected.action}: ${selected.name}`
      : "Tap a zone, an edge, or an empty spot on the map.";

    const actions = [];
    if (selected && selected.action === "point") {
      actions.push({
        label: `Mow here (${selected.x}, ${selected.y})`,
        primary: true,
        run: () => this._service("mow_point", { x: selected.x, y: selected.y }),
      });
      actions.push({
        label: "Drive here",
        run: () => this._service("go_to", { x: selected.x, y: selected.y }),
      });
    } else if (selected && selected.action === "zone") {
      actions.push({
        label: `Mow ${selected.name}`,
        primary: true,
        run: () => this._service("mow_zones", { zone_ids: [selected.id] }),
      });
    } else if (selected && selected.action === "spot") {
      actions.push({
        label: `Mow ${selected.name}`,
        primary: true,
        run: () => this._service("mow_spots", { spot_ids: [selected.id] }),
      });
    } else if (selected && selected.action === "edge") {
      actions.push({
        label: `Mow ${selected.name}`,
        primary: true,
        run: () => this._service("mow_edges", { contour_ids: [selected.pair] }),
      });
    }
    actions.push({ label: "Start mowing", run: () => this._mowerCommand("start_mowing") });
    actions.push({ label: "Pause", run: () => this._mowerCommand("pause") });
    actions.push({ label: "Dock", run: () => this._mowerCommand("dock") });
    actions.push({ label: "Stop", run: () => this._service("stop_mowing", {}) });

    host.textContent = "";
    for (const action of actions) {
      const button = this._el("button", `action${action.primary ? " primary" : ""}`);
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("click", action.run);
      host.appendChild(button);
    }
  }

  _renderStatus() {
    const meta = this.shadowRoot && this.shadowRoot.querySelector(".meta");
    if (!meta) {
      return;
    }
    const mower = this._mower;
    const data = this._data;
    const pills = [];
    if (mower) {
      pills.push(mower.state);
      const attrs = mower.attributes || {};
      if (attrs.battery_level !== undefined && attrs.battery_level !== null) {
        pills.push(`${attrs.battery_level}%`);
      }
      if (attrs.error_name) {
        pills.push({ text: humanise(attrs.error_name), warn: true });
      }
    }
    if (data && data.available) {
      if (data.name) {
        pills.push(data.name);
      }
      if (data.total_area) {
        pills.push(`${Math.round(data.total_area)} m²`);
      }
    }
    meta.textContent = "";
    for (const pill of pills) {
      const node = this._el("span", `pill${pill.warn ? " warn" : ""}`);
      node.textContent = typeof pill === "string" ? pill : pill.text;
      meta.appendChild(node);
    }
  }
}

/** Contour ids travel as [edge, index]; the map only carries the rendered name. */
function contourPair(contour) {
  const match = /Edge (\d+)\.(\d+)/.exec(contour.name || "");
  return match ? [Number(match[1]), Number(match[2])] : [contour.id, 0];
}

function invert(projection, px, py) {
  let x = px;
  let y = py;
  const nw = projection.native_width;
  const nh = projection.native_height;
  if (projection.rotation === 90) {
    [x, y] = [y, nh - 1 - x];
  } else if (projection.rotation === 180) {
    [x, y] = [nw - 1 - x, nh - 1 - y];
  } else if (projection.rotation === 270) {
    [x, y] = [nw - 1 - y, x];
  }
  return [
    projection.max_x - (x - projection.padding) / projection.scale,
    projection.min_y + (y - projection.padding) / projection.scale,
  ];
}

function robotTransform(robot) {
  const angle = (270 - robot.heading) % 360;
  return `translate(${robot.native[0]} ${robot.native[1]}) rotate(${angle})`;
}

function humanise(value) {
  const text = String(value).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

if (!customElements.get("dreame-robot-map")) {
  customElements.define("dreame-robot-map", DreameRobotMap);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "dreame-robot-map")) {
  window.customCards.push({
    type: "dreame-robot-map",
    name: "Dreame Robot Map",
    description: "Interactive map for a Dreame or MOVA robotic mower.",
    preview: true,
  });
}

/**
 * Rain Warner — Custom Lovelace Card
 *
 * Visualizes precipitation nowcasting from the Rain Warner integration:
 *   - Status banner ("Raining now", "Rain in X min", "Dry")
 *   - 2 h precipitation bar chart (5-min resolution)
 *   - Optional 6 h extended forecast tail (greyed out) when available
 *   - Current rate, type and air temperature
 *
 * Installation:
 *   1. Copy this file to /config/www/rain-warner-card.js
 *   2. Add as a Lovelace resource (Settings → Dashboards → Resources):
 *        URL:  /local/rain-warner-card.js
 *        Type: JavaScript Module
 *   3. Use in a dashboard:
 *        type: custom:rain-warner-card
 *        title: Rain Warner
 *        precipitation_entity: sensor.rain_warner_current_precipitation
 *        forecast_entity: binary_sensor.rain_warner_rain_expected
 *        type_entity: sensor.rain_warner_precipitation_type
 *        rain_end_entity: sensor.rain_warner_rain_ends_in
 *        rain_start_entity: sensor.rain_warner_rain_starts_in
 *        rain_ends_at_entity: sensor.rain_warner_rain_ends_at
 *        rain_starts_at_entity: sensor.rain_warner_rain_starts_at
 *        today_entity: sensor.rain_warner_precipitation_today
 *
 * No build step required — pure HTMLElement + DOM, ~6 KB minified.
 */

const CARD_VERSION = "1.0.0";

class RainWarnerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = null;
    this._lastRender = 0;
  }

  setConfig(config) {
    if (!config) {
      throw new Error("Invalid configuration");
    }
    if (
      !config.precipitation_entity &&
      !config.forecast_entity &&
      !config.entity
    ) {
      throw new Error(
        "rain-warner-card requires at least 'precipitation_entity' or 'forecast_entity'",
      );
    }
    this._config = config;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return {
      title: "Rain Warner",
      precipitation_entity: "sensor.rain_warner_current_precipitation",
      forecast_entity: "binary_sensor.rain_warner_rain_expected",
      type_entity: "sensor.rain_warner_precipitation_type",
      rain_end_entity: "sensor.rain_warner_rain_ends_in",
      rain_start_entity: "sensor.rain_warner_rain_starts_in",
      rain_ends_at_entity: "sensor.rain_warner_rain_ends_at",
      rain_starts_at_entity: "sensor.rain_warner_rain_starts_at",
      today_entity: "sensor.rain_warner_precipitation_today",
    };
  }

  _state(entityId) {
    if (!entityId || !this._hass) return null;
    return this._hass.states[entityId] || null;
  }

  _attr(entityId, attr) {
    const s = this._state(entityId);
    return s ? s.attributes[attr] : undefined;
  }

  _typeIcon(type) {
    return (
      {
        none: "☀️",
        rain: "🌧️",
        sleet: "🌨️",
        freezing_rain: "🥶",
        snow: "❄️",
        hail_likely: "⚠️",
        unknown: "❓",
      }[type] || "🌦️"
    );
  }

  _typeLabel(type) {
    const labels = {
      none: "Trocken",
      rain: "Regen",
      sleet: "Schneeregen",
      freezing_rain: "Gefrierender Regen",
      snow: "Schnee",
      hail_likely: "Hagel möglich",
      unknown: "Unbekannt",
    };
    // Fallback: capitalize the raw type
    if (!type) return "—";
    return labels[type] || type.replace(/_/g, " ");
  }

  _intensityColor(mmh) {
    if (mmh <= 0) return "transparent";
    if (mmh < 0.5) return "#a8d8ff";
    if (mmh < 2.5) return "#5fa8e0";
    if (mmh < 7.6) return "#3a72c8";
    if (mmh < 50) return "#244ea1";
    return "#7e1f6e";
  }

  _buildForecastBars() {
    const fc =
      this._attr(this._config.forecast_entity, "forecast") ||
      this._attr(this._config.precipitation_entity, "forecast") ||
      {};
    // The integration exposes forecast on rain_expected as
    // {minutes: mm/h}. Build sorted slots from t+5 .. t+120.
    const slots = Array.from({ length: 24 }, (_, i) => (i + 1) * 5);
    return slots.map((min) => ({ minutes: min, mmh: Number(fc[min] || 0) }));
  }

  _buildExtendedBars() {
    const fc =
      this._attr(this._config.forecast_entity, "forecast_extended") ||
      this._attr(this._config.precipitation_entity, "forecast_extended");
    if (!fc || typeof fc !== "object") return [];
    const minutes = Object.keys(fc)
      .map(Number)
      .filter((m) => m > 120 && m <= 360)
      .sort((a, b) => a - b);
    return minutes.map((m) => ({ minutes: m, mmh: Number(fc[m] || 0) }));
  }

  _formatClockTime(iso) {
    if (!iso || iso === "unknown" || iso === "unavailable") return null;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _statusText() {
    const isRaining = this._state(this._config.forecast_entity);
    const startMin = Number(this._state(this._config.rain_start_entity)?.state);
    const endVal = this._state(this._config.rain_end_entity)?.state;
    const startsAt = this._state(this._config.rain_starts_at_entity)?.state;
    const endsAt = this._state(this._config.rain_ends_at_entity)?.state;

    const currentMmh = Number(
      this._state(this._config.precipitation_entity)?.state || 0,
    );

    if (currentMmh > 0) {
      // Prefer the absolute clock time when we have a rain_ends_at sensor.
      const endsAtTxt = this._formatClockTime(endsAt);
      let endTxt = "";
      if (endsAtTxt) {
        endTxt = `, endet um ${endsAtTxt}`;
      } else if (endVal && endVal !== "unknown" && endVal !== "unavailable") {
        endTxt = `, endet in ${endVal} min`;
      }
      return {
        tone: "rain",
        text: `Es regnet jetzt (${currentMmh.toFixed(1)} mm/h)${endTxt}`,
      };
    }
    const startsAtTxt = this._formatClockTime(startsAt);
    if (startsAtTxt && Number.isFinite(startMin) && startMin > 0) {
      return {
        tone: "warn",
        text: `Regen ab ${startsAtTxt} (in ${startMin} min)`,
      };
    }
    if (Number.isFinite(startMin) && startMin > 0) {
      return {
        tone: "warn",
        text: `Regen in ${startMin} min`,
      };
    }
    if (isRaining && isRaining.state === "on") {
      return { tone: "warn", text: "Regen erwartet" };
    }
    return { tone: "dry", text: "Trocken — keine Niederschläge in 2 h" };
  }

  _render() {
    if (!this._config || !this._hass) return;
    // Throttle to once per 250 ms — cheap re-renders during state spam.
    const now = Date.now();
    if (now - this._lastRender < 250) return;
    this._lastRender = now;

    const status = this._statusText();
    const bars = this._buildForecastBars();
    const extBars = this._buildExtendedBars();
    const allBars = bars.concat(extBars);
    const maxMmh = Math.max(2, ...allBars.map((b) => b.mmh));

    const type = this._state(this._config.type_entity)?.state;
    const temperature = this._attr(this._config.type_entity, "temperature_c");
    const today = this._state(this._config.today_entity)?.state;

    const barsHtml = bars
      .map((b) => {
        const h = b.mmh > 0 ? Math.max(4, (b.mmh / maxMmh) * 100) : 2;
        const color = this._intensityColor(b.mmh);
        return `
          <div class="bar-wrap" title="t+${b.minutes} min: ${b.mmh.toFixed(1)} mm/h">
            <div class="bar" style="height:${h}%;background:${color};"></div>
          </div>`;
      })
      .join("");

    const extBarsHtml = extBars.length
      ? extBars
          .map((b) => {
            const h = b.mmh > 0 ? Math.max(4, (b.mmh / maxMmh) * 100) : 2;
            const color = this._intensityColor(b.mmh);
            return `
              <div class="bar-wrap ext" title="t+${b.minutes} min (extrapoliert): ${b.mmh.toFixed(1)} mm/h">
                <div class="bar" style="height:${h}%;background:${color};opacity:0.55;"></div>
              </div>`;
          })
          .join("")
      : "";

    // Compute axis label positions in % of the chart width. The chart
    // contains 24 RADVOR bars + (1 separator + N extended bars) when
    // forecast_extended is available, with all bars sharing flex:1. We
    // need labels at the actual bar positions, not at evenly spaced
    // intervals (justify-content:space-between would put +1h at 33% in
    // 6 h mode, but bar 12 is actually at ~17%).
    const totalCells = bars.length + (extBars.length ? 1 + extBars.length : 0);
    const sepIdx = bars.length; // separator sits between RADVOR and extended
    const pctOf = (cellIdx) =>
      totalCells === 0 ? 0 : (cellIdx / totalCells) * 100;
    const axisLabels = extBars.length
      ? [
          { txt: "jetzt", pct: 0, anchor: "start" },
          { txt: "+1 h", pct: pctOf(12), anchor: "center" },
          { txt: "+2 h", pct: pctOf(sepIdx), anchor: "center" },
          { txt: "+6 h", pct: 100, anchor: "end" },
        ]
      : [
          { txt: "jetzt", pct: 0, anchor: "start" },
          { txt: "+1 h", pct: pctOf(12), anchor: "center" },
          { txt: "+2 h", pct: 100, anchor: "end" },
        ];
    const axisHtml = axisLabels
      .map(({ txt, pct, anchor }) => {
        const transform =
          anchor === "start"
            ? "none"
            : anchor === "end"
              ? "translateX(-100%)"
              : "translateX(-50%)";
        return `<span style="left:${pct.toFixed(2)}%;transform:${transform};">${txt}</span>`;
      })
      .join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --rw-rain: var(--info-color, #3a72c8);
          --rw-warn: var(--warning-color, #f5a623);
          --rw-dry: var(--success-color, #6abf69);
        }
        ha-card {
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .title { font-size: 1.1rem; font-weight: 600; }
        .status {
          padding: 10px 12px;
          border-radius: 8px;
          color: white;
          font-weight: 500;
        }
        .status.rain { background: var(--rw-rain); }
        .status.warn { background: var(--rw-warn); }
        .status.dry  { background: var(--rw-dry); }
        .meta {
          display: flex;
          gap: 16px;
          flex-wrap: wrap;
          font-size: 0.9rem;
          color: var(--secondary-text-color);
        }
        .meta .v { color: var(--primary-text-color); font-weight: 500; }
        .chart {
          display: flex;
          gap: 1px;
          height: 100px;
          align-items: flex-end;
          background: var(--card-background-color);
          padding: 4px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          /* Subtle banding so users can tell where RADVOR ends and the
             optical-flow extrapolation begins. */
          background-image: linear-gradient(
            to right,
            transparent 0,
            transparent var(--rw-radvor-end, 33%),
            rgba(127, 127, 127, 0.06) var(--rw-radvor-end, 33%),
            rgba(127, 127, 127, 0.06) 100%
          );
        }
        .chart .sep {
          width: 1px;
          background: var(--divider-color);
          opacity: 0.6;
          margin: 0 2px;
        }
        .bar-wrap {
          flex: 1;
          height: 100%;
          display: flex;
          align-items: flex-end;
          min-width: 2px;
        }
        .bar {
          width: 100%;
          border-radius: 2px 2px 0 0;
          transition: height 0.3s ease;
        }
        .axis {
          position: relative;
          height: 1em;
          font-size: 0.72rem;
          color: var(--secondary-text-color);
          margin-top: 2px;
        }
        .axis span {
          position: absolute;
          white-space: nowrap;
        }
      </style>
      <ha-card>
        ${this._config.title ? `<div class="title">${this._config.title}</div>` : ""}
        <div class="status ${status.tone}">${status.text}</div>
        <div class="meta">
          <span>${this._typeIcon(type)} <span class="v">${this._typeLabel(type)}</span></span>
          ${
            temperature !== undefined && temperature !== null
              ? `<span>🌡️ <span class="v">${Number(temperature).toFixed(1)} °C</span></span>`
              : ""
          }
          ${
            today !== undefined && today !== "unknown"
              ? `<span>Heute: <span class="v">${Number(today).toFixed(1)} mm</span></span>`
              : ""
          }
        </div>
        <div class="chart" style="--rw-radvor-end:${pctOf(sepIdx).toFixed(2)}%">
          ${barsHtml}
          ${extBarsHtml ? `<div class="sep"></div>${extBarsHtml}` : ""}
        </div>
        <div class="axis">${axisHtml}</div>
      </ha-card>
    `;
  }
}

customElements.define("rain-warner-card", RainWarnerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "rain-warner-card",
  name: "Rain Warner Card",
  description: "Precipitation nowcast with 2-6 h bar chart",
  preview: false,
  documentationURL: "https://github.com/nodomain/ha-rain-warner",
});

console.info(
  `%c RAIN-WARNER-CARD %c v${CARD_VERSION} `,
  "color:white;background:#3a72c8;font-weight:bold;border-radius:3px;",
  "color:#3a72c8;background:transparent;font-weight:bold;",
);

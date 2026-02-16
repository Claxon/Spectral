"""OBS Browser Source server for the Spectrum Analyzer.

Runs a lightweight HTTP server that serves a real-time spectrum visualization
as an HTML5 Canvas page. Add http://localhost:9753 as a Browser Source in OBS.

Features:
- Transparent background (works with OBS chroma key or native transparency)
- JSON API endpoint for real-time audio data
- Self-contained: reuses the same DSP pipeline as the main app
- Configurable via query parameters (e.g. ?mode=bars&theme=neon&bands=64)

Usage:
    python obs_server.py
    Then in OBS: Sources -> Add -> Browser -> URL: http://localhost:9753
    Set width/height to match your scene (e.g., 800x400).
"""

import json
import sys
import time
import threading
import argparse
import numpy as np
from flask import Flask, Response, request, send_from_directory

from config import AppConfig
from ring_buffer import RingBuffer
from audio_capture import AudioCapture
from dsp import DSPProcessor

# ── Globals for audio pipeline ───────────────────────────────────────────────

_config: AppConfig = None
_ring_buffer: RingBuffer = None
_audio: AudioCapture = None
_dsp: DSPProcessor = None
_last_result_lock = threading.Lock()
_last_result_json: str = '{"bands":[],"peaks":[],"rms":-80,"peak":-80,"wave":[]}'

app = Flask(__name__, static_folder=None)


def _audio_loop():
    """Background thread: continuously run DSP and cache the result as JSON."""
    global _last_result_json
    while True:
        samples = _ring_buffer.read_latest(_config.fft_size)
        if samples is not None:
            result = _dsp.process(samples, 1.0 / 60.0)

            # Downsample waveform for transfer (128 points is plenty for vis)
            wave = result.waveform
            if len(wave) > 128:
                indices = np.linspace(0, len(wave) - 1, 128).astype(int)
                wave = wave[indices]

            data = {
                "bands": [round(float(v), 1) for v in result.band_magnitudes_db],
                "peaks": [round(float(v), 1) for v in result.peak_hold_db],
                "centers": [round(float(v), 1) for v in result.band_centers],
                "rms": round(float(result.rms_db), 1),
                "peak": round(float(result.peak_db), 1),
                "wave": [round(float(v), 3) for v in wave],
                "db_range": _config.db_range,
            }

            payload = json.dumps(data, separators=(",", ":"))
            with _last_result_lock:
                _last_result_json = payload

        time.sleep(1.0 / 60.0)  # ~60 fps


# ── HTTP Endpoints ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main overlay page."""
    return _OVERLAY_HTML


@app.route("/data")
def data():
    """Return the latest DSP result as JSON."""
    with _last_result_lock:
        payload = _last_result_json
    return Response(payload, mimetype="application/json",
                    headers={"Access-Control-Allow-Origin": "*",
                             "Cache-Control": "no-cache"})


# ── HTML Overlay ─────────────────────────────────────────────────────────────

_OVERLAY_HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Spectrum Analyzer – OBS Overlay</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: transparent;
    overflow: hidden;
    font-family: 'Segoe UI', 'Consolas', monospace;
  }
  canvas { display: block; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<script>
(() => {
  const canvas = document.getElementById('c');
  const ctx = canvas.getContext('2d');

  // Parse query params for configuration
  const params = new URLSearchParams(window.location.search);
  const MODE = params.get('mode') || 'bars';          // bars | line | radial
  const THEME = params.get('theme') || 'neon';         // neon | warm | ocean | light
  const BAR_GAP = parseFloat(params.get('gap') || '2');
  const SHOW_PEAKS = params.get('peaks') !== 'false';
  const SHOW_DB = params.get('db') !== 'false';
  const CORNER_RADIUS = parseFloat(params.get('radius') || '2');

  // Theme palettes
  const THEMES = {
    neon: {
      low: [0, 100, 255],
      mid: [180, 0, 255],
      high: [255, 0, 100],
      peak: [255, 0, 200],
      line: [0, 255, 220],
      fill: [0, 255, 220, 0.12],
      text: [0, 255, 220],
      grid: [255, 255, 255, 0.08],
      bg: null,
    },
    dark: {
      low: [20, 184, 72],
      mid: [242, 209, 20],
      high: [242, 30, 20],
      peak: [255, 255, 255],
      line: [77, 178, 255],
      fill: [77, 178, 255, 0.15],
      text: [235, 235, 240],
      grid: [255, 255, 255, 0.06],
      bg: null,
    },
    warm: {
      low: [255, 166, 38],
      mid: [255, 89, 26],
      high: [217, 20, 38],
      peak: [255, 242, 166],
      line: [255, 140, 51],
      fill: [255, 140, 51, 0.15],
      text: [255, 235, 209],
      grid: [255, 255, 255, 0.06],
      bg: null,
    },
    ocean: {
      low: [0, 140, 191],
      mid: [38, 204, 166],
      high: [115, 242, 217],
      peak: [166, 242, 255],
      line: [51, 191, 242],
      fill: [51, 191, 242, 0.15],
      text: [199, 235, 255],
      grid: [255, 255, 255, 0.06],
      bg: null,
    },
    light: {
      low: [38, 153, 77],
      mid: [217, 184, 26],
      high: [217, 46, 38],
      peak: [140, 38, 38],
      line: [38, 115, 204],
      fill: [38, 115, 204, 0.15],
      text: [26, 26, 30],
      grid: [0, 0, 0, 0.06],
      bg: null,
    },
  };

  const theme = THEMES[THEME] || THEMES.neon;

  let audioData = null;

  // Resize canvas to fill viewport
  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  window.addEventListener('resize', resize);
  resize();

  // Fetch data from the local server
  async function fetchData() {
    try {
      const resp = await fetch('/data');
      audioData = await resp.json();
    } catch (e) { /* server not ready yet */ }
  }

  // Color interpolation
  function lerpColor(t, low, mid, high) {
    t = Math.max(0, Math.min(1, t));
    let a, b, s;
    if (t < 0.5) {
      a = low; b = mid; s = t * 2;
    } else {
      a = mid; b = high; s = (t - 0.5) * 2;
    }
    return [
      Math.round(a[0] + (b[0] - a[0]) * s),
      Math.round(a[1] + (b[1] - a[1]) * s),
      Math.round(a[2] + (b[2] - a[2]) * s),
    ];
  }

  function rgba(c, a = 1) {
    if (c.length === 4) return `rgba(${c[0]},${c[1]},${c[2]},${c[3]})`;
    return `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  }

  // Rounded rect helper
  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arcTo(x + w, y, x + w, y + r, r);
    ctx.lineTo(x + w, y + h - r);
    ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
    ctx.lineTo(x + r, y + h);
    ctx.arcTo(x, y + h, x, y + h - r, r);
    ctx.lineTo(x, y + r);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
  }

  // ── Bar graph mode ──────────────────────────────────────────────
  function drawBars(data) {
    const W = canvas.width;
    const H = canvas.height;
    const bands = data.bands;
    const peaks = data.peaks;
    const dbRange = data.db_range || 80;
    const n = bands.length;
    if (n === 0) return;

    const margin = { left: 0, right: 0, top: 10, bottom: SHOW_DB ? 20 : 0 };
    const plotW = W - margin.left - margin.right;
    const plotH = H - margin.top - margin.bottom;
    const barW = (plotW - BAR_GAP * (n - 1)) / n;

    for (let i = 0; i < n; i++) {
      const db = bands[i];
      const t = Math.max(0, Math.min(1, (db + dbRange) / (dbRange + 6)));
      const barH = plotH * t;
      const x = margin.left + i * (barW + BAR_GAP);
      const y = margin.top + plotH - barH;

      const c = lerpColor(t, theme.low, theme.mid, theme.high);

      // Gradient fill
      const grad = ctx.createLinearGradient(x, y + barH, x, y);
      const cLow = lerpColor(0, theme.low, theme.mid, theme.high);
      grad.addColorStop(0, rgba(cLow, 0.6));
      grad.addColorStop(1, rgba(c, 1));
      ctx.fillStyle = grad;
      roundRect(ctx, x, y, Math.max(barW, 1), barH, CORNER_RADIUS);
      ctx.fill();

      // Peak marker
      if (SHOW_PEAKS && peaks && peaks[i] !== undefined) {
        const pt = Math.max(0, Math.min(1, (peaks[i] + dbRange) / (dbRange + 6)));
        const peakY = margin.top + plotH - plotH * pt;
        ctx.fillStyle = rgba(theme.peak, 0.9);
        ctx.fillRect(x, peakY - 1.5, barW, 2.5);
      }
    }

    // dB label
    if (SHOW_DB) {
      ctx.fillStyle = rgba(theme.text, 0.6);
      ctx.font = '11px Consolas, monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`RMS: ${data.rms} dB`, W - 8, H - 4);
      ctx.textAlign = 'left';
      ctx.fillText(`Peak: ${data.peak} dB`, 8, H - 4);
    }
  }

  // ── Smooth line mode ────────────────────────────────────────────
  function drawLine(data) {
    const W = canvas.width;
    const H = canvas.height;
    const bands = data.bands;
    const dbRange = data.db_range || 80;
    const n = bands.length;
    if (n < 2) return;

    const margin = { left: 4, right: 4, top: 10, bottom: SHOW_DB ? 20 : 4 };
    const plotW = W - margin.left - margin.right;
    const plotH = H - margin.top - margin.bottom;

    // Build points
    const points = [];
    for (let i = 0; i < n; i++) {
      const t = Math.max(0, Math.min(1, (bands[i] + dbRange) / (dbRange + 6)));
      const x = margin.left + (i / (n - 1)) * plotW;
      const y = margin.top + plotH * (1 - t);
      points.push({ x, y });
    }

    // Fill
    ctx.beginPath();
    ctx.moveTo(points[0].x, margin.top + plotH);
    for (const p of points) ctx.lineTo(p.x, p.y);
    ctx.lineTo(points[n - 1].x, margin.top + plotH);
    ctx.closePath();
    const fillC = theme.fill;
    ctx.fillStyle = `rgba(${fillC[0]},${fillC[1]},${fillC[2]},${fillC[3] || 0.12})`;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < n; i++) ctx.lineTo(points[i].x, points[i].y);
    ctx.strokeStyle = rgba(theme.line);
    ctx.lineWidth = 2;
    ctx.stroke();

    if (SHOW_DB) {
      ctx.fillStyle = rgba(theme.text, 0.6);
      ctx.font = '11px Consolas, monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`RMS: ${data.rms} dB`, W - 8, H - 4);
    }
  }

  // ── Radial mode ─────────────────────────────────────────────────
  function drawRadial(data) {
    const W = canvas.width;
    const H = canvas.height;
    const bands = data.bands;
    const dbRange = data.db_range || 80;
    const n = bands.length;
    if (n === 0) return;

    const cx = W / 2;
    const cy = H / 2;
    const radius = Math.min(W, H) * 0.45;
    const rMin = radius * 0.3;
    const rMax = radius;

    // Reference circles
    ctx.strokeStyle = rgba(theme.grid.length === 4 ? theme.grid : [...theme.grid, 0.08]);
    ctx.lineWidth = 0.5;
    for (const frac of [0.25, 0.5, 0.75, 1.0]) {
      const r = rMin + (rMax - rMin) * frac;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Bars as arcs
    for (let i = 0; i < n; i++) {
      const angleStart = (Math.PI * 2 * i / n) - Math.PI / 2;
      const angleEnd = (Math.PI * 2 * (i + 0.82) / n) - Math.PI / 2;
      const db = bands[i];
      const t = Math.max(0, Math.min(1, (db + dbRange) / (dbRange + 6)));
      const r = rMin + (rMax - rMin) * t;
      const c = lerpColor(t, theme.low, theme.mid, theme.high);

      ctx.beginPath();
      ctx.arc(cx, cy, rMin, angleStart, angleEnd);
      ctx.arc(cx, cy, r, angleEnd, angleStart, true);
      ctx.closePath();
      ctx.fillStyle = rgba(c, 0.85);
      ctx.fill();
    }

    // Center text
    ctx.fillStyle = rgba(theme.text, 0.9);
    ctx.font = 'bold 16px Consolas, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`${data.rms} dB`, cx, cy);
  }

  // ── Main render loop ────────────────────────────────────────────
  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!audioData || !audioData.bands || audioData.bands.length === 0) {
      ctx.fillStyle = rgba(theme.text, 0.3);
      ctx.font = '14px Segoe UI, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting for audio...', canvas.width / 2, canvas.height / 2);
      requestAnimationFrame(draw);
      return;
    }

    switch (MODE) {
      case 'line':  drawLine(audioData); break;
      case 'radial': drawRadial(audioData); break;
      default:       drawBars(audioData); break;
    }

    requestAnimationFrame(draw);
  }

  // Start
  setInterval(fetchData, 16);  // ~60 fps polling
  requestAnimationFrame(draw);
})();
</script>
</body>
</html>
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    global _config, _ring_buffer, _audio, _dsp

    parser = argparse.ArgumentParser(description="OBS Browser Source for Spectrum Analyzer")
    parser.add_argument("--port", type=int, default=9753, help="HTTP port (default: 9753)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Bind address")
    args = parser.parse_args()

    # Load saved config (reuse the same settings as the main app)
    _config = AppConfig.load()
    _ring_buffer = RingBuffer(capacity=_config.fft_size * 4, channels=1)
    _audio = AudioCapture(_ring_buffer, _config)
    _dsp = DSPProcessor(_config)

    # Start audio capture (same logic as main app)
    devices = _audio.enumerate_devices()
    if not devices:
        print("ERROR: No audio devices found.")
        sys.exit(1)

    target = None
    saved_name = _config.input_device_name
    if saved_name:
        for d in devices:
            if d.name == saved_name:
                target = d
                break

    if target is None:
        loopback = [d for d in devices if d.is_loopback]
        target = loopback[0] if loopback else devices[0]

    print(f"Audio device: {target.name}")
    print(f"Sample rate:  {int(target.sample_rate)} Hz")
    _config.sample_rate = int(target.sample_rate)
    _audio.start(target)

    # Start DSP background thread
    dsp_thread = threading.Thread(target=_audio_loop, daemon=True)
    dsp_thread.start()

    print(f"\n  OBS Browser Source URL: http://{args.host}:{args.port}")
    print(f"  Bar mode:    http://{args.host}:{args.port}?mode=bars")
    print(f"  Line mode:   http://{args.host}:{args.port}?mode=line")
    print(f"  Radial mode: http://{args.host}:{args.port}?mode=radial")
    print(f"  Themes:      ?theme=neon|dark|warm|ocean|light")
    print(f"  No peaks:    ?peaks=false")
    print(f"  No dB:       ?db=false")
    print(f"\n  Press Ctrl+C to stop.\n")

    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()

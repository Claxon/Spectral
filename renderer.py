"""Renderer: all display modes using ImPlot and ImGui DrawList."""

import math
import numpy as np
from imgui_bundle import imgui, implot

from config import AppConfig, DisplayMode, ColorTheme
from dsp import DSPResult
from themes import THEMES, ThemeColors, lerp_color, color_to_u32


class Renderer:
    def __init__(self, config: AppConfig):
        self.config = config
        self._spectrogram_history: list[np.ndarray] = []
        self._fps_samples: list[float] = []

    def render(self, result: DSPResult, dt: float) -> None:
        self._update_fps(dt)
        theme = THEMES[self.config.color_theme]

        match self.config.display_mode:
            case DisplayMode.BAR_GRAPH:
                self._render_bar_graph(result, theme)
            case DisplayMode.SMOOTH_LINE:
                self._render_smooth_line(result, theme)
            case DisplayMode.SPECTROGRAM:
                self._render_spectrogram(result, theme)
            case DisplayMode.RADIAL:
                self._render_radial(result, theme)
            case DisplayMode.OSCILLOSCOPE:
                self._render_oscilloscope(result, theme)
            case DisplayMode.COMBINED:
                self._render_combined(result, theme)

        self._render_level_meters(result, theme)

        if self.config.show_fps:
            self._render_fps_overlay()

    # ── Bar Graph ──────────────────────────────────────────────────────

    def _render_bar_graph(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        size = imgui.get_content_region_avail()
        if size.x < 10 or size.y < 10:
            imgui.end()
            return

        num = len(result.band_magnitudes_db)
        if num == 0:
            imgui.end()
            return

        if implot.begin_plot("##bars", imgui.ImVec2(size.x, size.y)):
            implot.setup_axes("Frequency", "dB", implot.AxisFlags_.no_tick_labels, 0)
            implot.setup_axes_limits(0, num, -self.config.db_range, 6, implot.Cond_.always)

            # Custom tick labels for frequency axis
            tick_count = min(12, num)
            if tick_count > 0 and len(result.band_centers) == num:
                step = max(1, num // tick_count)
                positions = list(range(0, num, step))
                tick_pos = np.array(positions, dtype=np.float64) + 0.5
                tick_labels = [_format_freq(result.band_centers[i]) for i in positions]
                implot.setup_axis_ticks(implot.ImAxis_.x1, tick_pos.tolist(), tick_labels, False)

            # Draw gradient bars via draw list
            plot_dl = implot.get_plot_draw_list()
            implot.push_plot_clip_rect()

            bar_w = 0.85
            for i in range(num):
                db = result.band_magnitudes_db[i]
                t = max(0.0, min(1.0, (db + self.config.db_range) / (self.config.db_range + 6)))
                color = lerp_color(t, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high)

                p_min = implot.plot_to_pixels(i + 0.5 - bar_w / 2, -self.config.db_range)
                p_max = implot.plot_to_pixels(i + 0.5 + bar_w / 2, db)

                col = color_to_u32(*color)
                # Gradient: draw bottom half with low color, top with actual
                mid_y = p_min.y + (p_max.y - p_min.y) * 0.5
                col_base = color_to_u32(*lerp_color(t * 0.4, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high))
                plot_dl.add_rect_filled_multi_color(
                    imgui.ImVec2(p_min.x, min(p_min.y, p_max.y)),
                    imgui.ImVec2(p_max.x, max(p_min.y, p_max.y)),
                    col, col, col_base, col_base,
                )

            # Peak markers as small horizontal lines
            peak_col = color_to_u32(*theme.peak_marker)
            for i in range(num):
                pk = result.peak_hold_db[i]
                if pk > -self.config.db_range:
                    p1 = implot.plot_to_pixels(i + 0.5 - bar_w / 2, pk)
                    p2 = implot.plot_to_pixels(i + 0.5 + bar_w / 2, pk)
                    plot_dl.add_line(
                        imgui.ImVec2(p1.x, p1.y),
                        imgui.ImVec2(p2.x, p2.y),
                        peak_col, 2.0,
                    )

            implot.pop_plot_clip_rect()
            implot.end_plot()

        imgui.end()

    # ── Smooth Line ────────────────────────────────────────────────────

    def _render_smooth_line(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        size = imgui.get_content_region_avail()
        if size.x < 10 or size.y < 10:
            imgui.end()
            return

        num = len(result.band_magnitudes_db)
        if num == 0 or len(result.band_centers) != num:
            imgui.end()
            return

        if implot.begin_plot("##line", imgui.ImVec2(size.x, size.y)):
            implot.setup_axes("Frequency (Hz)", "dB")
            implot.setup_axes_limits(
                self.config.freq_min, self.config.freq_max,
                -self.config.db_range, 6,
                implot.Cond_.always,
            )
            implot.setup_axis_scale(implot.ImAxis_.x1, implot.Scale_.log10)

            xs = result.band_centers.astype(np.float64)
            ys = result.band_magnitudes_db.astype(np.float64)
            floor = np.full_like(ys, -self.config.db_range)

            # Filled area
            implot.push_style_color(implot.Col_.fill, imgui.ImVec4(*theme.line_fill))
            implot.push_style_var(implot.StyleVar_.fill_alpha, 0.35)
            implot.plot_shaded("##fill", xs, ys, floor)
            implot.pop_style_var()
            implot.pop_style_color()

            # Main line
            implot.push_style_color(implot.Col_.line, imgui.ImVec4(*theme.line_color))
            implot.set_next_line_style(imgui.ImVec4(*theme.line_color), 2.0)
            implot.plot_line("Spectrum", xs, ys)
            implot.pop_style_color()

            # Peak hold
            peak_ys = result.peak_hold_db.astype(np.float64)
            implot.set_next_line_style(imgui.ImVec4(*theme.peak_marker), 1.0)
            implot.plot_line("Peak", xs, peak_ys)

            implot.end_plot()

        imgui.end()

    # ── Spectrogram ────────────────────────────────────────────────────

    def _render_spectrogram(self, result: DSPResult, theme: ThemeColors):
        # Downsample FFT to fixed column count
        target_cols = 256
        spec_line = result.spectrogram_line
        if len(spec_line) > target_cols:
            indices = np.linspace(0, len(spec_line) - 1, target_cols).astype(int)
            spec_line = spec_line[indices]
        elif len(spec_line) < target_cols:
            spec_line = np.interp(
                np.linspace(0, len(spec_line) - 1, target_cols),
                np.arange(len(spec_line)),
                spec_line,
            )

        self._spectrogram_history.append(spec_line.astype(np.float64))
        max_lines = int(self.config.spectrogram_history_seconds * 60)
        if len(self._spectrogram_history) > max_lines:
            self._spectrogram_history = self._spectrogram_history[-max_lines:]

        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        size = imgui.get_content_region_avail()
        if size.x < 10 or size.y < 10:
            imgui.end()
            return

        if len(self._spectrogram_history) < 2:
            imgui.text("Accumulating spectrogram data...")
            imgui.end()
            return

        if implot.begin_plot("##spectrogram", imgui.ImVec2(size.x, size.y)):
            implot.setup_axes("Frequency", "Time")

            data = np.array(self._spectrogram_history, dtype=np.float64)
            rows, cols = data.shape

            implot.push_colormap(theme.spectrogram_colormap)
            implot.plot_heatmap(
                "##heat",
                data,
                scale_min=-self.config.db_range,
                scale_max=0.0,
                label_fmt="",
                bounds_min=implot.Point(0, 0),
                bounds_max=implot.Point(cols, rows),
            )
            implot.pop_colormap()
            implot.end_plot()

        imgui.end()

    # ── Radial ─────────────────────────────────────────────────────────

    def _render_radial(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(600, 600), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        size = imgui.get_content_region_avail()
        if size.x < 10 or size.y < 10:
            imgui.end()
            return

        draw_list = imgui.get_window_draw_list()
        pos = imgui.get_cursor_screen_pos()

        cx = pos.x + size.x / 2
        cy = pos.y + size.y / 2
        radius = min(size.x, size.y) * 0.45
        r_min = radius * 0.30
        r_max = radius

        num = len(result.band_magnitudes_db)
        if num == 0:
            imgui.end()
            return

        # Draw reference circles
        grid_col = color_to_u32(*theme.grid)
        for frac in [0.25, 0.5, 0.75, 1.0]:
            r = r_min + (r_max - r_min) * frac
            draw_list.add_circle(imgui.ImVec2(cx, cy), r, grid_col, 64, 1.0)

        # Draw bars as arc segments
        for i in range(num):
            angle_start = 2.0 * math.pi * i / num - math.pi / 2
            angle_end = 2.0 * math.pi * (i + 0.82) / num - math.pi / 2

            db = result.band_magnitudes_db[i]
            t = max(0.0, min(1.0, (db + self.config.db_range) / (self.config.db_range + 6)))
            r = r_min + (r_max - r_min) * t

            color = lerp_color(t, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high)
            col = color_to_u32(*color)

            # Build polygon for arc segment
            steps = 4
            points = []
            for s in range(steps + 1):
                a = angle_start + (angle_end - angle_start) * s / steps
                points.append(imgui.ImVec2(cx + r_min * math.cos(a), cy + r_min * math.sin(a)))
            for s in range(steps, -1, -1):
                a = angle_start + (angle_end - angle_start) * s / steps
                points.append(imgui.ImVec2(cx + r * math.cos(a), cy + r * math.sin(a)))

            draw_list.add_convex_poly_filled(points, col)

            # Peak marker arc
            pk = result.peak_hold_db[i]
            pk_t = max(0.0, min(1.0, (pk + self.config.db_range) / (self.config.db_range + 6)))
            pk_r = r_min + (r_max - r_min) * pk_t
            if pk_r > r_min + 2:
                a_mid = (angle_start + angle_end) / 2
                p1 = imgui.ImVec2(cx + pk_r * math.cos(angle_start), cy + pk_r * math.sin(angle_start))
                p2 = imgui.ImVec2(cx + pk_r * math.cos(angle_end), cy + pk_r * math.sin(angle_end))
                draw_list.add_line(p1, p2, color_to_u32(*theme.peak_marker), 1.5)

        # Center info
        draw_list.add_circle_filled(imgui.ImVec2(cx, cy), r_min * 0.85,
                                     color_to_u32(*theme.background[:3], 0.8), 48)
        text = f"{result.rms_db:.1f} dB"
        text_size = imgui.calc_text_size(text)
        draw_list.add_text(
            imgui.ImVec2(cx - text_size.x / 2, cy - text_size.y / 2),
            color_to_u32(*theme.text),
            text,
        )

        imgui.dummy(size)
        imgui.end()

    # ── Oscilloscope ───────────────────────────────────────────────────

    def _render_oscilloscope(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        size = imgui.get_content_region_avail()
        if size.x < 10 or size.y < 10:
            imgui.end()
            return

        if implot.begin_plot("##scope", imgui.ImVec2(size.x, size.y)):
            implot.setup_axes("Sample", "Amplitude")
            n = len(result.waveform)
            implot.setup_axes_limits(0, n, -1, 1, implot.Cond_.always)

            xs = np.arange(n, dtype=np.float64)
            ys = result.waveform.astype(np.float64)

            # Zero line
            implot.push_style_color(implot.Col_.line, imgui.ImVec4(*theme.grid))
            implot.plot_line("##zero", np.array([0.0, float(n)]), np.array([0.0, 0.0]))
            implot.pop_style_color()

            # Waveform
            implot.set_next_line_style(imgui.ImVec4(*theme.waveform_color), 1.5)
            implot.plot_line("Waveform", xs, ys)

            implot.end_plot()

        imgui.end()

    # ── Combined ───────────────────────────────────────────────────────

    def _render_combined(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(900, 600), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        avail = imgui.get_content_region_avail()
        if avail.x < 10 or avail.y < 10:
            imgui.end()
            return

        num = len(result.band_magnitudes_db)

        # Top: bar spectrum (60%)
        bar_h = avail.y * 0.58
        if num > 0 and implot.begin_plot("##combined_bars", imgui.ImVec2(avail.x, bar_h)):
            implot.setup_axes("Frequency", "dB", implot.AxisFlags_.no_tick_labels, 0)
            implot.setup_axes_limits(0, num, -self.config.db_range, 6, implot.Cond_.always)

            if len(result.band_centers) == num:
                tick_count = min(12, num)
                step = max(1, num // tick_count)
                positions = list(range(0, num, step))
                tick_pos = np.array(positions, dtype=np.float64) + 0.5
                tick_labels = [_format_freq(result.band_centers[i]) for i in positions]
                implot.setup_axis_ticks(implot.ImAxis_.x1, tick_pos.tolist(), tick_labels, False)

            plot_dl = implot.get_plot_draw_list()
            implot.push_plot_clip_rect()

            bar_w = 0.85
            for i in range(num):
                db = result.band_magnitudes_db[i]
                t = max(0.0, min(1.0, (db + self.config.db_range) / (self.config.db_range + 6)))
                color = lerp_color(t, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high)
                p_min = implot.plot_to_pixels(i + 0.5 - bar_w / 2, -self.config.db_range)
                p_max = implot.plot_to_pixels(i + 0.5 + bar_w / 2, db)
                col = color_to_u32(*color)
                col_base = color_to_u32(*lerp_color(t * 0.4, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high))
                plot_dl.add_rect_filled_multi_color(
                    imgui.ImVec2(p_min.x, min(p_min.y, p_max.y)),
                    imgui.ImVec2(p_max.x, max(p_min.y, p_max.y)),
                    col, col, col_base, col_base,
                )

            peak_col = color_to_u32(*theme.peak_marker)
            for i in range(num):
                pk = result.peak_hold_db[i]
                if pk > -self.config.db_range:
                    p1 = implot.plot_to_pixels(i + 0.5 - bar_w / 2, pk)
                    p2 = implot.plot_to_pixels(i + 0.5 + bar_w / 2, pk)
                    plot_dl.add_line(imgui.ImVec2(p1.x, p1.y), imgui.ImVec2(p2.x, p2.y), peak_col, 2.0)

            implot.pop_plot_clip_rect()
            implot.end_plot()

        # Bottom: oscilloscope (37%)
        scope_h = avail.y * 0.37
        n_wave = len(result.waveform)
        if n_wave > 0 and implot.begin_plot("##combined_scope", imgui.ImVec2(avail.x, scope_h)):
            implot.setup_axes("Sample", "Amplitude")
            implot.setup_axes_limits(0, n_wave, -1, 1, implot.Cond_.always)
            xs = np.arange(n_wave, dtype=np.float64)
            ys = result.waveform.astype(np.float64)
            implot.set_next_line_style(imgui.ImVec4(*theme.waveform_color), 1.5)
            implot.plot_line("Waveform", xs, ys)
            implot.end_plot()

        imgui.end()

    # ── Level Meters ───────────────────────────────────────────────────

    def _render_level_meters(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(140, 300), imgui.Cond_.first_use_ever)
        imgui.begin("Levels")
        avail = imgui.get_content_region_avail()
        if avail.x < 10 or avail.y < 30:
            imgui.end()
            return

        draw_list = imgui.get_window_draw_list()
        pos = imgui.get_cursor_screen_pos()

        bar_w = 28
        meter_h = avail.y - 50
        gap = 12

        if meter_h < 20:
            imgui.end()
            return

        # RMS meter
        rms_t = max(0.0, min(1.0, (result.rms_db + self.config.db_range) / self.config.db_range))
        rms_h = meter_h * rms_t
        x0 = pos.x + 10
        y_top = pos.y
        y_bot = pos.y + meter_h

        # Background
        draw_list.add_rect_filled(
            imgui.ImVec2(x0, y_top), imgui.ImVec2(x0 + bar_w, y_bot),
            color_to_u32(0.15, 0.15, 0.18, 1.0),
        )
        # Filled portion with gradient
        if rms_h > 0:
            for seg in range(int(rms_h)):
                seg_t = seg / max(meter_h, 1)
                c = lerp_color(seg_t, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high)
                y = y_bot - seg - 1
                draw_list.add_line(
                    imgui.ImVec2(x0 + 1, y), imgui.ImVec2(x0 + bar_w - 1, y),
                    color_to_u32(*c), 1.0,
                )

        draw_list.add_text(imgui.ImVec2(x0, y_bot + 4), color_to_u32(*theme.text), "RMS")

        # Peak meter
        peak_t = max(0.0, min(1.0, (result.peak_db + self.config.db_range) / self.config.db_range))
        peak_h = meter_h * peak_t
        x1 = x0 + bar_w + gap

        draw_list.add_rect_filled(
            imgui.ImVec2(x1, y_top), imgui.ImVec2(x1 + bar_w, y_bot),
            color_to_u32(0.15, 0.15, 0.18, 1.0),
        )
        if peak_h > 0:
            for seg in range(int(peak_h)):
                seg_t = seg / max(meter_h, 1)
                c = lerp_color(seg_t, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high)
                y = y_bot - seg - 1
                draw_list.add_line(
                    imgui.ImVec2(x1 + 1, y), imgui.ImVec2(x1 + bar_w - 1, y),
                    color_to_u32(*c), 1.0,
                )

        draw_list.add_text(imgui.ImVec2(x1, y_bot + 4), color_to_u32(*theme.text), "Peak")

        # dB values
        x_text = x1 + bar_w + gap
        draw_list.add_text(
            imgui.ImVec2(x_text, y_top),
            color_to_u32(*theme.text),
            f"{result.rms_db:+.1f}",
        )
        draw_list.add_text(
            imgui.ImVec2(x_text, y_top + 18),
            color_to_u32(*theme.text),
            f"{result.peak_db:+.1f}",
        )

        # dB scale markings
        for db_mark in [-60, -48, -36, -24, -12, -6, 0]:
            if db_mark < -self.config.db_range:
                continue
            mark_t = (db_mark + self.config.db_range) / self.config.db_range
            mark_y = y_bot - meter_h * mark_t
            draw_list.add_line(
                imgui.ImVec2(x0 - 4, mark_y), imgui.ImVec2(x0, mark_y),
                color_to_u32(*theme.grid), 1.0,
            )
            draw_list.add_text(
                imgui.ImVec2(x_text, mark_y - 6),
                color_to_u32(*theme.grid[:3], 0.8),
                f"{db_mark}",
            )

        imgui.dummy(avail)
        imgui.end()

    # ── FPS Overlay ────────────────────────────────────────────────────

    def _render_fps_overlay(self):
        flags = (
            imgui.WindowFlags_.no_decoration
            | imgui.WindowFlags_.always_auto_resize
            | imgui.WindowFlags_.no_focus_on_appearing
            | imgui.WindowFlags_.no_nav
            | imgui.WindowFlags_.no_move
        )
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            imgui.ImVec2(vp.work_pos.x + vp.work_size.x - 90, vp.work_pos.y + 5),
            imgui.Cond_.always,
        )
        imgui.set_next_window_bg_alpha(0.4)
        imgui.begin("##fps", None, flags)
        avg_dt = np.mean(self._fps_samples) if self._fps_samples else 1 / 60
        fps = 1.0 / max(avg_dt, 0.001)
        imgui.text(f"FPS: {fps:.0f}")
        imgui.end()

    def _update_fps(self, dt: float):
        self._fps_samples.append(dt)
        if len(self._fps_samples) > 120:
            self._fps_samples = self._fps_samples[-60:]


def _format_freq(f: float) -> str:
    if f >= 1000:
        return f"{f / 1000:.1f}k"
    return f"{f:.0f}"

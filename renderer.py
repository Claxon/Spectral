"""Renderer: all display modes using ImPlot and ImGui DrawList.

Each visualisation is split into a thin window wrapper (``_render_*``) and a
reusable ``_panel_*`` that draws the content into a given region. The wrappers
power the standalone single-visualisation modes; the COMBINED mode reuses the
same panels so the user can stack any two of them.
"""

import math
import numpy as np
from imgui_bundle import imgui, implot

from config import AppConfig, DisplayMode, ColorTheme
from dsp import DSPResult
from themes import THEMES, ThemeColors, lerp_color, color_to_u32


class Renderer:
    # Cap on points per 3D-waterfall trace, to keep the per-frame draw cheap.
    WATERFALL_MAX_POINTS = 160

    def __init__(self, config: AppConfig, instance_id: str = ""):
        self.config = config
        self._id = instance_id
        self._spectrogram_history: list[np.ndarray] = []
        self._waterfall_history: list[np.ndarray] = []    # heat-map waterfall (full spectra)
        self._waterfall3d_history: list[np.ndarray] = []  # 3D stack (band magnitudes)
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
            case DisplayMode.WATERFALL:
                self._render_waterfall(result, theme)
            case DisplayMode.WATERFALL_3D:
                self._render_waterfall3d(result, theme)
            case DisplayMode.RADIAL:
                self._render_radial(result, theme)
            case DisplayMode.OSCILLOSCOPE:
                self._render_oscilloscope(result, theme)
            case DisplayMode.COMBINED:
                self._render_combined(result, theme)

        self._render_level_meters(result, theme)

    def _draw_crosshair(self, theme: ThemeColors, x_label: str = "Freq", y_label: str = "dB",
                        x_format_fn=None):
        """Draw crosshair with labeled values at the centre. Call inside an active implot plot."""
        if not implot.is_plot_hovered():
            return

        mouse_pos = implot.get_plot_mouse_pos()
        plot_pos = imgui.get_mouse_pos()
        draw_list = implot.get_plot_draw_list()

        # Crosshair lines
        plot_limits = implot.get_plot_limits()
        cross_col = color_to_u32(*theme.text[:3], 0.45)

        p_left = implot.plot_to_pixels(plot_limits.x.min, mouse_pos.y)
        p_right = implot.plot_to_pixels(plot_limits.x.max, mouse_pos.y)
        draw_list.add_line(imgui.ImVec2(p_left.x, p_left.y),
                           imgui.ImVec2(p_right.x, p_right.y), cross_col, 1.0)

        p_top = implot.plot_to_pixels(mouse_pos.x, plot_limits.y.max)
        p_bot = implot.plot_to_pixels(mouse_pos.x, plot_limits.y.min)
        draw_list.add_line(imgui.ImVec2(p_top.x, p_top.y),
                           imgui.ImVec2(p_bot.x, p_bot.y), cross_col, 1.0)

        # Format values
        if x_format_fn:
            x_str = x_format_fn(mouse_pos.x)
        else:
            x_str = f"{mouse_pos.x:.1f}"
        y_str = f"{mouse_pos.y:.1f}"

        label = f"{x_label}: {x_str}\n{y_label}: {y_str}"
        label_size = imgui.calc_text_size(label)

        # Position label near crosshair center with slight offset
        offset_x = 12.0
        offset_y = -label_size.y - 8.0
        lx = plot_pos.x + offset_x
        ly = plot_pos.y + offset_y

        # Background box
        pad = 4.0
        bg_col = color_to_u32(*theme.background[:3], 0.85)
        draw_list.add_rect_filled(
            imgui.ImVec2(lx - pad, ly - pad),
            imgui.ImVec2(lx + label_size.x + pad, ly + label_size.y + pad),
            bg_col, 3.0,
        )
        draw_list.add_rect(
            imgui.ImVec2(lx - pad, ly - pad),
            imgui.ImVec2(lx + label_size.x + pad, ly + label_size.y + pad),
            color_to_u32(*theme.border), 3.0, 0, 1.0,
        )
        draw_list.add_text(imgui.ImVec2(lx, ly), color_to_u32(*theme.text), label)

    def _win(self, name: str) -> str:
        """Return unique window name for this instance."""
        return f"{name}##{self._id}" if self._id else name

    def _plot(self, name: str) -> str:
        """Return unique plot ID for this instance."""
        return f"{name}##{self._id}"

    # ── Panel dispatch (used by COMBINED) ──────────────────────────────

    def _render_panel(self, mode: DisplayMode, result: DSPResult,
                      theme: ThemeColors, size: imgui.ImVec2, tag: str) -> None:
        """Draw a single visualisation's content into the current cursor region.

        Assumes an imgui window is already active. ``tag`` keeps plot IDs unique
        when two panels share a window. COMBINED is not a valid sub-panel."""
        match mode:
            case DisplayMode.BAR_GRAPH:
                self._panel_bars(result, theme, size, tag)
            case DisplayMode.SMOOTH_LINE:
                self._panel_line(result, theme, size, tag)
            case DisplayMode.SPECTROGRAM:
                self._panel_spectrogram(result, theme, size, tag)
            case DisplayMode.WATERFALL:
                self._panel_waterfall(result, theme, size, tag)
            case DisplayMode.WATERFALL_3D:
                self._panel_waterfall3d(result, theme, size, tag)
            case DisplayMode.RADIAL:
                self._panel_radial(result, theme, size, tag)
            case DisplayMode.OSCILLOSCOPE:
                self._panel_scope(result, theme, size, tag)
            case _:
                self._panel_bars(result, theme, size, tag)

    # ── Bar Graph ──────────────────────────────────────────────────────

    def _render_bar_graph(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_bars(result, theme, size, "")
        imgui.end()

    def _panel_bars(self, result: DSPResult, theme: ThemeColors,
                    size: imgui.ImVec2, tag: str = ""):
        num = len(result.band_magnitudes_db)
        if num == 0:
            imgui.dummy(size)
            return

        if implot.begin_plot(self._plot(f"##bars{tag}"), imgui.ImVec2(size.x, size.y)):
            implot.setup_axes("Frequency", "dB", 0, 0)
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

            for i in range(num):
                db = result.band_magnitudes_db[i]
                t = max(0.0, min(1.0, (db + self.config.db_range) / (self.config.db_range + 6)))
                color = lerp_color(t, theme.bar_gradient_low, theme.bar_gradient_mid, theme.bar_gradient_high)

                p_min = implot.plot_to_pixels(float(i), -self.config.db_range)
                p_max = implot.plot_to_pixels(float(i + 1), db)

                col = color_to_u32(*color)
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
                    p1 = implot.plot_to_pixels(float(i), pk)
                    p2 = implot.plot_to_pixels(float(i + 1), pk)
                    plot_dl.add_line(
                        imgui.ImVec2(p1.x, p1.y),
                        imgui.ImVec2(p2.x, p2.y),
                        peak_col, 2.0,
                    )

            implot.pop_plot_clip_rect()

            self._draw_crosshair(theme, x_label="Freq", y_label="Volume (dB)",
                                 x_format_fn=lambda x: _format_freq(
                                     result.band_centers[min(max(int(x), 0), len(result.band_centers) - 1)]
                                 ) if len(result.band_centers) > 0 else None)

            implot.end_plot()

    # ── Smooth Line ────────────────────────────────────────────────────

    def _render_smooth_line(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_line(result, theme, size, "")
        imgui.end()

    def _panel_line(self, result: DSPResult, theme: ThemeColors,
                    size: imgui.ImVec2, tag: str = ""):
        num = len(result.band_magnitudes_db)
        if num == 0 or len(result.band_centers) != num:
            imgui.dummy(size)
            return

        if implot.begin_plot(self._plot(f"##line{tag}"), imgui.ImVec2(size.x, size.y)):
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

            self._draw_crosshair(theme, x_label="Freq", y_label="Volume (dB)",
                                 x_format_fn=lambda x: _format_freq(x) + " Hz")

            implot.end_plot()

    # ── Spectrogram ────────────────────────────────────────────────────

    def _render_spectrogram(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_spectrogram(result, theme, size, "")
        imgui.end()

    def _panel_spectrogram(self, result: DSPResult, theme: ThemeColors,
                           size: imgui.ImVec2, tag: str = ""):
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

        if len(self._spectrogram_history) < 2:
            imgui.dummy(size)
            return

        if implot.begin_plot(self._plot(f"##spectrogram{tag}"), imgui.ImVec2(size.x, size.y)):
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

    # ── Waterfall (SDR-style scrolling heat-map) ───────────────────────

    def _render_waterfall(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_waterfall(result, theme, size, "")
        imgui.end()

    def _panel_waterfall(self, result: DSPResult, theme: ThemeColors,
                         size: imgui.ImVec2, tag: str = ""):
        """SDR-style scrolling heat-map of the spectrum over time. Uses the same
        log-spaced band data and x-layout as the 3D waterfall, so the two line up
        column-for-column: a hot cell here is a tall ridge there. The newest row
        is at the bottom and the history scrolls upward, matching the 3D view."""
        mags = result.band_magnitudes_db
        num = len(mags)
        if num < 2:
            imgui.dummy(size)
            return

        depth = max(2, int(self.config.waterfall_depth))
        self._waterfall_history.append(mags.astype(np.float64))
        if len(self._waterfall_history) > depth:
            self._waterfall_history = self._waterfall_history[-depth:]

        if len(self._waterfall_history) < 2:
            imgui.dummy(size)
            return

        # Oldest row first → with implot drawing row 0 at the top, the newest
        # frame lands at the bottom and the history scrolls up (like the 3D).
        data = np.array(self._waterfall_history, dtype=np.float64)
        rows, cols = data.shape

        plot_flags = (int(implot.Flags_.no_legend) | int(implot.Flags_.no_mouse_text)
                      | int(implot.Flags_.no_menus))
        if implot.begin_plot(self._plot(f"##waterfall{tag}"), imgui.ImVec2(size.x, size.y), plot_flags):
            x_flags = int(implot.AxisFlags_.no_grid_lines)
            y_flags = (int(implot.AxisFlags_.no_grid_lines)
                       | int(implot.AxisFlags_.no_tick_labels)
                       | int(implot.AxisFlags_.no_tick_marks))
            implot.setup_axes("Frequency", "", x_flags, y_flags)
            # Fix the time axis to the full depth so rows keep a constant height
            # and the waterfall fills up from the bottom instead of stretching to
            # fill the screen while history accumulates.
            implot.setup_axes_limits(0, cols, 0, depth, implot.Cond_.always)

            # Frequency tick labels at the log-spaced band centres (matches the
            # bar graph / 3D waterfall axis).
            if len(result.band_centers) == cols:
                tick_count = min(12, cols)
                step = max(1, cols // tick_count)
                positions = list(range(0, cols, step))
                tick_pos = np.array(positions, dtype=np.float64) + 0.5
                tick_labels = [_format_freq(result.band_centers[i]) for i in positions]
                implot.setup_axis_ticks(implot.ImAxis_.x1, tick_pos.tolist(), tick_labels, False)

            # Same magnitude→intensity range as the bars/3D ridges so colour
            # tracks ridge height (db_range .. +6 dB). The rows occupy the bottom
            # `rows` units of the fixed 0..depth axis (newest at y≈0).
            implot.push_colormap(theme.spectrogram_colormap)
            implot.plot_heatmap(
                "##wf",
                data,
                scale_min=-self.config.db_range,
                scale_max=6.0,
                label_fmt="",
                bounds_min=implot.Point(0, 0),
                bounds_max=implot.Point(cols, rows),
            )
            implot.pop_colormap()

            self._draw_crosshair(
                theme, x_label="Freq", y_label="",
                x_format_fn=lambda x: (_format_freq(
                    result.band_centers[min(max(int(x), 0), len(result.band_centers) - 1)]
                ) + " Hz") if len(result.band_centers) > 0 else None,
            )

            implot.end_plot()

    # ── 3D Waterfall (perspective stacked spectra) ─────────────────────

    def _render_waterfall3d(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_waterfall3d(result, theme, size, "")
        imgui.end()

    def _panel_waterfall3d(self, result: DSPResult, theme: ThemeColors,
                           size: imgui.ImVec2, tag: str = ""):
        """A perspective waterfall: each frame's spectrum is drawn as a ridge,
        with newer ridges in front (bottom) and older ones receding up-and-back.
        Nearer ridges are filled solid so they occlude the ones behind, giving
        the classic hidden-line waterfall look. ``config.waterfall3d_depth``
        controls how many historical spectra are kept on screen."""
        mags = result.band_magnitudes_db
        if len(mags) < 2:
            imgui.dummy(size)
            return

        depth = max(8, int(self.config.waterfall3d_depth))
        self._waterfall3d_history.append(mags.astype(np.float64))
        if len(self._waterfall3d_history) > depth:
            self._waterfall3d_history = self._waterfall3d_history[-depth:]

        pos = imgui.get_cursor_screen_pos()
        x0, y0, w, h = pos.x, pos.y, size.x, size.y
        dl = imgui.get_window_draw_list()
        dl.push_clip_rect(imgui.ImVec2(x0, y0), imgui.ImVec2(x0 + w, y0 + h), True)

        # Panel backdrop
        dl.add_rect_filled(imgui.ImVec2(x0, y0), imgui.ImVec2(x0 + w, y0 + h),
                           color_to_u32(*theme.background[:3], 1.0))

        n = len(self._waterfall3d_history)
        skew_x = w * 0.16          # horizontal recede from front to back
        plot_w = w - skew_x
        # Size each ridge from the configured depth (not the current count) so
        # ridges keep a constant height and the stack fills up from the front
        # rather than stretching to fill the panel while history accumulates.
        trace_h = h * min(0.30, 14.0 / max(depth, 1))
        usable = h - trace_h
        rng = self.config.db_range + 6.0
        # Solid (dark) ridge body so nearer ridges hide farther ones.
        fill_col = color_to_u32(theme.background[0] * 0.5, theme.background[1] * 0.5,
                                theme.background[2] * 0.5, 1.0)

        # Draw oldest (back) first so the newest ridge ends up on top. Position
        # each ridge by its absolute age over the full depth so existing ridges
        # never shift as new frames arrive — they just march toward the back.
        for k in range(n):
            age = n - 1 - k                            # 0 = newest, grows with age
            frac_back = age / max(depth - 1, 1)        # 0 = front/newest, 1 = back/oldest
            base_x = x0 + frac_back * skew_x
            base_y = y0 + trace_h + (1.0 - frac_back) * usable

            trace = self._waterfall3d_history[k]
            m_full = len(trace)
            if m_full > self.WATERFALL_MAX_POINTS:
                idx = np.linspace(0, m_full - 1, self.WATERFALL_MAX_POINTS).astype(int)
                trace = trace[idx]
            m = len(trace)

            t = np.clip((trace + self.config.db_range) / rng, 0.0, 1.0)
            xs = base_x + (np.arange(m) / (m - 1)) * plot_w
            ys = base_y - t * trace_h

            crest = [imgui.ImVec2(float(xs[i]), float(ys[i])) for i in range(m)]

            # Filled body down to the ridge baseline (occludes ridges behind).
            poly = crest + [imgui.ImVec2(float(xs[-1]), base_y),
                            imgui.ImVec2(float(xs[0]), base_y)]
            dl.add_concave_poly_filled(poly, fill_col)

            # Crest line, coloured by mean energy and faded with depth.
            mean_t = float(np.mean(t))
            c = lerp_color(mean_t, theme.bar_gradient_low,
                           theme.bar_gradient_mid, theme.bar_gradient_high)
            depth_t = 1.0 - frac_back
            crest_col = color_to_u32(c[0], c[1], c[2], 0.25 + 0.75 * depth_t)
            dl.add_polyline(crest, crest_col, 0, 1.0 + 0.5 * depth_t)

        dl.pop_clip_rect()
        imgui.dummy(size)

    # ── Radial ─────────────────────────────────────────────────────────

    def _render_radial(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(600, 600), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_radial(result, theme, size, "")
        imgui.end()

    def _panel_radial(self, result: DSPResult, theme: ThemeColors,
                      size: imgui.ImVec2, tag: str = ""):
        num = len(result.band_magnitudes_db)
        if num == 0:
            imgui.dummy(size)
            return

        draw_list = imgui.get_window_draw_list()
        pos = imgui.get_cursor_screen_pos()

        cx = pos.x + size.x / 2
        cy = pos.y + size.y / 2
        radius = min(size.x, size.y) * 0.45
        r_min = radius * 0.30
        r_max = radius

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

    # ── Oscilloscope ───────────────────────────────────────────────────

    def _render_oscilloscope(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        size = imgui.get_content_region_avail()
        if size.x >= 10 and size.y >= 10:
            self._panel_scope(result, theme, size, "")
        imgui.end()

    def _panel_scope(self, result: DSPResult, theme: ThemeColors,
                     size: imgui.ImVec2, tag: str = ""):
        n = len(result.waveform)
        if n == 0:
            imgui.dummy(size)
            return

        if implot.begin_plot(self._plot(f"##scope{tag}"), imgui.ImVec2(size.x, size.y)):
            implot.setup_axes("Sample", "Amplitude")
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

            self._draw_crosshair(theme, x_label="Sample", y_label="Amplitude")

            implot.end_plot()

    # ── Combined (any two stacked panels) ──────────────────────────────

    def _render_combined(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(900, 600), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Spectrum Analyzer"))
        avail = imgui.get_content_region_avail()
        if avail.x < 10 or avail.y < 10:
            imgui.end()
            return

        # Split the window into two equal halves, accounting for the item spacing
        # imgui inserts between the two stacked panels.
        spacing = imgui.get_style().item_spacing.y
        panel_h = max(10.0, (avail.y - spacing) * 0.5)

        top = self.config.combined_top
        bottom = self.config.combined_bottom
        # Guard against a stale/invalid COMBINED selection in either slot.
        if top == DisplayMode.COMBINED:
            top = DisplayMode.BAR_GRAPH
        if bottom == DisplayMode.COMBINED:
            bottom = DisplayMode.OSCILLOSCOPE

        self._render_panel(top, result, theme, imgui.ImVec2(avail.x, panel_h), "top")
        self._render_panel(bottom, result, theme, imgui.ImVec2(avail.x, panel_h), "bottom")

        imgui.end()

    # ── Level Meters ───────────────────────────────────────────────────

    def _render_level_meters(self, result: DSPResult, theme: ThemeColors):
        imgui.set_next_window_size(imgui.ImVec2(140, 300), imgui.Cond_.first_use_ever)
        imgui.begin(self._win("Levels"))
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

    def _update_fps(self, dt: float):
        self._fps_samples.append(dt)
        if len(self._fps_samples) > 120:
            self._fps_samples = self._fps_samples[-60:]

    def get_fps(self) -> float:
        if not self._fps_samples:
            return 0.0
        avg_dt = np.mean(self._fps_samples)
        return 1.0 / max(avg_dt, 0.001)


def _format_freq(f: float) -> str:
    if f >= 1000:
        return f"{f / 1000:.1f}k"
    return f"{f:.0f}"

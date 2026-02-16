"""Settings window with all configurable controls."""

from imgui_bundle import imgui

from config import (
    AppConfig, DisplayMode, WindowFunction, ColorTheme, OctaveBandMode,
)
from audio_capture import AudioCapture, AudioDevice
from dsp import DSPProcessor
from themes import THEMES, apply_imgui_theme

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from license import LicenseManager


class SettingsUI:
    def __init__(self, config: AppConfig, audio: AudioCapture, dsp: DSPProcessor,
                 instance_id: str = "", license: "LicenseManager | None" = None):
        self.config = config
        self._audio = audio
        self._dsp = dsp
        self._id = instance_id
        self._license = license
        self._devices: list[AudioDevice] = []
        self._device_names: list[str] = []
        self._selected_device_idx: int = 0
        self.show_settings: bool = True
        self.request_upgrade: bool = False  # set True to open license modal

    def _uid(self, label: str) -> str:
        """Return unique widget ID for this instance."""
        return f"{label}##{self._id}" if self._id else label

    def refresh_devices(self):
        self._devices = self._audio.enumerate_devices()
        self._device_names = [d.name for d in self._devices]
        if not self._device_names:
            self._device_names = ["(No devices found)"]

    def render(self) -> bool:
        """Render settings panel. Returns True if config changed."""
        if not self.show_settings:
            return False

        changed = False

        imgui.set_next_window_size(imgui.ImVec2(340, 600), imgui.Cond_.first_use_ever)

        expanded, p_open = imgui.begin(self._uid("Settings"), True)
        if p_open is not None and not p_open:
            self.show_settings = False
            imgui.end()
            return False

        is_pro = self._license.is_pro if self._license else True

        if not is_pro:
            # Upgrade banner
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.16, 0.55, 0.94, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.22, 0.62, 1.0, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.12, 0.48, 0.85, 1.0))
            if imgui.button(self._uid("Upgrade to Pro"), imgui.ImVec2(-1, 28)):
                self.request_upgrade = True
            imgui.pop_style_color(3)
            imgui.spacing()
            imgui.separator()
            imgui.spacing()

        # ── Audio Device ──────────────────────────────────────────────
        if imgui.collapsing_header(self._uid("Audio Device"), imgui.TreeNodeFlags_.default_open):
            if imgui.button(self._uid("Refresh Devices")):
                self.refresh_devices()

            imgui.set_next_item_width(-1)
            ch, idx = imgui.combo(self._uid("##device"), self._selected_device_idx, self._device_names)
            if ch and self._devices:
                self._selected_device_idx = idx
                dev = self._devices[idx]
                self._audio.stop()
                self.config.use_loopback = dev.is_loopback
                self.config.input_device_index = dev.index
                self.config.input_device_name = dev.name
                self.config.sample_rate = int(dev.sample_rate)
                self._audio.start(dev)
                self._dsp.invalidate_caches()
                changed = True

            # Status
            if self._audio.is_running:
                dev = self._audio.current_device
                imgui.text_colored(imgui.ImVec4(0.3, 0.9, 0.4, 1.0), "Active")
                if dev:
                    imgui.same_line()
                    imgui.text_disabled(f"@ {self.config.sample_rate} Hz")
            else:
                imgui.text_colored(imgui.ImVec4(0.9, 0.3, 0.3, 1.0), "Stopped")

            imgui.separator()

        # ── Display Mode ──────────────────────────────────────────────
        if not is_pro:
            imgui.begin_disabled()
        _display_label = "Display" if is_pro else "\u2605 Display (Pro)"
        if imgui.collapsing_header(self._uid(_display_label), imgui.TreeNodeFlags_.default_open):
            dm_list = list(DisplayMode)
            dm_names = []
            for d in dm_list:
                name = d.name.replace("_", " ").title()
                if not is_pro and d != DisplayMode.BAR_GRAPH:
                    name = f"\u2605 {name} (Pro)"
                dm_names.append(name)
            dm_idx = dm_list.index(self.config.display_mode)
            imgui.text("Mode")
            imgui.same_line()
            imgui.set_next_item_width(-1)
            ch, dm_idx = imgui.combo(self._uid("##mode"), dm_idx, dm_names)
            if ch:
                self.config.display_mode = dm_list[dm_idx]
                changed = True

            # Color theme
            ct_list = list(ColorTheme)
            ct_names = [c.name.replace("_", " ").title() for c in ct_list]
            ct_idx = ct_list.index(self.config.color_theme)
            imgui.text("Theme")
            imgui.same_line()
            imgui.set_next_item_width(-1)
            ch, ct_idx = imgui.combo(self._uid("##theme"), ct_idx, ct_names)
            if ch:
                self.config.color_theme = ct_list[ct_idx]
                apply_imgui_theme(THEMES[self.config.color_theme])
                changed = True

            # dB range
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("dB Range"), self.config.db_range, 40.0, 120.0, "%.0f dB")
            if ch:
                self.config.db_range = val
                changed = True

            ch, val = imgui.checkbox(self._uid("Show FPS"), self.config.show_fps)
            if ch:
                self.config.show_fps = val

            ch, val = imgui.checkbox(self._uid("Show Grid"), self.config.show_grid)
            if ch:
                self.config.show_grid = val

            imgui.separator()

        # ── DSP Settings ──────────────────────────────────────────────
        _dsp_label = "DSP / Analysis" if is_pro else "\u2605 DSP / Analysis (Pro)"
        if imgui.collapsing_header(self._uid(_dsp_label), imgui.TreeNodeFlags_.default_open):
            # FFT Size
            fft_sizes = [512, 1024, 2048, 4096, 8192, 16384]
            fft_labels = [str(s) for s in fft_sizes]
            fft_idx = fft_sizes.index(self.config.fft_size) if self.config.fft_size in fft_sizes else 3
            imgui.text("FFT Size")
            imgui.same_line()
            imgui.set_next_item_width(-1)
            ch, fft_idx = imgui.combo(self._uid("##fft"), fft_idx, fft_labels)
            if ch:
                self.config.fft_size = fft_sizes[fft_idx]
                self._dsp.invalidate_caches()
                changed = True

            # Number of bands
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_int(self._uid("Bands"), self.config.num_bands, 8, 256)
            if ch:
                self.config.num_bands = val
                self._dsp.invalidate_caches()
                changed = True

            # Window function
            wf_list = list(WindowFunction)
            wf_names = [w.name.replace("_", " ").title() for w in wf_list]
            wf_idx = wf_list.index(self.config.window_function)
            imgui.text("Window")
            imgui.same_line()
            imgui.set_next_item_width(-1)
            ch, wf_idx = imgui.combo(self._uid("##window"), wf_idx, wf_names)
            if ch:
                self.config.window_function = wf_list[wf_idx]
                self._dsp.invalidate_caches()
                changed = True

            # Octave mode
            oct_list = list(OctaveBandMode)
            oct_names = [o.name.replace("_", " ").title() for o in oct_list]
            oct_idx = oct_list.index(self.config.octave_mode)
            imgui.text("Octave")
            imgui.same_line()
            imgui.set_next_item_width(-1)
            ch, oct_idx = imgui.combo(self._uid("##octave"), oct_idx, oct_names)
            if ch:
                self.config.octave_mode = oct_list[oct_idx]
                self._dsp.invalidate_caches()
                changed = True

            imgui.separator()

            # Smoothing
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("Smoothing"), self.config.smoothing_factor, 0.0, 0.95, "%.2f")
            if ch:
                self.config.smoothing_factor = val
                changed = True

            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_int(self._uid("Spectral Smooth"), self.config.spectral_smoothing, 1, 15)
            if ch:
                self.config.spectral_smoothing = val | 1
                changed = True

            # A-weighting
            ch, val = imgui.checkbox(self._uid("A-Weighting"), self.config.a_weighting)
            if ch:
                self.config.a_weighting = val
                self._dsp.invalidate_caches()
                changed = True

            imgui.separator()

            # Frequency range
            imgui.text("Frequency Range (Hz)")
            imgui.set_next_item_width(-1)
            ch, lo, hi = imgui.drag_float_range2(
                self._uid("##freq_range"),
                self.config.freq_min, self.config.freq_max,
                1.0, 20.0, 22050.0,
                "Min: %.0f", "Max: %.0f",
            )
            if ch:
                self.config.freq_min = max(lo, 20.0)
                self.config.freq_max = min(hi, 22050.0)
                changed = True

            imgui.separator()

        # ── Peak Hold ─────────────────────────────────────────────────
        _peak_label = "Peak Hold" if is_pro else "\u2605 Peak Hold (Pro)"
        if imgui.collapsing_header(self._uid(_peak_label)):
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("Hold Time"), self.config.peak_hold_time, 0.0, 10.0, "%.1f s")
            if ch:
                self.config.peak_hold_time = val
                changed = True

            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("Decay Rate"), self.config.peak_decay_rate, 0.01, 2.0, "%.2f dB/frame")
            if ch:
                self.config.peak_decay_rate = val
                changed = True

            imgui.separator()

        # ── Spectrogram ───────────────────────────────────────────────
        _spec_label = "Spectrogram" if is_pro else "\u2605 Spectrogram (Pro)"
        if imgui.collapsing_header(self._uid(_spec_label)):
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("History"), self.config.spectrogram_history_seconds, 1.0, 30.0, "%.1f s")
            if ch:
                self.config.spectrogram_history_seconds = val
                changed = True

        if not is_pro:
            imgui.end_disabled()

        imgui.end()
        return changed

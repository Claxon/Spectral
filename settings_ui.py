"""Settings window with all configurable controls.

The panel is built to be self-explanatory: every section header carries an icon,
display modes and themes are picked with visual buttons rather than bare combos,
and every control has a hover tooltip describing what it does.
"""

from imgui_bundle import imgui, icons_fontawesome_6 as fa

from config import (
    AppConfig, DisplayMode, WindowFunction, OctaveBandMode,
)
from audio_capture import AudioCapture, AudioDevice
from dsp import DSPProcessor

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from license import LicenseManager


# Short, human-readable description for each display mode — shown in tooltips
# and used as the button caption in the mode picker.
_DISPLAY_MODE_INFO: dict[DisplayMode, tuple[str, str, str]] = {
    #                         icon                     caption     tooltip body
    DisplayMode.BAR_GRAPH:   (fa.ICON_FA_CHART_BAR,    "Bars",
                              "Classic vertical frequency bars — low frequencies on the "
                              "left, high on the right. The default, easiest to read."),
    DisplayMode.SMOOTH_LINE: (fa.ICON_FA_CHART_LINE,   "Line",
                              "A filled, smoothed curve of the spectrum instead of "
                              "discrete bars. Cleaner look for slow-moving signals."),
    DisplayMode.SPECTROGRAM: (fa.ICON_FA_FIRE,         "Spectro",
                              "Scrolling heat-map of frequency content over time "
                              "(a waterfall). Brighter colour = more energy."),
    DisplayMode.RADIAL:      (fa.ICON_FA_BULLSEYE,     "Radial",
                              "The spectrum wrapped into a circle, with bars radiating "
                              "out from the centre. A decorative, symmetric view."),
    DisplayMode.OSCILLOSCOPE:(fa.ICON_FA_WAVE_SQUARE,  "Scope",
                              "Raw waveform / oscilloscope — shows the audio signal "
                              "itself in the time domain rather than its frequencies."),
    DisplayMode.COMBINED:    (fa.ICON_FA_LAYER_GROUP,  "Combined",
                              "Several visualisations stacked together at once for an "
                              "at-a-glance overview."),
}


class SettingsUI:
    # Accent colours used to highlight the currently-selected visual button.
    _ACCENT = imgui.ImVec4(0.16, 0.55, 0.94, 1.0)
    _ACCENT_HOVER = imgui.ImVec4(0.22, 0.62, 1.0, 1.0)
    _ACCENT_ACTIVE = imgui.ImVec4(0.12, 0.48, 0.85, 1.0)

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
        # Combined hover flags: respect the tooltip delay and still fire for
        # Pro-locked (disabled) controls so we can explain *why* they're locked.
        self._hover_flags = (
            int(imgui.HoveredFlags_.for_tooltip)
            | int(imgui.HoveredFlags_.allow_when_disabled)
        )

    def _uid(self, label: str) -> str:
        """Return unique widget ID for this instance."""
        return f"{label}##{self._id}" if self._id else label

    # ── presentation helpers ─────────────────────────────────────────────
    def _tip(self, title: str, body: str) -> None:
        """Attach a titled, word-wrapped tooltip to the item just submitted."""
        if imgui.is_item_hovered(self._hover_flags):
            imgui.begin_tooltip()
            imgui.push_text_wrap_pos(imgui.get_font_size() * 20.0)
            imgui.text_colored(self._ACCENT, title)
            imgui.separator()
            imgui.text_unformatted(body)
            imgui.pop_text_wrap_pos()
            imgui.end_tooltip()

    def _header(self, icon: str, title: str, *, default_open: bool = False,
                locked: bool = False) -> bool:
        """Collapsing section header with a leading icon (and Pro star if locked)."""
        if locked:
            label = f"{fa.ICON_FA_STAR}  {title}   (Pro)"
        else:
            label = f"{icon}  {title}"
        flags = imgui.TreeNodeFlags_.default_open if default_open else 0
        return imgui.collapsing_header(self._uid(label), flags)

    def _label(self, icon: str, text: str, tip_title: str, tip_body: str) -> None:
        """Draw an icon + caption row followed by a hoverable (?) help marker.

        The following widget should be submitted on the next line (the help
        marker does not call same_line afterwards, so imgui wraps naturally)."""
        imgui.align_text_to_frame_padding()
        imgui.text_disabled(icon)
        imgui.same_line()
        imgui.text(text)
        imgui.same_line()
        imgui.text_disabled(fa.ICON_FA_CIRCLE_QUESTION)
        self._tip(tip_title, tip_body)

    def refresh_devices(self):
        self._devices = self._audio.enumerate_devices()
        self._device_names = [d.name for d in self._devices]
        if not self._device_names:
            self._device_names = ["(No devices found)"]

    # ── individual sections ──────────────────────────────────────────────
    def _render_mode_picker(self) -> bool:
        """Visual grid of display-mode buttons. Returns True if changed."""
        changed = False
        is_pro = self._license.is_pro if self._license else True
        per_row = 3
        spacing = imgui.get_style().item_spacing.x
        avail = imgui.get_content_region_avail().x
        btn_w = (avail - spacing * (per_row - 1)) / per_row

        for i, mode in enumerate(DisplayMode):
            icon, caption, body = _DISPLAY_MODE_INFO[mode]
            if i % per_row != 0:
                imgui.same_line()

            selected = self.config.display_mode == mode
            if selected:
                imgui.push_style_color(imgui.Col_.button, self._ACCENT)
                imgui.push_style_color(imgui.Col_.button_hovered, self._ACCENT_HOVER)
                imgui.push_style_color(imgui.Col_.button_active, self._ACCENT_ACTIVE)

            if imgui.button(self._uid(f"{icon}\n{caption}##mode{i}"),
                            imgui.ImVec2(btn_w, 46)):
                self.config.display_mode = mode
                changed = True

            if selected:
                imgui.pop_style_color(3)

            locked = (not is_pro) and mode != DisplayMode.BAR_GRAPH
            tip = body + ("\n\n★ Requires Pro." if locked else "")
            self._tip(caption, tip)
        return changed

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
            imgui.push_style_color(imgui.Col_.button, self._ACCENT)
            imgui.push_style_color(imgui.Col_.button_hovered, self._ACCENT_HOVER)
            imgui.push_style_color(imgui.Col_.button_active, self._ACCENT_ACTIVE)
            if imgui.button(self._uid(f"{fa.ICON_FA_STAR}  Upgrade to Pro"),
                            imgui.ImVec2(-1, 28)):
                self.request_upgrade = True
            imgui.pop_style_color(3)
            self._tip("Unlock Pro",
                      "Enables every display mode, the DSP/analysis controls, peak "
                      "hold and the spectrogram. Click to see upgrade options.")
            imgui.spacing()
            imgui.separator()
            imgui.spacing()

        # ── Audio Device ──────────────────────────────────────────────
        if self._header(fa.ICON_FA_VOLUME_HIGH, "Audio Device", default_open=True):
            if imgui.button(self._uid(f"{fa.ICON_FA_ARROWS_ROTATE}  Refresh Devices")):
                self.refresh_devices()
            self._tip("Refresh devices",
                      "Re-scan the system for audio inputs and loopback (speaker) "
                      "outputs — use after plugging in a new mic or interface.")

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
            self._tip("Input source",
                      "Which audio source to analyse. A '[Loopback]' device captures "
                      "whatever your speakers are playing; other devices are physical "
                      "microphones or line inputs.")

            # Status
            if self._audio.is_running:
                imgui.text_colored(imgui.ImVec4(0.3, 0.9, 0.4, 1.0),
                                   f"{fa.ICON_FA_SIGNAL}  Active")
                imgui.same_line()
                imgui.text_disabled(f"@ {self.config.sample_rate} Hz")
            else:
                imgui.text_colored(imgui.ImVec4(0.9, 0.3, 0.3, 1.0),
                                   f"{fa.ICON_FA_VOLUME_XMARK}  Stopped")

            imgui.separator()

        # Everything below requires Pro — disable & star-mark the headers.
        if not is_pro:
            imgui.begin_disabled()

        # ── Display Mode ──────────────────────────────────────────────
        if self._header(fa.ICON_FA_DESKTOP, "Display",
                        default_open=True, locked=not is_pro):
            self._label(fa.ICON_FA_TV, "Mode", "Display mode",
                        "Pick how the audio is visualised. Hover a button to see what "
                        "it does; the highlighted one is active.")
            if self._render_mode_picker():
                changed = True

            imgui.spacing()
            self._label(fa.ICON_FA_GAUGE_HIGH, "Dynamic range", "Dynamic range (dB)",
                        "The loudness span shown on the meter, from the top down. A "
                        "smaller value zooms into loud signals; a larger value also "
                        "shows quiet detail (and more noise).")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("##dbrange"), self.config.db_range, 40.0, 120.0, "%.0f dB")
            if ch:
                self.config.db_range = val
                changed = True
            self._tip("Dynamic range (dB)",
                      "How many decibels of range the display covers. Typical music "
                      "sits well within 80 dB.")

            ch, val = imgui.checkbox(self._uid(f"{fa.ICON_FA_GAUGE}  Show FPS"), self.config.show_fps)
            if ch:
                self.config.show_fps = val
            self._tip("Show FPS",
                      "Overlay the rendering frame-rate in the corner of the "
                      "visualiser. Handy for spotting performance issues.")

            ch, val = imgui.checkbox(self._uid(f"{fa.ICON_FA_BORDER_ALL}  Show Grid"), self.config.show_grid)
            if ch:
                self.config.show_grid = val
            self._tip("Show grid",
                      "Draw reference grid-lines (frequency and dB scale) behind the "
                      "spectrum to make values easier to read off.")

            imgui.separator()

        # ── DSP Settings ──────────────────────────────────────────────
        if self._header(fa.ICON_FA_SLIDERS, "DSP / Analysis",
                        default_open=True, locked=not is_pro):
            # FFT Size
            fft_sizes = [512, 1024, 2048, 4096, 8192, 16384]
            fft_labels = [str(s) for s in fft_sizes]
            fft_idx = fft_sizes.index(self.config.fft_size) if self.config.fft_size in fft_sizes else 3
            self._label(fa.ICON_FA_TABLE_CELLS, "FFT Size", "FFT size (samples)",
                        "How many audio samples are analysed at once. Bigger = finer "
                        "frequency resolution but slower to react; smaller = snappier "
                        "but coarser. 4096 is a good default.")
            imgui.set_next_item_width(-1)
            ch, fft_idx = imgui.combo(self._uid("##fft"), fft_idx, fft_labels)
            if ch:
                self.config.fft_size = fft_sizes[fft_idx]
                self._dsp.invalidate_caches()
                changed = True
            self._tip("FFT size (samples)",
                      "Larger windows resolve closely-spaced frequencies (e.g. bass "
                      "notes) better, at the cost of time resolution and CPU.")

            # Number of bands
            self._label(fa.ICON_FA_BARS, "Bands", "Number of bands",
                        "How many bars/buckets the spectrum is split into for display. "
                        "More bands = more detail across the screen.")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_int(self._uid("##bands"), self.config.num_bands, 8, 256)
            if ch:
                self.config.num_bands = val
                self._dsp.invalidate_caches()
                changed = True
            self._tip("Number of bands",
                      "The count of frequency bars drawn. Purely a display choice — it "
                      "doesn't change the underlying analysis accuracy.")

            # Window function
            wf_list = list(WindowFunction)
            wf_names = [w.name.replace("_", " ").title() for w in wf_list]
            wf_idx = wf_list.index(self.config.window_function)
            self._label(fa.ICON_FA_WATER, "Window", "Window function",
                        "The shape applied to each chunk of audio before analysis to "
                        "reduce edge artefacts (spectral leakage). Hanning is a safe "
                        "all-rounder; Flat-Top is best for accurate level readings.")
            imgui.set_next_item_width(-1)
            ch, wf_idx = imgui.combo(self._uid("##window"), wf_idx, wf_names)
            if ch:
                self.config.window_function = wf_list[wf_idx]
                self._dsp.invalidate_caches()
                changed = True
            self._tip("Window function",
                      "Trade-off between frequency sharpness and amplitude accuracy. "
                      "Blackman / Blackman-Harris give cleaner peaks; Flat-Top gives "
                      "the most accurate magnitudes.")

            # Octave mode
            oct_list = list(OctaveBandMode)
            oct_names = [o.name.replace("_", " ").title() for o in oct_list]
            oct_idx = oct_list.index(self.config.octave_mode)
            self._label(fa.ICON_FA_MUSIC, "Octave", "Octave banding",
                        "Group frequencies into musical octave bands instead of a "
                        "linear split. 1/3-octave matches how we perceive pitch and is "
                        "common for acoustic measurement.")
            imgui.set_next_item_width(-1)
            ch, oct_idx = imgui.combo(self._uid("##octave"), oct_idx, oct_names)
            if ch:
                self.config.octave_mode = oct_list[oct_idx]
                self._dsp.invalidate_caches()
                changed = True
            self._tip("Octave banding",
                      "None = even linear bands. Full / Third octave bunch bars to "
                      "standard octave or 1/3-octave centre frequencies.")

            imgui.separator()

            # Smoothing
            self._label(fa.ICON_FA_BROOM, "Smoothing", "Temporal smoothing",
                        "How much each frame is blended with the previous one over "
                        "time. Higher = calmer, smoother motion; lower = more "
                        "responsive but jumpier.")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("##smoothing"), self.config.smoothing_factor, 0.0, 0.95, "%.2f")
            if ch:
                self.config.smoothing_factor = val
                changed = True
            self._tip("Temporal smoothing",
                      "0 = no averaging (instant, twitchy). Towards 0.95 the bars ease "
                      "between values for a fluid look.")

            self._label(fa.ICON_FA_FILTER, "Spectral Smooth", "Spectral smoothing",
                        "Averages neighbouring frequency bars together to tame jagged, "
                        "noisy spectra. Forced to an odd width.")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_int(self._uid("##spectral"), self.config.spectral_smoothing, 1, 15)
            if ch:
                self.config.spectral_smoothing = val | 1
                changed = True
            self._tip("Spectral smoothing",
                      "1 = off. Higher values blur across adjacent frequency bins for "
                      "a softer curve.")

            # A-weighting
            ch, val = imgui.checkbox(self._uid(f"{fa.ICON_FA_FILTER}  A-Weighting"), self.config.a_weighting)
            if ch:
                self.config.a_weighting = val
                self._dsp.invalidate_caches()
                changed = True
            self._tip("A-weighting",
                      "Applies the standard A-weighting curve, which de-emphasises very "
                      "low and very high frequencies to better match human hearing "
                      "(as used for dB(A) loudness measurements).")

            imgui.separator()

            # Frequency range
            self._label(fa.ICON_FA_RULER_HORIZONTAL, "Frequency Range (Hz)",
                        "Frequency range",
                        "The lowest and highest frequencies shown on screen. Drag each "
                        "end to zoom the display into a band of interest "
                        "(e.g. 20–200 Hz for bass).")
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
            self._tip("Frequency range (Hz)",
                      "Limits the horizontal axis. Human hearing spans roughly "
                      "20 Hz – 20 kHz; narrowing the range magnifies detail.")

            imgui.separator()

        # ── Peak Hold ─────────────────────────────────────────────────
        if self._header(fa.ICON_FA_GAUGE_HIGH, "Peak Hold", locked=not is_pro):
            self._label(fa.ICON_FA_CLOCK, "Hold Time", "Peak hold time",
                        "How long a peak marker lingers at its highest point before it "
                        "starts to fall. 0 disables peak hold.")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("##holdtime"), self.config.peak_hold_time, 0.0, 10.0, "%.1f s")
            if ch:
                self.config.peak_hold_time = val
                changed = True
            self._tip("Peak hold time",
                      "Seconds a peak stays pinned before decaying — useful for "
                      "catching brief transients.")

            self._label(fa.ICON_FA_ARROW_DOWN_WIDE_SHORT, "Decay Rate", "Peak decay rate",
                        "How quickly a held peak slides back down once it starts "
                        "falling. Higher = drops faster.")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("##decay"), self.config.peak_decay_rate, 0.01, 2.0, "%.2f dB/frame")
            if ch:
                self.config.peak_decay_rate = val
                changed = True
            self._tip("Peak decay rate",
                      "The dB the peak marker drops each frame after the hold time "
                      "elapses.")

            imgui.separator()

        # ── Spectrogram ───────────────────────────────────────────────
        if self._header(fa.ICON_FA_FIRE, "Spectrogram", locked=not is_pro):
            self._label(fa.ICON_FA_CLOCK, "History", "Spectrogram history",
                        "How many seconds of past audio the scrolling spectrogram "
                        "keeps on screen before it scrolls off.")
            imgui.set_next_item_width(-1)
            ch, val = imgui.slider_float(self._uid("##history"), self.config.spectrogram_history_seconds, 1.0, 30.0, "%.1f s")
            if ch:
                self.config.spectrogram_history_seconds = val
                changed = True
            self._tip("Spectrogram history",
                      "The length of the waterfall window in seconds — longer shows "
                      "more history but each moment is thinner.")

        if not is_pro:
            imgui.end_disabled()

        imgui.end()
        return changed

"""Spectrum Analyzer - Real-time audio spectrum visualization.

Usage: python main.py
"""

import sys
import numpy as np
from imgui_bundle import imgui, implot, immapp, hello_imgui

from config import AppConfig
from ring_buffer import RingBuffer
from audio_capture import AudioCapture
from dsp import DSPProcessor, DSPResult
from renderer import Renderer
from settings_ui import SettingsUI
from themes import THEMES, apply_imgui_theme


class SpectrumAnalyzerApp:
    def __init__(self):
        self.config = AppConfig()
        self.ring_buffer = RingBuffer(capacity=self.config.fft_size * 4, channels=1)
        self.audio = AudioCapture(self.ring_buffer, self.config)
        self.dsp = DSPProcessor(self.config)
        self.renderer = Renderer(self.config)
        self.settings_ui = SettingsUI(self.config, self.audio, self.dsp)
        self._last_result: DSPResult | None = None
        self._prev_time: float = 0.0

    def setup(self) -> None:
        """Called once after imgui/implot context is created."""
        apply_imgui_theme(THEMES[self.config.color_theme])

        # Enumerate devices and auto-start the first one
        self.settings_ui.refresh_devices()
        devices = self.audio.enumerate_devices()
        if devices:
            # Prefer loopback device if available, else first input
            loopback = [d for d in devices if d.is_loopback]
            if loopback:
                self.audio.start(loopback[0])
                # Update settings UI selection
                try:
                    idx = self.settings_ui._devices.index(loopback[0])
                    self.settings_ui._selected_device_idx = idx
                except ValueError:
                    self.audio.start(devices[0])
            else:
                self.audio.start(devices[0])

    def gui(self) -> None:
        """Called every frame."""
        t = imgui.get_time()
        dt = t - self._prev_time if self._prev_time > 0 else 1.0 / 60.0
        self._prev_time = t

        # Read audio data and run DSP
        samples = self.ring_buffer.read_latest(self.config.fft_size)
        if samples is not None:
            self._last_result = self.dsp.process(samples, dt)

        # Render visualization
        if self._last_result is not None:
            self.renderer.render(self._last_result, dt)
        else:
            self._render_waiting()

        # Settings panel
        config_changed = self.settings_ui.render()
        if config_changed:
            self._handle_config_change()

    def cleanup(self) -> None:
        """Called on exit."""
        self.audio.stop()

    def _render_waiting(self):
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin("Spectrum Analyzer")
        avail = imgui.get_content_region_avail()
        text = "Waiting for audio data..."
        text_size = imgui.calc_text_size(text)
        imgui.set_cursor_pos(imgui.ImVec2(
            (avail.x - text_size.x) / 2,
            (avail.y - text_size.y) / 2,
        ))
        imgui.text_disabled(text)
        imgui.end()

        # Still show level meters (zeroed)
        imgui.set_next_window_size(imgui.ImVec2(140, 300), imgui.Cond_.first_use_ever)
        imgui.begin("Levels")
        imgui.text_disabled("No signal")
        imgui.end()

    def _handle_config_change(self):
        """Handle config changes that need buffer or state updates."""
        needed_capacity = self.config.fft_size * 4
        if self.ring_buffer.capacity < needed_capacity:
            new_buf = RingBuffer(capacity=needed_capacity, channels=1)
            self.ring_buffer = new_buf
            self.audio.ring_buffer = new_buf


def main():
    app = SpectrumAnalyzerApp()

    runner_params = hello_imgui.RunnerParams()
    runner_params.app_window_params.window_title = "Spectrum Analyzer"
    runner_params.app_window_params.window_geometry.size = (1400, 800)
    runner_params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.no_default_window
    )
    runner_params.imgui_window_params.enable_viewports = True
    runner_params.callbacks.post_init = app.setup
    runner_params.callbacks.show_gui = app.gui
    runner_params.callbacks.before_exit = app.cleanup
    runner_params.fps_idling.enable_idling = False  # Always render, no idle

    addons = immapp.AddOnsParams()
    addons.with_implot = True

    immapp.run(runner_params, addons)


if __name__ == "__main__":
    main()

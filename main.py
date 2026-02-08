"""Spectrum Analyzer - Real-time audio spectrum visualization.

Supports multiple analyzer instances, window docking, and always-on-top mode.

Usage: python main.py
"""

import sys
import ctypes
import numpy as np
from imgui_bundle import imgui, implot, immapp, hello_imgui

from config import AppConfig, _ini_path
from ring_buffer import RingBuffer
from audio_capture import AudioCapture
from dsp import DSPProcessor, DSPResult
from renderer import Renderer
from settings_ui import SettingsUI
from themes import THEMES, apply_imgui_theme


class AnalyzerInstance:
    """A self-contained spectrum analyzer with its own audio, DSP, and rendering."""

    _next_id = 1

    def __init__(self, config: AppConfig | None = None, name: str | None = None):
        self.id = AnalyzerInstance._next_id
        AnalyzerInstance._next_id += 1
        self.name = name or f"Analyzer {self.id}"
        self._id_str = f"inst{self.id}"

        self.config = config or AppConfig()
        self.ring_buffer = RingBuffer(capacity=self.config.fft_size * 4, channels=1)
        self.audio = AudioCapture(self.ring_buffer, self.config)
        self.dsp = DSPProcessor(self.config)
        self.renderer = Renderer(self.config, self._id_str)
        self.settings_ui = SettingsUI(self.config, self.audio, self.dsp, self._id_str)
        self._last_result: DSPResult | None = None
        self.show_controls = True

    def start_default_device(self):
        """Enumerate devices and start the first available one."""
        self.settings_ui.refresh_devices()
        devices = self.audio.enumerate_devices()
        if devices:
            loopback = [d for d in devices if d.is_loopback]
            target = loopback[0] if loopback else devices[0]
            self.audio.start(target)
            try:
                idx = self.settings_ui._devices.index(target)
                self.settings_ui._selected_device_idx = idx
            except ValueError:
                pass

    def update(self, dt: float):
        """Read audio, run DSP, render visualizations."""
        samples = self.ring_buffer.read_latest(self.config.fft_size)
        if samples is not None:
            self._last_result = self.dsp.process(samples, dt)

        if self._last_result is not None:
            self.renderer.render(self._last_result, dt)
        else:
            self._render_waiting()

        if self.show_controls:
            config_changed = self.settings_ui.render()
            if config_changed:
                self._handle_config_change()
                self.config.save()

    def stop(self):
        self.audio.stop()

    def _render_waiting(self):
        win_name = f"Spectrum Analyzer##{self._id_str}"
        imgui.set_next_window_size(imgui.ImVec2(800, 400), imgui.Cond_.first_use_ever)
        imgui.begin(win_name)
        avail = imgui.get_content_region_avail()
        text = "Waiting for audio data..."
        text_size = imgui.calc_text_size(text)
        imgui.set_cursor_pos(imgui.ImVec2(
            (avail.x - text_size.x) / 2,
            (avail.y - text_size.y) / 2,
        ))
        imgui.text_disabled(text)
        imgui.end()

        lvl_name = f"Levels##{self._id_str}"
        imgui.set_next_window_size(imgui.ImVec2(140, 300), imgui.Cond_.first_use_ever)
        imgui.begin(lvl_name)
        imgui.text_disabled("No signal")
        imgui.end()

    def _handle_config_change(self):
        needed_capacity = self.config.fft_size * 4
        if self.ring_buffer.capacity < needed_capacity:
            new_buf = RingBuffer(capacity=needed_capacity, channels=1)
            self.ring_buffer = new_buf
            self.audio.ring_buffer = new_buf


class SpectrumAnalyzerApp:
    def __init__(self):
        self.instances: list[AnalyzerInstance] = []
        self._prev_time: float = 0.0
        self._always_on_top: bool = False
        self._hwnd = None
        self._show_global_fps: bool = True
        self._instances_to_remove: list[int] = []
        self._show_input_modal: bool = False
        self._modal_target_instance: AnalyzerInstance | None = None
        self._modal_devices: list = []
        self._modal_device_levels: dict[int, float] = {}
        self._first_frame: bool = True

    def setup(self) -> None:
        """Called once after imgui/implot context is created."""
        io = imgui.get_io()
        io.config_flags = io.config_flags | imgui.ConfigFlags_.docking_enable

        # Point imgui.ini to our persistent location
        io.set_ini_filename(_ini_path())

        # Load saved config
        saved_config = AppConfig.load()
        apply_imgui_theme(THEMES[saved_config.color_theme])

        self._init_native_handle()

        # Create first analyzer with saved config
        self._add_instance(saved_config)

    def gui(self) -> None:
        """Called every frame."""
        t = imgui.get_time()
        dt = t - self._prev_time if self._prev_time > 0 else 1.0 / 60.0
        self._prev_time = t

        # Build a default docked layout on first run (no imgui.ini yet)
        if self._first_frame:
            self._first_frame = False
            self._setup_default_layout()

        self._render_dockspace()
        self._render_toolbar()

        for inst in self.instances:
            inst.update(dt)

        if self._instances_to_remove:
            for inst_id in self._instances_to_remove:
                for inst in self.instances:
                    if inst.id == inst_id:
                        inst.stop()
                        self.instances.remove(inst)
                        break
            self._instances_to_remove.clear()

        if self._show_global_fps:
            self._render_fps_overlay(dt)

        # Input selection modal
        if self._show_input_modal:
            self._render_input_modal()

    def cleanup(self) -> None:
        for inst in self.instances:
            inst.config.save()
            inst.stop()

    def _add_instance(self, config: AppConfig | None = None):
        inst = AnalyzerInstance(config=config)
        inst.start_default_device()
        self.instances.append(inst)

    def _setup_default_layout(self):
        """Programmatically dock windows on first launch."""
        import os
        ini_path = _ini_path()
        if os.path.exists(ini_path):
            return  # Layout already saved, don't override

        dockspace_id = imgui.get_id("MainDockSpace")
        imgui.internal.dock_builder_remove_node(dockspace_id)
        imgui.internal.dock_builder_add_node(dockspace_id, imgui.DockNodeFlags_.none)

        vp = imgui.get_main_viewport()
        imgui.internal.dock_builder_set_node_size(dockspace_id, vp.work_size)

        # Split: right panel for settings+levels, rest for main view
        right_id = imgui.IntPtr(0)
        left_id = imgui.internal.dock_builder_split_node(
            dockspace_id, imgui.Dir_.left, 0.78, None, right_id
        )

        # Split right into top (settings) and bottom (levels)
        right_bottom_id = imgui.IntPtr(0)
        right_top_id = imgui.internal.dock_builder_split_node(
            right_id.value, imgui.Dir_.up, 0.65, None, right_bottom_id
        )

        # Dock windows
        if self.instances:
            inst = self.instances[0]
            imgui.internal.dock_builder_dock_window(f"Spectrum Analyzer##{inst._id_str}", left_id)
            imgui.internal.dock_builder_dock_window(f"Settings##{inst._id_str}", right_top_id.value)
            imgui.internal.dock_builder_dock_window(f"Levels##{inst._id_str}", right_bottom_id.value)

        imgui.internal.dock_builder_finish(dockspace_id)

    def _render_dockspace(self):
        """Create a fullscreen dockspace."""
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        imgui.set_next_window_viewport(vp.id_)

        flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_nav_focus
            | imgui.WindowFlags_.no_background
            | imgui.WindowFlags_.menu_bar
        )
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 0))
        imgui.begin("##DockSpace", None, flags)
        imgui.pop_style_var(3)

        dockspace_id = imgui.get_id("MainDockSpace")
        imgui.dock_space(dockspace_id, imgui.ImVec2(0, 0), imgui.DockNodeFlags_.passthru_central_node)

        imgui.end()

    def _render_toolbar(self):
        """Render the main menu/toolbar bar."""
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(imgui.ImVec2(vp.work_size.x, 0))

        flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_scrollbar
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.menu_bar
        )

        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(8, 4))
        imgui.begin("##Toolbar", None, flags)
        imgui.pop_style_var()

        if imgui.begin_menu_bar():
            if imgui.begin_menu("Analyzers"):
                if imgui.menu_item("Add Analyzer", "Ctrl+N", False, True)[0]:
                    self._add_instance()

                imgui.separator()

                for inst in self.instances:
                    if imgui.begin_menu(f"{inst.name} (#{inst.id})"):
                        ch, val = imgui.checkbox("Show Controls", inst.show_controls)
                        if ch:
                            inst.show_controls = val
                            inst.settings_ui.show_settings = val

                        if imgui.menu_item("Select Input Device...", "", False, True)[0]:
                            self._open_input_modal(inst)

                        if not inst.settings_ui.show_settings and inst.show_controls:
                            if imgui.menu_item("Open Settings", "", False, True)[0]:
                                inst.settings_ui.show_settings = True

                        if imgui.menu_item("Remove", "", False, len(self.instances) > 1)[0]:
                            self._instances_to_remove.append(inst.id)

                        imgui.end_menu()

                imgui.end_menu()

            if imgui.begin_menu("View"):
                ch, self._show_global_fps = imgui.checkbox("Show FPS", self._show_global_fps)
                ch, self._always_on_top = imgui.checkbox("Always on Top", self._always_on_top)
                if ch:
                    self._set_always_on_top(self._always_on_top)
                imgui.end_menu()

            imgui.same_line(imgui.get_window_width() - 120)
            if imgui.small_button("+ Add Analyzer"):
                self._add_instance()

            imgui.end_menu_bar()

        imgui.end()

    def _open_input_modal(self, inst: AnalyzerInstance):
        """Open the input device selection modal for a given analyzer."""
        self._show_input_modal = True
        self._modal_target_instance = inst
        inst.settings_ui.refresh_devices()
        self._modal_devices = inst.settings_ui._devices[:]

    def _render_input_modal(self):
        """Render a modal popup for input device selection with level bars."""
        inst = self._modal_target_instance
        if inst is None:
            self._show_input_modal = False
            return

        imgui.open_popup("Select Audio Input")

        center = imgui.get_main_viewport().get_center()
        imgui.set_next_window_pos(center, imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
        imgui.set_next_window_size(imgui.ImVec2(560, 420), imgui.Cond_.appearing)

        opened, _ = imgui.begin_popup_modal(
            "Select Audio Input", None,
            imgui.WindowFlags_.no_resize | imgui.WindowFlags_.no_scrollbar
        )
        if not opened:
            self._show_input_modal = False
            return

        imgui.text("Choose an audio input device:")
        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        devices = self._modal_devices
        current_idx = inst.settings_ui._selected_device_idx

        imgui.begin_child("##device_list", imgui.ImVec2(0, -40), child_flags=imgui.ChildFlags_.borders)

        for i, dev in enumerate(devices):
            is_selected = (i == current_idx)

            # Determine icon/type label
            if dev.is_loopback:
                type_label = "LOOPBACK"
                type_color = imgui.ImVec4(0.3, 0.7, 1.0, 1.0)
            else:
                type_label = "INPUT"
                type_color = imgui.ImVec4(0.3, 0.9, 0.4, 1.0)

            imgui.push_id(i)

            # Selectable row area
            cursor_y = imgui.get_cursor_pos_y()
            row_height = 48.0
            selected_changed, _ = imgui.selectable(
                f"##dev_{i}", is_selected,
                imgui.SelectableFlags_.allow_double_click,
                imgui.ImVec2(0, row_height),
            )

            if selected_changed:
                # Switch device
                inst.settings_ui._selected_device_idx = i
                inst.audio.stop()
                inst.config.use_loopback = dev.is_loopback
                inst.config.input_device_index = dev.index
                inst.config.sample_rate = int(dev.sample_rate)
                inst.audio.start(dev)
                inst.dsp.invalidate_caches()
                inst.config.save()
                current_idx = i

                if imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
                    self._show_input_modal = False
                    imgui.close_current_popup()

            # Draw content over the selectable
            imgui.set_cursor_pos_y(cursor_y + 4)
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + 8)

            # Type badge
            imgui.text_colored(type_color, f"[{type_label}]")
            imgui.same_line()

            # Device name (strip prefix for cleaner display)
            display_name = dev.name
            for prefix in ("[Input] ", "[Loopback] "):
                if display_name.startswith(prefix):
                    display_name = display_name[len(prefix):]
                    break
            imgui.text(display_name)

            # Second line: sample rate + host API + level bar
            imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + 8)
            imgui.text_disabled(f"{int(dev.sample_rate)} Hz  |  {dev.host_api}  |  {dev.channels}ch")

            # Level indicator bar (horizontal) on the right side
            if is_selected and inst.audio.is_running:
                # Get current audio level
                samples = inst.ring_buffer.read_latest(1024)
                if samples is not None:
                    rms = float(np.sqrt(np.mean(samples ** 2)))
                    level_db = 20.0 * np.log10(max(rms, 1e-10))
                    level_t = max(0.0, min(1.0, (level_db + 60.0) / 60.0))
                else:
                    level_t = 0.0

                draw_list = imgui.get_window_draw_list()
                bar_width = 120.0
                bar_height = 6.0
                screen_pos = imgui.get_cursor_screen_pos()
                bar_x = screen_pos.x + 8
                bar_y = screen_pos.y - 4

                # Background
                draw_list.add_rect_filled(
                    imgui.ImVec2(bar_x, bar_y),
                    imgui.ImVec2(bar_x + bar_width, bar_y + bar_height),
                    imgui.get_color_u32(imgui.ImVec4(0.2, 0.2, 0.2, 1.0)),
                    2.0,
                )
                # Filled portion
                if level_t > 0:
                    r = min(1.0, level_t * 2.0)
                    g = min(1.0, (1.0 - level_t) * 2.0)
                    draw_list.add_rect_filled(
                        imgui.ImVec2(bar_x, bar_y),
                        imgui.ImVec2(bar_x + bar_width * level_t, bar_y + bar_height),
                        imgui.get_color_u32(imgui.ImVec4(r, g, 0.1, 1.0)),
                        2.0,
                    )

            imgui.set_cursor_pos_y(cursor_y + row_height + 2)
            imgui.pop_id()

        imgui.end_child()

        imgui.spacing()
        if imgui.button("Close", imgui.ImVec2(80, 0)):
            self._show_input_modal = False
            imgui.close_current_popup()
        imgui.same_line()
        if imgui.button("Refresh", imgui.ImVec2(80, 0)):
            inst.settings_ui.refresh_devices()
            self._modal_devices = inst.settings_ui._devices[:]

        imgui.end_popup()

    def _render_fps_overlay(self, dt: float):
        flags = (
            imgui.WindowFlags_.no_decoration
            | imgui.WindowFlags_.always_auto_resize
            | imgui.WindowFlags_.no_focus_on_appearing
            | imgui.WindowFlags_.no_nav
            | imgui.WindowFlags_.no_move
        )
        vp = imgui.get_main_viewport()
        imgui.set_next_window_pos(
            imgui.ImVec2(vp.work_pos.x + vp.work_size.x - 90, vp.work_pos.y + 25),
            imgui.Cond_.always,
        )
        imgui.set_next_window_bg_alpha(0.4)
        imgui.begin("##global_fps", None, flags)
        fps = 1.0 / max(dt, 0.001)
        imgui.text(f"FPS: {fps:.0f}")
        imgui.text(f"x{len(self.instances)}")
        imgui.end()

    def _init_native_handle(self):
        """Get the Win32 HWND for always-on-top support."""
        try:
            self._hwnd = ctypes.windll.user32.FindWindowW(None, "Spectrum Analyzer")
        except Exception as e:
            print(f"Could not get native window handle: {e}")
            self._hwnd = None

    def _set_always_on_top(self, on_top: bool):
        """Toggle always-on-top using Win32 API."""
        if self._hwnd is None:
            try:
                self._hwnd = ctypes.windll.user32.FindWindowW(None, "Spectrum Analyzer")
            except Exception:
                pass

        if self._hwnd:
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            flag = HWND_TOPMOST if on_top else HWND_NOTOPMOST
            ctypes.windll.user32.SetWindowPos(
                self._hwnd, flag, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE,
            )


def main():
    app = SpectrumAnalyzerApp()

    runner_params = hello_imgui.RunnerParams()
    runner_params.app_window_params.window_title = "Spectrum Analyzer"
    runner_params.app_window_params.window_geometry.size = (1400, 800)
    runner_params.app_window_params.borderless = True
    runner_params.app_window_params.borderless_movable = True
    runner_params.app_window_params.borderless_resizable = True
    runner_params.app_window_params.borderless_closable = True
    runner_params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.no_default_window
    )
    runner_params.imgui_window_params.enable_viewports = True
    runner_params.callbacks.post_init = app.setup
    runner_params.callbacks.show_gui = app.gui
    runner_params.callbacks.before_exit = app.cleanup
    runner_params.fps_idling.enable_idling = False

    # Use our own ini file path (set in setup callback after context creation)
    runner_params.ini_folder_type = hello_imgui.IniFolderType.current_folder

    addons = immapp.AddOnsParams()
    addons.with_implot = True

    immapp.run(runner_params, addons)


if __name__ == "__main__":
    main()

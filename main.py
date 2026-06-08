"""Spectrum Analyzer - Real-time audio spectrum visualization.

Supports multiple analyzer instances, window docking, and always-on-top mode.

Usage: python main.py
"""

import sys
import time
import ctypes
import math
import numpy as np
from imgui_bundle import imgui, implot, immapp, hello_imgui

from config import AppConfig, DisplayMode, _ini_path
from ring_buffer import RingBuffer
from audio_capture import AudioCapture, DeviceLevelMonitor
from dsp import DSPProcessor, DSPResult
from renderer import Renderer
from settings_ui import SettingsUI
from themes import THEMES, apply_imgui_theme
from license import LicenseManager, PURCHASE_URL

# Bump this when the built-in default window layout changes, to force a one-time
# reset of users' saved layout so they pick up the new arrangement.
LAYOUT_VERSION = 1


class AnalyzerInstance:
    """A self-contained spectrum analyzer with its own audio, DSP, and rendering."""

    _next_id = 1

    def __init__(self, config: AppConfig | None = None, name: str | None = None,
                 license: LicenseManager | None = None):
        self.id = AnalyzerInstance._next_id
        AnalyzerInstance._next_id += 1
        self.name = name or f"Analyzer {self.id}"
        self._id_str = f"inst{self.id}"
        self._license = license

        self.config = config or AppConfig()
        self.ring_buffer = RingBuffer(capacity=self.config.fft_size * 4, channels=1)
        self.audio = AudioCapture(self.ring_buffer, self.config)
        self.dsp = DSPProcessor(self.config)
        self.renderer = Renderer(self.config, self._id_str)
        self.settings_ui = SettingsUI(self.config, self.audio, self.dsp, self._id_str, license)
        self._last_result: DSPResult | None = None
        self.show_controls = True

    def start_default_device(self):
        """Enumerate devices and start the saved device, or first available."""
        self.settings_ui.refresh_devices()
        devices = self.audio.enumerate_devices()
        if not devices:
            return

        target = None

        # Try to restore previously saved device by name
        saved_name = self.config.input_device_name
        if saved_name:
            for d in devices:
                if d.name == saved_name:
                    target = d
                    break

        # Fallback: first loopback, then first device
        if target is None:
            loopback = [d for d in devices if d.is_loopback]
            target = loopback[0] if loopback else devices[0]

        self.config.input_device_name = target.name
        self.config.use_loopback = target.is_loopback
        self.config.input_device_index = target.index
        self.config.sample_rate = int(target.sample_rate)
        self.audio.start(target)
        self.config.save()
        try:
            idx = self.settings_ui._devices.index(target)
            self.settings_ui._selected_device_idx = idx
        except ValueError:
            pass

    def update(self, dt: float):
        """Read audio, run DSP, render visualizations."""
        # Enforce free mode restrictions
        if self._license and not self._license.is_pro:
            if self.config.display_mode != DisplayMode.BAR_GRAPH:
                self.config.display_mode = DisplayMode.BAR_GRAPH

        samples = self.ring_buffer.read_latest(self.config.fft_size)
        if samples is not None:
            self._last_result = self.dsp.process(samples, dt)

        if self._last_result is not None:
            self.renderer.render(self._last_result, dt)
        else:
            self._render_waiting()

        if self.show_controls:
            config_changed = self.settings_ui.render()
            if self.settings_ui.request_upgrade:
                self.settings_ui.request_upgrade = False
                # Signal to app to open license modal
                self._request_upgrade = True
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
        self._device_level_monitor = DeviceLevelMonitor()
        self._first_frame: bool = True
        self._toolbar_height: float = 0.0
        self._force_default_layout: bool = False
        self._pending_layout_save: int = 0
        self._dockspace_id: int = 0
        self._license = LicenseManager()
        self._show_license_modal: bool = False
        self._license_key_buf: str = ""
        self._license_modal_open_time: float = 0.0

        # Splash screen
        self._splash_active: bool = True
        self._splash_start_time: float = 0.0
        self._splash_duration: float = 2.5  # seconds

    def setup(self) -> None:
        """Called once after imgui/implot context is created."""
        io = imgui.get_io()
        io.config_flags = io.config_flags | imgui.ConfigFlags_.docking_enable

        # Persist the imgui layout to a fixed file (imgui auto-saves the docking
        # arrangement here). hello_imgui additionally persists the OS window
        # geometry (restore_previous_geometry, configured in main()).
        io.set_ini_filename(_ini_path())

        # Decide whether to rebuild the built-in default layout this run (first
        # run, or after a LAYOUT_VERSION bump); otherwise the saved layout loads.
        self._force_default_layout = self._layout_should_reset()

        # Load saved config
        saved_config = AppConfig.load()
        apply_imgui_theme(THEMES[saved_config.color_theme])

        self._init_native_handle()
        self._license.validate_on_startup()
        self._splash_start_time = time.time()

        # Create first analyzer with saved config
        self._add_instance(saved_config)

    def gui(self) -> None:
        """Called every frame."""
        t = imgui.get_time()
        dt = t - self._prev_time if self._prev_time > 0 else 1.0 / 60.0
        self._prev_time = t

        # Splash screen overlay
        if self._splash_active:
            elapsed = time.time() - self._splash_start_time
            if elapsed >= self._splash_duration:
                self._splash_active = False
            else:
                self._render_splash(elapsed)
                return  # Don't render normal UI while splash is active

        self._render_toolbar()
        self._render_dockspace()

        for inst in self.instances:
            inst.update(dt)
            if getattr(inst, '_request_upgrade', False):
                inst._request_upgrade = False
                self._show_license_modal = True

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

        # License activation modal
        if self._show_license_modal:
            self._render_license_modal()

        # Force-persist a freshly built default layout once its windows have
        # docked (or at the latest when the countdown elapses), so it survives
        # even a very short first session, before imgui's auto-save would fire.
        if self._pending_layout_save > 0:
            self._pending_layout_save -= 1
            docked = False
            try:
                node = imgui.internal.dock_builder_get_node(self._dockspace_id)
                docked = node is not None and node.count_node_with_windows > 0
            except Exception:
                docked = False
            if docked or self._pending_layout_save == 0:
                try:
                    imgui.save_ini_settings_to_disk(_ini_path())
                except Exception:
                    pass
                self._pending_layout_save = 0

    def cleanup(self) -> None:
        self._device_level_monitor.stop()
        for inst in self.instances:
            inst.config.save()
            inst.stop()

    def _add_instance(self, config: AppConfig | None = None):
        inst = AnalyzerInstance(config=config, license=self._license)
        inst.start_default_device()
        self.instances.append(inst)

    def _layout_should_reset(self) -> bool:
        """Return True when the built-in default layout should be (re)built this
        run: first run, or after LAYOUT_VERSION advanced. Persists a version
        marker so subsequent runs restore the user's saved layout instead."""
        import os
        try:
            marker = os.path.join(os.path.dirname(_ini_path()), "layout.version")
            current = 0
            if os.path.exists(marker):
                with open(marker, "r") as f:
                    current = int((f.read().strip() or "0"))
            if current < LAYOUT_VERSION:
                with open(marker, "w") as f:
                    f.write(str(LAYOUT_VERSION))
                return True
        except Exception:
            pass
        return False

    def _setup_default_layout(self, dockspace_id):
        """Programmatically dock windows into the main dockspace. dockspace_id
        MUST be the id used by dock_space() in _render_dockspace, computed in the
        same window scope (otherwise the layout targets a phantom node)."""
        imgui.internal.dock_builder_remove_node(dockspace_id)
        imgui.internal.dock_builder_add_node(
            dockspace_id, imgui.internal.DockNodeFlagsPrivate_.dock_space
        )

        vp = imgui.get_main_viewport()
        imgui.internal.dock_builder_set_node_size(dockspace_id, vp.work_size)

        # Split: right panel for settings+levels, rest for main view
        split_main = imgui.internal.dock_builder_split_node(
            dockspace_id, imgui.Dir_.left, 0.78
        )
        left_id = split_main.id_at_dir
        right_id = split_main.id_at_opposite_dir

        # Split right into top (settings) and bottom (levels)
        split_right = imgui.internal.dock_builder_split_node(
            right_id, imgui.Dir_.up, 0.65
        )
        right_top_id = split_right.id_at_dir
        right_bottom_id = split_right.id_at_opposite_dir

        # Dock windows
        if self.instances:
            inst = self.instances[0]
            imgui.internal.dock_builder_dock_window(f"Spectrum Analyzer##{inst._id_str}", left_id)
            imgui.internal.dock_builder_dock_window(f"Settings##{inst._id_str}", right_top_id)
            imgui.internal.dock_builder_dock_window(f"Levels##{inst._id_str}", right_bottom_id)

        imgui.internal.dock_builder_finish(dockspace_id)

    def _render_dockspace(self):
        """Create a fullscreen dockspace."""
        vp = imgui.get_main_viewport()
        offset_y = self._toolbar_height
        imgui.set_next_window_pos(imgui.ImVec2(vp.work_pos.x, vp.work_pos.y + offset_y))
        imgui.set_next_window_size(imgui.ImVec2(vp.work_size.x, vp.work_size.y - offset_y))
        imgui.set_next_window_viewport(vp.id_)

        flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_nav_focus
            | imgui.WindowFlags_.no_background
        )
        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0, 0))
        imgui.begin("##DockSpace", None, flags)
        imgui.pop_style_var(3)

        dockspace_id = imgui.get_id("MainDockSpace")
        self._dockspace_id = dockspace_id
        # On the first frame, (re)build the default layout if needed, using THIS
        # dockspace_id so the dock-builder targets the same node dock_space()
        # submits below. Rebuild when forced (version bump) OR when no real
        # layout was restored (fresh run, or a prior session that never saved
        # one) — detected from the live dock node. This self-heals: the user
        # never ends up with the analyzer floating in a separate window by
        # default, regardless of ini save timing.
        if self._first_frame:
            self._first_frame = False
            try:
                node = imgui.internal.dock_builder_get_node(dockspace_id)
            except Exception:
                node = None
            no_layout = (node is None) or (not node.is_split_node())
            if self._force_default_layout or no_layout:
                self._setup_default_layout(dockspace_id)
                # Persist the freshly built default as soon as the windows have
                # actually docked (checked in the gui() tick), so it survives even
                # a very short session, before imgui's periodic auto-save fires.
                # Value is a max-frames budget; the save happens earlier once the
                # dock node reports docked windows.
                self._pending_layout_save = 30
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

        is_pro = self._license.is_pro

        if imgui.begin_menu_bar():
            if imgui.begin_menu("Analyzers"):
                if imgui.menu_item("Add Analyzer", "Ctrl+N", False, is_pro)[0]:
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

            if imgui.begin_menu("License"):
                if is_pro:
                    imgui.text_colored(imgui.ImVec4(0.3, 0.9, 0.4, 1.0), "Pro License Active")
                    imgui.separator()
                    if imgui.menu_item("Manage License...", "", False, True)[0]:
                        self._show_license_modal = True
                else:
                    imgui.text_disabled("Free Mode")
                    imgui.separator()
                    if imgui.menu_item("Enter License Key...", "", False, True)[0]:
                        self._show_license_modal = True
                    if imgui.menu_item("Buy Pro License (15 GBP)", "", False, True)[0]:
                        import webbrowser
                        webbrowser.open(PURCHASE_URL)
                imgui.end_menu()

            # Right-aligned buttons
            if is_pro:
                imgui.same_line(imgui.get_window_width() - 120)
                if imgui.small_button("+ Add Analyzer"):
                    self._add_instance()
            else:
                imgui.same_line(imgui.get_window_width() - 140)
                imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.16, 0.55, 0.94, 1.0))
                imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.22, 0.62, 1.0, 1.0))
                imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.12, 0.48, 0.85, 1.0))
                if imgui.small_button("Upgrade to Pro"):
                    self._show_license_modal = True
                imgui.pop_style_color(3)

            imgui.end_menu_bar()

        self._toolbar_height = imgui.get_window_height()
        imgui.end()

    def _open_input_modal(self, inst: AnalyzerInstance):
        """Open the input device selection modal for a given analyzer."""
        self._show_input_modal = True
        self._modal_target_instance = inst
        inst.settings_ui.refresh_devices()
        self._modal_devices = inst.settings_ui._devices[:]
        # Start monitoring levels on all devices
        self._device_level_monitor.start(self._modal_devices)

    def _close_input_modal(self):
        """Clean up when closing the input device modal."""
        self._show_input_modal = False
        self._device_level_monitor.stop()

    def _render_input_modal(self):
        """Render a modal popup for input device selection with tabs and level meters."""
        inst = self._modal_target_instance
        if inst is None:
            self._close_input_modal()
            return

        imgui.open_popup("Select Audio Device")

        center = imgui.get_main_viewport().get_center()
        imgui.set_next_window_pos(center, imgui.Cond_.appearing, imgui.ImVec2(0.5, 0.5))
        imgui.set_next_window_size(imgui.ImVec2(700, 500), imgui.Cond_.appearing)

        opened, _ = imgui.begin_popup_modal(
            "Select Audio Device", None,
            imgui.WindowFlags_.no_resize
        )
        if not opened:
            self._close_input_modal()
            return

        devices = self._modal_devices
        current_idx = inst.settings_ui._selected_device_idx

        # Split devices into tabs
        input_devices = [(i, d) for i, d in enumerate(devices) if not d.is_loopback]
        output_devices = [(i, d) for i, d in enumerate(devices) if d.is_loopback]

        imgui.text_disabled("Click to select. Double-click to select and close.")
        imgui.spacing()

        if imgui.begin_tab_bar("##device_tabs"):
            if imgui.begin_tab_item(f"Inputs ({len(input_devices)})")[0]:
                self._render_device_table(inst, input_devices, current_idx, "##input_table")
                imgui.end_tab_item()
            if imgui.begin_tab_item(f"Outputs / Loopback ({len(output_devices)})")[0]:
                self._render_device_table(inst, output_devices, current_idx, "##output_table")
                imgui.end_tab_item()
            imgui.end_tab_bar()

        # Footer buttons
        imgui.spacing()
        button_width = 100.0
        avail = imgui.get_content_region_avail()
        imgui.set_cursor_pos_x(imgui.get_cursor_pos_x() + avail.x - button_width * 2 - 8)
        if imgui.button("Refresh", imgui.ImVec2(button_width, 0)):
            self._device_level_monitor.stop()
            inst.settings_ui.refresh_devices()
            self._modal_devices = inst.settings_ui._devices[:]
            self._device_level_monitor.start(self._modal_devices)
        imgui.same_line()
        if imgui.button("Close", imgui.ImVec2(button_width, 0)):
            self._close_input_modal()
            imgui.close_current_popup()

        imgui.end_popup()

    def _render_device_table(self, inst: AnalyzerInstance,
                             device_list: list[tuple[int, 'AudioDevice']],
                             current_idx: int, table_id: str):
        """Render a multi-column device table with live level meters."""
        from audio_capture import AudioDevice

        child_h = imgui.get_content_region_avail().y - 40
        imgui.begin_child(f"##child{table_id}", imgui.ImVec2(0, child_h),
                          child_flags=imgui.ChildFlags_.borders)

        table_flags = (
            imgui.TableFlags_.row_bg
            | imgui.TableFlags_.borders_inner_v
            | imgui.TableFlags_.scroll_y
            | imgui.TableFlags_.sizing_stretch_prop
        )

        if imgui.begin_table(table_id, 4, table_flags):
            imgui.table_setup_column("Name", imgui.TableColumnFlags_.width_stretch, 3.0)
            imgui.table_setup_column("Level", imgui.TableColumnFlags_.width_stretch, 1.5)
            imgui.table_setup_column("Sample Rate", imgui.TableColumnFlags_.width_fixed, 80.0)
            imgui.table_setup_column("Channels", imgui.TableColumnFlags_.width_fixed, 65.0)
            imgui.table_headers_row()

            for list_idx, (dev_idx, dev) in enumerate(device_list):
                is_selected = (dev_idx == current_idx)
                imgui.push_id(dev_idx)
                imgui.table_next_row()

                # ── Column 0: Name ──
                imgui.table_set_column_index(0)
                selected_changed, _ = imgui.selectable(
                    f"##sel_{dev_idx}", is_selected,
                    imgui.SelectableFlags_.span_all_columns
                    | imgui.SelectableFlags_.allow_double_click,
                    imgui.ImVec2(0, 24),
                )

                if selected_changed:
                    inst.settings_ui._selected_device_idx = dev_idx
                    inst.audio.stop()
                    inst.config.use_loopback = dev.is_loopback
                    inst.config.input_device_index = dev.index
                    inst.config.input_device_name = dev.name
                    inst.config.sample_rate = int(dev.sample_rate)
                    inst.audio.start(dev)
                    inst.dsp.invalidate_caches()
                    inst.config.save()
                    current_idx = dev_idx

                    if imgui.is_mouse_double_clicked(imgui.MouseButton_.left):
                        self._close_input_modal()
                        imgui.close_current_popup()

                # Draw device name over the selectable
                imgui.same_line(0, 0)
                display_name = dev.name
                for prefix in ("[Input] ", "[Loopback] "):
                    if display_name.startswith(prefix):
                        display_name = display_name[len(prefix):]
                        break
                # Truncate long names
                if len(display_name) > 40:
                    display_name = display_name[:37] + "..."
                if is_selected:
                    imgui.text_colored(imgui.ImVec4(0.4, 0.9, 0.5, 1.0), display_name)
                else:
                    imgui.text(display_name)

                # ── Column 1: Level meter ──
                imgui.table_set_column_index(1)

                # Get level from monitor (all devices updating simultaneously)
                if is_selected and inst.audio.is_running:
                    # For the active device, read from main ring buffer (more accurate)
                    samples = inst.ring_buffer.read_latest(1024)
                    if samples is not None:
                        rms = float(np.sqrt(np.mean(samples ** 2)))
                        level_db = 20.0 * np.log10(max(rms, 1e-10))
                        level_t = max(0.0, min(1.0, (level_db + 60.0) / 60.0))
                    else:
                        level_t = 0.0
                else:
                    level_t = self._device_level_monitor.get_level(dev.index)

                # Draw the level bar
                bar_width = max(20.0, imgui.get_content_region_avail().x - 4)
                bar_height = 10.0
                screen_pos = imgui.get_cursor_screen_pos()
                imgui.dummy(imgui.ImVec2(bar_width, bar_height))
                draw_list = imgui.get_window_draw_list()
                bx, by = screen_pos.x, screen_pos.y

                # Background
                draw_list.add_rect_filled(
                    imgui.ImVec2(bx, by),
                    imgui.ImVec2(bx + bar_width, by + bar_height),
                    imgui.get_color_u32(imgui.ImVec4(0.15, 0.15, 0.18, 1.0)),
                    2.0,
                )
                # Filled portion with gradient
                if level_t > 0.01:
                    fill_w = bar_width * level_t
                    r = min(1.0, level_t * 2.0)
                    g = min(1.0, (1.0 - level_t) * 2.0)
                    draw_list.add_rect_filled(
                        imgui.ImVec2(bx, by),
                        imgui.ImVec2(bx + fill_w, by + bar_height),
                        imgui.get_color_u32(imgui.ImVec4(r, g, 0.15, 1.0)),
                        2.0,
                    )

                # ── Column 2: Sample Rate ──
                imgui.table_set_column_index(2)
                imgui.text(f"{int(dev.sample_rate)} Hz")

                # ── Column 3: Channels ──
                imgui.table_set_column_index(3)
                ch_label = "Mono" if dev.channels == 1 else "Stereo" if dev.channels == 2 else f"{dev.channels}ch"
                imgui.text(ch_label)

                imgui.pop_id()

            imgui.end_table()

        imgui.end_child()

    def _render_license_modal(self):
        """Render the license activation/management modal with shrink animation."""
        imgui.open_popup("License")

        center = imgui.get_main_viewport().get_center()

        # Animate: start large and shrink to target over 0.5s
        if self._license_modal_open_time == 0.0:
            self._license_modal_open_time = time.time()

        anim_elapsed = time.time() - self._license_modal_open_time
        anim_duration = 0.5
        anim_t = min(1.0, anim_elapsed / anim_duration)
        # Ease-out cubic
        ease_t = 1.0 - (1.0 - anim_t) ** 3

        target_w = 480.0
        start_w = 720.0
        current_w = start_w + (target_w - start_w) * ease_t

        target_h = 220.0
        start_h = 400.0
        current_h = start_h + (target_h - start_h) * ease_t

        imgui.set_next_window_pos(center, imgui.Cond_.always, imgui.ImVec2(0.5, 0.5))
        imgui.set_next_window_size(imgui.ImVec2(current_w, 0), imgui.Cond_.always)

        opened, _ = imgui.begin_popup_modal("License", None, imgui.WindowFlags_.always_auto_resize)
        if not opened:
            self._show_license_modal = False
            self._license_modal_open_time = 0.0
            return

        is_pro = self._license.is_pro

        if is_pro:
            imgui.text_colored(imgui.ImVec4(0.3, 0.9, 0.4, 1.0), "Pro License Active")
            imgui.spacing()
            imgui.separator()
            imgui.spacing()

            if self._license.status_message:
                imgui.text_disabled(self._license.status_message)
                imgui.spacing()

            imgui.begin_disabled(self._license.is_busy)
            if imgui.button("Deactivate License", imgui.ImVec2(-1, 0)):
                self._license.deactivate()
            imgui.end_disabled()
        else:
            imgui.text("Enter your license key to unlock Pro features:")
            imgui.spacing()

            imgui.set_next_item_width(-1)
            changed, self._license_key_buf = imgui.input_text(
                "##license_key", self._license_key_buf, imgui.InputTextFlags_.none,
            )

            imgui.spacing()

            if self._license.status_message:
                if "Error" in self._license.status_message or "invalid" in self._license.status_message.lower():
                    imgui.text_colored(imgui.ImVec4(0.9, 0.3, 0.3, 1.0), self._license.status_message)
                elif "Checking" in self._license.status_message:
                    imgui.text_disabled(self._license.status_message)
                else:
                    imgui.text(self._license.status_message)
                imgui.spacing()

            has_key = bool(self._license_key_buf.strip())
            imgui.begin_disabled(self._license.is_busy or not has_key)
            if imgui.button("Activate", imgui.ImVec2(120, 0)):
                self._license.activate(self._license_key_buf)
            imgui.end_disabled()

            imgui.same_line()

            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.16, 0.55, 0.94, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.22, 0.62, 1.0, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.12, 0.48, 0.85, 1.0))
            if imgui.button("Buy License (15 GBP)", imgui.ImVec2(-1, 0)):
                import webbrowser
                webbrowser.open(PURCHASE_URL)
            imgui.pop_style_color(3)

        imgui.spacing()
        imgui.separator()
        imgui.spacing()

        if imgui.button("Close", imgui.ImVec2(-1, 0)):
            self._show_license_modal = False
            self._license_modal_open_time = 0.0
            imgui.close_current_popup()

        imgui.end_popup()

    def _render_splash(self, elapsed: float):
        """Render an animated splash screen overlay."""
        vp = imgui.get_main_viewport()
        progress = elapsed / self._splash_duration  # 0..1

        # Fade: in for first 20%, hold, out for last 30%
        if progress < 0.2:
            alpha = progress / 0.2
        elif progress > 0.7:
            alpha = 1.0 - (progress - 0.7) / 0.3
        else:
            alpha = 1.0
        alpha = max(0.0, min(1.0, alpha))

        # Full-screen overlay
        flags = (
            imgui.WindowFlags_.no_decoration
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_nav
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.no_bring_to_front_on_focus
        )
        imgui.set_next_window_pos(vp.work_pos)
        imgui.set_next_window_size(vp.work_size)
        imgui.set_next_window_bg_alpha(0.0)
        imgui.begin("##splash", None, flags)

        draw_list = imgui.get_window_draw_list()
        x0, y0 = vp.work_pos.x, vp.work_pos.y
        w, h = vp.work_size.x, vp.work_size.y

        # Background gradient
        bg_alpha = int(alpha * 240)
        top_col = imgui.get_color_u32(imgui.ImVec4(0.06, 0.06, 0.12, alpha * 0.95))
        bot_col = imgui.get_color_u32(imgui.ImVec4(0.02, 0.02, 0.06, alpha * 0.95))
        draw_list.add_rect_filled_multi_color(
            imgui.ImVec2(x0, y0), imgui.ImVec2(x0 + w, y0 + h),
            top_col, top_col, bot_col, bot_col,
        )

        cx = x0 + w / 2
        cy = y0 + h / 2

        # Animated spectrum bars behind the title
        num_bars = 32
        bar_region_w = min(500, w * 0.6)
        bar_w = bar_region_w / num_bars * 0.75
        bar_gap = bar_region_w / num_bars
        max_bar_h = 120.0

        for i in range(num_bars):
            # Animated sine-based heights
            phase = elapsed * 3.0 + i * 0.3
            bar_t = (math.sin(phase) * 0.5 + 0.5) * (0.3 + 0.7 * math.sin(elapsed * 1.5 + i * 0.15) ** 2)
            bar_h = max_bar_h * bar_t * alpha

            bx = cx - bar_region_w / 2 + i * bar_gap
            by_top = cy + 15 - bar_h / 2
            by_bot = cy + 15 + bar_h / 2

            # Gradient color per bar
            t_norm = i / max(num_bars - 1, 1)
            r = 0.2 + 0.6 * t_norm
            g = 0.8 - 0.5 * t_norm
            b = 0.9 - 0.4 * t_norm
            bar_alpha = alpha * (0.3 + 0.4 * bar_t)

            col_top = imgui.get_color_u32(imgui.ImVec4(r, g, b, bar_alpha))
            col_bot = imgui.get_color_u32(imgui.ImVec4(r * 0.3, g * 0.3, b * 0.3, bar_alpha * 0.5))
            draw_list.add_rect_filled_multi_color(
                imgui.ImVec2(bx, by_top), imgui.ImVec2(bx + bar_w, by_bot),
                col_top, col_top, col_bot, col_bot,
            )

        # Title text (drawn at 2.5x font size using draw list overload)
        title = "Spectrum Analyzer"
        font = imgui.get_font()
        base_size = imgui.get_font_size()
        large_size = base_size * 2.5
        # Approximate title width by scaling from normal text size
        normal_size = imgui.calc_text_size(title)
        title_w = normal_size.x * 2.5
        title_h = normal_size.y * 2.5
        title_y = cy - 45
        draw_list.add_text(
            font, large_size,
            imgui.ImVec2(cx - title_w / 2, title_y),
            imgui.get_color_u32(imgui.ImVec4(1.0, 1.0, 1.0, alpha)),
            title,
        )

        # Subtitle
        sub = "Real-time Audio Visualization"
        sub_size = imgui.calc_text_size(sub)
        draw_list.add_text(
            imgui.ImVec2(cx - sub_size.x / 2, cy + 80),
            imgui.get_color_u32(imgui.ImVec4(0.6, 0.7, 0.9, alpha * 0.8)),
            sub,
        )

        # Loading dots
        dots = "." * (int(elapsed * 3) % 4)
        loading = f"Loading{dots}"
        load_size = imgui.calc_text_size(loading)
        draw_list.add_text(
            imgui.ImVec2(cx - load_size.x / 2, cy + 120),
            imgui.get_color_u32(imgui.ImVec4(0.5, 0.5, 0.6, alpha * 0.6)),
            loading,
        )

        imgui.end()

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
    # Remember and restore the OS window size/position across runs.
    runner_params.app_window_params.restore_previous_geometry = True
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

    # Store hello_imgui's settings (incl. saved window geometry) in a stable
    # location next to the executable so it survives restarts regardless of the
    # working directory. The imgui layout ini path is set separately in setup().
    runner_params.ini_folder_type = hello_imgui.IniFolderType.app_executable_folder

    addons = immapp.AddOnsParams()
    addons.with_implot = True

    immapp.run(runner_params, addons)


def _run_with_crash_log():
    """Run main(); on any unhandled exception, write a traceback to crash.log
    next to the executable so failures are diagnosable in frozen/windowed builds
    (where there is no console). Re-raises so exit behavior is unchanged."""
    import os
    import traceback

    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        try:
            base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
                else os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(base, "crash.log"), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
                f.write("\n")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    _run_with_crash_log()

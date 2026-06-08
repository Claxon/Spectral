# Spectral — project guide for Claude

Real-time audio spectrum analyzer for **Windows**. Captures system audio via WASAPI
loopback, runs FFT-based DSP, and renders live bar graphs / waveforms / spectrograms
through Dear ImGui (imgui-bundle + ImPlot). Ships as a standalone Windows exe built
with PyInstaller. Repo: https://github.com/Claxon/Spectral

## Run / build / release

- **From source:** `pip install -r requirements.txt` then `python main.py`
- **Launch the built exe:** `Spectral.bat` (local, untracked — runs `dist/SpectrumAnalyzer/SpectrumAnalyzer.exe`)
- **Build:** `python -m PyInstaller --noconfirm SpectrumAnalyzer.spec`
  → one-folder build in `dist/SpectrumAnalyzer/`. Requires **Python 3.13 at `C:/Python313`**
  (the spec pins native binary paths there).
- **Release:** clean rebuild → zip `dist/SpectrumAnalyzer/*` → `gh release create vX.Y.Z <zip> --target master`.
  Before zipping, delete runtime state files from the build dir so users get clean
  defaults: `imgui.ini`, `imgui_compact.ini`, `layout.version`, `app_prefs.json`,
  `Spectrum_Analyzer.ini`, `crash.log`. (A fresh PyInstaller build already wipes
  `dist/SpectrumAnalyzer`, but a smoke-test run recreates them.)

### SpectrumAnalyzer.spec — settings that must stay (each fixes a real crash/issue)
- Exclude Qt bindings (`PyQt5/6`, `PySide2/6`) — env has several; PyInstaller refuses two.
- `collect_all('pydantic')` + `collect_all('pydantic_core')` — imported transitively by
  `imgui_bundle.imgui_pydantic`; excluding them crashes at startup.
- Do **not** exclude `unittest`/`doctest` — `numpy.testing` needs `unittest`.
- `upx=False` (distribution reliability / fewer AV false positives).
- `icon='spectral.ico'`; `hiddenimports` includes `app_icon_data`.

## Licensing (important)

`license.py` gates "Pro" features via LemonSqueezy (placeholder URLs; no live server).
There is a **local-only developer unlock kept intentionally out of git** — `license.py`
shows as modified in the working tree and must **not** be committed/pushed.
**Public release exes must be built from the committed `license.py`** (temporarily
`git checkout -- license.py`, build, then restore the local copy) so the unlock is not
shipped. See private memory notes for specifics.

## Persistence (saved on graceful window close; force-killing skips the save)

- **Layout:** `imgui.ini` (normal mode) and `imgui_compact.ini` (compact mode), via
  `io.set_ini_filename(...)`. The two modes use separate files so they never overwrite
  each other.
- **Window size/position:** hello_imgui `restore_previous_geometry`, stored in
  `Spectrum_Analyzer.ini` next to the exe (`ini_folder_type = app_executable_folder`).
- **Per-analyzer settings:** `settings.json` (`config.py`, saved on change + exit).
- **App-level View toggles** (Show FPS, Always on Top, Compact Mode): `app_prefs.json`.
- **Default-layout control:** `LAYOUT_VERSION` + a `layout.version` marker file force a
  one-time layout reset when the built-in default changes. On a normal run the default
  is only rebuilt when no real layout is loaded (self-heals; never floats by default).

## imgui-bundle API gotchas (current version)

- `imgui.IntPtr` was **removed**. `dock_builder_split_node(id, dir, ratio)` now returns a
  `DockBuilderSplitNodeResult` with `.id_at_dir` / `.id_at_opposite_dir`.
- **`imgui.get_id()` is scope-dependent.** The dockspace id used to build the default
  layout MUST be computed inside the dockspace window (same scope as `dock_space()`),
  or the layout targets a phantom node and windows float into a separate OS window.
- Use `imgui.internal.DockNodeFlagsPrivate_.dock_space` when adding the dockspace node,
  and `...no_window_menu_button` on `dock_space()` to drop the tab-bar ▼ button.

## Features / behavior notes

- **Compact mode:** `View → Compact Mode` or `--compact` CLI flag. Hides the settings
  panel, trims padding, docks the spectrum large with a slim Levels strip.
- **Always on Top:** `_sync_always_on_top` resolves the real HWND (viewport native handle,
  falling back to the process's top-level window) and calls `SetWindowPos` with correct
  64-bit `argtypes`.
- **Window/taskbar icon:** set at runtime via `glfw.set_window_icon` from RGBA pixels
  embedded (base64) in `app_icon_data.py` — no Pillow at runtime (Pillow is excluded).
  Regenerate `spectral.ico` / `icon.png` / `app_icon_data.py` from a source image if the
  art changes. `icon.png` (256px) is the kept source.
- **Crash diagnostics:** `main()` writes a traceback to `crash.log` next to the exe on any
  unhandled exception (windowed builds have no console).

## Verifying a windowed build actually works

A windowed PyInstaller app keeps its process alive while showing an **error dialog**, so
"process still alive" is NOT proof of success. Enumerate the process's top-level window
class: `GLFW30` = real app window (OK); `#32770` titled "Unhandled exception in script" =
crash. Also note the **2.5s splash screen** shows a window first — wait >3s before judging.

## Module map

`main.py` app + windowing/layout/menus · `config.py` AppConfig + settings/prefs/ini paths ·
`audio_capture.py` WASAPI/sounddevice capture + device monitor · `dsp.py` FFT/windowing/
weighting · `renderer.py` ImPlot drawing + level meters · `settings_ui.py` settings panel ·
`themes.py` color themes · `license.py` Pro gating · `obs_server.py` Flask OBS overlay
server · `ring_buffer.py` audio ring buffer · `app_icon_data.py` embedded icon pixels.

"""Configuration dataclass and enums for the Spectrum Analyzer."""

import json
import os
from dataclasses import dataclass, fields, asdict
from enum import Enum, auto
from pathlib import Path


class DisplayMode(Enum):
    BAR_GRAPH = auto()
    SMOOTH_LINE = auto()
    SPECTROGRAM = auto()
    RADIAL = auto()
    OSCILLOSCOPE = auto()
    COMBINED = auto()


class WindowFunction(Enum):
    HANNING = auto()
    HAMMING = auto()
    BLACKMAN = auto()
    BLACKMAN_HARRIS = auto()
    FLAT_TOP = auto()
    KAISER = auto()


class ColorTheme(Enum):
    DARK = auto()
    NEON_CYBERPUNK = auto()
    WARM_SUNSET = auto()
    OCEAN = auto()
    LIGHT = auto()


class OctaveBandMode(Enum):
    NONE = auto()
    FULL_OCTAVE = auto()
    THIRD_OCTAVE = auto()


def _settings_path() -> Path:
    """Return path to persistent settings file next to the executable/script."""
    return Path(os.path.dirname(os.path.abspath(__file__))) / "settings.json"


def _ini_path() -> str:
    """Return path to imgui.ini for layout persistence (normal mode)."""
    return str(Path(os.path.dirname(os.path.abspath(__file__))) / "imgui.ini")


def _compact_ini_path() -> str:
    """Return path to the separate imgui layout file used in compact mode, so the
    normal-mode layout is never overwritten while compact is active."""
    return str(Path(os.path.dirname(os.path.abspath(__file__))) / "imgui_compact.ini")


def _app_prefs_path() -> Path:
    """Return path to app-level (non per-analyzer) UI preferences."""
    return Path(os.path.dirname(os.path.abspath(__file__))) / "app_prefs.json"


def load_app_prefs() -> dict:
    """Load app-level UI preferences (View-menu toggles), or {} if none."""
    path = _app_prefs_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r") as fp:
            return json.load(fp)
    except Exception as e:
        print(f"Failed to load app prefs: {e}")
        return {}


def save_app_prefs(prefs: dict) -> None:
    """Persist app-level UI preferences."""
    try:
        with open(_app_prefs_path(), "w") as fp:
            json.dump(prefs, fp, indent=2)
    except Exception as e:
        print(f"Failed to save app prefs: {e}")


@dataclass
class AppConfig:
    # Audio
    input_device_index: int = -1
    input_device_name: str = ""
    use_loopback: bool = False
    sample_rate: int = 44100

    # DSP
    fft_size: int = 4096
    num_bands: int = 64
    window_function: WindowFunction = WindowFunction.HANNING
    smoothing_factor: float = 0.3
    spectral_smoothing: int = 1
    a_weighting: bool = False
    freq_min: float = 20.0
    freq_max: float = 20000.0
    octave_mode: OctaveBandMode = OctaveBandMode.NONE

    # Display
    display_mode: DisplayMode = DisplayMode.BAR_GRAPH
    color_theme: ColorTheme = ColorTheme.DARK

    # Peak hold
    peak_hold_time: float = 2.0
    peak_decay_rate: float = 0.15

    # Spectrogram
    spectrogram_history_seconds: float = 5.0

    # Rendering
    show_fps: bool = True
    show_grid: bool = True
    db_range: float = 80.0

    def save(self) -> None:
        """Persist settings to JSON."""
        data = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, Enum):
                data[f.name] = val.name
            else:
                data[f.name] = val
        try:
            with open(_settings_path(), "w") as fp:
                json.dump(data, fp, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")

    @classmethod
    def load(cls) -> "AppConfig":
        """Load settings from JSON, returning defaults for missing keys."""
        cfg = cls()
        path = _settings_path()
        if not path.exists():
            return cfg
        try:
            with open(path, "r") as fp:
                data = json.load(fp)
            enum_map = {
                "window_function": WindowFunction,
                "display_mode": DisplayMode,
                "color_theme": ColorTheme,
                "octave_mode": OctaveBandMode,
            }
            for f in fields(cfg):
                if f.name in data:
                    val = data[f.name]
                    if f.name in enum_map:
                        try:
                            val = enum_map[f.name][val]
                        except KeyError:
                            continue
                    setattr(cfg, f.name, val)
        except Exception as e:
            print(f"Failed to load settings: {e}")
        return cfg

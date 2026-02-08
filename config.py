"""Configuration dataclass and enums for the Spectrum Analyzer."""

from dataclasses import dataclass
from enum import Enum, auto


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


@dataclass
class AppConfig:
    # Audio
    input_device_index: int = -1
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

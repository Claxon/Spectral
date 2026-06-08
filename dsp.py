"""DSP processing: FFT, band aggregation, peak hold, A-weighting, smoothing."""

import numpy as np
from dataclasses import dataclass
from scipy.signal import windows as scipy_windows

from config import AppConfig, WindowFunction, OctaveBandMode


@dataclass
class DSPResult:
    band_magnitudes_db: np.ndarray   # (num_bands,) in dB
    peak_hold_db: np.ndarray         # (num_bands,) peak markers in dB
    rms_db: float
    peak_db: float
    waveform: np.ndarray             # raw time-domain mono samples
    spectrogram_line: np.ndarray     # full FFT magnitude in dB
    fft_freqs: np.ndarray            # frequency axis
    band_centers: np.ndarray         # center frequency per band


class DSPProcessor:
    def __init__(self, config: AppConfig):
        self.config = config
        self._prev_magnitudes: np.ndarray | None = None
        self._peak_hold: np.ndarray | None = None
        self._peak_timers: np.ndarray | None = None
        self._window_cache: dict = {}
        self._a_weight_cache: dict = {}

    def process(self, samples: np.ndarray, dt: float) -> DSPResult:
        """Main DSP pipeline. samples shape: (fft_size, 1) or (fft_size,)."""
        mono = samples[:, 0] if samples.ndim > 1 else samples

        # Window
        windowed = mono * self._get_window(len(mono))

        # FFT
        spectrum = np.fft.rfft(windowed)
        freqs = np.fft.rfftfreq(len(mono), 1.0 / self.config.sample_rate)
        magnitudes = np.abs(spectrum) * 2.0 / len(mono)  # normalize

        # A-weighting
        if self.config.a_weighting:
            magnitudes = magnitudes * self._get_a_weight_curve(freqs)

        # To dB
        magnitudes_db = 20.0 * np.log10(np.maximum(magnitudes, 1e-10))

        # Band aggregation
        band_mags, band_centers = self._aggregate_bands(magnitudes_db, freqs)

        # The first and last bands straddle the DC (≈0 Hz) and Nyquist bins,
        # which carry windowing/sampling artifacts rather than real signal and
        # otherwise show up as fixed phantom peaks at the graph edges. Duplicate
        # each neighbour inward so the endpoints follow the real spectrum.
        if len(band_mags) >= 3:
            band_mags[0] = band_mags[1]
            band_mags[-1] = band_mags[-2]

        # Spectral smoothing
        if self.config.spectral_smoothing > 1:
            k = self.config.spectral_smoothing
            kernel = np.ones(k) / k
            band_mags = np.convolve(band_mags, kernel, mode='same')

        # Temporal smoothing (EMA)
        if self._prev_magnitudes is not None and len(self._prev_magnitudes) == len(band_mags):
            alpha = self.config.smoothing_factor
            band_mags = alpha * self._prev_magnitudes + (1 - alpha) * band_mags
        self._prev_magnitudes = band_mags.copy()

        # Peak hold
        self._update_peak_hold(band_mags, dt)

        # Overall levels
        rms = np.sqrt(np.mean(mono ** 2))
        peak = np.max(np.abs(mono))
        rms_db = 20.0 * np.log10(max(rms, 1e-10))
        peak_db = 20.0 * np.log10(max(peak, 1e-10))

        return DSPResult(
            band_magnitudes_db=band_mags,
            peak_hold_db=self._peak_hold.copy(),
            rms_db=rms_db,
            peak_db=peak_db,
            waveform=mono.copy(),
            spectrogram_line=magnitudes_db,
            fft_freqs=freqs,
            band_centers=band_centers,
        )

    def _get_window(self, size: int) -> np.ndarray:
        key = (self.config.window_function, size)
        if key not in self._window_cache:
            match self.config.window_function:
                case WindowFunction.HANNING:
                    w = np.hanning(size)
                case WindowFunction.HAMMING:
                    w = np.hamming(size)
                case WindowFunction.BLACKMAN:
                    w = np.blackman(size)
                case WindowFunction.BLACKMAN_HARRIS:
                    w = scipy_windows.blackmanharris(size)
                case WindowFunction.FLAT_TOP:
                    w = scipy_windows.flattop(size)
                case WindowFunction.KAISER:
                    w = np.kaiser(size, 14)
                case _:
                    w = np.hanning(size)
            self._window_cache[key] = w.astype(np.float32)
        return self._window_cache[key]

    def _aggregate_bands(self, magnitudes_db: np.ndarray, freqs: np.ndarray):
        match self.config.octave_mode:
            case OctaveBandMode.THIRD_OCTAVE:
                return self._third_octave_bands(magnitudes_db, freqs)
            case OctaveBandMode.FULL_OCTAVE:
                return self._full_octave_bands(magnitudes_db, freqs)
            case _:
                return self._log_spaced_bands(magnitudes_db, freqs)

    def _log_spaced_bands(self, mags_db: np.ndarray, freqs: np.ndarray):
        fmin = max(self.config.freq_min, freqs[1]) if len(freqs) > 1 else 20.0
        fmax = min(self.config.freq_max, freqs[-1]) if len(freqs) > 0 else 20000.0
        num = self.config.num_bands

        band_edges = np.logspace(np.log10(fmin), np.log10(fmax), num + 1)
        band_centers = np.sqrt(band_edges[:-1] * band_edges[1:])
        band_mags = np.full(num, -self.config.db_range)

        for i in range(num):
            mask = (freqs >= band_edges[i]) & (freqs < band_edges[i + 1])
            if np.any(mask):
                band_mags[i] = np.max(mags_db[mask])

        return band_mags, band_centers

    def _third_octave_bands(self, mags_db, freqs):
        centers = [20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250,
                   315, 400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500,
                   3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000, 20000]
        factor = 2 ** (1 / 6)
        return self._octave_aggregate(mags_db, freqs, centers, factor)

    def _full_octave_bands(self, mags_db, freqs):
        centers = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        factor = 2 ** 0.5
        return self._octave_aggregate(mags_db, freqs, centers, factor)

    def _octave_aggregate(self, mags_db, freqs, centers, factor):
        band_mags = []
        valid_centers = []
        for fc in centers:
            if fc < self.config.freq_min or fc > self.config.freq_max:
                continue
            lo, hi = fc / factor, fc * factor
            mask = (freqs >= lo) & (freqs < hi)
            if np.any(mask):
                band_mags.append(np.max(mags_db[mask]))
            else:
                band_mags.append(-self.config.db_range)
            valid_centers.append(fc)
        return np.array(band_mags, dtype=np.float64), np.array(valid_centers, dtype=np.float64)

    def _get_a_weight_curve(self, freqs: np.ndarray) -> np.ndarray:
        key = len(freqs)
        if key not in self._a_weight_cache:
            f2 = np.maximum(freqs ** 2, 1e-10)
            num = 12194.0 ** 2 * f2 ** 2
            den = ((f2 + 20.6 ** 2) *
                   np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) *
                   (f2 + 12194.0 ** 2))
            a_weight = num / np.maximum(den, 1e-10)
            ref_idx = np.argmin(np.abs(freqs - 1000.0))
            if ref_idx < len(a_weight) and a_weight[ref_idx] > 0:
                a_weight /= a_weight[ref_idx]
            self._a_weight_cache[key] = a_weight.astype(np.float64)
        return self._a_weight_cache[key]

    def _update_peak_hold(self, band_mags: np.ndarray, dt: float):
        if self._peak_hold is None or len(self._peak_hold) != len(band_mags):
            self._peak_hold = band_mags.copy()
            self._peak_timers = np.zeros_like(band_mags)
            return

        new_peaks = band_mags > self._peak_hold
        self._peak_hold[new_peaks] = band_mags[new_peaks]
        self._peak_timers[new_peaks] = 0.0
        self._peak_timers += dt

        decaying = self._peak_timers > self.config.peak_hold_time
        self._peak_hold[decaying] -= self.config.peak_decay_rate
        self._peak_hold = np.maximum(self._peak_hold, band_mags)

    def invalidate_caches(self):
        self._window_cache.clear()
        self._a_weight_cache.clear()
        self._prev_magnitudes = None
        self._peak_hold = None
        self._peak_timers = None

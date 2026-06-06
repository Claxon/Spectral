# Spectral

A real-time audio spectrum analyzer built with Python and Dear ImGui. Captures system audio (via WASAPI loopback on Windows), runs FFT-based DSP with configurable windowing, octave band aggregation, A-weighting, and peak hold, then renders live bar graphs, waveforms, and spectrograms through ImGui/ImPlot. Supports multiple analyzer instances, switchable color themes, always-on-top mode, and an OBS WebSocket integration server for streaming overlays. Packaged as a standalone Windows executable via PyInstaller.

## Tech Stack

- **GUI:** imgui-bundle (Dear ImGui + ImPlot)
- **Audio:** sounddevice / PyAudioWPatch (WASAPI loopback)
- **DSP:** NumPy, SciPy (FFT, windowing, filtering)
- **Packaging:** PyInstaller

## Usage

```bash
pip install -r requirements.txt
python main.py
```

A pre-built executable is available in `dist/SpectrumAnalyzer/SpectrumAnalyzer.exe`.

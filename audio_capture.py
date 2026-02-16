"""Audio device enumeration and capture using sounddevice and PyAudioWPatch."""

import threading
import time
import numpy as np
from dataclasses import dataclass

from ring_buffer import RingBuffer
from config import AppConfig


@dataclass
class AudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: float
    is_input: bool
    is_loopback: bool
    host_api: str
    backend: str  # "sounddevice" or "pyaudiowpatch"


class AudioCapture:
    def __init__(self, ring_buffer: RingBuffer, config: AppConfig):
        self.ring_buffer = ring_buffer
        self.config = config
        self._stream = None
        self._pyaudio_instance = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._current_device: AudioDevice | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_device(self) -> AudioDevice | None:
        return self._current_device

    def enumerate_devices(self) -> list[AudioDevice]:
        """Return all available input and loopback devices."""
        devices = []
        devices.extend(self._enumerate_sounddevice())
        devices.extend(self._enumerate_wasapi_loopback())
        return devices

    def _enumerate_sounddevice(self) -> list[AudioDevice]:
        devices = []
        try:
            import sounddevice as sd
            for i, dev in enumerate(sd.query_devices()):
                if dev['max_input_channels'] > 0:
                    devices.append(AudioDevice(
                        index=i,
                        name=f"[Input] {dev['name']}",
                        channels=dev['max_input_channels'],
                        sample_rate=dev['default_samplerate'],
                        is_input=True,
                        is_loopback=False,
                        host_api=sd.query_hostapis(dev['hostapi'])['name'],
                        backend="sounddevice",
                    ))
        except Exception as e:
            print(f"sounddevice enumeration error: {e}")
        return devices

    def _enumerate_wasapi_loopback(self) -> list[AudioDevice]:
        devices = []
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            try:
                wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
                for i in range(p.get_device_count()):
                    dev = p.get_device_info_by_index(i)
                    if dev.get('hostApi') == wasapi_info['index']:
                        if dev.get('isLoopbackDevice', False) or '[Loopback]' in dev.get('name', ''):
                            devices.append(AudioDevice(
                                index=i,
                                name=f"[Loopback] {dev['name']}",
                                channels=max(dev.get('maxInputChannels', 2), 1),
                                sample_rate=dev.get('defaultSampleRate', 44100),
                                is_input=False,
                                is_loopback=True,
                                host_api="WASAPI",
                                backend="pyaudiowpatch",
                            ))
            finally:
                p.terminate()
        except ImportError:
            print("PyAudioWPatch not available - loopback capture disabled")
        except Exception as e:
            print(f"WASAPI loopback enumeration error: {e}")
        return devices

    def start(self, device: AudioDevice) -> None:
        """Start capture on the given device."""
        self.stop()
        self._current_device = device
        self._running = True

        if device.backend == "sounddevice":
            self._start_sounddevice(device)
        elif device.backend == "pyaudiowpatch":
            self._thread = threading.Thread(
                target=self._run_wasapi_loopback,
                args=(device,),
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the current capture stream."""
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._current_device = None

    def _start_sounddevice(self, device: AudioDevice) -> None:
        import sounddevice as sd
        self.config.sample_rate = int(device.sample_rate)

        def callback(indata, frames, time_info, status):
            if status:
                pass  # Silently ignore xruns
            if self._running:
                mono = indata.mean(axis=1, keepdims=True) if indata.shape[1] > 1 else indata
                self.ring_buffer.write(mono)

        try:
            self._stream = sd.InputStream(
                device=device.index,
                channels=min(device.channels, 2),
                samplerate=device.sample_rate,
                dtype='float32',
                blocksize=1024,
                callback=callback,
            )
            self._stream.start()
        except Exception as e:
            print(f"Failed to start sounddevice stream: {e}")
            self._running = False

    def _run_wasapi_loopback(self, device: AudioDevice) -> None:
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            self._pyaudio_instance = p

            dev_info = p.get_device_info_by_index(device.index)
            channels = max(int(dev_info.get('maxInputChannels', 2)), 1)
            rate = int(dev_info.get('defaultSampleRate', 44100))
            self.config.sample_rate = rate

            chunk_size = 1024

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=chunk_size,
            )

            try:
                while self._running:
                    try:
                        data = stream.read(chunk_size, exception_on_overflow=False)
                        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                        if channels > 1:
                            samples = samples.reshape(-1, channels).mean(axis=1, keepdims=True)
                        else:
                            samples = samples.reshape(-1, 1)
                        self.ring_buffer.write(samples)
                    except Exception:
                        if not self._running:
                            break
            finally:
                stream.stop_stream()
                stream.close()
                p.terminate()
                self._pyaudio_instance = None

        except Exception as e:
            print(f"WASAPI loopback error: {e}")
            self._running = False


class DeviceLevelMonitor:
    """Opens lightweight streams on multiple devices to read RMS levels simultaneously.

    Used by the device selection modal to show live levels for all devices.
    Call start() with a list of devices, then read levels via get_levels().
    Call stop() when done (e.g. when modal closes).
    """

    def __init__(self):
        self._streams: list = []          # active sounddevice InputStream objects
        self._pa_threads: list[threading.Thread] = []
        self._levels: dict[int, float] = {}  # device index -> rms level (0..1)
        self._lock = threading.Lock()
        self._running = False
        self._pa_running_flags: dict[int, list] = {}  # device index -> [bool]

    def start(self, devices: list[AudioDevice]):
        """Begin monitoring the given devices."""
        self.stop()
        self._running = True
        self._levels.clear()

        for dev in devices:
            self._levels[dev.index] = 0.0
            try:
                if dev.backend == "sounddevice":
                    self._start_sd_monitor(dev)
                elif dev.backend == "pyaudiowpatch":
                    self._start_pa_monitor(dev)
            except Exception as e:
                print(f"Level monitor failed for {dev.name}: {e}")

    def stop(self):
        """Stop all monitoring streams."""
        self._running = False
        for flag_list in self._pa_running_flags.values():
            flag_list[0] = False
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams.clear()
        for t in self._pa_threads:
            t.join(timeout=1.0)
        self._pa_threads.clear()
        self._pa_running_flags.clear()

    def get_level(self, device_index: int) -> float:
        """Get current RMS level (0..1) for a device. Returns 0 if not monitored."""
        with self._lock:
            return self._levels.get(device_index, 0.0)

    def _start_sd_monitor(self, dev: AudioDevice):
        import sounddevice as sd
        idx = dev.index

        def callback(indata, frames, time_info, status):
            if not self._running:
                return
            rms = float(np.sqrt(np.mean(indata ** 2)))
            db = 20.0 * np.log10(max(rms, 1e-10))
            level = max(0.0, min(1.0, (db + 60.0) / 60.0))
            with self._lock:
                self._levels[idx] = level

        try:
            stream = sd.InputStream(
                device=dev.index,
                channels=min(dev.channels, 2),
                samplerate=dev.sample_rate,
                dtype='float32',
                blocksize=2048,
                callback=callback,
            )
            stream.start()
            self._streams.append(stream)
        except Exception as e:
            print(f"SD level monitor error for {dev.name}: {e}")

    def _start_pa_monitor(self, dev: AudioDevice):
        flag = [True]
        self._pa_running_flags[dev.index] = flag

        def run():
            try:
                import pyaudiowpatch as pyaudio
                p = pyaudio.PyAudio()
                try:
                    dev_info = p.get_device_info_by_index(dev.index)
                    channels = max(int(dev_info.get('maxInputChannels', 2)), 1)
                    rate = int(dev_info.get('defaultSampleRate', 44100))
                    chunk = 2048

                    stream = p.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=rate,
                        input=True,
                        input_device_index=dev.index,
                        frames_per_buffer=chunk,
                    )
                    try:
                        while self._running and flag[0]:
                            try:
                                data = stream.read(chunk, exception_on_overflow=False)
                                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                                rms = float(np.sqrt(np.mean(samples ** 2)))
                                db = 20.0 * np.log10(max(rms, 1e-10))
                                level = max(0.0, min(1.0, (db + 60.0) / 60.0))
                                with self._lock:
                                    self._levels[dev.index] = level
                            except Exception:
                                if not self._running:
                                    break
                                time.sleep(0.05)
                    finally:
                        stream.stop_stream()
                        stream.close()
                finally:
                    p.terminate()
            except Exception as e:
                print(f"PA level monitor error for {dev.name}: {e}")

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self._pa_threads.append(t)

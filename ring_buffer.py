"""Thread-safe ring buffer for audio samples."""

import numpy as np
import threading


class RingBuffer:
    def __init__(self, capacity: int, channels: int = 1):
        self._buf = np.zeros((capacity, channels), dtype=np.float32)
        self._capacity = capacity
        self._channels = channels
        self._write_pos = 0
        self._count = 0
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def available(self) -> int:
        with self._lock:
            return self._count

    def write(self, data: np.ndarray) -> None:
        """Write samples from audio callback thread.
        data shape: (n_samples,) or (n_samples, channels)."""
        if data.ndim == 1:
            data = data.reshape(-1, 1)
        if data.shape[1] != self._channels:
            # Mix to target channel count
            data = data.mean(axis=1, keepdims=True)
            if self._channels > 1:
                data = np.tile(data, (1, self._channels))

        n = data.shape[0]
        with self._lock:
            if n >= self._capacity:
                # Data larger than buffer - just keep the tail
                self._buf[:] = data[-self._capacity:]
                self._write_pos = 0
                self._count = self._capacity
                return

            end = self._write_pos + n
            if end <= self._capacity:
                self._buf[self._write_pos:end] = data
            else:
                first = self._capacity - self._write_pos
                self._buf[self._write_pos:] = data[:first]
                self._buf[:n - first] = data[first:]
            self._write_pos = end % self._capacity
            self._count = min(self._count + n, self._capacity)

    def read_latest(self, n: int) -> np.ndarray | None:
        """Read the most recent n samples, discarding older data.
        Returns None if fewer than n samples available."""
        with self._lock:
            if self._count < n:
                return None
            start = (self._write_pos - n) % self._capacity
            if start + n <= self._capacity:
                out = self._buf[start:start + n].copy()
            else:
                first = self._capacity - start
                out = np.empty((n, self._channels), dtype=np.float32)
                out[:first] = self._buf[start:]
                out[first:] = self._buf[:n - first]
            # Don't reset count - allow re-reads of same data
            return out

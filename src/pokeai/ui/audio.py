"""In-window game audio for the dashboard.

PyBoy fills ``pyboy.sound.ndarray`` with one frame of emulated audio every
tick, even when its native window is disabled. This player pulls those samples
(via ``EmulatorWrapper.audio_samples``) and streams them through ``pygame.mixer``
so the streamer gets real game sound from the dashboard's own window — no second
PyBoy window required.

Design notes:
  * The Game Boy DAC samples are small positive int8 values, so we remove the DC
    offset (a slow EMA) and scale to signed int16 for the mixer.
  * Audio is only meaningful at 1x emulation speed (real time). At higher speeds
    the game produces samples faster than they can be played, so the dashboard
    mutes us — we simply stop being fed.
  * Everything is wrapped defensively: if no audio device is available (e.g. CI),
    the player disables itself and becomes a no-op instead of crashing the UI.
"""
from __future__ import annotations

import numpy as np


class AudioPlayer:
    """Streams emulated Game Boy audio to the speakers via pygame.mixer."""

    # Keep at most this many seconds of audio buffered ahead, so toggling sound
    # or a speed change doesn't leave a long tail of stale sound playing.
    MAX_LOOKAHEAD_S = 0.3
    # Minimum samples to accumulate before emitting a chunk (~33ms at 48kHz).
    # A pygame Channel holds at most current+queued, so ~33ms chunks give a
    # ~66ms buffer — enough to ride through the once-per-step panel repaint
    # without underrunning (which would click/stutter).
    MIN_CHUNK = 1600

    def __init__(self, pygame, sample_rate: int, volume: int = 80):
        self.pygame = pygame
        self.sample_rate = sample_rate or 48000
        self._volume = max(0, min(100, volume))
        self._dc = 0.0  # running DC estimate for offset removal
        self._pending: list[np.ndarray] = []
        self._pending_len = 0
        self.ok = False
        self._channel = None
        self._init_mixer()

    # --- setup ---

    def _init_mixer(self) -> None:
        try:
            mixer = self.pygame.mixer
            init = mixer.get_init()
            if not init or init[0] != self.sample_rate or init[2] < 2:
                if init:
                    mixer.quit()
                mixer.init(frequency=self.sample_rate, size=-16, channels=2, buffer=512)
            mixer.set_num_channels(8)
            # Reserve a dedicated channel so game audio never collides with any
            # UI sound effects we might add later.
            self._channel = mixer.Channel(0)
            self.ok = True
        except Exception:
            self.ok = False

    # --- control ---

    @property
    def volume(self) -> int:
        return self._volume

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, volume))

    def reset(self) -> None:
        """Drop buffered audio and stop playback (e.g. on mute / speed change)."""
        self._pending.clear()
        self._pending_len = 0
        if self.ok and self._channel is not None:
            try:
                self._channel.stop()
            except Exception:
                pass

    # --- streaming ---

    def feed(self, samples: np.ndarray) -> None:
        """Queue one frame of (N, 2) int8 samples for playback."""
        if not self.ok or self._volume == 0 or samples.size == 0:
            return
        s = samples.astype(np.float32)
        # Slow DC tracking keeps the waveform centered without per-chunk clicks.
        self._dc = 0.995 * self._dc + 0.005 * float(s.mean())
        gain = (self._volume / 100.0) * 360.0
        s = (s - self._dc) * gain
        np.clip(s, -32767, 32767, out=s)
        self._pending.append(np.ascontiguousarray(s, dtype=np.int16))
        self._pending_len += s.shape[0]
        # Bound latency: if we've buffered too much, drop the oldest frames.
        max_len = int(self.MAX_LOOKAHEAD_S * self.sample_rate)
        while self._pending_len > max_len and len(self._pending) > 1:
            self._pending_len -= self._pending.pop(0).shape[0]

    def pump(self) -> None:
        """Flush buffered samples into the mixer. Call once per UI frame."""
        if not self.ok or self._channel is None or self._pending_len < self.MIN_CHUNK:
            return
        try:
            if self._channel.get_busy() and self._channel.get_queue() is not None:
                return  # already have a chunk playing and one queued; wait
            chunk = np.concatenate(self._pending, axis=0)
            self._pending.clear()
            self._pending_len = 0
            sound = self.pygame.sndarray.make_sound(chunk)
            if self._channel.get_busy():
                self._channel.queue(sound)
            else:
                self._channel.play(sound)
        except Exception:
            # A single bad chunk should never take down the dashboard.
            self._pending.clear()
            self._pending_len = 0

    def close(self) -> None:
        self.reset()
        if self.ok:
            try:
                self.pygame.mixer.quit()
            except Exception:
                pass

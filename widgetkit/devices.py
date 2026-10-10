"""Devices of this computer a widget may use, behind actions the user has allowed: the microphone.

`Recorder` records the default input to a WAV file, reports a live level, and stops itself after `seconds`. It works
on the GUI thread (Qt's audio classes do). The runtime makes one per `record_start` and asks for it through
`recorder_factory`, so a test (or another platform) can stand in a different one.
"""
import array
import math
import os
import tempfile
import time
import wave

from PySide6.QtCore import QTimer


class NoMicrophone(RuntimeError):
    pass


def input_names():
    from PySide6.QtMultimedia import QMediaDevices
    return [d.description() for d in QMediaDevices.audioInputs()]


class Recorder:
    def __init__(self, path=None, seconds=60, on_level=None, on_done=None):
        self.path = path or os.path.join(tempfile.gettempdir(), "widgetkit-%d.wav" % int(time.time() * 1000))
        self.seconds, self.on_level, self.on_done = seconds, on_level, on_done
        self.level = 0.0
        self.recording = False
        self._frames = 0
        self._rate = self._channels = 0
        self._width = 2
        self._src = self._io = self._wav = self._timer = None
        self._kind = "int16"

    def start(self):
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise NoMicrophone("this computer has no microphone")
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        sf = QAudioFormat.SampleFormat
        self._kind = {sf.UInt8: "uint8", sf.Int16: "int16", sf.Int32: "int32", sf.Float: "float"}.get(fmt.sampleFormat())
        if self._kind is None:
            raise NoMicrophone("unsupported sample format")
        self._width = {"uint8": 1, "int16": 2, "int32": 4, "float": 4}[self._kind]
        self._rate, self._channels = fmt.sampleRate(), fmt.channelCount()
        self._raw = open(self.path + ".raw", "wb")
        self._src = QAudioSource(device, fmt)
        self._io = self._src.start()
        if self._io is None:
            raise NoMicrophone("the microphone could not be opened")
        self._io.readyRead.connect(self._read)
        self.recording = True
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.stop)
        self._timer.start(int(self.seconds * 1000))

    def _read(self):
        data = bytes(self._io.readAll())
        if not data:
            return
        self._raw.write(data)
        self._frames += len(data) // (self._width * self._channels)
        self.level = _level(data, self._kind)
        if self.on_level:
            self.on_level(self.level)

    def stop(self):
        """Stop and save; returns the WAV's path (None if nothing was heard at all)."""
        if not self.recording:
            return None
        self.recording = False
        self._timer.stop()
        self._read()
        self._src.stop()
        self._raw.close()
        path = self._finish()
        self.level = 0.0
        if self.on_level:
            self.on_level(0.0)
        if self.on_done:
            self.on_done(path)
        return path

    def _finish(self):
        raw = self.path + ".raw"
        try:
            if self._frames == 0:
                return None
            with open(raw, "rb") as f:
                data = f.read()
            width = self._width
            if self._kind == "float":                       # WAV from the standard library is integer only
                floats = array.array("f", data[:len(data) // 4 * 4])
                data = array.array("h", [max(-32768, min(32767, int(x * 32767))) for x in floats]).tobytes()
                width = 2
            with wave.open(self.path, "wb") as w:
                w.setnchannels(self._channels)
                w.setsampwidth(width)
                w.setframerate(self._rate)
                w.writeframes(data)
            return self.path
        finally:
            try:
                os.remove(raw)
            except OSError:
                pass

    @property
    def seconds_recorded(self):
        return self._frames / self._rate if self._rate else 0.0


def _level(data, kind):
    """The loudness of a block, 0..1 (RMS, lifted a little so speech moves the meter)."""
    if kind == "int16":
        v = array.array("h", data[:len(data) // 2 * 2])
        peak = 32768.0
    elif kind == "int32":
        v = array.array("i", data[:len(data) // 4 * 4])
        peak = 2147483648.0
    elif kind == "float":
        v = array.array("f", data[:len(data) // 4 * 4])
        peak = 1.0
    else:
        v = array.array("B", data)
        v = array.array("h", [x - 128 for x in v])
        peak = 128.0
    if not v:
        return 0.0
    rms = math.sqrt(sum(x * x for x in v) / len(v)) / peak
    return max(0.0, min(1.0, rms * 4))

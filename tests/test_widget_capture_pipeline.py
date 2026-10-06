import threading
import unittest
from unittest.mock import patch

from nativeui import widget_capture as wc


class Api:
    widget_glass_deferred = True
    prefs = {}


def wait_until(condition, seconds=3.0):
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(.005)
    return False


class DeferredPixelWork(unittest.TestCase):
    def setUp(self):
        self.published, self.submitted = [], []
        self.lock = threading.Lock()
        def publish(reader, shot, generation):
            with self.lock:
                self.published.append((reader, shot, generation))
            return reader, shot, generation
        patches = (patch.object(wc, 'publish', publish),
                   patch.object(wc, 'submit', lambda packets: self.submitted.extend(packets)))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_finish_runs_each_deferred_shot_and_survives_a_failing_one(self):
        def broken():
            raise RuntimeError('filter failed')
        self.assertEqual(wc.finish(Api(), [lambda: 1, broken, {'plain': True}, None]),
                         [1, None, {'plain': True}, None])

    def test_every_widgets_frame_is_published_with_its_generation(self):
        api, a, b = Api(), object(), object()
        wc.hand_over(api, [a, b], [3, 4], [lambda: 'a', lambda: 'b'])
        self.assertTrue(wait_until(lambda: len(self.published) == 2))
        self.assertEqual(sorted((generation, shot) for _, shot, generation in self.published),
                         [(3, 'a'), (4, 'b')])
        self.assertEqual(len(self.submitted), 2)

    def test_a_newer_frame_replaces_an_unstarted_one_without_dropping_other_widgets(self):
        api, a, b = Api(), object(), object()
        release, started = threading.Event(), threading.Event()
        def slow():
            started.set()
            release.wait(3)
            return 'busy'
        wc.hand_over(api, [a], [1], [slow])
        self.assertTrue(started.wait(3))
        # The prep thread is busy: queue an old frame of both, then a new one of a.
        wc.hand_over(api, [a, b], [1, 1], [lambda: 'a-old', lambda: 'b'])
        wc.hand_over(api, [a], [2], [lambda: 'a-new'])
        release.set()
        self.assertTrue(wait_until(lambda: len(self.published) == 3))
        by_reader = {}
        for reader, shot, generation in self.published:
            by_reader.setdefault(reader, []).append((shot, generation))
        self.assertEqual(by_reader[a], [('busy', 1), ('a-new', 2)])
        self.assertEqual(by_reader[b], [('b', 1)])


if __name__ == '__main__':
    unittest.main()

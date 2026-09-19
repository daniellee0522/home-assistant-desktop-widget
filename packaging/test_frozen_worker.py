"""Verify the packaged EXE can start its capture subprocess without a GUI."""
import multiprocessing
import multiprocessing.spawn
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capture_worker import CaptureWorker


def main():
    executable = Path(sys.argv[1]).resolve(strict=True)
    multiprocessing.set_executable(str(executable))
    # Use the same spawn command line as a frozen parent process.
    sys.frozen = True
    worker = CaptureWorker(startup_timeout=15)
    original_preparation = multiprocessing.spawn.get_preparation_data

    def frozen_preparation(name):
        data = original_preparation(name)
        # A source test runner must not replace the child's bundled module
        # paths with the development interpreter's paths.
        internal = executable.parent / '_internal'
        data['sys_path'] = [str(internal / 'base_library.zip'), str(internal)]
        data.pop('init_main_from_path', None)
        data.pop('init_main_from_name', None)
        return data

    try:
        with patch('multiprocessing.spawn.get_preparation_data', frozen_preparation):
            frame = worker.grab(0, 0, 16, 16)
        assert worker._process is not None and worker._process.is_alive(), 'Packaged worker did not start'
        assert frame is None or len(frame) == 16 * 16 * 4
        print('PASS: packaged EXE imported its capture worker and completed a native request.')
    finally:
        worker.close()
        del sys.frozen
        multiprocessing.set_executable(sys.executable)


if __name__ == '__main__':
    main()

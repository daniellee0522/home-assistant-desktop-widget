"""Compare actual D3D11 glass with the original CPU renderer."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops, ImageStat
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from nativeui import dcomp, liquid
from nativeui.gpu_glass import Renderer


def main():
    app = QApplication.instance() or QApplication([])
    out = Path('visual/gpu-glass')
    out.mkdir(parents=True, exist_ok=True)
    compositor = dcomp.Slider()
    try:
        size = (320, 320)
        compositor._make_surfaces(*size)
        image = Image.merge('RGB', tuple(Image.effect_noise((80, 80), 35) for _ in range(3)))
        qimage = QImage(image.tobytes(), 80, 80, 240, QImage.Format_RGB888).copy()
        foreground = QImage(*size, QImage.Format_ARGB32_Premultiplied)
        foreground.fill(0)
        tiles = [(16, 70, 120, 130, 24), (170, 90, 130, 140, 24)]
        for level in (0, 50, 100):
            cpu = liquid.Lens(*size, 48)
            before = cpu.frame(image, cpu.card_mask(), tiles, 8 + 4 * level / 100, 22 * level / 100)
            renderer = Renderer(compositor, size, 48, 1, level, tiles)
            try:
                renderer.update(qimage)
                renderer.set_foreground(foreground)
                result = renderer.readback().convertToFormat(QImage.Format_RGBA8888)
                after = Image.frombytes('RGBA', size, result.constBits().tobytes())
                before.save(out / f'cpu-{level}.png')
                after.save(out / f'gpu-{level}.png')
                # Compare premultiplied color at transparent corners fairly.
                a = Image.alpha_composite(Image.new('RGBA', size, (30, 30, 30, 255)), before).convert('RGB')
                b = Image.alpha_composite(Image.new('RGBA', size, (30, 30, 30, 255)), after).convert('RGB')
                diff = ImageChops.difference(a, b)
                print(level, 'max difference', max(hi for _, hi in diff.getextrema()),
                      'mean', ImageStat.Stat(diff).mean, flush=True)
                start = time.perf_counter()
                for _ in range(30):
                    renderer.update(qimage)
                    renderer.draw()
                    dcomp._call(compositor.composition, 3, ())
                print('GPU submission ms', (time.perf_counter() - start) * 1000 / 30, flush=True)
            finally:
                renderer.close()
    finally:
        compositor.close()
    from tools import glass_review as review
    for pattern in ('bright', 'dark', 'busy', 'fine'):
        for theme in ('light', 'dark'):
            for level in (0, 50, 100):
                api, win, surface = review.create('liquid', theme, pattern, level, gpu=True)
                try:
                    review.shot(surface, pattern).save(str(out / f'widget-{pattern}-{theme}-{level}.png'))
                finally:
                    review.close(win)


if __name__ == '__main__':
    main()

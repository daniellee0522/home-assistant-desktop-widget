"""Compare liquid rendering before/after strip batching, for 1 and 6 widgets."""
import sys
import time
import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops, ImageFilter
from nativeui import liquid


class ReferenceLens(liquid.Lens):
    """Original full-frame composition, retained for pixel/throughput checks."""
    def frame(self, picture, card_mask, tiles=(), blur=12.0, frost=0.0):
        sharp = picture.resize((self.w, self.h), Image.BICUBIC)
        base = sharp
        lens = sharp.transform((self.w, self.h), Image.MESH, self.mesh, Image.BILINEAR)
        lens = Image.composite(self.white, lens, self.line)
        lens.putalpha(self.alpha)
        out = base.convert('RGBA')
        out.alpha_composite(lens)
        if frost > 0.05:
            out = out.convert('RGB').resize(picture.size, Image.BICUBIC).filter(
                ImageFilter.GaussianBlur(frost * picture.width / self.w)).resize(
                    (self.w, self.h), Image.BICUBIC).convert('RGBA')
        for x, y, w, h, radius in tiles:
            region = out.crop((x, y, x + w, y + h)).convert('RGB')
            small = region.reduce(2).filter(ImageFilter.GaussianBlur(blur / 2))
            out.paste(small.resize((w, h), Image.BILINEAR), (x, y), self.tile_mask(w, h, radius))
        out.putalpha(card_mask)
        return out


def measure(lens, source, card, count, frames=20):
    # Each widget owns its frame caches, just as GlassMixin does. Share only
    # immutable shape data so construction isn't included in update timing.
    workers = [copy.copy(lens) for _ in range(count)]
    for worker in workers:
        worker.tile_masks = {}
    def run(worker):
        for _ in range(frames):
            worker.frame(source, card, ((24, 80, 180, 160, 24),), frost=8)
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=count) as pool:
        list(pool.map(run, workers))
    return (time.perf_counter() - start) * 1000 / frames


def main():
    for w, h in ((320, 320), (640, 480), (960, 720)):
        source = Image.effect_noise((w // 2, h // 2), 80).convert('RGB')
        with patch.object(liquid, '_strip_mesh', lambda mesh: mesh):
            old = ReferenceLens(w, h, 48)
        new = liquid.Lens(w, h, 48)
        card = new.card_mask()
        before, after = old.frame(source, card), new.frame(source, card)
        delta = max(hi for _, hi in ImageChops.difference(before, after).getextrema())
        print(f'{w}x{h}: quads {len(old.mesh)} -> {len(new.mesh)}, max pixel delta {delta}', flush=True)
        for count in (1, 6):
            a, b = measure(old, source, card, count), measure(new, source, card, count)
            print(f'  {count} widgets: {a:.1f} -> {b:.1f} ms/update ({(1-b/a)*100:.0f}% less)', flush=True)


if __name__ == '__main__':
    main()

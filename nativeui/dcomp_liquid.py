"""GPU liquid material for the compositor's stationary desktop surface.

Material constants follow the motion clock; reduced desktop textures update
when a new capture arrives. The card and its outline move through DirectComposition.
"""
import ctypes as C
import struct
from functools import lru_cache

from .dcomp import _call, _void, _new, _release, _guid, _GUID, _Point, _IID_TEXTURE2D

P = C.c_void_p
U = C.c_uint
F = C.c_float


class TextureDesc(C.Structure):
    _fields_ = [(n, U) for n in ('width', 'height', 'mips', 'array', 'format', 'samples',
                               'quality', 'usage', 'bind', 'cpu', 'misc')]


class Data(C.Structure):
    _fields_ = [('data', P), ('pitch', U), ('slice', U)]


class BufferDesc(C.Structure):
    _fields_ = [(n, U) for n in ('size', 'usage', 'bind', 'cpu', 'misc', 'stride')]


class SamplerDesc(C.Structure):
    _fields_ = [('filter', U), ('u', U), ('v', U), ('w', U), ('bias', F),
                ('anisotropy', U), ('comparison', U), ('border', F * 4), ('minlod', F), ('maxlod', F)]


SHADER = b'''
cbuffer Material : register(b0) {
 float4 surface; // texture width, height, atlas x, y
 float4 card;    // card width, height, radius, offset
 float4 lens;    // height, amount, frost, tile count
 float4 tiles[128]; // rectangle then radius
};
Texture2D sharp : register(t0);
Texture2D frosted : register(t1);
Texture2D blurred : register(t2);
SamplerState linearClamp : register(s0);
float sd(float2 p, float2 size, float r) {
 float2 q=abs(p-size*.5)-(size*.5-r);
 float2 o=max(q,0); float2 o2=o*o;
 return sqrt(sqrt(dot(o2,o2)))-r+min(max(q.x,q.y),0);
}
float4 vs(uint id : SV_VertexID) : SV_POSITION {
 float2 p=float2((id<<1)&2,id&2);
 return float4(p*float2(2,-2)+float2(-1,1),0,1);
}
float4 ps(float4 position : SV_POSITION) : SV_TARGET {
 float2 screen=position.xy-surface.zw;
 float2 local=screen-float2(0,card.w);
 float distance=sd(local,card.xy,card.z);
 float t=saturate(1+distance/lens.x);
 float strength=1-sqrt(max(0,1-t*t));
 float2 p=local-card.xy*.5;
 float gr=min(card.z*1.5,min(card.x,card.y)*.5);
 float2 q=abs(p)-(card.xy*.5-gr);
 float2 n=pow(max(q,0),3)*sign(p);
 if(dot(n,n)>0) n=normalize(n);
 else n=q.x>q.y?float2(sign(p.x),0):float2(0,sign(p.y));
 float2 refracted=clamp(local-n*strength*lens.y,.5,card.xy-.5)+float2(0,card.w);
 float3 base=frosted.Sample(linearClamp,screen/surface.xy).rgb;
 float3 ring=sharp.Sample(linearClamp,refracted/surface.xy).rgb;
 float rim=(1-smoothstep(0,1.8,abs(-distance-1.4)))*.16;
 ring=lerp(ring,1,rim);
 float alpha=1.0*(1-smoothstep(max(0,lens.x-8),lens.x,-distance));
 float3 color=lerp(base,ring,alpha);
 [loop] for(int i=0;i<(int)lens.w;i++) {
  float4 rect=tiles[i*2];
  float inside=1-smoothstep(-.5,.5,sd(local-rect.xy,rect.zw,tiles[i*2+1].x));
  color=lerp(color,blurred.Sample(linearClamp,screen/surface.xy).rgb,inside);
 }
 return float4(color,1);
}
'''


# The panel's backdrop made on the GPU: the desktop rectangle reduced to a quarter, then blurred twice
# (the frost of the glass, the blur behind the tiles). One pixel shader, two operations.
BACKDROP = b'''
cbuffer Step : register(b0) { float4 target; float4 args; }; // target size; operation, sigma, axis x, axis y
Texture2D src : register(t0);
SamplerState linearClamp : register(s0);
float4 vs(uint id : SV_VertexID) : SV_POSITION {
 float2 p=float2((id<<1)&2,id&2);
 return float4(p*float2(2,-2)+float2(-1,1),0,1);
}
float4 ps(float4 position : SV_POSITION) : SV_TARGET {
 float2 uv=position.xy/target.xy;
 uint w,h; src.GetDimensions(w,h);
 float2 texel=1.0/float2(w,h);
 float3 sum=0;
 if(args.x==0) { // a block of the source, averaged
  float2 block=float2(w,h)/target.xy;
  int2 n=(int2)clamp(ceil(block),1,8);
  for(int y=0;y<n.y;y++) for(int x=0;x<n.x;x++)
   sum+=src.SampleLevel(linearClamp,uv+((float2(x,y)+.5)/n-.5)*block*texel,0).rgb;
  return float4(sum/(n.x*n.y),1);
 }
 float sigma=max(args.y,.01);
 int r=(int)min(ceil(3*sigma),48);
 float total=0;
 [loop] for(int i=-r;i<=r;i++) {
  float wt=exp(-i*i/(2*sigma*sigma));
  sum+=src.SampleLevel(linearClamp,uv+float2(args.z,args.w)*texel*i,0).rgb*wt;
  total+=wt;
 }
 return float4(sum/total,1);
}
'''


def _blob_value(blob, index, result):
    table = C.cast(P(blob), C.POINTER(P)).contents.value
    entry = C.cast(table + index * C.sizeof(P), C.POINTER(P)).contents.value
    return C.WINFUNCTYPE(result, P)(entry)(blob)


@lru_cache(maxsize=4)
def _compile(entry, target, source=None):
    source = source or SHADER
    compiler = C.WinDLL('d3dcompiler_47')
    compiler.D3DCompile.restype = C.c_long
    compiler.D3DCompile.argtypes = [P, C.c_size_t, C.c_char_p, P, P, C.c_char_p,
                                  C.c_char_p, U, U, C.POINTER(P), C.POINTER(P)]
    blob, errors = P(), P()
    result = compiler.D3DCompile(source, len(source), None, None, None, entry, target,
                                 1 << 15, 0, C.byref(blob), C.byref(errors))
    try:
        if result < 0:
            message = C.string_at(_blob_value(errors.value, 3, P)).decode() if errors.value else str(result)
            raise OSError(message)
        return C.string_at(_blob_value(blob.value, 3, P), _blob_value(blob.value, 4, C.c_size_t))
    finally:
        _release(blob.value)
        _release(errors.value)


class DesktopBackdrop:
    """The three pictures a Material samples, made from the desktop without it reaching the processor: a copy of the
    window's rectangle taken on the GPU, a quarter-size reduction, and two blurs of that. A compute shader tells
    whether a new copy differs from the one shown by more than noise, so a still desktop redraws nothing."""

    def __init__(self, material):
        from .gpu_glass import DIFF_GROUPS, compile_shader
        self.material, self.slider = material, material.slider
        self.device, self.context = self.slider.device, self.slider.context
        self.resources, self.size = [], None
        self.groups = DIFF_GROUPS
        self.copies, self.targets, self.shown, self.issued, self.views = [], {}, None, None, None
        self.dynamic = []
        try:
            code = compile_shader(b'diff', b'cs_5_0')
            self.difference = self._own(_new(self.device, 18, (C.c_char_p, C.c_size_t, P), code, len(code), None))
            for entry, target, index, name in ((b'vs', b'vs_4_0', 12, 'vs'), (b'ps', b'ps_4_0', 15, 'ps')):
                code = _compile(entry, target, BACKDROP)
                setattr(self, name, self._own(_new(self.device, index, (C.c_char_p, C.c_size_t, P),
                                                    code, len(code), None)))
            self.compute_buffer = self._own(_new(self.device, 3, (P, P), C.byref(BufferDesc(64, 0, 4, 0, 0, 0)), None))
            self.pass_buffer = self._own(_new(self.device, 3, (P, P), C.byref(BufferDesc(32, 0, 4, 0, 0, 0)), None))
            sampler = SamplerDesc(0x15, 3, 3, 3, 0, 1, 8, (F * 4)(), 0, 3.4e38)
            self.sampler = self._own(_new(self.device, 23, (P,), C.byref(sampler)))
            desc = TextureDesc(self.groups, 1, 1, 1, 42, 1, 0, 0, 0x88, 0, 0)
            self.peak = self._own(_new(self.device, 5, (P, P), C.byref(desc), None))
            self.peak_view = self._own(_new(self.device, 8, (P, P), self.peak, None))
            desc = TextureDesc(self.groups, 1, 1, 1, 42, 1, 0, 3, 0, 0x20000, 0)
            self.peak_stage = self._own(_new(self.device, 5, (P, P), C.byref(desc), None))
        except Exception:
            self.close()
            raise

    def _own(self, obj):
        self.resources.append(obj)
        return obj

    def _texture(self, w, h, target):
        desc = TextureDesc(max(1, w), max(1, h), 1, 1, 87, 1, 0, 0, 0x28 if target else 8, 0, 0)
        texture = _new(self.device, 5, (P, P), C.byref(desc), None)
        view = _new(self.device, 7, (P, P), texture, None)
        render = _new(self.device, 9, (P, P), texture, None) if target else None
        self.dynamic += [o for o in (render, view, texture) if o]
        return texture, view, render

    def _prepare(self, size):
        if self.size == size:
            return
        for obj in self.dynamic:
            _release(obj)
        self.dynamic = []
        w, h = size
        self.size = size
        self.copies = [self._texture(w, h, False) for _ in range(2)]
        small = (max(1, w // 4), max(1, h // 4))
        self.targets = {name: self._texture(small[0], small[1], True)
                        for name in ('small', 'frost', 'blur', 'scratch')}
        self.shown = None

    # -- one update: issue (nothing waits), then collect --------------------------------------------------
    def issue(self, frame):
        size = (frame.w, frame.h)
        self._prepare(size)
        index = 0 if self.shown is None else 1 - self.shown
        if not frame.copy_into(self.copies[index][0], self.device, self.context):
            self.issued = None
            return False
        measured = False
        if self.shown is not None:
            ctx = self.context
            _void(ctx, 33, (U, P, P), 0, None, None)
            _void(ctx, 69, (P, P, U), self.difference, None, 0)
            _void(ctx, 71, (U, U, P), 0, 1, C.byref(P(self.compute_buffer)))
            _void(ctx, 48, (P, U, P, C.c_char_p, U, U), self.compute_buffer, 0, None,
                  struct.pack('<16I', size[0], size[1], *([0] * 14)), 0, 0)
            _void(ctx, 67, (U, U, P), 0, 2, (P * 2)(self.copies[index][1], self.copies[self.shown][1]))
            _void(ctx, 68, (U, U, P, P), 0, 1, C.byref(P(self.peak_view)), None)
            _void(ctx, 41, (U, U, U), self.groups, 1, 1)
            _void(ctx, 67, (U, U, P), 0, 2, (P * 2)())
            _void(ctx, 68, (U, U, P, P), 0, 1, (P * 1)(), None)
            _void(ctx, 47, (P, P), self.peak_stage, self.peak)
            measured = True
        self.issued = (frame, index, measured)
        return True

    def collect(self, frame):
        """'changed' when the pictures were made again, 'static' when the copy is within noise of the one
        shown, None when the desktop can't be copied on the GPU."""
        if self.issued is None or self.issued[0] is not frame:
            if not self.issue(frame):
                return None
        _, index, measured = self.issued
        self.issued = None
        if measured:
            from dxgi_capture import _MAPPED
            mapped = _MAPPED()
            _call(self.context, 14, (P, U, U, U, P), self.peak_stage, 0, 1, 0, C.byref(mapped))
            try:
                worst = max(struct.unpack('<%dI' % self.groups, C.string_at(mapped.pData, 4 * self.groups)))
            finally:
                _void(self.context, 15, (P, U), self.peak_stage, 0)
            if worst <= 3:
                return 'static'
        self._make(index)
        self.shown = index
        return 'changed'

    def _pass(self, source_view, name, op, sigma=0.0, axis=(0, 0)):
        render = self.targets[name][2]
        w, h = max(1, self.size[0] // 4), max(1, self.size[1] // 4)
        ctx = self.context
        data = struct.pack('<8f', w, h, 0, 0, op, sigma, axis[0], axis[1])
        _void(ctx, 48, (P, U, P, C.c_char_p, U, U), self.pass_buffer, 0, None, data, 0, 0)
        viewport = (F * 6)(0, 0, w, h, 0, 1)
        _void(ctx, 44, (U, P), 1, C.byref(viewport))
        _void(ctx, 33, (U, P, P), 1, C.byref(P(render)), None)
        _void(ctx, 17, (P,), None)
        _void(ctx, 24, (U,), 4)
        _void(ctx, 11, (P, P, U), self.vs, None, 0)
        _void(ctx, 9, (P, P, U), self.ps, None, 0)
        _void(ctx, 16, (U, U, P), 0, 1, C.byref(P(self.pass_buffer)))
        _void(ctx, 10, (U, U, P), 0, 1, C.byref(P(self.sampler)))
        _void(ctx, 8, (U, U, P), 0, 1, (P * 1)(source_view))
        _void(ctx, 13, (U, U), 3, 0)
        _void(ctx, 8, (U, U, P), 0, 1, (P * 1)())

    def _make(self, index):
        m = self.material
        sharp = self.copies[index][1]
        self._pass(sharp, 'small', 0)
        small = self.targets['small'][1]
        scale = m.scale / 4
        frost_sigma = 22 * m.level * scale
        blur_sigma = (22 * m.level + 8 + 4 * m.level) * scale
        if m.level > .002:
            self._pass(small, 'scratch', 1, frost_sigma, (1, 0))
            self._pass(self.targets['scratch'][1], 'frost', 1, frost_sigma, (0, 1))
            frost = self.targets['frost'][1]
        else:
            frost = sharp
        self._pass(small, 'scratch', 1, blur_sigma, (1, 0))
        self._pass(self.targets['scratch'][1], 'blur', 1, blur_sigma, (0, 1))
        _void(self.context, 33, (U, P, P), 0, None, None)
        self.views = [sharp, frost, self.targets['blur'][1]]

    def close(self):
        for obj in reversed(self.resources + self.dynamic):
            _release(obj)
        self.resources, self.dynamic = [], []


class Material:
    def __init__(self, slider, image, size, radius, level, scale, tiles):
        self.slider = slider
        self.resources = []
        self.views = []
        self.size, self.radius = size, radius
        self.tiles = list(tiles)[:64]
        self.level = max(0, min(100, level)) / 100
        try:
            for entry, target, index, name in ((b'vs', b'vs_4_0', 12, 'vs'), (b'ps', b'ps_4_0', 15, 'ps')):
                code = _compile(entry, target)
                obj = _new(slider.device, index, (C.c_char_p, C.c_size_t, P), code, len(code), None)
                setattr(self, name, obj)
                self.resources.append(obj)
            desc = BufferDesc(2112, 0, 4, 0, 0, 0)
            self.buffer = _new(slider.device, 3, (P, P), C.byref(desc), None)
            self.resources.append(self.buffer)
            desc = SamplerDesc(0x15, 3, 3, 3, 0, 1, 8, (F * 4)(), 0, 3.4e38)
            self.sampler = _new(slider.device, 23, (P,), C.byref(desc))
            self.resources.append(self.sampler)
            self.scale = scale
            self.textures = []
            self.backdrop = None
            self.gpu_views = None
            self._update_image(image)
        except Exception:
            self.close()
            raise

    def update(self, image):
        """Take a new capture: a QImage (made on the processor) or a DesktopFrame (taken on the GPU).
        'static' when a GPU frame is within noise of what is shown (nothing was redone)."""
        if hasattr(image, 'copy_into'):
            if self.backdrop is None:
                self.backdrop = DesktopBackdrop(self)
            outcome = self.backdrop.collect(image)
            if outcome == 'changed':
                self.gpu_views = self.backdrop.views
            elif outcome is None:
                self.gpu_views = None
            return outcome
        if self.backdrop is not None:
            self.backdrop.shown = None                      # the next GPU copy is compared with nothing
        self.gpu_views = None
        self._update_image(image)

    def _update_image(self, image):
        from PIL import Image, ImageFilter
        from PySide6.QtGui import QImage
        rgb = image.convertToFormat(QImage.Format_RGBA8888)
        source = Image.frombytes('RGBA', (rgb.width(), rgb.height()), rgb.constBits().tobytes())
        # Capture arrives reduced already. Never expand it on the processor.
        w, h = self.slider.size
        small = source.resize((max(1, w // 4), max(1, h // 4)), Image.Resampling.BILINEAR)
        frost = (small.filter(ImageFilter.GaussianBlur(22 * self.level * self.scale / 4))
                 if self.level > .002 else source)
        blur = small.filter(ImageFilter.GaussianBlur((22 * self.level + 8 + 4 * self.level) * self.scale / 4))
        pictures = (source, frost, blur)
        sizes = [(p.width, p.height) for p in pictures]
        if getattr(self, 'texture_sizes', None) != sizes:
            for obj in self.views + self.textures:
                self.resources.remove(obj)
                _release(obj)
            self.views, self.textures = [], []
            for picture in pictures:
                desc = TextureDesc(picture.width, picture.height, 1, 1, 87, 1, 0, 0, 8, 0, 0)
                texture = _new(self.slider.device, 5, (P, P), C.byref(desc), None)
                self.textures.append(texture)
                self.resources.append(texture)
                view = _new(self.slider.device, 7, (P, P), texture, None)
                self.views.append(view)
                self.resources.append(view)
            self.texture_sizes = sizes
        for texture, picture in zip(self.textures, pictures):
            data = picture.tobytes('raw', 'BGRA')
            _void(self.slider.context, 48, (P, U, P, C.c_char_p, U, U),
                  texture, 0, None, data, picture.width * 4, 0)

    def draw(self, offset):
        s = self.slider
        point, texture = _Point(), P()
        _call(s.glass_surface, 3, (P, C.POINTER(_GUID), C.POINTER(P), C.POINTER(_Point)),
              None, C.byref(_guid(_IID_TEXTURE2D)), C.byref(texture), C.byref(point))
        target = None
        try:
            target = _new(s.device, 9, (P, P), texture.value, None)
            w, h = s.size
            H = min(46., self.radius * 1.05)
            values = [w, h, point.x, point.y, *self.size, self.radius, offset,
                      H, min(58., H * 1.45), self.level, len(self.tiles)]
            for x, y, tw, th, r in self.tiles:
                values.extend((x, y, tw, th, r, 0, 0, 0))
            values.extend([0.] * (528 - len(values)))
            data = struct.pack('<528f', *values)
            _void(s.context, 48, (P, U, P, C.c_char_p, U, U), self.buffer, 0, None, data, 0, 0)
            viewport = (F * 6)(point.x, point.y, w, h, 0, 1)
            _void(s.context, 44, (U, P), 1, C.byref(viewport))
            _void(s.context, 33, (U, P, P), 1, C.byref(P(target)), None)
            _void(s.context, 17, (P,), None)
            _void(s.context, 24, (U,), 4)
            _void(s.context, 11, (P, P, U), self.vs, None, 0)
            _void(s.context, 9, (P, P, U), self.ps, None, 0)
            _void(s.context, 16, (U, U, P), 0, 1, C.byref(P(self.buffer)))
            _void(s.context, 10, (U, U, P), 0, 1, C.byref(P(self.sampler)))
            views = (P * 3)(*(self.gpu_views or self.views))
            _void(s.context, 8, (U, U, P), 0, 3, views)
            _void(s.context, 13, (U, U), 3, 0)
            _void(s.context, 33, (U, P, P), 0, None, None)
        finally:
            _call(s.glass_surface, 4, ())
            _release(target)
            _release(texture.value)

    def close(self):
        if getattr(self, 'backdrop', None) is not None:
            self.backdrop.close()
            self.backdrop = None
        for obj in reversed(self.resources):
            _release(obj)
        self.resources = []

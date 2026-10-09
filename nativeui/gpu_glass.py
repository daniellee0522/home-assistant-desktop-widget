"""Widget liquid glass on D3D11: fixed Pillow mesh/masks, GPU image operations.

Only the reduced capture and a changed foreground are uploaded. Full-size
glass stays on the GPU through DirectComposition; readback is for snapshots
and visual verification only. Shader filters follow Pillow's byte rounding.
"""
import array
import ctypes as C
import math
import struct
from functools import lru_cache

from PIL import Image, ImageFilter
from PySide6.QtGui import QImage

from . import liquid
from .dcomp import _call, _new, _release, _guid, _GUID, _Point, _IID_TEXTURE2D
from .dcomp_liquid import TextureDesc, BufferDesc, SamplerDesc, _blob_value
from winsys.dxgi_capture import _MAPPED

P, U, F = C.c_void_p, C.c_uint, C.c_float

SHADER = b'''
cbuffer Settings : register(b0) {
 float4 target; // output size, DirectComposition atlas offset
 float4 region; // crop rectangle in first input
 float4 filter; // operation, axis, box weight, far weight
 float4 misc;   // integer box radius, tile position
};
Texture2D a : register(t0);
Texture2D b : register(t1);
Texture2D geometry : register(t2);
Texture2D mask : register(t3);
SamplerState linearClamp : register(s0);
float4 vs(uint id: SV_VertexID): SV_POSITION {
 float2 p=float2((id<<1)&2,id&2);
 return float4(p*float2(2,-2)+float2(-1,1),0,1);
}
float4 bytes(float4 value) { return floor(saturate(value)*255+.5)/255; }
float4 loadA(int2 p) {
 uint w,h; a.GetDimensions(w,h); return a.Load(int3(clamp(p,int2(0,0),int2(w,h)-1),0));
}
float cubic(float x) {
 x=abs(x);
 return x<1? ((1.5*x-2.5)*x)*x+1 : x<2? ((-.5*x+2.5)*x-4)*x+2 : 0;
}
float4 ps(float4 position: SV_POSITION): SV_TARGET {
 float2 p=position.xy-target.zw;
 int2 pixel=int2(p);
 uint w,h; a.GetDimensions(w,h);
 int operation=(int)filter.x;
 if(operation==0 || operation==1) { // separable cubic / bilinear resize
  float2 q=region.xy+p*region.zw/target.xy-.5;
  if(operation==1) return bytes(a.SampleLevel(linearClamp,(q+.5)/float2(w,h),0));
  int2 origin=int2(floor(q)); float4 color=0; float weight=0;
  float shrink=max(1., filter.y==0?region.z/target.x:region.w/target.y);
  int support=(int)ceil(2*shrink);
  [loop] for(int i=1-support;i<=support;i++) {
   int2 samplePixel=origin+(filter.y==0?int2(i,0):int2(0,i));
   if(shrink>1 && (any(samplePixel<0)||any(samplePixel>=int2(w,h)))) continue;
   float v=cubic((filter.y==0?q.x-samplePixel.x:q.y-samplePixel.y)/shrink);
   color+=loadA(samplePixel)*v; weight+=v;
  }
  return bytes(color/weight);
 }
 if(operation==2) { // Pillow's extended box, used three times per axis
  int2 axis=filter.y==0?int2(1,0):int2(0,1);
  int radius=(int)misc.x;
  uint4 sum=0;
  [loop] for(int i=-radius;i<=radius;i++) sum+=(uint4)floor(loadA(pixel+axis*i)*255+.5);
  uint4 far=(uint4)floor(loadA(pixel-axis*(radius+1))*255+.5)
           +(uint4)floor(loadA(pixel+axis*(radius+1))*255+.5);
  uint4 bulk=sum*(uint)filter.z+far*(uint)filter.w;
  return ((bulk+8388608)>>24)/255.0;
 }
 if(operation==3) { // the precomputed original mesh, rim and opacity
  float4 field=geometry.Load(int3(pixel,0));
  float4 ring=all(field.xy==0)?float4(0,0,0,1):bytes(a.SampleLevel(linearClamp,field.xy/float2(w,h),0));
  ring=bytes(lerp(ring,1,field.w));
  return bytes(lerp(b.Load(int3(pixel,0)),ring,field.z));
 }
 if(operation==7) { // a rotated screen's copy, turned upright (filter.y: DXGI's rotation 2, 3 or 4)
  int2 size=int2(target.xy); int turn=(int)filter.y;
  int2 s=turn==2 ? int2(pixel.y,size.x-1-pixel.x) : turn==3 ? size-1-pixel : int2(size.y-1-pixel.y,pixel.x);
  return a.Load(int3(s,0));
 }
 if(operation==4) { // reduce a tile by 2, with Pillow's partial last cell
  int2 start=int2(region.xy)+pixel*2;
  float4 sum=0; int count=0;
  [unroll] for(int y=0;y<2;y++) [unroll] for(int x=0;x<2;x++) {
   int2 q=start+int2(x,y);
   if(all(q<int2(region.xy+region.zw))) {
    sum+=all(q>=0)&&all(q<int2(w,h))?a.Load(int3(q,0)):float4(0,0,0,1); count++;
   }
  }
  return bytes(sum/count);
 }
 if(operation==5) { // paste the independently blurred tile through its mask
  float4 base=a.Load(int3(pixel,0)); int2 local=pixel-int2(misc.yz);
  uint tw,th; b.GetDimensions(tw,th);
  if(all(local>=0)&&all(local<int2(tw,th)))
   return bytes(lerp(base,b.Load(int3(local,0)),mask.Load(int3(local,0)).r));
  return base;
 }
 // Encoded-value foreground blend, exactly as the native QPainter layer.
 float4 glass=a.Load(int3(pixel,0));
 float alpha=mask.Load(int3(pixel,0)).r;
 float4 foreground=b.Load(int3(pixel,0));
 if(misc.w>0) foreground=lerp(foreground,geometry.Load(int3(pixel,0)),misc.x);
 return float4(foreground.rgb+glass.rgb*alpha*(1-foreground.a),
               foreground.a+alpha*(1-foreground.a));
}
'''


# Each group loads a halo once and performs all three boxes in shared memory.
# Packed byte colors preserve every integer rounding and edge clamp exactly.
COMPUTE = b'''
cbuffer Box : register(b0) { uint axis; uint radius; uint weight; uint farWeight; };
Texture2D source : register(t0);
RWTexture2D<float4> destination : register(u0);
groupshared uint first[512];
groupshared uint second[512];
uint4 unpack(uint value) { return uint4(value&255,(value>>8)&255,(value>>16)&255,value>>24); }
uint pack(uint4 value) { return value.x|(value.y<<8)|(value.z<<16)|(value.w<<24); }
uint4 rounded(uint4 sum, uint4 far) {
 return (sum*weight+far*farWeight+8388608)>>24;
}
[numthreads(256,1,1)]
void cs(uint3 group:SV_GroupID, uint thread:SV_GroupIndex) {
 uint width,height; source.GetDimensions(width,height);
 int length=axis==0?width:height;
 int reach=(int)radius+1;
 int origin=(int)group.x*256-3*reach;
 int count=256+6*reach;
 for(int i=(int)thread;i<count;i+=256) {
  int position=clamp(origin+i,0,length-1);
  int2 pixel=axis==0?int2(position,group.y):int2(group.y,position);
  first[i]=pack((uint4)floor(source.Load(int3(pixel,0))*255+.5));
 }
 GroupMemoryBarrierWithGroupSync();
 for(int i=reach+(int)thread;i<count-reach;i+=256) {
  int centre=clamp(origin+i,0,length-1); uint4 sum=0;
  for(int j=-(int)radius;j<=(int)radius;j++) sum+=unpack(first[clamp(centre+j,0,length-1)-origin]);
  uint4 far=unpack(first[clamp(centre-reach,0,length-1)-origin])+unpack(first[clamp(centre+reach,0,length-1)-origin]);
  second[i]=pack(rounded(sum,far));
 }
 GroupMemoryBarrierWithGroupSync();
 for(int i=2*reach+(int)thread;i<count-2*reach;i+=256) {
  int centre=clamp(origin+i,0,length-1); uint4 sum=0;
  for(int j=-(int)radius;j<=(int)radius;j++) sum+=unpack(second[clamp(centre+j,0,length-1)-origin]);
  uint4 far=unpack(second[clamp(centre-reach,0,length-1)-origin])+unpack(second[clamp(centre+reach,0,length-1)-origin]);
  first[i]=pack(rounded(sum,far));
 }
 GroupMemoryBarrierWithGroupSync();
 int position=(int)group.x*256+(int)thread;
 if(position<length) {
  uint4 sum=0;
  for(int j=-(int)radius;j<=(int)radius;j++) sum+=unpack(first[clamp(position+j,0,length-1)-origin]);
  uint4 far=unpack(first[clamp(position-reach,0,length-1)-origin])+unpack(first[clamp(position+reach,0,length-1)-origin]);
  int2 pixel=axis==0?int2(position,group.y):int2(group.y,position);
  destination[pixel]=rounded(sum,far)/255.0;
 }
}
'''


# The largest per-channel difference between two pictures of one size, per group of rows. The
# rule of the CPU path (a change of 3 or less is noise) is applied to the eight values.
DIFF_GROUPS = 8
DIFFERENCE = b'''
Texture2D cur : register(t0);
Texture2D old : register(t1);
RWTexture2D<uint> peak : register(u0);
cbuffer Size : register(b0) { uint width; uint height; uint2 pad; };
groupshared uint worst[256];
[numthreads(256,1,1)]
void diff(uint3 group:SV_GroupID, uint thread:SV_GroupIndex) {
 uint best=0;
 for(uint y=group.x; y<height; y+=8)
  for(uint x=thread; x<width; x+=256) {
   int3 a=(int3)floor(cur.Load(int3(x,y,0)).rgb*255+.5);
   int3 b=(int3)floor(old.Load(int3(x,y,0)).rgb*255+.5);
   int3 d=abs(a-b); best=max(best,max(d.x,max(d.y,d.z)));
  }
 worst[thread]=best; GroupMemoryBarrierWithGroupSync();
 for(uint s=128; s>0; s>>=1) {
  if(thread<s) worst[thread]=max(worst[thread],worst[thread+s]);
  GroupMemoryBarrierWithGroupSync();
 }
 if(thread==0) peak[uint2(group.x,0)]=worst[0];
}
'''


@lru_cache(maxsize=4)
def compile_shader(entry, target):
    compiler = C.WinDLL('d3dcompiler_47')
    compiler.D3DCompile.restype = C.c_long
    compiler.D3DCompile.argtypes = [P, C.c_size_t, C.c_char_p, P, P, C.c_char_p,
                                  C.c_char_p, U, U, C.POINTER(P), C.POINTER(P)]
    blob, errors = P(), P()
    source = COMPUTE if entry == b'cs' else DIFFERENCE if entry == b'diff' else SHADER
    result = compiler.D3DCompile(source, len(source), None, None, None, entry, target,
                                 1 << 15, 0, C.byref(blob), C.byref(errors))
    try:
        if result < 0:
            raise OSError(C.string_at(_blob_value(errors.value, 3, P)).decode()
                          if errors.value else str(result))
        return C.string_at(_blob_value(blob.value, 3, P), _blob_value(blob.value, 4, C.c_size_t))
    finally:
        _release(blob.value)
        _release(errors.value)


def box_parameters(sigma):
    """Pillow's three extended boxes, including float32 and 24-bit weights."""
    f = lambda x: C.c_float(x).value
    sigma = f(sigma)
    variance = f(f(sigma * sigma) / 3)
    length = f(math.sqrt(f(f(12 * variance) + 1)))
    integer = math.floor(f(f(length - 1) / 2))
    numerator = f(f(2 * integer + 1) * f(integer * (integer + 1) - f(3 * variance)))
    denominator = f(6 * f(variance - (integer + 1) ** 2))
    radius = f(integer + f(numerator / denominator))
    weight = int(f(16777216 / f(f(radius * 2) + 1)))
    far = (16777216 - (int(radius) * 2 + 1) * weight) // 2
    return int(radius), weight, far


@lru_cache(maxsize=16)
def shape_data(size, radius, frost):
    """Immutable geometry can be reused by widgets of the same shape."""
    w, h = size
    shape = liquid.Lens(w, h, radius)
    alpha = shape.alpha
    x = array.array('f', [i + .5 for i in range(w)] * h)
    y = array.array('f', [j + .5 for j in range(h) for _ in range(w)])
    xmap = Image.frombytes('F', size, x.tobytes()).transform(size, Image.MESH, shape.mesh, Image.BILINEAR)
    ymap = Image.frombytes('F', size, y.tobytes()).transform(size, Image.MESH, shape.mesh, Image.BILINEAR)
    xs, ys = array.array('f'), array.array('f')
    xs.frombytes(xmap.tobytes())
    ys.frombytes(ymap.tobytes())
    values = array.array('f')
    for px, py, opacity, rim in zip(xs, ys, alpha.tobytes(), shape.line.tobytes()):
        values.extend((px, py, opacity / 255, rim / 255))
    return shape, shape.card_mask(), values.tobytes()


class Texture:
    def __init__(self, renderer, size, data=None, format=87, pitch=None):
        self.renderer, self.size = renderer, tuple(size)
        self.texture = self.view = self.target = self.uav = None
        try:
            desc = TextureDesc(*size, 1, 1, format, 1, 0, 0, 0xa8 if format in (28, 42) else 0x28, 0, 0)
            self.texture = _new(renderer.device, 5, (P, P), C.byref(desc), None)
            self.view = _new(renderer.device, 7, (P, P), self.texture, None)
            self.target = _new(renderer.device, 9, (P, P), self.texture, None)
            if format in (28, 42):
                self.uav = _new(renderer.device, 8, (P, P), self.texture, None)
            if data is not None:
                self.upload(data, pitch or size[0] * (16 if format == 2 else 4))
        except Exception:
            self.close()
            raise

    def upload(self, data, pitch):
        self.renderer._command(48, (P, U, P, C.c_char_p, U, U),
              self.texture, 0, None, data, pitch, 0)

    def close(self):
        for name in ('uav', 'target', 'view', 'texture'):
            _release(getattr(self, name))
            setattr(self, name, None)


# The classic (non-liquid) glass: the desktop averaged over 8 x 8 cells, blurred by this much (in those cells),
# then stretched over the card. The same picture the processor used to make, now made on the GPU.
CLASSIC_CELL_HALVINGS = 3
CLASSIC_BLUR = 2.0


class Renderer:
    def __init__(self, compositor, size, radius, scale, level, tiles, classic=False):
        self.compositor = compositor
        self.classic = classic
        self.device, self.context = compositor.device, compositor.context
        self.size, self.scale, self.level = size, scale, max(0, min(100, level)) / 100
        self.tiles = list(tiles)
        self.resources, self.textures, self.pool = [], [], {}
        self.commands, self.passes = {}, {}
        self.empty_views = (P * 4)()
        self.source = self.result = None
        try:
            for entry, target, index, name in ((b'vs', b'vs_4_0', 12, 'vs'), (b'ps', b'ps_4_0', 15, 'ps')):
                code = compile_shader(entry, target)
                obj = _new(self.device, index, (C.c_char_p, C.c_size_t, P), code, len(code), None)
                setattr(self, name, obj)
                self.resources.append(obj)
            desc = BufferDesc(64, 0, 4, 0, 0, 0)
            self.buffer = _new(self.device, 3, (P, P), C.byref(desc), None)
            self.resources.append(self.buffer)
            desc = SamplerDesc(0x15, 3, 3, 3, 0, 1, 8, (F * 4)(), 0, 3.4e38)
            self.sampler = _new(self.device, 23, (P,), C.byref(desc))
            self.resources.append(self.sampler)
            w, h = size
            if classic:
                # No lens: the card's shape is uploaded with the foreground (see Controller.present).
                self.card = self._texture(size)
                self.tile_masks, self.field = [], None
            else:
                shape, card, field = shape_data(tuple(size), radius, 22 * self.level * scale)
                self.card = self._image_texture(card.convert('RGBA'))
                self.tile_masks = [self._image_texture(shape.tile_mask(tw, th, r).convert('RGBA'))
                                   for x, y, tw, th, r in self.tiles]
                # Float mesh maps are computed once with the exact original Pillow
                # rasterizer. The GPU reads them without simplifying any corner.
                self.field = self._texture(size, field, format=2)
            self.foreground = self._texture(size)
            self.foreground_dim = self._texture(size)
            self.dim_mix = None
            self.presentation = [compositor.glass_surface]
            for _ in range(2):
                surface = _new(compositor.composition, 8, (U, U, U, U), w, h, 87, 1)
                self.presentation.append(surface)
                self.resources.append(surface)
            self.presentation_index = 0
            self.cs = self.difference = None
            self.shown = self.shown_size = self.issued = None
            self.peak = self.peak_stage = None
            try:
                code = compile_shader(b'cs', b'cs_5_0')
                self.cs = _new(self.device, 18, (C.c_char_p, C.c_size_t, P), code, len(code), None)
                self.resources.append(self.cs)
                code = compile_shader(b'diff', b'cs_5_0')
                self.difference = _new(self.device, 18, (C.c_char_p, C.c_size_t, P), code, len(code), None)
                self.resources.append(self.difference)
                self.peak = self._texture((DIFF_GROUPS, 1), format=42)
                desc = TextureDesc(DIFF_GROUPS, 1, 1, 1, 42, 1, 0, 3, 0, 0x20000, 0)
                self.peak_stage = _new(self.device, 5, (P, P), C.byref(desc), None)
                self.resources.append(self.peak_stage)
            except OSError:
                pass  # feature-level 10 devices keep the identical six-pass blur
        except Exception:
            self.close()
            raise

    def _texture(self, size, data=None, format=87):
        texture = Texture(self, size, data, format)
        self.textures.append(texture)
        return texture

    def _image_texture(self, image):
        return self._texture(image.size, image.tobytes('raw', 'BGRA'))

    def _temporary(self, name, size):
        key = name, tuple(size)
        if key not in self.pool:
            self.pool[key] = self._texture(size)
        return self.pool[key]

    def _command(self, index, argtypes, *args):
        function = self.commands.get(index)
        if function is None:
            table = C.cast(P(self.context), C.POINTER(P)).contents.value
            entry = C.cast(table + index * C.sizeof(P), C.POINTER(P)).contents.value
            # These are short context setters/dispatches, not frame waits.
            # Keep a submission together instead of releasing/reacquiring the
            # GIL for every command while capture filters compete for it.
            # Windows x64 has one calling convention; x86 retains stdcall.
            factory = C.PYFUNCTYPE if C.sizeof(P) == 8 else C.WINFUNCTYPE
            function = factory(None, P, *argtypes)(entry)
            self.commands[index] = function
        function(self.context, *args)

    def _pass(self, target, operation, inputs, region=None, axis=0, box=None, tile=None,
              external_target=None, offset=(0, 0), mix=None):
        w, h = target.size if external_target is None else self.size
        region = region or (0, 0, *inputs[0].size)
        key = (target, operation, tuple(inputs), tuple(region), axis, box, tile) if target is not None and mix is None else None
        prepared = self.passes.get(key) if key is not None else None
        if prepared is None:
            n, weight, far = box or (0, 0, 0)
            values = [w, h, *offset, *region, operation, axis, weight, far, n if mix is None else mix, *(tile or (0, 0)), int(mix is not None)]
            data = struct.pack('<16f', *values)
            viewport = (F * 6)(*offset, w, h, 0, 1)
            views = (P * 4)(*[t.view if t is not None else None for t in inputs],
                             *([None] * (4 - len(inputs))))
            target_pointer = C.byref(P(external_target or target.target))
            prepared = data, viewport, views, target_pointer
            if key is not None:
                self.passes[key] = prepared
        data, viewport, views, target_pointer = prepared
        self._command(48, (P, U, P, C.c_char_p, U, U), self.buffer, 0, None, data, 0, 0)
        self._command(44, (U, P), 1, C.byref(viewport))
        self._command(33, (U, P, P), 1, target_pointer, None)
        if not getattr(self, '_pipeline_bound', False):
            self._command(17, (P,), None)
            self._command(24, (U,), 4)
            self._command(11, (P, P, U), self.vs, None, 0)
            self._command(9, (P, P, U), self.ps, None, 0)
            self._command(16, (U, U, P), 0, 1, C.byref(P(self.buffer)))
            self._command(10, (U, U, P), 0, 1, C.byref(P(self.sampler)))
            self._pipeline_bound = True
        self._command(8, (U, U, P), 0, 4, views)
        self._command(13, (U, U), 3, 0)
        self._command(8, (U, U, P), 0, 4, self.empty_views)

    def _resize(self, source, size, name, cubic=True):
        if source.size == tuple(size):
            return source
        if not cubic:
            target = self._temporary(name, size)
            self._pass(target, 1, [source])
            return target
        intermediate = self._temporary(name + '-h', (size[0], source.size[1]))
        target = self._temporary(name, size)
        self._pass(intermediate, 0, [source], axis=0)
        self._pass(target, 0, [intermediate], axis=1)
        return target

    def _blur(self, source, sigma, name):
        if sigma <= .001:
            return source
        box = box_parameters(sigma)
        if self.cs is not None and 256 + 6 * (box[0] + 1) <= 512:
            return self._compute_blur(source, box, name)
        targets = [self._temporary(name + str(i), source.size) for i in range(2)]
        for i in range(6):
            target = targets[i % 2]
            self._pass(target, 2, [source], axis=0 if i < 3 else 1, box=box)
            source = target
        return source

    def _compute_blur(self, source, box, name):
        self._command(33, (U, P, P), 0, None, None)
        self._command(69, (P, P, U), self.cs, None, 0)
        self._command(71, (U, U, P), 0, 1, C.byref(P(self.buffer)))
        for axis in range(2):
            key = name + '-compute-' + str(axis), source.size
            if key not in self.pool:
                self.pool[key] = self._texture(source.size, format=28)
            target = self.pool[key]
            data = struct.pack('<16I', axis, *box, *([0] * 12))
            self._command(48, (P, U, P, C.c_char_p, U, U), self.buffer, 0, None, data, 0, 0)
            self._command(67, (U, U, P), 0, 1, C.byref(P(source.view)))
            self._command(68, (U, U, P, P), 0, 1, C.byref(P(target.uav)), None)
            w, h = source.size
            self._command(41, (U, U, U), ((w if axis == 0 else h) + 255) // 256, h if axis == 0 else w, 1)
            self._command(67, (U, U, P), 0, 1, self.empty_views)
            self._command(68, (U, U, P, P), 0, 1, self.empty_views, None)
            source = target
        return source

    def update(self, image):
        self._pipeline_bound = False
        rgb = image if image.format() in (QImage.Format_RGB32, QImage.Format_ARGB32) else image.convertToFormat(QImage.Format_ARGB32)
        size = (rgb.width(), rgb.height())
        self.source = self._temporary('capture', size)
        captured = getattr(image, '_capture_bytes', None) if image.format() == QImage.Format_RGB32 else None
        self.source.upload(captured if captured is not None else rgb.constBits().tobytes(), rgb.bytesPerLine())
        self._refract(size, getattr(image, '_pre_blur', 0))

    def issue_desktop(self, frame):
        """Start taking a window's part of the desktop: copy it on the GPU and measure how far it is from
        the picture last drawn. Nothing waits here, so every widget of a frame can start before any
        of them looks at its result."""
        self._pipeline_bound = False
        size = (frame.w, frame.h)
        index = 0 if self.shown is None else 1 - self.shown
        current = self._temporary('capture%d' % index, size)
        turn = frame.rotation if frame.rotation in (2, 3, 4) else 0
        if turn:
            # The screen is rotated: its copy has the turned shape, and a pass turns it upright.
            held = self._temporary('turned', (size[1], size[0]) if turn != 3 else size)
            if not frame.copy_into(held.texture, self.device, self.context):
                self.issued = None
                return False
            self._pass(current, 7, [held], axis=turn)
        elif not frame.copy_into(current.texture, self.device, self.context):
            self.issued = None
            return False
        measured = False
        if self.difference is not None and self.shown is not None and self.shown_size == size:
            last = self._temporary('capture%d' % self.shown, size)
            self._command(33, (U, P, P), 0, None, None)
            self._command(69, (P, P, U), self.difference, None, 0)
            self._command(71, (U, U, P), 0, 1, C.byref(P(self.buffer)))
            self._command(48, (P, U, P, C.c_char_p, U, U), self.buffer, 0, None,
                          struct.pack('<16I', size[0], size[1], *([0] * 14)), 0, 0)
            self._command(67, (U, U, P), 0, 2, (P * 2)(current.view, last.view))
            self._command(68, (U, U, P, P), 0, 1, C.byref(P(self.peak.uav)), None)
            self._command(41, (U, U, U), DIFF_GROUPS, 1, 1)
            self._command(67, (U, U, P), 0, 2, (P * 2)())
            self._command(68, (U, U, P, P), 0, 1, self.empty_views, None)
            self._command(47, (P, P), self.peak_stage, self.peak.texture)
            measured = True
        self.issued = (frame, index, size, measured)
        return True

    def update_desktop(self, frame):
        """The same picture as update(), taken from the desktop's own texture without a CPU copy.
        'changed' when the glass was made again, 'static' when the picture is within noise of the one
        drawn (nothing was redone), None when the desktop can no longer be copied that way."""
        if self.issued is None or self.issued[0] is not frame:
            if not self.issue_desktop(frame):
                return None
        _, index, size, measured = self.issued
        self.issued = None
        if measured:
            mapped = _MAPPED()
            _call(self.context, 14, (P, U, U, U, P), self.peak_stage, 0, 1, 0, C.byref(mapped))
            try:
                worst = max(struct.unpack('<%dI' % DIFF_GROUPS, C.string_at(mapped.pData, 4 * DIFF_GROUPS)))
            finally:
                self._command(15, (P, U), self.peak_stage, 0)
            if worst <= 3:
                return 'static'
        elif self.difference is None:
            return None            # no compute shaders: the CPU path keeps its own noise rule
        self._pipeline_bound = False
        self.source = self._temporary('capture%d' % index, size)
        self._refract(size, frame._pre_blur, frame.divide)
        self.shown, self.shown_size = index, size
        return 'changed'

    def _classic(self, size):
        """The classic glass from a picture of the desktop: a full-size one is averaged over 8 x 8 cells and
        blurred here; one the processor already made small (and blurred) is only stretched over the card."""
        source = self.source
        if size[0] * 2 > self.size[0] or size[1] * 2 > self.size[1]:
            for i in range(CLASSIC_CELL_HALVINGS):
                w, h = source.size
                half = self._temporary('cell%d' % i, ((w + 1) // 2, (h + 1) // 2))
                self._pass(half, 4, [source], region=(0, 0, w, h))
                source = half
            source = self._blur(source, CLASSIC_BLUR, 'classic-blur')
        self.result = self._resize(source, self.size, 'classic-card', cubic=False)

    def _refract(self, size, pre_blur, divide=1):
        if self.classic:
            return self._classic(size)
        source = self._blur(self.source, pre_blur, 'capture-prefilter')
        sharp = self._resize(source, self.size, 'sharp')
        self.result = self._temporary('glass', self.size)
        self._pass(self.result, 3, [sharp, sharp, self.field])
        if self.level > .001:
            # The frost is blurred on a smaller picture the more of it there is (the processor's path made the
            # capture that small before anything else); a desktop frame arrives whole, so it shrinks here.
            if divide > 1:
                size = (max(1, round(size[0] / divide)), max(1, round(size[1] / divide)))
            reduced = self._resize(self.result, size, 'refracted-small')
            frost = self._blur(reduced, 22 * self.level * self.scale * size[0] / self.size[0], 'frost')
            self.result = self._resize(frost, self.size, 'frosted')
        for i, (x, y, w, h, radius) in enumerate(self.tiles):
            name = 'tile' + str(i)
            small = self._temporary(name + '-small', ((w + 1) // 2, (h + 1) // 2))
            self._pass(small, 4, [self.result], region=(x, y, w, h))
            blurred = self._blur(small, (8 + 4 * self.level) * self.scale / 2, name + '-blur')
            tile = self._resize(blurred, (w, h), name + '-large', cubic=False)
            target = self._temporary('paste' + str(i % 2), self.size)
            self._pass(target, 5, [self.result, tile, None, self.tile_masks[i]], tile=(x, y))
            self.result = target

    def set_foreground(self, image):
        self._lit_layer = None
        self.dim_mix = None
        image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.foreground.upload(image.constBits().tobytes(), image.bytesPerLine())

    def set_layers(self, lit, dim):
        if getattr(self, '_lit_layer', None) is not lit:
            self.set_foreground(lit)
            self._lit_layer = lit
        dim = dim.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.foreground_dim.upload(dim.constBits().tobytes(), dim.bytesPerLine())
        self.dim_mix = 0.0

    def draw(self):
        self._pipeline_bound = False
        if self.result is None:
            return
        point, texture = _Point(), P()
        self.presentation_index = (self.presentation_index + 1) % len(self.presentation)
        surface = self.presentation[self.presentation_index]
        _call(surface, 3, (P, C.POINTER(_GUID), C.POINTER(P), C.POINTER(_Point)),
              None, C.byref(_guid(_IID_TEXTURE2D)), C.byref(texture), C.byref(point))
        target = None
        try:
            target = _new(self.device, 9, (P, P), texture.value, None)
            self._pass(None, 6, [self.result, self.foreground, self.foreground_dim, self.card],
                       external_target=target, offset=(point.x, point.y), mix=self.dim_mix)
        finally:
            self._command(33, (U, P, P), 0, None, None)
            _call(surface, 4, ())
            _release(target)
            _release(texture.value)
        _call(self.compositor.glass_visual, 15, (P,), surface)

    def readback(self):
        """Diagnostic/snapshot only; production presents without this transfer."""
        self._pipeline_bound = False
        from winsys.dxgi_capture import _MAPPED
        target = self._temporary('snapshot', self.size)
        self._pass(target, 6, [self.result, self.foreground, self.foreground_dim, self.card], mix=self.dim_mix)
        self._command(33, (U, P, P), 0, None, None)
        w, h = self.size
        staging = getattr(self, 'snapshot_stage', None)
        if staging is None:      # one staging texture for every snapshot of this card
            desc = TextureDesc(w, h, 1, 1, 87, 1, 0, 3, 0, 0x20000, 0)
            staging = self.snapshot_stage = _new(self.device, 5, (P, P), C.byref(desc), None)
            self.resources.append(staging)
        self._command(47, (P, P), staging, target.texture)
        mapped = _MAPPED()
        _call(self.context, 14, (P, U, U, U, P), staging, 0, 1, 0, C.byref(mapped))
        try:
            data = C.string_at(mapped.pData, mapped.RowPitch * h)
            return QImage(data, w, h, mapped.RowPitch, QImage.Format_ARGB32_Premultiplied).copy()
        finally:
            self._command(15, (P, U), staging, 0)

    def close(self):
        self.passes.clear()
        self.commands.clear()
        for texture in reversed(self.textures):
            texture.close()
        for obj in reversed(self.resources):
            _release(obj)
        self.textures, self.resources, self.pool = [], [], {}
        self.snapshot_stage = None

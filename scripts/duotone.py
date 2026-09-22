"""Duotone any photo to the brand palette. Usage: python3 scripts/duotone.py in.jpg out.jpg"""
import sys
from PIL import Image
INK = (10, 11, 13); ICE = (98, 182, 232)
def duotone(src, dst):
    img = Image.open(src).convert('L')
    lut = []
    for v in range(256):
        t = (v/255)**1.15
        lut.extend(int(INK[i] + (ICE[i]-INK[i])*t) for i in range(3))
    Image.merge('RGB', [img.point(lut[i::3]) for i in range(3)]).save(dst, quality=84, optimize=True)
if __name__ == '__main__':
    duotone(sys.argv[1], sys.argv[2]); print('duotoned ->', sys.argv[2])

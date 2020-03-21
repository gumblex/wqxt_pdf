#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import sys
import math
import numpy as np
from PIL import Image, ImageStat, ImageFilter

_PIXWEIGHT = np.concatenate((np.arange(128, 0, -1), np.arange(0, 128))) / 128


def otsu_threshold(hist):
    total = sum(hist)
    sumB = 0
    wB = 0
    maximum = 0.0
    sum1 = np.dot(np.arange(256), hist)
    for i in range(256):
        wB += hist[i]
        wF = total - wB
        if wB == 0 or wF == 0:
            continue
        sumB += i * hist[i]
        mF = (sum1 - sumB) / wF
        between = wB * wF * ((sumB / wB) - mF) * ((sumB / wB) - mF)
        if between >= maximum:
            level = i + 1
            maximum = between
    return level


def auto_downgrade(pil_img, thumb_size=128, grey_cutoff=1, bw_ratio=0.99, bw_supersample=1):
    mode = pil_img.mode
    if mode == '1' and mode not in ('L', 'LA', 'RGB', 'RGBA'):
        # ignore special modes
        return pil_img
    elif mode == 'P':
        pil_img = pil_img.convert('RGB')
    elif mode == 'PA':
        pil_img = pil_img.convert('RGBA')
    bands = pil_img.getbands()
    alpha_band = False
    if bands[-1] == 'A':
        alpha_band = True
        if all(x == 255 for x in pil_img.getdata(len(bands) - 1)):
            alpha_band = False
    if bands[:3] == ('R', 'G', 'B'):
        thumb = pil_img.resize((thumb_size,thumb_size), resample=Image.BILINEAR)
        pixels = np.array(thumb.getdata(), dtype=float)[:, :3]
        pixels_max = np.max(pixels, axis=1)
        pixels_min = np.min(pixels, axis=1)
        val = np.mean(pixels_max - pixels_min)
        if val > grey_cutoff:
            if bands[-1] == 'A' and not alpha_band:
                return pil_img.convert('RGB')
            else:
                return pil_img
        if alpha_band:
            return pil_img.convert('LA')
        else:
            pil_img = pil_img.convert('L')
    if alpha_band:
        return pil_img
    hist = pil_img.histogram()[:256]
    if np.average(_PIXWEIGHT, weights=hist) > bw_ratio:
        if bw_supersample != 1:
            width, height = pil_img.size
            width = round(width * bw_supersample)
            height = round(height * bw_supersample)
            scaled = pil_img.resize((width, height), resample=Image.BICUBIC)
        else:
            scaled = pil_img
        threshold = otsu_threshold(hist)
        if 50 < threshold < 250:  # resonable range
            scaled = scaled.point(lambda p: p > threshold and 255)
        return scaled.convert('1', dither=Image.NONE)
    if bands[-1] == 'A':
        return pil_img.convert('L')
    return pil_img


def auto_encode(fp, quality=95, thumb_size=128, grey_cutoff=1, bw_ratio=0.99, bw_supersample=1):
    if isinstance(fp, str):
        with open(fp, 'rb') as f:
            orig_data = f.read()
    elif isinstance(fp, bytes):
        orig_data = fp
    else:
        orig_data = fp.read()
    orig_buf = io.BytesIO(orig_data)
    orig_size = len(orig_data)
    im = Image.open(orig_buf)
    out_im = auto_downgrade(im, thumb_size, grey_cutoff, bw_ratio)
    buf = io.BytesIO()
    if out_im.mode == '1':
        out_im.save(buf, 'TIFF', compression='group4')
        return buf.getvalue(), 'TIFF'
    elif out_im.mode[0] == 'L' or out_im.mode[-1] == 'A':
        out_im.save(buf, 'PNG', optimize=True)
        return buf.getvalue(), 'PNG'
    if im.format.startswith('JPEG'):
        out_format = 'PNG'
        out_im.save(buf, 'PNG', optimize=True)
    else:
        out_format = 'JPEG'
        out_im.convert('RGB').save(buf, 'JPEG', quality=quality, optimize=True)
    out_data = buf.getvalue()
    if len(out_data) > orig_size:
        if out_im.mode == im.mode:
            return orig_data, im.format
        else:
            buf = io.BytesIO()
            out_im.save(buf, 'PNG', optimize=True)
            return buf.getvalue(), 'PNG'
    else:
        return out_data, out_format


if __name__ == '__main__':
    input_file = sys.argv[1]
    output_prefix = sys.argv[2]
    output_data, output_format = auto_encode(input_file)
    if output_format == 'JPEG':
        output_name = output_prefix + '.jpg'
    else:
        output_name = output_prefix + '.' + output_format.lower()
    with open(output_name, 'wb') as f:
        f.write(output_data)

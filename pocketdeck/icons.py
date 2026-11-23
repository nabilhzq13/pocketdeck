"""Extract real Windows icons (apps, exes, shortcuts, folders) as PNG bytes, no Pillow needed.
Must run on a COM-initialised thread."""
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import struct
import zlib

shell32 = ctypes.WinDLL("shell32")
user32 = ctypes.WinDLL("user32")
gdi32 = ctypes.WinDLL("gdi32")
ole32 = ctypes.WinDLL("ole32")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s):
        import uuid
        return cls.from_buffer_copy(uuid.UUID(s).bytes_le)


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wt.HICON), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
                ("szDisplayName", wt.WCHAR * 260), ("szTypeName", wt.WCHAR * 80)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wt.LONG), ("bmWidth", wt.LONG), ("bmHeight", wt.LONG),
                ("bmWidthBytes", wt.LONG), ("bmPlanes", wt.WORD), ("bmBitsPixel", wt.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
                ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


shell32.SHGetFileInfoW.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.POINTER(SHFILEINFOW),
                                   wt.UINT, wt.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t
shell32.SHParseDisplayName.argtypes = [wt.LPCWSTR, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p), wt.ULONG,
                                       ctypes.POINTER(wt.ULONG)]
shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(GUID),
                                   ctypes.POINTER(ctypes.c_void_p)]
ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
user32.GetIconInfo.argtypes = [wt.HICON, ctypes.POINTER(ICONINFO)]
user32.DestroyIcon.argtypes = [wt.HICON]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.GetObjectW.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p]
gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                            ctypes.c_void_p, wt.UINT]
gdi32.DeleteObject.argtypes = [wt.HANDLE]

IID_IImageList = GUID.parse("46EB5926-582E-4017-9FDF-E8998DAA0950")
SHIL_JUMBO, SHIL_EXTRALARGE = 4, 2
_GetIcon = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, wt.UINT,
                              ctypes.POINTER(wt.HICON))
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)


def _sys_index(source):
    """source: 'app:<AppUserModelID>' or a file/folder path."""
    sfi = SHFILEINFOW()
    SHGFI_SYSICONINDEX, SHGFI_PIDL = 0x4000, 0x8
    if source.startswith("app:"):
        pidl = ctypes.c_void_p()
        hr = shell32.SHParseDisplayName("shell:AppsFolder\\" + source[4:], None,
                                        ctypes.byref(pidl), 0, None)
        if hr != 0 or not pidl:
            return None
        try:
            ok = shell32.SHGetFileInfoW(pidl, 0, ctypes.byref(sfi), ctypes.sizeof(sfi),
                                        SHGFI_SYSICONINDEX | SHGFI_PIDL)
        finally:
            ole32.CoTaskMemFree(pidl)
    else:
        path = ctypes.create_unicode_buffer(os.path.expandvars(source))
        ok = shell32.SHGetFileInfoW(ctypes.cast(path, ctypes.c_void_p), 0, ctypes.byref(sfi),
                                    ctypes.sizeof(sfi), SHGFI_SYSICONINDEX)
    return sfi.iIcon if ok else None


def _hicon(index, size):
    il = ctypes.c_void_p()
    if shell32.SHGetImageList(size, ctypes.byref(IID_IImageList), ctypes.byref(il)) != 0:
        return None
    vtbl = ctypes.cast(ctypes.cast(il, ctypes.POINTER(ctypes.c_void_p))[0],
                       ctypes.POINTER(ctypes.c_void_p))
    hicon = wt.HICON()
    hr = _GetIcon(vtbl[10])(il, index, 0x1, ctypes.byref(hicon))  # ILD_TRANSPARENT
    _Release(vtbl[2])(il)
    return hicon if hr == 0 and hicon else None


def _bitmap_pixels(hbm):
    bm = BITMAP()
    gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm))
    w, h = bm.bmWidth, abs(bm.bmHeight)
    bi = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h,
                          biPlanes=1, biBitCount=32, biCompression=0)
    buf = (ctypes.c_ubyte * (w * h * 4))()
    hdc = user32.GetDC(None)
    gdi32.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(bi), 0)
    user32.ReleaseDC(None, hdc)
    return w, h, bytearray(buf)


def _icon_rgba(hicon):
    ii = ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    try:
        if not ii.hbmColor:
            return None
        w, h, px = _bitmap_pixels(ii.hbmColor)
        if not any(px[3::4]):  # icon without alpha channel: use the mask
            _, _, mask = _bitmap_pixels(ii.hbmMask)
            px[3::4] = bytes(0 if mask[i] else 255 for i in range(0, len(mask), 4))
        px[0::4], px[2::4] = px[2::4], px[0::4]  # BGRA -> RGBA
        return w, h, px
    finally:
        if ii.hbmColor:
            gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            gdi32.DeleteObject(ii.hbmMask)


def _crop(w, h, px, cw, ch):
    rows = [bytes(px[y * w * 4:(y * w + cw) * 4]) for y in range(ch)]
    return cw, ch, bytearray(b"".join(rows))


def _alpha_bbox(w, h, px):
    xs, ys = [], []
    alpha = px[3::4]
    for y in range(h):
        row = alpha[y * w:(y + 1) * w]
        if any(row):
            ys.append(y)
            xs.append(next(i for i, a in enumerate(row) if a))
            xs.append(w - 1 - next(i for i, a in enumerate(reversed(row)) if a))
    if not ys:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def encode_png(w, h, rgba):
    raw = b"".join(b"\x00" + bytes(rgba[y * w * 4:(y + 1) * w * 4]) for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def extract_png(source):
    idx = _sys_index(source)
    if idx is None:
        return None
    for size in (SHIL_JUMBO, SHIL_EXTRALARGE):
        hicon = _hicon(idx, size)
        if not hicon:
            continue
        try:
            img = _icon_rgba(hicon)
        finally:
            user32.DestroyIcon(hicon)
        if not img:
            continue
        w, h, px = img
        box = _alpha_bbox(w, h, px)
        if not box:
            continue
        # Apps without a 256px icon get their 48px icon drawn in the top-left corner.
        if w >= 256 and box[2] <= 48 and box[3] <= 48:
            w, h, px = _crop(w, h, px, 48, 48)
        return encode_png(w, h, px)
    return None


class IconCache:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)

    def get(self, source):
        key = hashlib.sha1(source.lower().encode("utf-8")).hexdigest()[:20]
        path = os.path.join(self.folder, key + ".png")
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        data = extract_png(source)
        if data:
            with open(path, "wb") as f:
                f.write(data)
        return data

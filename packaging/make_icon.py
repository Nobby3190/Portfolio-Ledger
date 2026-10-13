"""Draw packaging/icon.png (1024x1024) with AppKit; scripts/make_icon.sh turns it into Ledger.icns.

The app's own vocabulary on a navy ink tile: ledger entries (description left, amount right), the
accountant's double rule, and under it the asset-allocation band from the dashboard as the total.
Colours are the app's (frontend/src/styles.css): the same as the topbar's .brand-mark, so the Dock
icon and the mark inside the window match.
"""

import AppKit as K

S = 1024


def rgb(hex_: str, alpha: float = 1.0) -> K.NSColor:
    h = hex_.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return K.NSColor.colorWithDeviceRed_green_blue_alpha_(r, g, b, alpha)


INK_TOP = rgb("#2a3a66")  # .brand-mark gradient
INK_BOTTOM = rgb("#121a30")
IVORY = "#f4efe4"  # entries and the double rule
SAPPHIRE_SOFT = "#a9bbe0"  # --brand-soft: the mark's second line
# Allocation band: brass and sapphire as in the mark, then their soft tints.
BAND = [rgb("#e2bf78"), rgb("#6f95e2"), rgb(SAPPHIRE_SOFT), rgb(IVORY)]


def bar(x: float, y: float, w: float, h: float, color: K.NSColor) -> None:
    color.setFill()
    K.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x, y), (w, h)), h / 2, h / 2).fill()


# Draw straight into a 1024px sRGB bitmap (NSImage.lockFocus renders at 2x in a calibrated space).
rep = K.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, S, S, 8, 4, True, False, K.NSDeviceRGBColorSpace, 0, 0
).bitmapImageRepByRetaggingWithColorSpace_(K.NSColorSpace.sRGBColorSpace())
K.NSGraphicsContext.saveGraphicsState()
K.NSGraphicsContext.setCurrentContext_(K.NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))

# Rounded-square body on the macOS icon grid (824px inside the 1024 canvas), ink gradient.
inset, body = 100, 824
tile = K.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((inset, inset), (body, body)), 185, 185)
K.NSGradient.alloc().initWithStartingColor_endingColor_(INK_TOP, INK_BOTTOM).drawInBezierPath_angle_(tile, -90)

# Content column on the tile, vertically centred (origin is bottom-left).
left, right = 236, 788
width = right - left


def rect(x: float, y: float, w: float, h: float, r: float, color: K.NSColor) -> None:
    color.setFill()
    K.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x, y), (w, h)), r, r).fill()


# Three ledger entries: a description on the left, its amount right-aligned.
thick = 40
for y, label_w, amount_w, color, alpha in (
    (673, 236, 150, IVORY, 1.0),
    (581, 300, 112, SAPPHIRE_SOFT, 1.0),
    (489, 196, 168, SAPPHIRE_SOFT, 0.55),
):
    bar(left, y, label_w, thick, rgb(color, alpha))
    bar(right - amount_w, y, amount_w, thick, rgb(color, alpha))

# The accountant's double rule under the column, then the total: the allocation band.
rect(left, 433, width, 10, 5, rgb(IVORY, 0.9))
rect(left, 413, width, 10, 5, rgb(IVORY, 0.9))
band_y, band_h, gap = 301, 64, 12
shares = (0.44, 0.27, 0.17, 0.12)
x = left
usable = width - gap * (len(shares) - 1)
for share, color in zip(shares, BAND):
    w = usable * share
    rect(x, band_y, w, band_h, 14, color)
    x += w + gap

K.NSGraphicsContext.restoreGraphicsState()

rep.representationUsingType_properties_(K.NSBitmapImageFileTypePNG, None).writeToFile_atomically_(
    "packaging/icon.png", True
)

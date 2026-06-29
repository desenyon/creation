// Renders the Creation app icon (1024×1024 PNG) headlessly via CoreGraphics.
// Usage: swift scripts/make_icon.swift <out.png>
import CoreGraphics
import ImageIO
import Foundation
import UniformTypeIdentifiers

let size = 1024
let cs = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
                          bytesPerRow: 0, space: cs,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
    exit(1)
}
let S = CGFloat(size)

// Rounded "squircle" plate with a cream → soft-pink gradient.
let inset = S * 0.055
let rect = CGRect(x: inset, y: inset, width: S - 2 * inset, height: S - 2 * inset)
let plate = CGPath(roundedRect: rect, cornerWidth: S * 0.225, cornerHeight: S * 0.225, transform: nil)
ctx.saveGState()
ctx.addPath(plate)
ctx.clip()
let colors = [
    CGColor(red: 0.992, green: 0.992, blue: 0.972, alpha: 1),
    CGColor(red: 0.988, green: 0.909, blue: 0.949, alpha: 1),
] as CFArray
let grad = CGGradient(colorsSpace: cs, colors: colors, locations: [0, 1])!
ctx.drawLinearGradient(grad, start: CGPoint(x: 0, y: S), end: CGPoint(x: S, y: 0), options: [])
ctx.restoreGState()

// Creation infinity mark: two facing arcs (blue over, pink under).
ctx.setLineCap(.round)
ctx.setLineWidth(S * 0.075)

ctx.setStrokeColor(CGColor(red: 0.262, green: 0.537, blue: 0.643, alpha: 1))
let top = CGMutablePath()
top.move(to: CGPoint(x: S * 0.30, y: S * 0.5))
top.addQuadCurve(to: CGPoint(x: S * 0.70, y: S * 0.5), control: CGPoint(x: S * 0.5, y: S * 0.83))
ctx.addPath(top); ctx.strokePath()

ctx.setStrokeColor(CGColor(red: 0.788, green: 0.471, blue: 0.620, alpha: 1))
let bot = CGMutablePath()
bot.move(to: CGPoint(x: S * 0.70, y: S * 0.5))
bot.addQuadCurve(to: CGPoint(x: S * 0.30, y: S * 0.5), control: CGPoint(x: S * 0.5, y: S * 0.17))
ctx.addPath(bot); ctx.strokePath()

guard let img = ctx.makeImage() else { exit(1) }
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"
let url = URL(fileURLWithPath: out)
guard let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    exit(1)
}
CGImageDestinationAddImage(dest, img, nil)
if !CGImageDestinationFinalize(dest) { exit(1) }
print("wrote \(out)")

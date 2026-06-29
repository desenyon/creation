// Renders the Creation social/OG card (1200×630 PNG) headlessly via CoreGraphics + CoreText.
// Usage: swift scripts/make_og.swift <out.png>
import CoreGraphics
import CoreText
import ImageIO
import Foundation
import UniformTypeIdentifiers

let W = 1200, H = 630
let cs = CGColorSpaceCreateDeviceRGB()
guard let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8,
                          bytesPerRow: 0, space: cs,
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { exit(1) }
let fw = CGFloat(W), fh = CGFloat(H)

// Background: cream → soft pink diagonal gradient.
let bg = CGGradient(colorsSpace: cs, colors: [
    CGColor(red: 0.984, green: 0.984, blue: 0.972, alpha: 1),
    CGColor(red: 0.988, green: 0.913, blue: 0.952, alpha: 1),
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: fh), end: CGPoint(x: fw, y: 0), options: [])

// Subtle pink corner glow.
if let glow = CGGradient(colorsSpace: cs, colors: [
    CGColor(red: 0.941, green: 0.565, blue: 0.722, alpha: 0.22),
    CGColor(red: 0.941, green: 0.565, blue: 0.722, alpha: 0.0),
] as CFArray, locations: [0, 1]) {
    ctx.drawRadialGradient(glow, startCenter: CGPoint(x: fw * 0.86, y: fh * 0.82), startRadius: 0,
                           endCenter: CGPoint(x: fw * 0.86, y: fh * 0.82), endRadius: 420, options: [])
}

// Creation infinity mark (top-left).
let mx: CGFloat = 96, my = fh - 92, ms: CGFloat = 64
ctx.setLineCap(.round)
ctx.setLineWidth(7)
ctx.setStrokeColor(CGColor(red: 0.262, green: 0.537, blue: 0.643, alpha: 1))
let top = CGMutablePath()
top.move(to: CGPoint(x: mx, y: my))
top.addQuadCurve(to: CGPoint(x: mx + ms, y: my), control: CGPoint(x: mx + ms/2, y: my + ms * 0.55))
ctx.addPath(top); ctx.strokePath()
ctx.setStrokeColor(CGColor(red: 0.788, green: 0.471, blue: 0.620, alpha: 1))
let bot = CGMutablePath()
bot.move(to: CGPoint(x: mx + ms, y: my))
bot.addQuadCurve(to: CGPoint(x: mx, y: my), control: CGPoint(x: mx + ms/2, y: my - ms * 0.55))
ctx.addPath(bot); ctx.strokePath()

func draw(_ text: String, font: CTFont, color: CGColor, x: CGFloat, y: CGFloat) {
    let attrs: [CFString: Any] = [
        kCTFontAttributeName: font,
        kCTForegroundColorAttributeName: color,
    ]
    guard let attr = CFAttributedStringCreate(nil, text as CFString, attrs as CFDictionary) else { return }
    let line = CTLineCreateWithAttributedString(attr)
    ctx.textPosition = CGPoint(x: x, y: y)
    CTLineDraw(line, ctx)
}

let serif = CTFontCreateWithName("Georgia" as CFString, 52, nil)
let sansBold = CTFontCreateWithName("HelveticaNeue-Bold" as CFString, 64, nil)
let sans = CTFontCreateWithName("HelveticaNeue" as CFString, 30, nil)
let sansMed = CTFontCreateWithName("HelveticaNeue-Medium" as CFString, 27, nil)

let ink = CGColor(red: 0.04, green: 0.04, blue: 0.04, alpha: 1)
let muted = CGColor(red: 0.42, green: 0.42, blue: 0.42, alpha: 1)
let pink = CGColor(red: 0.788, green: 0.471, blue: 0.620, alpha: 1)

draw("creation", font: serif, color: ink, x: mx + ms + 26, y: my - 18)

// Headline (two lines).
draw("A team of agents", font: sansBold, color: ink, x: 96, y: fh - 250)
draw("that never stop working.", font: sansBold, color: ink, x: 96, y: fh - 330)

draw("Agent operating system for software teams — local-first, on your keys.",
     font: sans, color: muted, x: 96, y: 150)
draw("creation.dev", font: sansMed, color: pink, x: 96, y: 80)

guard let img = ctx.makeImage() else { exit(1) }
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "og-image.png"
guard let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: out) as CFURL,
                                                 UTType.png.identifier as CFString, 1, nil) else { exit(1) }
CGImageDestinationAddImage(dest, img, nil)
if !CGImageDestinationFinalize(dest) { exit(1) }
print("wrote \(out)")

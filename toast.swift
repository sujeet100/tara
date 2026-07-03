// toast — a small, self-dismissing notification card in the top-right corner.
// The gentle sibling of the full-screen overlay: used for moments that deserve
// a glanceable visual cue but not an interrupt (lead alerts, wrap-up, lunch).
// Launched detached by brain.py; slides in, waits --duration seconds, fades
// out, exits. Clicking it opens --url (if given) and dismisses. It never takes
// focus (non-activating panel), so it can't yank the keyboard mid-thought.
//
// Args: --title <t> --message <m> --duration <sec> --theme <name> --url <u>

import AppKit
import Foundation

func arg(_ name: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: name), i + 1 < a.count { return a[i + 1] }
    return nil
}

let title = arg("--title") ?? "Tara"
let message = arg("--message") ?? ""
let duration = Double(arg("--duration") ?? "") ?? 8
let themeName = arg("--theme") ?? "midnight"
let urlStr = arg("--url") ?? ""
let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> NSColor {
    NSColor(calibratedRed: r, green: g, blue: b, alpha: 1)
}

// accent per overlay theme, so the toast feels like part of the same family
let ACCENTS: [String: NSColor] = [
    "midnight": rgb(0.45, 0.68, 1.00),
    "sunrise":  rgb(1.00, 0.77, 0.42),
    "forest":   rgb(0.35, 0.88, 0.62),
    "grape":    rgb(0.76, 0.58, 1.00),
    "mono":     rgb(0.92, 0.92, 0.95),
    "glass":    rgb(0.56, 0.78, 1.00),
]
let accent = ACCENTS[themeName] ?? ACCENTS["midnight"]!

func dismiss(open: Bool) {
    if open, !urlStr.isEmpty, let u = URL(string: urlStr) { NSWorkspace.shared.open(u) }
    NSApp.terminate(nil)
}

final class ToastView: NSView {
    override func mouseDown(with event: NSEvent) { dismiss(open: true) }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let panel = NSPanel(contentRect: .zero,
                    styleMask: [.borderless, .nonactivatingPanel],
                    backing: .buffered, defer: false)
panel.level = .statusBar
panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
panel.isOpaque = false
panel.backgroundColor = .clear
panel.hasShadow = true
panel.isFloatingPanel = true
panel.becomesKeyOnlyIfNeeded = true

let card = ToastView()
card.wantsLayer = true
card.layer?.backgroundColor = rgb(0.12, 0.10, 0.13).withAlphaComponent(0.96).cgColor
card.layer?.cornerRadius = 14
card.layer?.borderColor = NSColor(white: 1, alpha: 0.12).cgColor
card.layer?.borderWidth = 1

let stripe = NSView()
stripe.wantsLayer = true
stripe.layer?.backgroundColor = accent.cgColor
stripe.layer?.cornerRadius = 2.5
stripe.translatesAutoresizingMaskIntoConstraints = false
stripe.widthAnchor.constraint(equalToConstant: 5).isActive = true
stripe.heightAnchor.constraint(equalToConstant: 40).isActive = true

let icon = NSTextField(labelWithString: "🌸")
icon.font = NSFont.systemFont(ofSize: 22)

let titleLabel = NSTextField(labelWithString: title)
titleLabel.font = NSFont.systemFont(ofSize: 14, weight: .semibold)
titleLabel.textColor = .white
titleLabel.lineBreakMode = .byTruncatingTail
titleLabel.maximumNumberOfLines = 1
titleLabel.preferredMaxLayoutWidth = 250

let msgLabel = NSTextField(labelWithString: message)
msgLabel.font = NSFont.systemFont(ofSize: 12.5, weight: .regular)
msgLabel.textColor = NSColor(white: 1, alpha: 0.72)
msgLabel.lineBreakMode = .byWordWrapping
msgLabel.maximumNumberOfLines = 2
msgLabel.preferredMaxLayoutWidth = 250
msgLabel.isHidden = message.isEmpty

let text = NSStackView(views: message.isEmpty ? [titleLabel] : [titleLabel, msgLabel])
text.orientation = .vertical
text.alignment = .leading
text.spacing = 2

let row = NSStackView(views: [stripe, icon, text])
row.orientation = .horizontal
row.alignment = .centerY
row.spacing = 10
row.edgeInsets = NSEdgeInsets(top: 12, left: 12, bottom: 12, right: 16)
row.translatesAutoresizingMaskIntoConstraints = false

card.addSubview(row)
NSLayoutConstraint.activate([
    row.leadingAnchor.constraint(equalTo: card.leadingAnchor),
    row.trailingAnchor.constraint(equalTo: card.trailingAnchor),
    row.topAnchor.constraint(equalTo: card.topAnchor),
    row.bottomAnchor.constraint(equalTo: card.bottomAnchor),
])

panel.contentView = card
let size = row.fittingSize
let vis = (NSScreen.main ?? NSScreen.screens.first!).visibleFrame
let margin: CGFloat = 14
let final = NSRect(x: vis.maxX - size.width - margin,
                   y: vis.maxY - size.height - margin,
                   width: size.width, height: size.height)

if reduceMotion {
    panel.setFrame(final, display: true)
    panel.orderFront(nil)
} else {
    var start = final
    start.origin.x = vis.maxX + 10   // just off-screen right
    panel.setFrame(start, display: true)
    panel.orderFront(nil)
    NSAnimationContext.runAnimationGroup { ctx in
        ctx.duration = 0.35
        ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
        panel.animator().setFrame(final, display: true)
    }
}

DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
    if reduceMotion { dismiss(open: false); return }
    NSAnimationContext.runAnimationGroup({ ctx in
        ctx.duration = 0.45
        panel.animator().alphaValue = 0
    }, completionHandler: { dismiss(open: false) })
}
// belt and braces: never linger past duration + a beat, whatever animations do
DispatchQueue.main.asyncAfter(deadline: .now() + duration + 2) { dismiss(open: false) }

app.run()

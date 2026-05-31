// overlay — a borderless, full-screen attention window that floats above
// everything (including full-screen Spaces). Launched detached by brain.py, it
// lives ON ITS OWN until the user acts: an internal 1-second timer drives a live
// countdown, so the periodic brain never has to "hold" it open.
//
// On a button press it writes the user's choice to <runtime>/<id>.choice
//   join | ack | snooze:<min>   then exits.
//
// Args: --id <id> --title <t> --start <iso8601> --url <u>
//       --mode meeting|error --theme <name> --runtime <dir>

import AppKit
import Foundation

func arg(_ name: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: name), i + 1 < a.count { return a[i + 1] }
    return nil
}

let id = arg("--id") ?? "unknown"
let title = arg("--title") ?? "Meeting"
let urlStr = arg("--url") ?? ""
let mode = arg("--mode") ?? "meeting"
let themeName = arg("--theme") ?? "midnight"
let runtimeDir = arg("--runtime") ?? NSHomeDirectory() + "/.meeting-assistant/runtime"
let startDate: Date? = {
    guard let s = arg("--start") else { return nil }
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = f.date(from: s) { return d }
    f.formatOptions = [.withInternetDateTime]
    return f.date(from: s)
}()

func writeChoice(_ value: String) {
    let path = (runtimeDir as NSString).appendingPathComponent("\(id).choice")
    try? value.write(toFile: path, atomically: true, encoding: .utf8)
}

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> NSColor {
    NSColor(calibratedRed: r, green: g, blue: b, alpha: 1)
}

// ----------------------------------------------------------------------------
// Themes: gradient top/bottom, accent (Join button), and an icon glyph.
// ----------------------------------------------------------------------------
struct Theme {
    let top: NSColor, bottom: NSColor, accent: NSColor, icon: String
    var translucent: Bool = false   // frosted-glass blur over your screen
}
let THEMES: [String: Theme] = [
    "midnight": Theme(top: rgb(0.05, 0.08, 0.20), bottom: rgb(0.10, 0.13, 0.34),
                      accent: rgb(0.30, 0.56, 1.00), icon: "🔔"),
    "sunrise":  Theme(top: rgb(0.98, 0.36, 0.45), bottom: rgb(0.99, 0.64, 0.33),
                      accent: rgb(0.20, 0.12, 0.18), icon: "☀️"),
    "forest":   Theme(top: rgb(0.03, 0.20, 0.16), bottom: rgb(0.07, 0.34, 0.28),
                      accent: rgb(0.22, 0.82, 0.55), icon: "🌲"),
    "grape":    Theme(top: rgb(0.17, 0.07, 0.28), bottom: rgb(0.33, 0.11, 0.49),
                      accent: rgb(0.70, 0.48, 1.00), icon: "🍇"),
    "mono":     Theme(top: rgb(0.10, 0.10, 0.11), bottom: rgb(0.17, 0.17, 0.19),
                      accent: rgb(0.92, 0.92, 0.95), icon: "⏰"),
    "glass":    Theme(top: rgb(0.10, 0.12, 0.22), bottom: rgb(0.20, 0.10, 0.26),
                      accent: rgb(0.45, 0.72, 1.00), icon: "🪟", translucent: true),
]
let theme = (mode == "error")
    ? Theme(top: rgb(0.42, 0.04, 0.05), bottom: rgb(0.66, 0.10, 0.10),
            accent: rgb(1.0, 0.85, 0.30), icon: "⚠️")
    : (THEMES[themeName] ?? THEMES["midnight"]!)

// ----------------------------------------------------------------------------

final class OverlayController: NSObject {
    let window: NSWindow
    let countdown = NSTextField(labelWithString: "")
    var timer: Timer?
    let isError: Bool

    override init() {
        isError = (mode == "error")
        let screen = NSScreen.main!.frame
        window = NSWindow(contentRect: screen, styleMask: .borderless,
                          backing: .buffered, defer: false)
        super.init()
        configureWindow()
        buildContent()
        startTimer()
    }

    func configureWindow() {
        window.level = NSWindow.Level(rawValue: Int(CGShieldingWindowLevel()))
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        window.hasShadow = false

        let root = NSView(frame: window.contentView!.bounds)
        root.autoresizingMask = [.width, .height]
        root.wantsLayer = true

        if theme.translucent {
            // frosted glass: blur whatever's behind, then a soft colour tint
            window.isOpaque = false
            window.backgroundColor = .clear
            let blur = NSVisualEffectView(frame: root.bounds)
            blur.autoresizingMask = [.width, .height]
            blur.blendingMode = .behindWindow
            blur.material = .hudWindow
            blur.state = .active
            root.addSubview(blur)
            let tint = NSView(frame: root.bounds)
            tint.autoresizingMask = [.width, .height]
            tint.wantsLayer = true
            let grad = CAGradientLayer()
            grad.frame = root.bounds
            grad.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
            grad.colors = [theme.top.withAlphaComponent(0.45).cgColor,
                           theme.bottom.withAlphaComponent(0.45).cgColor]
            grad.startPoint = CGPoint(x: 0, y: 1)
            grad.endPoint = CGPoint(x: 1, y: 0)
            tint.layer?.addSublayer(grad)
            root.addSubview(tint)
        } else {
            window.isOpaque = true
            let grad = CAGradientLayer()
            grad.frame = root.bounds
            grad.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
            grad.colors = [theme.top.cgColor, theme.bottom.cgColor]
            grad.startPoint = CGPoint(x: 0, y: 1)
            grad.endPoint = CGPoint(x: 1, y: 0)
            root.layer?.addSublayer(grad)
        }
        window.contentView = root
    }

    func pill(_ view: NSView, alpha: CGFloat, radius: CGFloat) {
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor(white: 0, alpha: alpha).cgColor
        view.layer?.cornerRadius = radius
    }

    func makeButton(_ label: String, _ action: Selector, filled: Bool) -> NSButton {
        let b = NSButton(title: label, target: self, action: action)
        b.bezelStyle = .regularSquare
        b.isBordered = false
        b.wantsLayer = true
        b.font = NSFont.systemFont(ofSize: 21, weight: .semibold)
        b.layer?.cornerRadius = 14
        if filled {
            b.layer?.backgroundColor = theme.accent.cgColor
            let dark = theme.accent.brightnessComponent > 0.6
            b.attributedTitle = NSAttributedString(string: label, attributes: [
                .foregroundColor: dark ? NSColor.black : NSColor.white,
                .font: NSFont.systemFont(ofSize: 21, weight: .bold)])
        } else {
            b.layer?.backgroundColor = NSColor(white: 1, alpha: 0.14).cgColor
            b.layer?.borderColor = NSColor(white: 1, alpha: 0.30).cgColor
            b.layer?.borderWidth = 1
            b.attributedTitle = NSAttributedString(string: label, attributes: [
                .foregroundColor: NSColor.white,
                .font: NSFont.systemFont(ofSize: 21, weight: .medium)])
        }
        b.translatesAutoresizingMaskIntoConstraints = false
        b.widthAnchor.constraint(greaterThanOrEqualToConstant: 190).isActive = true
        b.heightAnchor.constraint(equalToConstant: 62).isActive = true
        return b
    }

    func buildContent() {
        let content = window.contentView!

        let icon = NSTextField(labelWithString: theme.icon)
        icon.font = NSFont.systemFont(ofSize: 90)
        icon.alignment = .center

        let heading = NSTextField(labelWithString: isError ? "Calendar unreachable" : title)
        heading.font = NSFont.systemFont(ofSize: 60, weight: .bold)
        heading.textColor = .white
        heading.alignment = .center
        heading.lineBreakMode = .byTruncatingTail
        heading.maximumNumberOfLines = 2

        let timeLabel = NSTextField(labelWithString: meetingClock())
        timeLabel.font = NSFont.systemFont(ofSize: 26, weight: .medium)
        timeLabel.textColor = NSColor(white: 1, alpha: 0.75)
        timeLabel.alignment = .center

        countdown.font = NSFont.monospacedDigitSystemFont(ofSize: 34, weight: .semibold)
        countdown.textColor = .white
        countdown.alignment = .center
        let cdWrap = NSView()
        cdWrap.translatesAutoresizingMaskIntoConstraints = false
        pill(cdWrap, alpha: 0.22, radius: 22)
        countdown.translatesAutoresizingMaskIntoConstraints = false
        cdWrap.addSubview(countdown)
        NSLayoutConstraint.activate([
            countdown.leadingAnchor.constraint(equalTo: cdWrap.leadingAnchor, constant: 28),
            countdown.trailingAnchor.constraint(equalTo: cdWrap.trailingAnchor, constant: -28),
            countdown.topAnchor.constraint(equalTo: cdWrap.topAnchor, constant: 12),
            countdown.bottomAnchor.constraint(equalTo: cdWrap.bottomAnchor, constant: -12),
        ])

        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 22
        if isError {
            buttons.addArrangedSubview(makeButton("Dismiss", #selector(dismiss), filled: true))
        } else {
            if !urlStr.isEmpty {
                buttons.addArrangedSubview(makeButton("Join now", #selector(join), filled: true))
            }
            buttons.addArrangedSubview(makeButton("I'm in", #selector(imIn), filled: false))
            buttons.addArrangedSubview(makeButton("Snooze 1 min", #selector(snooze), filled: false))
        }

        let stack = NSStackView(views: [icon, heading, timeLabel, cdWrap, buttons])
        stack.orientation = .vertical
        stack.spacing = 22
        stack.alignment = .centerX
        stack.setCustomSpacing(34, after: cdWrap)
        stack.translatesAutoresizingMaskIntoConstraints = false
        if isError { timeLabel.isHidden = true }

        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: content.widthAnchor, multiplier: 0.86),
        ])
    }

    func meetingClock() -> String {
        guard let s = startDate else { return "" }
        let f = DateFormatter(); f.dateFormat = "h:mm a"
        return f.string(from: s)
    }

    func startTimer() {
        updateCountdown()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.updateCountdown()
        }
    }

    func updateCountdown() {
        guard !isError, let start = startDate else {
            if isError { countdown.stringValue = "Reconnect your calendar feed to clear this." }
            return
        }
        let secs = Int(start.timeIntervalSinceNow)
        let m = abs(secs) / 60, s = abs(secs) % 60
        let clock = String(format: "%d:%02d", m, s)
        countdown.stringValue = secs >= 0 ? "starts in \(clock)" : "started \(clock) ago"
        countdown.textColor = secs >= 0 ? .white : NSColor.systemOrange
    }

    func show() {
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
    }

    @objc func join() {
        if let u = URL(string: urlStr) { NSWorkspace.shared.open(u) }
        writeChoice("join"); quit()
    }
    @objc func imIn()    { writeChoice("ack"); quit() }
    @objc func snooze()  { writeChoice("snooze:1"); quit() }
    @objc func dismiss() { writeChoice("ack"); quit() }
    func quit() { timer?.invalidate(); NSApp.terminate(nil) }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let controller = OverlayController()
controller.show()
app.run()

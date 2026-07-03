// overlay — a borderless, full-screen attention window that floats above
// everything (including full-screen Spaces). Launched detached by brain.py, it
// lives ON ITS OWN until the user acts: an internal 1-second timer drives a live
// countdown, so the periodic brain never has to "hold" it open.
//
// "Daybreak" design: the theme paints a calm sky while there's time, with a
// progress ring depleting around the countdown. The moment the meeting starts
// the WHOLE sky burns to a universal alarm palette and slowly pulses — the
// visuals escalate the same way Tara's voice does. One window per screen, so
// the interrupt lands wherever you're looking. ⏎ joins, esc snoozes.
//
// On a button press it writes the user's choice to <runtime>/<id>.choice
//   join | ack | snooze:<min>   then exits.
//
// Args: --id <id> --title <t> --start <iso8601> --url <u>
//       --mode meeting|error --theme <name> --runtime <dir>
//       --lead <min> --snooze <min> --line <text> --lateline <text>
// The last four are optional (older callers, preview-theme.sh, still work).

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
let leadMin = Double(arg("--lead") ?? "") ?? 3
let snoozeMin = Int(arg("--snooze") ?? "") ?? 2
let taraLine = arg("--line") ?? ""
let taraLateLine = arg("--lateline") ?? ""
let startDate: Date? = {
    guard let s = arg("--start") else { return nil }
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let d = f.date(from: s) { return d }
    f.formatOptions = [.withInternetDateTime]
    return f.date(from: s)
}()
let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion

func writeChoice(_ value: String) {
    let path = (runtimeDir as NSString).appendingPathComponent("\(id).choice")
    try? value.write(toFile: path, atomically: true, encoding: .utf8)
}

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> NSColor {
    NSColor(calibratedRed: r, green: g, blue: b, alpha: 1)
}

func rounded(_ size: CGFloat, _ weight: NSFont.Weight) -> NSFont {
    let base = NSFont.systemFont(ofSize: size, weight: weight)
    if let desc = base.fontDescriptor.withDesign(.rounded),
       let f = NSFont(descriptor: desc, size: size) { return f }
    return base
}

func platformName(_ url: String) -> String {
    if url.contains("meet.google.com") { return "Google Meet" }
    if url.contains("zoom.us") { return "Zoom" }
    if url.contains("teams.") { return "Teams" }
    return url.isEmpty ? "" : "Video call"
}

// ----------------------------------------------------------------------------
// Themes paint the CALM sky (gradient + ring/button accent + horizon glow).
// The LATE palette is universal — once you're overdue it's an alarm, and an
// alarm looks the same in every theme: the sky burns.
// ----------------------------------------------------------------------------
struct Theme {
    let top: NSColor, bottom: NSColor, accent: NSColor, glow: NSColor
    var translucent: Bool = false   // frosted-glass blur over your screen
}
let THEMES: [String: Theme] = [
    "midnight": Theme(top: rgb(0.05, 0.08, 0.20), bottom: rgb(0.12, 0.15, 0.38),
                      accent: rgb(0.45, 0.68, 1.00), glow: rgb(0.30, 0.45, 1.00)),
    "sunrise":  Theme(top: rgb(0.13, 0.10, 0.27), bottom: rgb(0.64, 0.30, 0.32),
                      accent: rgb(1.00, 0.77, 0.42), glow: rgb(1.00, 0.65, 0.33)),
    "forest":   Theme(top: rgb(0.03, 0.20, 0.16), bottom: rgb(0.09, 0.38, 0.30),
                      accent: rgb(0.35, 0.88, 0.62), glow: rgb(0.25, 0.75, 0.45)),
    "grape":    Theme(top: rgb(0.17, 0.07, 0.28), bottom: rgb(0.38, 0.14, 0.54),
                      accent: rgb(0.76, 0.58, 1.00), glow: rgb(0.62, 0.38, 0.95)),
    "mono":     Theme(top: rgb(0.10, 0.10, 0.11), bottom: rgb(0.19, 0.19, 0.22),
                      accent: rgb(0.92, 0.92, 0.95), glow: rgb(0.55, 0.55, 0.62)),
    "glass":    Theme(top: rgb(0.10, 0.12, 0.22), bottom: rgb(0.20, 0.10, 0.26),
                      accent: rgb(0.56, 0.78, 1.00), glow: rgb(0.40, 0.60, 1.00),
                      translucent: true),
]
let LATE_TOP = rgb(0.24, 0.05, 0.08)
let LATE_BOTTOM = rgb(0.66, 0.20, 0.10)
let LATE_ACCENT = rgb(1.00, 0.58, 0.38)
let LATE_GLOW = rgb(1.00, 0.42, 0.16)

let theme = (mode == "error")
    ? Theme(top: rgb(0.42, 0.04, 0.05), bottom: rgb(0.66, 0.10, 0.10),
            accent: rgb(1.0, 0.85, 0.30), glow: rgb(1.0, 0.5, 0.2))
    : (THEMES[themeName] ?? THEMES["midnight"]!)

// ----------------------------------------------------------------------------
// Actions are global — with one window per screen, any window's button acts
// for all of them (the process exits, taking every window along).
// ----------------------------------------------------------------------------
enum Act {
    static func join() {
        if !urlStr.isEmpty, let u = URL(string: urlStr) { NSWorkspace.shared.open(u) }
        writeChoice(urlStr.isEmpty ? "ack" : "join")
        NSApp.terminate(nil)
    }
    static func imIn() { writeChoice("ack"); NSApp.terminate(nil) }
    static func snooze() { writeChoice("snooze:\(snoozeMin)"); NSApp.terminate(nil) }
    static func dismiss() { writeChoice("ack"); NSApp.terminate(nil) }
}

final class KeyWindow: NSWindow {
    override var canBecomeKey: Bool { true }   // borderless windows refuse key by default
}

final class HoverButton: NSButton {
    var normalBG: CGColor = NSColor(white: 1, alpha: 0.14).cgColor
    var hoverBG: CGColor = NSColor(white: 1, alpha: 0.26).cgColor
    override func updateTrackingAreas() {
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: bounds,
                                       options: [.mouseEnteredAndExited, .activeAlways],
                                       owner: self, userInfo: nil))
        super.updateTrackingAreas()
    }
    override func mouseEntered(with event: NSEvent) { layer?.backgroundColor = hoverBG }
    override func mouseExited(with event: NSEvent) { layer?.backgroundColor = normalBG }
}

// ----------------------------------------------------------------------------

final class OverlayController: NSObject {
    let window: NSWindow
    let isError = (mode == "error")

    let kicker = NSTextField(labelWithString: "")
    let digits = NSTextField(labelWithString: "")
    let digitsSub = NSTextField(labelWithString: "")
    let tara = NSTextField(labelWithString: "")
    var gradLayer = CAGradientLayer()
    var glowLayer = CAGradientLayer()
    var vignette = CAGradientLayer()
    var ringFill = CAShapeLayer()
    var joinBtn: HoverButton?
    var timer: Timer?
    var isLate = false

    init(screen: NSScreen) {
        window = KeyWindow(contentRect: screen.frame, styleMask: .borderless,
                           backing: .buffered, defer: false)
        super.init()
        configureWindow()
        buildContent()
        startTimer()
    }

    // ---- window + sky -------------------------------------------------------
    func configureWindow() {
        window.level = NSWindow.Level(rawValue: Int(CGShieldingWindowLevel()))
        window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        window.hasShadow = false

        let root = NSView(frame: window.contentView!.bounds)
        root.autoresizingMask = [.width, .height]
        root.wantsLayer = true
        let b = root.bounds

        if theme.translucent {
            window.isOpaque = false
            window.backgroundColor = .clear
            let blur = NSVisualEffectView(frame: b)
            blur.autoresizingMask = [.width, .height]
            blur.blendingMode = .behindWindow
            blur.material = .hudWindow
            blur.state = .active
            root.addSubview(blur)
        } else {
            window.isOpaque = true
        }

        gradLayer.frame = b
        gradLayer.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        let alpha: CGFloat = theme.translucent ? 0.55 : 1.0
        gradLayer.colors = [theme.top.withAlphaComponent(alpha).cgColor,
                            theme.bottom.withAlphaComponent(alpha).cgColor]
        gradLayer.startPoint = CGPoint(x: 0.5, y: 1)
        gradLayer.endPoint = CGPoint(x: 0.5, y: 0)

        // the sun, waiting under the horizon — warms the bottom of the sky
        glowLayer.type = .radial
        glowLayer.frame = CGRect(x: -b.width * 0.25, y: -b.height * 0.65,
                                 width: b.width * 1.5, height: b.height * 1.1)
        glowLayer.colors = [theme.glow.withAlphaComponent(0.55).cgColor,
                            theme.glow.withAlphaComponent(0).cgColor]
        glowLayer.startPoint = CGPoint(x: 0.5, y: 0.5)
        glowLayer.endPoint = CGPoint(x: 1, y: 1)

        // breathing red edge for the late state (invisible until then)
        vignette.type = .radial
        vignette.frame = b
        vignette.autoresizingMask = [.layerWidthSizable, .layerHeightSizable]
        vignette.colors = [LATE_GLOW.withAlphaComponent(0).cgColor,
                           LATE_GLOW.withAlphaComponent(0.45).cgColor]
        vignette.startPoint = CGPoint(x: 0.5, y: 0.5)
        vignette.endPoint = CGPoint(x: 1.1, y: 1.1)
        vignette.opacity = 0

        let sky = NSView(frame: b)
        sky.autoresizingMask = [.width, .height]
        sky.wantsLayer = true
        sky.layer?.addSublayer(gradLayer)
        sky.layer?.addSublayer(glowLayer)
        sky.layer?.addSublayer(vignette)
        root.addSubview(sky)
        window.contentView = root
    }

    // ---- widgets ------------------------------------------------------------
    func makeButton(_ label: String, _ action: Selector, filled: Bool) -> NSButton {
        let b = HoverButton(title: label, target: self, action: action)
        b.bezelStyle = .regularSquare
        b.isBordered = false
        b.wantsLayer = true
        b.layer?.cornerRadius = 16
        if filled {
            b.normalBG = theme.accent.cgColor
            b.hoverBG = theme.accent.blended(withFraction: 0.18, of: .white)?.cgColor
                        ?? theme.accent.cgColor
            let dark = theme.accent.brightnessComponent > 0.6
            b.attributedTitle = NSAttributedString(string: label, attributes: [
                .foregroundColor: dark ? NSColor.black : NSColor.white,
                .font: rounded(21, .bold)])
        } else {
            b.layer?.borderColor = NSColor(white: 1, alpha: 0.30).cgColor
            b.layer?.borderWidth = 1
            b.attributedTitle = NSAttributedString(string: label, attributes: [
                .foregroundColor: NSColor.white,
                .font: rounded(21, .medium)])
        }
        b.layer?.backgroundColor = b.normalBG
        b.translatesAutoresizingMaskIntoConstraints = false
        b.widthAnchor.constraint(greaterThanOrEqualToConstant: 190).isActive = true
        b.heightAnchor.constraint(equalToConstant: 62).isActive = true
        return b
    }

    func capsLabel(_ text: String, size: CGFloat, alpha: CGFloat) -> NSTextField {
        let l = NSTextField(labelWithString: "")
        l.attributedStringValue = NSAttributedString(
            string: text.uppercased(),
            attributes: [.font: rounded(size, .semibold), .kern: size * 0.18,
                         .foregroundColor: NSColor(white: 1, alpha: alpha)])
        l.alignment = .center
        return l
    }

    func chip(_ text: String) -> NSView {
        let l = NSTextField(labelWithString: text)
        l.font = rounded(15, .semibold)
        l.textColor = NSColor(white: 1, alpha: 0.9)
        l.translatesAutoresizingMaskIntoConstraints = false
        let wrap = NSView()
        wrap.wantsLayer = true
        wrap.layer?.backgroundColor = NSColor(white: 1, alpha: 0.16).cgColor
        wrap.layer?.cornerRadius = 12
        wrap.translatesAutoresizingMaskIntoConstraints = false
        wrap.addSubview(l)
        NSLayoutConstraint.activate([
            l.leadingAnchor.constraint(equalTo: wrap.leadingAnchor, constant: 12),
            l.trailingAnchor.constraint(equalTo: wrap.trailingAnchor, constant: -12),
            l.topAnchor.constraint(equalTo: wrap.topAnchor, constant: 4),
            l.bottomAnchor.constraint(equalTo: wrap.bottomAnchor, constant: -4),
        ])
        return wrap
    }

    func keyHint(_ key: String, _ what: String) -> NSTextField {
        let s = NSMutableAttributedString()
        s.append(NSAttributedString(string: " \(key) ", attributes: [
            .font: rounded(13, .semibold),
            .foregroundColor: NSColor(white: 1, alpha: 0.85),
            .backgroundColor: NSColor(white: 1, alpha: 0.15)]))
        s.append(NSAttributedString(string: "  \(what)", attributes: [
            .font: rounded(13, .medium),
            .foregroundColor: NSColor(white: 1, alpha: 0.55)]))
        let l = NSTextField(labelWithString: "")
        l.attributedStringValue = s
        return l
    }

    func makeRing() -> NSView {
        let size: CGFloat = 250
        let box = NSView()
        box.translatesAutoresizingMaskIntoConstraints = false
        box.widthAnchor.constraint(equalToConstant: size).isActive = true
        box.heightAnchor.constraint(equalToConstant: size).isActive = true
        box.wantsLayer = true

        let path = CGPath(ellipseIn: CGRect(x: 8, y: 8, width: size - 16, height: size - 16),
                          transform: nil)
        let track = CAShapeLayer()
        track.path = path
        track.fillColor = NSColor.clear.cgColor
        track.strokeColor = NSColor(white: 1, alpha: 0.16).cgColor
        track.lineWidth = 9
        box.layer?.addSublayer(track)

        ringFill.path = path
        ringFill.fillColor = NSColor.clear.cgColor
        ringFill.strokeColor = theme.accent.cgColor
        ringFill.lineWidth = 9
        ringFill.lineCap = .round
        ringFill.strokeEnd = 1
        ringFill.frame = CGRect(x: 0, y: 0, width: size, height: size)
        // start the stroke at 12 o'clock
        ringFill.setAffineTransform(CGAffineTransform(translationX: size / 2, y: size / 2)
            .rotated(by: .pi / 2).translatedBy(x: -size / 2, y: -size / 2))
        box.layer?.addSublayer(ringFill)

        digits.font = NSFont.monospacedDigitSystemFont(ofSize: 52, weight: .bold)
        digits.textColor = .white
        digits.alignment = .center
        digits.translatesAutoresizingMaskIntoConstraints = false
        digitsSub.translatesAutoresizingMaskIntoConstraints = false
        digitsSub.alignment = .center
        box.addSubview(digits)
        box.addSubview(digitsSub)
        NSLayoutConstraint.activate([
            digits.centerXAnchor.constraint(equalTo: box.centerXAnchor),
            digits.centerYAnchor.constraint(equalTo: box.centerYAnchor, constant: -8),
            digitsSub.centerXAnchor.constraint(equalTo: box.centerXAnchor),
            digitsSub.topAnchor.constraint(equalTo: digits.bottomAnchor, constant: 4),
        ])
        return box
    }

    // ---- content ------------------------------------------------------------
    func buildContent() {
        let content = window.contentView!

        if isError {
            let icon = NSTextField(labelWithString: "⚠️")
            icon.font = NSFont.systemFont(ofSize: 90)
            let heading = NSTextField(labelWithString: "Calendar unreachable")
            heading.font = rounded(54, .bold)
            heading.textColor = .white
            let msg = NSTextField(labelWithString: "Reconnect your calendar feed to clear this.")
            msg.font = rounded(22, .medium)
            msg.textColor = NSColor(white: 1, alpha: 0.8)
            let stack = NSStackView(views: [icon, heading, msg,
                makeButton("Dismiss", #selector(dismissA), filled: true)])
            stack.orientation = .vertical
            stack.spacing = 26
            stack.alignment = .centerX
            stack.translatesAutoresizingMaskIntoConstraints = false
            content.addSubview(stack)
            NSLayoutConstraint.activate([
                stack.centerXAnchor.constraint(equalTo: content.centerXAnchor),
                stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            ])
            return
        }

        kicker.attributedStringValue = capsLabel("Starting soon", size: 15, alpha: 0.75)
            .attributedStringValue
        kicker.alignment = .center

        let heading = NSTextField(labelWithString: title)
        heading.font = rounded(58, .bold)
        heading.textColor = .white
        heading.alignment = .center
        heading.lineBreakMode = .byTruncatingTail
        heading.maximumNumberOfLines = 2

        let whenRow = NSStackView()
        whenRow.orientation = .horizontal
        whenRow.spacing = 12
        if let s = startDate {
            let f = DateFormatter(); f.dateFormat = "h:mm a"
            let t = NSTextField(labelWithString: f.string(from: s))
            t.font = rounded(24, .medium)
            t.textColor = NSColor(white: 1, alpha: 0.8)
            whenRow.addArrangedSubview(t)
        }
        let plat = platformName(urlStr)
        if !plat.isEmpty { whenRow.addArrangedSubview(chip(plat)) }

        let ring = makeRing()

        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.spacing = 22
        if !urlStr.isEmpty {
            let jb = makeButton("Join now", #selector(joinA), filled: true) as! HoverButton
            joinBtn = jb
            buttons.addArrangedSubview(jb)
        }
        buttons.addArrangedSubview(makeButton("I'm in", #selector(imInA), filled: false))
        buttons.addArrangedSubview(makeButton("Snooze \(snoozeMin) min", #selector(snoozeA), filled: false))

        tara.stringValue = taraLine
        tara.font = NSFont.systemFont(ofSize: 20, weight: .regular).withItalics()
        tara.textColor = NSColor(white: 1, alpha: 0.85)
        tara.alignment = .center
        tara.lineBreakMode = .byWordWrapping
        tara.maximumNumberOfLines = 2
        tara.isHidden = taraLine.isEmpty

        let keys = NSStackView(views: [keyHint("⏎", "Join"), keyHint("esc", "Snooze")])
        keys.orientation = .horizontal
        keys.spacing = 26

        let stack = NSStackView(views: [kicker, heading, whenRow, ring, buttons, tara, keys])
        stack.orientation = .vertical
        stack.spacing = 22
        stack.alignment = .centerX
        stack.setCustomSpacing(30, after: ring)
        stack.setCustomSpacing(30, after: buttons)
        stack.setCustomSpacing(14, after: tara)
        stack.translatesAutoresizingMaskIntoConstraints = false

        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            stack.widthAnchor.constraint(lessThanOrEqualTo: content.widthAnchor, multiplier: 0.86),
        ])
    }

    // ---- countdown + escalation ---------------------------------------------
    func startTimer() {
        updateCountdown()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            self?.updateCountdown()
        }
    }

    func updateCountdown() {
        guard !isError, let start = startDate else { return }
        let secs = Int(start.timeIntervalSinceNow)
        let m = abs(secs) / 60, s = abs(secs) % 60
        digits.stringValue = String(format: "%d:%02d", m, s)
        digitsSub.attributedStringValue = capsLabel(secs >= 0 ? "until start" : "overdue",
                                                    size: 12, alpha: 0.6).attributedStringValue
        if secs >= 0 {
            ringFill.strokeEnd = CGFloat(max(0, min(1, Double(secs) / (leadMin * 60))))
        } else if !isLate {
            isLate = true
            enterLateState()
        }
    }

    /// The sky burns: cross-fade to the universal alarm palette, swap the copy
    /// to Tara's upset register, and start a slow breathing pulse at the edges.
    func enterLateState() {
        let dur = reduceMotion ? 0.0 : 1.4
        let alpha: CGFloat = theme.translucent ? 0.65 : 1.0
        let newColors = [LATE_TOP.withAlphaComponent(alpha).cgColor,
                         LATE_BOTTOM.withAlphaComponent(alpha).cgColor]
        let fade = CABasicAnimation(keyPath: "colors")
        fade.fromValue = gradLayer.colors
        fade.toValue = newColors
        fade.duration = dur
        gradLayer.add(fade, forKey: "colors")
        gradLayer.colors = newColors

        glowLayer.colors = [LATE_GLOW.withAlphaComponent(0.75).cgColor,
                            LATE_GLOW.withAlphaComponent(0).cgColor]
        ringFill.strokeColor = LATE_ACCENT.cgColor
        ringFill.strokeEnd = 1
        joinBtn?.normalBG = LATE_ACCENT.cgColor
        joinBtn?.hoverBG = LATE_ACCENT.blended(withFraction: 0.2, of: .white)?.cgColor
                           ?? LATE_ACCENT.cgColor
        joinBtn?.layer?.backgroundColor = LATE_ACCENT.cgColor

        kicker.attributedStringValue = capsLabel("Meeting in progress — without you",
                                                 size: 15, alpha: 0.9).attributedStringValue
        if !taraLateLine.isEmpty {
            tara.stringValue = taraLateLine
            tara.isHidden = false
        }

        if reduceMotion {
            vignette.opacity = 0.5
        } else {
            vignette.opacity = 0.6
            let pulse = CABasicAnimation(keyPath: "opacity")
            pulse.fromValue = 0.6
            pulse.toValue = 0.2
            pulse.duration = 1.6
            pulse.autoreverses = true
            pulse.repeatCount = .infinity
            pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            vignette.add(pulse, forKey: "breathe")
        }
    }

    func show(makeKey: Bool) {
        if reduceMotion {
            if makeKey { window.makeKeyAndOrderFront(nil) } else { window.orderFront(nil) }
            return
        }
        window.alphaValue = 0
        if makeKey { window.makeKeyAndOrderFront(nil) } else { window.orderFront(nil) }
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.5
            window.animator().alphaValue = 1
        }
    }

    @objc func joinA() { Act.join() }
    @objc func imInA() { Act.imIn() }
    @objc func snoozeA() { Act.snooze() }
    @objc func dismissA() { Act.dismiss() }
}

extension NSFont {
    func withItalics() -> NSFont {
        NSFont(descriptor: fontDescriptor.withSymbolicTraits(.italic), size: pointSize) ?? self
    }
}

// ----------------------------------------------------------------------------

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

// one overlay per screen — the interrupt should land wherever you're looking
let controllers = NSScreen.screens.map { OverlayController(screen: $0) }

NSEvent.addLocalMonitorForEvents(matching: .keyDown) { ev in
    if mode == "error" {
        if ev.keyCode == 36 || ev.keyCode == 53 { Act.dismiss(); return nil }
        return ev
    }
    switch ev.keyCode {
    case 36, 76: Act.join(); return nil     // return / keypad enter
    case 53: Act.snooze(); return nil       // esc
    default: return ev
    }
}

NSApp.activate(ignoringOtherApps: true)
for (i, c) in controllers.enumerated() { c.show(makeKey: i == 0) }
app.run()

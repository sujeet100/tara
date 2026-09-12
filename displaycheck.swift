// displaycheck — prints "1" if the screen is genuinely ON (Sujit could see a
// window right now), "0" if it's asleep. Reads display power state only; needs no
// permission and captures nothing, like miccheck/camcheck.
//
// Why the brain cares: launchd keeps ticking through a "dark wake", the brief
// hourly wake macOS takes with the lid shut to check mail and run maintenance.
// A tick during dark wake used to fire the full fail-loud alarm — voice into a
// sleeping speaker, and an overlay stacked onto a screen nobody was looking at.
// Those alarms weren't warnings, they were the backlog that greeted him on open.
//
// CGDisplayIsAsleep covers display sleep; an empty console session (fast user
// switching, login window) also means nothing we draw would be seen. Any failure
// to answer prints "1" — if we can't tell, we must assume he IS there and let the
// alarm through. Fail loud, not silent.

import CoreGraphics
import Foundation

func screenIsOn() -> Bool {
    if CGDisplayIsAsleep(CGMainDisplayID()) != 0 {
        return false
    }
    guard let session = CGSessionCopyCurrentDictionary() as? [String: Any] else {
        return true   // no session info — assume he's there
    }
    if let onConsole = session["kCGSSessionOnConsoleKey"] as? Bool, !onConsole {
        return false
    }
    return true
}

print(screenIsOn() ? "1" : "0")

// remindercheck — dump every incomplete Apple Reminder as JSON on stdout:
//   [{"id": "…", "title": "Submit timesheet", "list": "Work",
//     "due": "2026-07-31T16:00:00+05:30", "has_time": true}, …]
// "due" is absent when the reminder has no due date; a date-only reminder gets
// "yyyy-MM-dd" with has_time=false. Recurring reminders surface as their next
// incomplete occurrence, so a weekly "timesheet" fires every week.
//
// First use triggers macOS's one-time Reminders-access prompt (and prints
// {"error":"denied"} on refusal). The prompt only appears if an Info.plist with
// a usage description is linked INTO the binary — hence the extra flags:
//   swiftc -O remindercheck.swift -o bin/remindercheck \
//     -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist \
//     -Xlinker remindercheck-info.plist
// Recompiling changes the binary's identity, so macOS may ask again after one.

import EventKit
import Foundation

let store = EKEventStore()
var granted = false
let authSem = DispatchSemaphore(value: 0)
if #available(macOS 14.0, *) {
    store.requestFullAccessToReminders { ok, _ in granted = ok; authSem.signal() }
} else {
    store.requestAccess(to: .reminder) { ok, _ in granted = ok; authSem.signal() }
}
authSem.wait()

guard granted else {
    print("{\"error\": \"denied\"}")
    exit(2)
}

let dateOnly = DateFormatter()
dateOnly.dateFormat = "yyyy-MM-dd"
let dateTime = DateFormatter()
dateTime.dateFormat = "yyyy-MM-dd'T'HH:mm:ssZZZZZ"

var out: [[String: Any]] = []
let fetchSem = DispatchSemaphore(value: 0)
let pred = store.predicateForIncompleteReminders(withDueDateStarting: nil,
                                                 ending: nil, calendars: nil)
store.fetchReminders(matching: pred) { rems in
    for r in rems ?? [] {
        var item: [String: Any] = [
            "id": r.calendarItemIdentifier,
            "title": r.title ?? "Untitled",
            "list": r.calendar?.title ?? "",
        ]
        if let comps = r.dueDateComponents,
           let date = Calendar.current.date(from: comps) {
            let hasTime = comps.hour != nil
            item["due"] = hasTime ? dateTime.string(from: date) : dateOnly.string(from: date)
            item["has_time"] = hasTime
        }
        out.append(item)
    }
    fetchSem.signal()
}
fetchSem.wait()

let data = try! JSONSerialization.data(withJSONObject: out)
print(String(data: data, encoding: .utf8)!)

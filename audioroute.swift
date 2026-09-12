// audioroute — two small CoreAudio jobs for the voice worker:
//
//   audioroute check
//     JSON snapshot of output routing, e.g.
//     {"default_id":73,"default_name":"WH-1000XM4","default_transport":"bluetooth",
//      "builtin_id":52,"builtin_name":"MacBook Pro Speakers"}
//     voice.py uses default_transport to spot the "Bluetooth headphones are
//     connected but maybe lying on the desk" trap.
//
//   audioroute play <file> [--device <id>] [--volume <0..1>]
//     Play an audio file to a SPECIFIC output device (afplay can only use the
//     default one). This is how announcements get mirrored to the built-in
//     speakers while headphones hold the default route.
//
// Recompile: swiftc -O audioroute.swift -o bin/audioroute

import AVFoundation
import CoreAudio
import Foundation

func getUInt32(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector,
               scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> UInt32? {
    var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: scope,
                                          mElement: kAudioObjectPropertyElementMain)
    var val = UInt32(0)
    var size = UInt32(MemoryLayout<UInt32>.size)
    return AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &val) == noErr ? val : nil
}

func deviceName(_ dev: AudioDeviceID) -> String {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
                                          mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var name: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(dev, &addr, 0, nil, &size, &name) == noErr,
          let cf = name?.takeRetainedValue() else { return "" }
    return cf as String
}

func hasOutput(_ dev: AudioDeviceID) -> Bool {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreams,
                                          mScope: kAudioObjectPropertyScopeOutput,
                                          mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(0)
    guard AudioObjectGetPropertyDataSize(dev, &addr, 0, nil, &size) == noErr else { return false }
    return size > 0
}

func defaultOutputDevice() -> AudioDeviceID? {
    getUInt32(AudioObjectID(kAudioObjectSystemObject),
              kAudioHardwarePropertyDefaultOutputDevice).map { AudioDeviceID($0) }
}

func allDevices() -> [AudioDeviceID] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
                                          mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(0)
    guard AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject),
                                         &addr, 0, nil, &size) == noErr else { return [] }
    var devs = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject),
                                     &addr, 0, nil, &size, &devs) == noErr else { return [] }
    return devs
}

func transportLabel(_ dev: AudioDeviceID) -> String {
    switch getUInt32(dev, kAudioDevicePropertyTransportType) {
    case kAudioDeviceTransportTypeBluetooth?,
         kAudioDeviceTransportTypeBluetoothLE?: return "bluetooth"
    case kAudioDeviceTransportTypeBuiltIn?:     return "builtin"
    case kAudioDeviceTransportTypeUSB?:         return "usb"
    case kAudioDeviceTransportTypeAirPlay?:     return "airplay"
    case kAudioDeviceTransportTypeHDMI?:        return "hdmi"
    case kAudioDeviceTransportTypeDisplayPort?: return "displayport"
    case kAudioDeviceTransportTypeAggregate?:   return "aggregate"
    case kAudioDeviceTransportTypeVirtual?:     return "virtual"
    default:                                    return "other"
    }
}

func jsonEscape(_ s: String) -> String {
    s.replacingOccurrences(of: "\\", with: "\\\\")
     .replacingOccurrences(of: "\"", with: "\\\"")
}

func check() {
    var fields: [String] = []
    if let dev = defaultOutputDevice() {
        fields.append("\"default_id\":\(dev)")
        fields.append("\"default_name\":\"\(jsonEscape(deviceName(dev)))\"")
        fields.append("\"default_transport\":\"\(transportLabel(dev))\"")
    }
    if let builtin = allDevices().first(where: { hasOutput($0) && transportLabel($0) == "builtin" }) {
        fields.append("\"builtin_id\":\(builtin)")
        fields.append("\"builtin_name\":\"\(jsonEscape(deviceName(builtin)))\"")
    }
    print("{\(fields.joined(separator: ","))}")
}

func flag(_ name: String) -> String? {
    let a = CommandLine.arguments
    if let i = a.firstIndex(of: name), i + 1 < a.count { return a[i + 1] }
    return nil
}

func play(path: String) {
    let engine = AVAudioEngine()
    let player = AVAudioPlayerNode()
    engine.attach(player)
    guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
        FileHandle.standardError.write("cannot read \(path)\n".data(using: .utf8)!)
        exit(1)
    }
    engine.connect(player, to: engine.mainMixerNode, format: file.processingFormat)
    if let idStr = flag("--device"), let id = UInt32(idStr),
       let au = engine.outputNode.audioUnit {
        var dev = AudioDeviceID(id)
        AudioUnitSetProperty(au, kAudioOutputUnitProperty_CurrentDevice,
                             kAudioUnitScope_Global, 0, &dev,
                             UInt32(MemoryLayout<AudioDeviceID>.size))
    }
    player.volume = Float(flag("--volume") ?? "") ?? 1.0
    do { try engine.start() } catch {
        FileHandle.standardError.write("engine start failed\n".data(using: .utf8)!)
        exit(1)
    }
    let done = DispatchSemaphore(value: 0)
    player.scheduleFile(file, at: nil, completionCallbackType: .dataPlayedBack) { _ in
        done.signal()
    }
    player.play()
    done.wait()
    Thread.sleep(forTimeInterval: 0.1)   // let the tail of the buffer drain
    engine.stop()
}

let args = CommandLine.arguments
switch args.count > 1 ? args[1] : "check" {
case "check":
    check()
case "play" where args.count > 2:
    play(path: args[2])
default:
    FileHandle.standardError.write(
        "usage: audioroute check | play <file> [--device <id>] [--volume <0..1>]\n"
            .data(using: .utf8)!)
    exit(64)
}

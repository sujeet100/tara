// miccheck — prints "1" if the default audio INPUT device is currently capturing
// (i.e. some app has the mic live), else "0". This is an app-agnostic "you're in
// a call" signal: covers Zoom, Google Meet (Brave PWA / Arc), Teams, etc.
// Querying kAudioDevicePropertyDeviceIsRunningSomewhere reads device state only —
// it does NOT capture audio, so it needs no microphone permission.

import CoreAudio
import Foundation

func defaultInputDevice() -> AudioDeviceID? {
    var deviceID = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(
        AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &deviceID)
    return status == noErr ? deviceID : nil
}

func isRunningSomewhere(_ device: AudioDeviceID) -> Bool {
    var running = UInt32(0)
    var size = UInt32(MemoryLayout<UInt32>.size)
    var addr = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(device, &addr, 0, nil, &size, &running)
    return status == noErr && running != 0
}

if let dev = defaultInputDevice(), isRunningSomewhere(dev) {
    print("1")
} else {
    print("0")
}

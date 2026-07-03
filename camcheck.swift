// camcheck — prints "1" if any video INPUT device (camera) is currently capturing
// (i.e. some app has the camera live), else "0". Companion to miccheck: when
// video is turned on, that's a strong "I've really joined" signal. Reads
// kCMIODevicePropertyDeviceIsRunningSomewhere — device state only, captures no
// video, so it needs no camera permission.

import CoreMediaIO
import Foundation

let scope = CMIOObjectPropertyScope(kCMIOObjectPropertyScopeGlobal)
let element = CMIOObjectPropertyElement(0)  // main element

func videoDevices() -> [CMIOObjectID] {
    var addr = CMIOObjectPropertyAddress(
        mSelector: CMIOObjectPropertySelector(kCMIOHardwarePropertyDevices),
        mScope: scope, mElement: element)
    var dataSize: UInt32 = 0
    guard CMIOObjectGetPropertyDataSize(
        CMIOObjectID(kCMIOObjectSystemObject), &addr, 0, nil, &dataSize) == noErr,
        dataSize > 0 else { return [] }
    let count = Int(dataSize) / MemoryLayout<CMIOObjectID>.size
    var devices = [CMIOObjectID](repeating: 0, count: count)
    var used: UInt32 = 0
    guard CMIOObjectGetPropertyData(
        CMIOObjectID(kCMIOObjectSystemObject), &addr, 0, nil,
        dataSize, &used, &devices) == noErr else { return [] }
    return devices
}

func isRunningSomewhere(_ device: CMIOObjectID) -> Bool {
    var addr = CMIOObjectPropertyAddress(
        mSelector: CMIOObjectPropertySelector(kCMIODevicePropertyDeviceIsRunningSomewhere),
        mScope: scope, mElement: element)
    var running: UInt32 = 0
    let size = UInt32(MemoryLayout<UInt32>.size)
    var used: UInt32 = 0
    let status = CMIOObjectGetPropertyData(device, &addr, 0, nil, size, &used, &running)
    return status == noErr && running != 0
}

let active = videoDevices().contains { isRunningSomewhere($0) }
print(active ? "1" : "0")

// Print "<windowID> <x> <y> <w> <h>" for the Connect IQ simulator's largest on-screen window.
import CoreGraphics
import Foundation
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
var best: (Int, CGRect)? = nil
for w in list {
    let owner = (w[kCGWindowOwnerName as String] as? String ?? "").lowercased()
    guard owner.contains("simulator") || owner.contains("connectiq") else { continue }
    var r = CGRect.zero
    if let b = w[kCGWindowBounds as String] { r = CGRect(dictionaryRepresentation: b as! CFDictionary) ?? .zero }
    let id = w[kCGWindowNumber as String] as! Int
    if best == nil || r.width * r.height > best!.1.width * best!.1.height { best = (id, r) }
}
if let b = best { print("\(b.0) \(Int(b.1.minX)) \(Int(b.1.minY)) \(Int(b.1.width)) \(Int(b.1.height))") }

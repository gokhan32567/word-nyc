import Foundation
import UIKit
import OneSignalFramework

/// OneSignal push for the noon "Tonight's picks". Started from AppDelegate so a tap on a notification that
/// launches the app is never missed; the web page picks the tap up through WordNYCPlugin.takePendingOpen.
public final class WordNYCPush: NSObject, OSNotificationClickListener {
    public static let shared = WordNYCPush()
    public static let appId = "d9f2eefb-d834-4054-92cc-422321667627"
    static let opened = Notification.Name("WordNYCPushOpened")

    private let lock = NSLock()
    private var pending: [String: Any]?
    private var started = false

    /// Call once from application(_:didFinishLaunchingWithOptions:).
    public static func start(launchOptions: [UIApplication.LaunchOptionsKey: Any]?) {
        guard !shared.started else { return }
        shared.started = true
        OneSignal.initialize(appId, withLaunchOptions: launchOptions)
        OneSignal.Notifications.addClickListener(shared)
    }

    // A notification was tapped. scraper/notify.py puts the page to open in data.path,
    // e.g. "/?show=birdland-1050&source=noon".
    public func onClick(event: OSNotificationClickEvent) {
        let data = event.notification.additionalData ?? [:]
        var path = (data["path"] as? String) ?? "/?source=noon"
        if !path.hasPrefix("/") { path = "/?source=noon" }
        setPending(["path": path, "id": event.notification.notificationId ?? ""])
    }

    func setPending(_ value: [String: Any]) {
        lock.lock()
        pending = value
        lock.unlock()
        NotificationCenter.default.post(name: WordNYCPush.opened, object: nil)
    }

    /// The tap waiting to be handled, if any (cleared once taken).
    func takePending() -> [String: Any]? {
        lock.lock()
        defer { lock.unlock() }
        let value = pending
        pending = nil
        return value
    }
}

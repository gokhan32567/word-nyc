import Foundation
import UIKit
import WebKit
import SafariServices
import UserNotifications
import Capacitor
import OneSignalFramework

/// Native features for the Word NYC app. The site (https://word-nyc.com) runs in the web view and calls these
/// through wn.js: Capacitor.nativePromise('WordNYC', method, options).
///
/// - Push: notification permission, OneSignal tags for favorite venues (fav_<slug>), taps on the noon push
/// - Links: other websites open in an in-app Safari view, maps in Apple Maps, so the app never becomes a browser
/// - No ads: a content blocker stops ad networks in every page the app shows
/// - Share sheet for links and the story image; haptics
/// - Offline: keeps the latest lineup and the favorites list on the phone
@objc(WordNYCPlugin)
public class WordNYCPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "WordNYCPlugin"
    public let jsName = "WordNYC"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "pushState", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "enablePush", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "disablePush", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setTags", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "takePendingOpen", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "share", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "haptic", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setFavorites", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getFavorites", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "saveLineup", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "getLineup", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openExternal", returnType: CAPPluginReturnPromise)
    ]

    static let site = "https://word-nyc.com"
    static let ownHosts: Set<String> = ["word-nyc.com", "www.word-nyc.com"]
    private let favoritesKey = "wn.favs"
    private let pushOffKey = "wn.pushOff"  // the person turned the noon notification off inside the app

    override public func load() {
        NotificationCenter.default.addObserver(self, selector: #selector(pushOpened), name: WordNYCPush.opened, object: nil)
        NotificationCenter.default.addObserver(self, selector: #selector(openedURL(_:)), name: .capacitorOpenURL, object: nil)
        DispatchQueue.main.async { [weak self] in
            guard let webView = self?.bridge?.webView else { return }
            webView.allowsBackForwardNavigationGestures = true  // swipe back from a venue page to the map
            webView.allowsLinkPreview = false
            webView.isOpaque = false
            webView.backgroundColor = UIColor(red: 13 / 255, green: 18 / 255, blue: 48 / 255, alpha: 1)
            webView.scrollView.backgroundColor = webView.backgroundColor
            self?.blockAds(in: webView)
        }
    }

    // MARK: - No ads inside the app

    /// The site gates AdSense out of the app itself (wn.js); this is the second lock, for every page.
    private func blockAds(in webView: WKWebView) {
        // WebKit's rule regexes have no "|", so one rule per ad host.
        let hosts = ["googlesyndication", "doubleclick", "googleadservices", "adservice\\.google",
                     "fundingchoicesmessages\\.google", "googletagservices", "adtrafficquality\\.google"]
        let rules: [[String: Any]] = hosts.map {
            ["trigger": ["url-filter": "^https?://[^/]*" + $0 + "\\."], "action": ["type": "block"]]
        }
        guard let data = try? JSONSerialization.data(withJSONObject: rules), let json = String(data: data, encoding: .utf8) else { return }
        let store = WKContentRuleListStore.default()
        let id = "wordnyc-no-ads-v1"
        store?.lookUpContentRuleList(forIdentifier: id) { list, _ in
            if let list = list {
                webView.configuration.userContentController.add(list)
                return
            }
            store?.compileContentRuleList(forIdentifier: id, encodedContentRuleList: json) { list, error in
                if let list = list { webView.configuration.userContentController.add(list) }
                if let error = error { CAPLog.print("WordNYC: ad filter not compiled: \(error)") }
            }
        }
    }

    // MARK: - Links: keep the app the app

    @objc override public func shouldOverrideLoad(_ navigationAction: WKNavigationAction) -> NSNumber? {
        guard let url = navigationAction.request.url, let scheme = url.scheme?.lowercased() else { return nil }
        let topLevel = navigationAction.targetFrame == nil || navigationAction.targetFrame?.isMainFrame == true
        guard topLevel else { return nil }  // iframes etc.: Capacitor's default
        switch scheme {
        case "http", "https":
            let host = (url.host ?? "").lowercased()
            if WordNYCPlugin.ownHosts.contains(host) { return nil }  // the site itself stays in the web view
            DispatchQueue.main.async { self.open(url) }
            return NSNumber(value: true)
        case "capacitor", "about", "data", "blob":
            return nil
        default:  // mailto:, tel:, sms:, maps:, itms-apps: ...
            DispatchQueue.main.async { UIApplication.shared.open(url) }
            return NSNumber(value: true)
        }
    }

    /// Maps and App Store links go to their apps; everything else (ticket sellers, venue sites) opens in an
    /// in-app Safari view: a purchase of a real-world event ticket on the seller's own site.
    private func open(_ url: URL) {
        let host = (url.host ?? "").lowercased()
        let toApp = host == "maps.apple.com" || host == "apps.apple.com" || host == "maps.google.com"
            || host == "goo.gl" || host == "maps.app.goo.gl"
            || ((host == "www.google.com" || host == "google.com") && url.path.hasPrefix("/maps"))
        if toApp {
            UIApplication.shared.open(url)
            return
        }
        guard let presenter = bridge?.viewController else {
            UIApplication.shared.open(url)
            return
        }
        let config = SFSafariViewController.Configuration()
        config.barCollapsingEnabled = true
        let safari = SFSafariViewController(url: url, configuration: config)
        safari.preferredBarTintColor = UIColor(red: 13 / 255, green: 18 / 255, blue: 48 / 255, alpha: 1)
        safari.preferredControlTintColor = UIColor(red: 1, green: 194 / 255, blue: 75 / 255, alpha: 1)
        safari.dismissButtonStyle = .done
        (presenter.presentedViewController ?? presenter).present(safari, animated: true)
    }

    @objc func openExternal(_ call: CAPPluginCall) {
        guard let raw = call.getString("url"), let url = URL(string: raw), ["http", "https"].contains(url.scheme ?? "") else {
            call.reject("Needs an http(s) url")
            return
        }
        DispatchQueue.main.async {
            self.open(url)
            call.resolve()
        }
    }

    // MARK: - Deep links: wordnyc://open/<path>  (e.g. wordnyc://open/?show=birdland-1050)

    @objc private func openedURL(_ note: Notification) {
        guard let info = note.object as? [String: Any], let url = info["url"] as? URL,
              url.scheme?.lowercased() == "wordnyc" else { return }
        var path = url.path.isEmpty ? "/" : url.path
        if let query = url.query { path += "?" + query }
        guard let target = URL(string: WordNYCPlugin.site + path) else { return }
        DispatchQueue.main.async { [weak self] in
            _ = self?.bridge?.webView?.load(URLRequest(url: target))
        }
    }

    // MARK: - Push

    @objc private func pushOpened() {
        notifyListeners("pushOpen", data: [:])
    }

    @objc func takePendingOpen(_ call: CAPPluginCall) {
        call.resolve(WordNYCPush.shared.takePending() ?? [:])
    }

    private func readPushState(_ completion: @escaping ([String: Any]) -> Void) {
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            let permission: String
            switch settings.authorizationStatus {
            case .authorized, .provisional, .ephemeral: permission = "granted"
            case .denied: permission = "denied"
            default: permission = "default"
            }
            let off = UserDefaults.standard.bool(forKey: self.pushOffKey)
            completion(["permission": permission, "optedIn": permission == "granted" && !off])
        }
    }

    @objc func pushState(_ call: CAPPluginCall) {
        readPushState { call.resolve($0) }
    }

    /// Asks iOS for permission the first time; after a "Don't Allow" it opens Settings instead.
    @objc func enablePush(_ call: CAPPluginCall) {
        UserDefaults.standard.set(false, forKey: pushOffKey)
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            switch settings.authorizationStatus {
            case .notDetermined:
                DispatchQueue.main.async {
                    OneSignal.Notifications.requestPermission({ accepted in
                        if accepted { OneSignal.User.pushSubscription.optIn() }
                        self.readPushState { call.resolve($0) }
                    }, fallbackToSettings: false)
                }
            case .denied:
                DispatchQueue.main.async {
                    let settingsURL: String
                    if #available(iOS 16.0, *) {
                        settingsURL = UIApplication.openNotificationSettingsURLString
                    } else {
                        settingsURL = UIApplication.openSettingsURLString
                    }
                    if let url = URL(string: settingsURL) { UIApplication.shared.open(url) }
                    self.readPushState { call.resolve($0) }
                }
            default:
                OneSignal.User.pushSubscription.optIn()
                self.readPushState { call.resolve($0) }
            }
        }
    }

    /// Stops the noon notification for this phone (OneSignal opt-out), without touching iOS permission.
    @objc func disablePush(_ call: CAPPluginCall) {
        UserDefaults.standard.set(true, forKey: pushOffKey)
        OneSignal.User.pushSubscription.optOut()
        readPushState { call.resolve($0) }
    }

    /// Favorite venues as OneSignal tags: { add: { "fav_smalls-jazz-club": "1" }, remove: ["fav_x"] }
    @objc func setTags(_ call: CAPPluginCall) {
        var add: [String: String] = [:]
        for (key, value) in call.getObject("add") ?? [:] {
            if key.hasPrefix("fav_"), key.count <= 100 { add[key] = "\(value)" }
        }
        let remove = (call.getArray("remove", String.self) ?? []).filter { $0.hasPrefix("fav_") }
        if !remove.isEmpty { OneSignal.User.removeTags(remove) }
        if !add.isEmpty { OneSignal.User.addTags(add) }
        call.resolve()
    }

    // MARK: - Share sheet

    @objc func share(_ call: CAPPluginCall) {
        var items: [Any] = []
        if let base64 = call.getString("image"), let data = Data(base64Encoded: base64), let image = UIImage(data: data) {
            items.append(image)
        }
        if let text = call.getString("text"), !text.isEmpty { items.append(text) }
        if let raw = call.getString("url"), let url = URL(string: raw) { items.append(url) }
        if items.isEmpty, let title = call.getString("title") { items.append(title) }
        guard !items.isEmpty else {
            call.reject("Nothing to share")
            return
        }
        DispatchQueue.main.async {
            guard let presenter = self.bridge?.viewController else {
                call.reject("No view")
                return
            }
            let sheet = UIActivityViewController(activityItems: items, applicationActivities: nil)
            sheet.completionWithItemsHandler = { activity, completed, _, _ in
                call.resolve(["completed": completed, "activity": activity?.rawValue ?? ""])
            }
            if let pop = sheet.popoverPresentationController {  // iPad
                pop.sourceView = presenter.view
                pop.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 1, height: 1)
                pop.permittedArrowDirections = []
            }
            presenter.present(sheet, animated: true)
        }
    }

    @objc func haptic(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            call.resolve()
        }
    }

    // MARK: - On-device copies (favorites, tonight's lineup for offline use)

    @objc func setFavorites(_ call: CAPPluginCall) {
        UserDefaults.standard.set(call.getString("json") ?? "[]", forKey: favoritesKey)
        call.resolve()
    }

    @objc func getFavorites(_ call: CAPPluginCall) {
        call.resolve(["json": UserDefaults.standard.string(forKey: favoritesKey) ?? "[]"])
    }

    private var lineupFile: URL? {
        guard let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else { return nil }
        let folder = dir.appendingPathComponent("WordNYC", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder.appendingPathComponent("lineup.json")
    }

    @objc func saveLineup(_ call: CAPPluginCall) {
        guard let json = call.getString("json"), let file = lineupFile else {
            call.reject("No lineup")
            return
        }
        do {
            try Data(json.utf8).write(to: file, options: .atomic)
            call.resolve()
        } catch {
            call.reject("Couldn't save the lineup", nil, error)
        }
    }

    @objc func getLineup(_ call: CAPPluginCall) {
        guard let file = lineupFile, let data = try? Data(contentsOf: file), let json = String(data: data, encoding: .utf8) else {
            call.resolve(["json": ""])
            return
        }
        call.resolve(["json": json])
    }
}

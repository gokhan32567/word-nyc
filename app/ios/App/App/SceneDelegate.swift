import UIKit
import Capacitor

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = CAPBridgeViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)

        // Opened from a word-nyc.com link (a shared show): show that page once the map has loaded.
        if let url = connectionOptions.userActivities.first(where: { $0.activityType == NSUserActivityTypeBrowsingWeb })?.webpageURL {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.open(url) }
        }
    }

    /// Loads a word-nyc.com link (e.g. /?show=...) in the app's web view.
    private func open(_ url: URL) {
        guard let host = url.host, host == "word-nyc.com" || host == "www.word-nyc.com",
              let bridge = window?.rootViewController as? CAPBridgeViewController else { return }
        bridge.webView?.load(URLRequest(url: url))
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
        if userActivity.activityType == NSUserActivityTypeBrowsingWeb, let url = userActivity.webpageURL {
            open(url)  // a word-nyc.com link tapped while the app was running
        }
    }
}

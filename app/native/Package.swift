// swift-tools-version: 5.9
// Word NYC's native plugin. Capacitor's CLI adds it to ios/App/CapApp-SPM/Package.swift as "WordnycNative"
// (the npm package name "wordnyc-native", converted by Capacitor), so the names below must stay as they are.
import PackageDescription

let package = Package(
    name: "WordnycNative",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "WordnycNative", targets: ["WordnycNative"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", from: "8.0.0"),
        .package(url: "https://github.com/OneSignal/OneSignal-XCFramework", from: "5.8.0")
    ],
    targets: [
        .target(
            name: "WordnycNative",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
                .product(name: "OneSignalFramework", package: "OneSignal-XCFramework")
            ],
            path: "ios/Sources/WordnycNative",
            resources: [.copy("PrivacyInfo.xcprivacy")]
        )
    ]
)

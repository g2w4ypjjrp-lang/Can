// swift-tools-version: 6.0
// ATICore: iOS uygulamasının platformdan bağımsız çekirdeği (protokol, imza, doğrulama, durum).
// Apple platformlarında CryptoKit, Linux'ta (CI/geliştirme) swift-crypto kullanılır.
import PackageDescription

let package = Package(
    name: "ATICore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "ATICore", targets: ["ATICore"])],
    dependencies: [
        .package(url: "https://github.com/apple/swift-crypto.git", "3.0.0"..<"6.0.0")
    ],
    targets: [
        .target(
            name: "ATICore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto", condition: .when(platforms: [.linux]))
            ]
        ),
        .testTarget(name: "ATICoreTests", dependencies: ["ATICore"]),
    ]
)

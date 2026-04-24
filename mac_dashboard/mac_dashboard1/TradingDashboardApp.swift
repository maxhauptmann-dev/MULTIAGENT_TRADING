import SwiftUI

@main
struct TradingDashboardApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowStyle(.automatic)
        .commands {
            CommandGroup(replacing: .appInfo) {
                Button("About Trading Dashboard") {
                    // About action
                }
            }
        }
    }
}

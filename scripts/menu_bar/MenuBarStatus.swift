import AppKit

// WhiteNight 菜单栏状态入口（阶段 7）。
// 构建：./scripts/build_menu_bar.sh（使用 swiftc，无需 Xcode 工程）。
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let api = URL(string: "http://127.0.0.1:8765/healthz")!
    private let web = URL(string: "http://127.0.0.1:8765/")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "小白"
        refreshMenu()
    }

    @objc private func openWeb() {
        NSWorkspace.shared.open(web)
    }

    @objc private func checkHealth() {
        URLSession.shared.dataTask(with: api) { [weak self] _, response, _ in
            guard let self else { return }
            let healthy = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async {
                let item = NSMenuItem(title: healthy ? "服务运行中 ✓" : "服务未响应 ✗", action: nil, keyEquivalent: "")
                item.isEnabled = false
                self.statusItem.button?.title = healthy ? "小白 ✓" : "小白 ✗"
                var items = [item]
                items.append(NSMenuItem(title: "打开 WebUI", action: #selector(self.openWeb), keyEquivalent: ""))
                items.append(NSMenuItem.separator())
                let quit = NSMenuItem(title: "退出", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
                items.append(quit)
                let menu = NSMenu()
                items.forEach { menu.addItem($0) }
                self.statusItem.menu = menu
            }
        }.resume()
    }

    private func refreshMenu() {
        checkHealth()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()

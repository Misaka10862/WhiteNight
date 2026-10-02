// Stable application identity for the background Python service and macOS TCC.
import AppKit
import Foundation

let arguments = CommandLine.arguments
if arguments.count != 3 || arguments[1] != "--project" {
    fputs("Usage: WhiteNight --project /absolute/project\n", stderr)
    exit(64)
}
let project = URL(fileURLWithPath: arguments[2], isDirectory: true)
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let child = Process()
child.executableURL = project.appendingPathComponent(".venv/bin/python")
child.arguments = ["-m", "whitenight"]
child.currentDirectoryURL = project
var environment = ProcessInfo.processInfo.environment
environment["WHITENIGHT_SERVICE_APP"] = Bundle.main.bundlePath
child.environment = environment
child.standardOutput = FileHandle.standardOutput
child.standardError = FileHandle.standardError
// Keep this application alive as the responsible parent throughout service life.
var stopping = false
let sources = [SIGTERM, SIGINT].map { signalNumber -> DispatchSourceSignal in
    signal(signalNumber, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
    source.setEventHandler {
        stopping = true
        if child.isRunning { child.terminate() }
    }
    source.resume()
    return source
}
child.terminationHandler = { process in
    DispatchQueue.main.async {
        exit(stopping ? 0 : process.terminationStatus)
    }
}
do {
    try child.run()
    app.run()
} catch {
    fputs("WhiteNight could not start: \(error)\n", stderr)
    exit(1)
}
withExtendedLifetime(sources) {}

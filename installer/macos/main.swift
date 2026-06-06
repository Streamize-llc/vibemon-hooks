// VibeMon Installer — macOS GUI shell around the public install.sh.
//
// Design invariant ("thin GUI shell", see INSTALLER_PLAN.md): this app
// contains NO install logic of its own. It downloads
// https://vibemon.dev/install.sh (302 → the GitHub Release artifact —
// the same auditable bytes everyone gets) and runs it with the API key
// the user pastes. Hook merges, privacy guarantees, idempotency and the
// daily auto-update are all inherited from that script; this app is a
// one-shot bootstrap and can be deleted afterwards.
//
// Built by installer/macos/build.sh — universal binary, ad-hoc signed.
// Korean-first copy (vibemon's primary audience).

import SwiftUI
import AppKit

private let installScriptURL = "https://vibemon.dev/install.sh"
private let docsURL = "https://vibemon.dev/docs"

// ─── Model ───────────────────────────────────────────────────────────

final class InstallerModel: ObservableObject {
    enum Phase: Equatable {
        case idle
        case needsDevTools
        case running
        case success
        case failure(String)
    }

    @Published var phase: Phase = .idle
    @Published var apiKey: String = ""
    @Published var logTail: [String] = []
    @Published var clipboardDetected = false

    var keyLooksValid: Bool {
        let k = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        return k.hasPrefix("vbm_") && k.count >= 12 && !k.contains(" ")
    }

    /// Prefill from the clipboard when it plainly holds an API key —
    /// the app/web "키 복사" button puts exactly that there.
    func prefillFromClipboard() {
        guard apiKey.isEmpty,
              let s = NSPasteboard.general.string(forType: .string)?
                  .trimmingCharacters(in: .whitespacesAndNewlines),
              s.hasPrefix("vbm_"), s.count >= 12, s.count < 200, !s.contains(" ")
        else { return }
        apiKey = s
        clipboardDetected = true
    }

    private func appendLog(_ line: String) {
        DispatchQueue.main.async {
            self.logTail.append(line)
            if self.logTail.count > 200 {
                self.logTail.removeFirst(self.logTail.count - 200)
            }
        }
    }

    /// `xcode-select -p` succeeds iff Command Line Tools (or Xcode) are
    /// installed — which is what provides /usr/bin/python3's real body.
    private func devToolsPresent() -> Bool {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/xcode-select")
        p.arguments = ["-p"]
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch { return false }
        p.waitUntilExit()
        return p.terminationStatus == 0
    }

    /// Running the python3 shim without CLT triggers Apple's standard
    /// "command line developer tools" install dialog.
    func openDevToolsInstaller() {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = ["--version"]
        p.standardInput = FileHandle.nullDevice
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        try? p.run()
    }

    func install() {
        let key = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard key.hasPrefix("vbm_") else { return }
        phase = .running
        logTail = []

        DispatchQueue.global(qos: .userInitiated).async {
            // 1. Preflight — install.sh (and the hook runtime after it)
            //    needs python3, which macOS only ships via CLT/Xcode.
            guard self.devToolsPresent() else {
                DispatchQueue.main.async { self.phase = .needsDevTools }
                return
            }

            // 2. Fetch the audited public installer (follows the 302 to
            //    the GitHub Release artifact).
            self.appendLog("· install.sh 다운로드 중…")
            guard let url = URL(string: installScriptURL) else { return }
            var req = URLRequest(url: url)
            req.timeoutInterval = 30
            let sem = DispatchSemaphore(value: 0)
            var script: Data?
            var fetchErr = ""
            URLSession.shared.dataTask(with: req) { data, resp, err in
                let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
                if code == 200, let d = data, !d.isEmpty {
                    script = d
                } else {
                    fetchErr = err?.localizedDescription ?? "HTTP \(code)"
                }
                sem.signal()
            }.resume()
            sem.wait()
            guard let body = script else {
                DispatchQueue.main.async {
                    self.phase = .failure("설치 스크립트를 내려받지 못했어요 (\(fetchErr)).\n네트워크 연결을 확인한 뒤 다시 시도해주세요.")
                }
                return
            }

            // 3. Run it — exactly what the documented one-liner does,
            //    with stdin pinned to /dev/null (the v24 lesson: a live
            //    stdin gets slurped by the hook's test probe).
            let tmp = FileManager.default.temporaryDirectory
                .appendingPathComponent("vibemon-install-\(ProcessInfo.processInfo.processIdentifier).sh")
            do {
                try body.write(to: tmp)
            } catch {
                DispatchQueue.main.async {
                    self.phase = .failure("임시 파일을 쓰지 못했어요: \(error.localizedDescription)")
                }
                return
            }
            defer { try? FileManager.default.removeItem(at: tmp) }

            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: "/bin/bash")
            proc.arguments = [tmp.path, key]
            proc.standardInput = FileHandle.nullDevice
            let pipe = Pipe()
            proc.standardOutput = pipe
            proc.standardError = pipe

            var buf = Data()
            pipe.fileHandleForReading.readabilityHandler = { h in
                let d = h.availableData
                guard !d.isEmpty else { return }
                buf.append(d)
                while let nl = buf.firstIndex(of: 0x0A) {
                    let lineData = Data(buf[..<nl])
                    buf = Data(buf[buf.index(after: nl)...])
                    let line = (String(data: lineData, encoding: .utf8) ?? "")
                        .trimmingCharacters(in: .whitespaces)
                    if !line.isEmpty { self.appendLog(line) }
                }
            }

            do {
                try proc.run()
            } catch {
                DispatchQueue.main.async {
                    self.phase = .failure("bash 실행에 실패했어요: \(error.localizedDescription)")
                }
                return
            }
            proc.waitUntilExit()
            pipe.fileHandleForReading.readabilityHandler = nil

            DispatchQueue.main.async {
                if proc.terminationStatus == 0 {
                    self.phase = .success
                } else {
                    let tail = self.logTail.suffix(6).joined(separator: "\n")
                    self.phase = .failure("설치 스크립트가 실패했어요 (exit \(proc.terminationStatus)).\n\(tail)")
                }
            }
        }
    }
}

// ─── Views ───────────────────────────────────────────────────────────

struct ContentView: View {
    @StateObject private var model = InstallerModel()

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(24)
        }
        .frame(width: 480, height: 440)
        .onAppear { model.prefillFromClipboard() }
    }

    private var header: some View {
        VStack(spacing: 4) {
            Text("VibeMon")
                .font(.system(size: 30, weight: .heavy, design: .monospaced))
            Text("AI 코딩 슬라임 — 설치")
                .font(.system(.subheadline, design: .monospaced))
                .foregroundColor(.secondary)
        }
        .padding(.vertical, 18)
        .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    private var content: some View {
        switch model.phase {
        case .idle:
            idleView
        case .needsDevTools:
            devToolsView
        case .running:
            runningView
        case .success:
            successView
        case .failure(let msg):
            failureView(msg)
        }
    }

    private var idleView: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("API 키")
                .font(.headline)
            TextField("vbm_ 로 시작하는 키를 붙여넣어 주세요", text: $model.apiKey)
                .font(.system(.body, design: .monospaced))
                .textFieldStyle(.roundedBorder)
                .disableAutocorrection(true)
            if model.clipboardDetected {
                Label("클립보드에서 키를 감지해 채워 넣었어요", systemImage: "doc.on.clipboard")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Text("키는 vibemon 앱 · 웹의 설정 → API 키에서 복사할 수 있어요.")
                .font(.caption)
                .foregroundColor(.secondary)

            Spacer()

            Button(action: { model.install() }) {
                Text("설치하기")
                    .font(.system(.body, design: .monospaced).weight(.bold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
            }
            .keyboardShortcut(.defaultAction)
            .disabled(!model.keyLooksValid)

            HStack {
                Link("터미널로 설치하는 방법", destination: URL(string: docsURL)!)
                Spacer()
                Text("설치 후 이 앱은 삭제해도 됩니다")
            }
            .font(.caption)
            .foregroundColor(.secondary)
        }
    }

    private var devToolsView: some View {
        VStack(spacing: 14) {
            Image(systemName: "wrench.and.screwdriver")
                .font(.system(size: 40))
                .foregroundColor(.orange)
            Text("개발자 도구가 필요해요")
                .font(.headline)
            Text("VibeMon 훅은 macOS의 python3를 사용하는데,\nApple 명령어 라인 도구(Command Line Tools)에 포함되어 있어요.\n아래 버튼을 누르면 Apple 설치 창이 뜹니다 — 설치가 끝나면\n다시 ‘설치하기’를 눌러주세요.")
                .font(.callout)
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
            HStack(spacing: 12) {
                Button("개발자 도구 설치 열기") { model.openDevToolsInstaller() }
                Button("다시 시도") { model.install() }
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private var runningView: some View {
        VStack(spacing: 14) {
            ProgressView()
            Text("설치 중…")
                .font(.headline)
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(model.logTail.suffix(12).enumerated()), id: \.offset) { _, line in
                        Text(line)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .frame(maxHeight: 180)
        }
    }

    private var successView: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48))
                .foregroundColor(.green)
            Text("슬라임과 연결됐어요!")
                .font(.title3.weight(.bold))
            Text("Claude Code / Cursor 세션을 재시작하면 적용됩니다.\n이제 코딩할 때마다 슬라임이 자라요. 이 앱은 삭제해도 됩니다.")
                .font(.callout)
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
            Button("완료") { NSApplication.shared.terminate(nil) }
                .keyboardShortcut(.defaultAction)
        }
    }

    private func failureView(_ msg: String) -> some View {
        VStack(spacing: 14) {
            Image(systemName: "xmark.octagon.fill")
                .font(.system(size: 40))
                .foregroundColor(.red)
            Text("설치에 실패했어요")
                .font(.headline)
            ScrollView {
                Text(msg)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 120)
            HStack(spacing: 12) {
                Button("다시 시도") { model.phase = .idle }
                    .keyboardShortcut(.defaultAction)
                Link("터미널로 설치하기", destination: URL(string: docsURL)!)
            }
        }
    }
}

// ─── App ─────────────────────────────────────────────────────────────

@main
struct VibeMonInstallerApp: App {
    init() {
        // CI smoke hook: `VibeMonInstaller --version` must run headless
        // and exit before any UI spins up.
        if CommandLine.arguments.contains("--version") {
            let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "dev"
            print("vibemon-installer \(v)")
            exit(0)
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .windowResizability(.contentSize)
    }
}

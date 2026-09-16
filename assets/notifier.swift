// ABOUTME: Posts one macOS notice for the Agents sidebar and reports how it was answered.
// ABOUTME: Runs inside Agents.app: UNUserNotificationCenter refuses a bare executable.
//
//   agents-notifier post --id ID --title T --body B [--button KEY=LABEL]... [--reply PLACEHOLDER]
//   agents-notifier remove --id ID
//
// `post` stays alive until the notice is acted on, then prints one JSON line
// and exits: {"action":"default"} for a click, {"action":"KEY"} for a button,
// {"action":"reply","text":"..."} for the text field, {"action":"dismiss"}
// when closed or after an hour. SIGTERM removes the notice and exits quietly.
// The daemon keeps one of these per standing notice. macOS hands every
// response for the bundle to one running process, whichever notice was
// acted on, so each line carries the notice's "id" and a response for
// another notice is printed for the daemon to route, without exiting.

import AppKit
import UserNotifications

let lifetime: TimeInterval = 3600

struct Options {
    var command = ""
    var id = ""
    var title = ""
    var body = ""
    var buttons: [(key: String, label: String)] = []
    var reply: String?
}

func parse(_ argv: [String]) -> Options? {
    var options = Options()
    var rest = argv.dropFirst()
    guard let command = rest.popFirst() else { return nil }
    options.command = command
    while let flag = rest.popFirst() {
        guard let value = rest.popFirst() else { return nil }
        switch flag {
        case "--id": options.id = value
        case "--title": options.title = value
        case "--body": options.body = value
        case "--reply": options.reply = value
        case "--button":
            guard let eq = value.firstIndex(of: "=") else { return nil }
            options.buttons.append((String(value[..<eq]), String(value[value.index(after: eq)...])))
        default: return nil
        }
    }
    return options.id.isEmpty ? nil : options
}

func emit(_ fields: [String: String]) {
    if let data = try? JSONSerialization.data(withJSONObject: fields),
       let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

final class Answer: NSObject, UNUserNotificationCenterDelegate {
    let id: String
    var done = false

    init(id: String) { self.id = id }

    func finish(_ fields: [String: String]) {
        guard !done else { return }
        done = true
        emit(fields.merging(["id": id]) { own, _ in own })
        exit(0)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                didReceive response: UNNotificationResponse,
                                withCompletionHandler completion: @escaping () -> Void) {
        completion()
        var fields: [String: String]
        switch response.actionIdentifier {
        case UNNotificationDefaultActionIdentifier: fields = ["action": "default"]
        case UNNotificationDismissActionIdentifier: fields = ["action": "dismiss"]
        default:
            if let typed = response as? UNTextInputNotificationResponse {
                fields = ["action": "reply", "text": typed.userText]
            } else {
                fields = ["action": response.actionIdentifier]
            }
        }
        let target = response.notification.request.identifier
        if target == id {
            finish(fields)
        } else {
            fields["id"] = target
            emit(fields)
        }
    }

    // The notice is wanted even while this app is "in front", which it never
    // visibly is.
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler completion: @escaping (UNNotificationPresentationOptions) -> Void) {
        completion([.banner, .list])
    }
}

guard let options = parse(CommandLine.arguments) else {
    FileHandle.standardError.write("usage: agents-notifier post|remove --id ID [--title T --body B --button K=L --reply P]\n".data(using: .utf8)!)
    exit(2)
}

// A run loop the delegate can be called on, without a window or a Dock icon.
let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let center = UNUserNotificationCenter.current()

if options.command == "remove" {
    if options.id == "ALL" {
        center.removeAllDeliveredNotifications()
        center.removeAllPendingNotificationRequests()
    } else {
        center.removeDeliveredNotifications(withIdentifiers: [options.id])
        center.removePendingNotificationRequests(withIdentifiers: [options.id])
    }
    // Removal is asynchronous; give it a moment to reach the daemon.
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { exit(0) }
    app.run()
}

let answer = Answer(id: options.id)
center.delegate = answer

signal(SIGTERM) { _ in
    UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: [CommandLine.arguments[CommandLine.arguments.firstIndex(of: "--id")! + 1]])
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { exit(0) }
}

center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
    guard granted else {
        emit(["action": "dismiss", "error": "not authorized"])
        exit(1)
    }
    // Each notice gets its own category: the buttons are the question's own.
    var actions: [UNNotificationAction] = options.buttons.map {
        UNNotificationAction(identifier: $0.key, title: $0.label, options: [])
    }
    if let placeholder = options.reply {
        actions.append(UNTextInputNotificationAction(identifier: "reply", title: placeholder, options: [],
                                                     textInputButtonTitle: "Send", textInputPlaceholder: placeholder))
    }
    let categoryId = "agents-" + options.id
    center.setNotificationCategories([
        UNNotificationCategory(identifier: categoryId, actions: actions, intentIdentifiers: [],
                               options: [.customDismissAction])
    ])
    let content = UNMutableNotificationContent()
    content.title = options.title
    content.body = options.body
    content.categoryIdentifier = categoryId
    content.threadIdentifier = options.id
    let request = UNNotificationRequest(identifier: options.id, content: content, trigger: nil)
    center.add(request) { error in
        if let error = error {
            emit(["action": "dismiss", "error": error.localizedDescription])
            exit(1)
        }
    }
}

DispatchQueue.main.asyncAfter(deadline: .now() + lifetime) {
    center.removeDeliveredNotifications(withIdentifiers: [options.id])
    answer.finish(["action": "dismiss"])
}

// A notice outliving its daemon is one nobody can answer: the reply would go
// down a pipe with no reader. Reparenting to launchd is how that shows.
let orphanWatch = DispatchSource.makeTimerSource(queue: .main)
orphanWatch.schedule(deadline: .now() + 2, repeating: 2)
orphanWatch.setEventHandler {
    if getppid() == 1 {
        center.removeDeliveredNotifications(withIdentifiers: [options.id])
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { exit(0) }
    }
}
orphanWatch.resume()

app.run()

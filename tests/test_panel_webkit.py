# ABOUTME: Native WKWebViews load the real panel from a real daemon, as iTerm2 windows' Toolbelts do.
# ABOUTME: The slow native tests (about 5 s each): each compiles a probe with clang and needs a window server.
"""WebKit gives a host six HTTP connections. A panel that held one open for
its live frames left a sixth window's Allow, Deny and answers waiting forever
behind the streams, so one test loads six panels and times a fetch from the last.
"""
import asyncio
import ctypes
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sidebar import Server, Sidebar  # noqa: E402

TOKEN = "webkit-token-not-a-real-secret"
PAYLOAD = {"groups": [{"name": "AGENTS", "rows": [
    {"session_id": "abc", "window_id": "w", "tab_id": "26", "label": "iterm"}]}]}
PANELS = 6

PROBE = r"""
#import <Cocoa/Cocoa.h>
#import <WebKit/WebKit.h>

// argv: url, panels, script. Every panel loads url; once all have, the last
// runs script, and each message it posts to `result` is printed until DONE.
@interface Probe : NSObject <WKScriptMessageHandler, WKNavigationDelegate>
@property(strong) NSMutableArray *panels;
@property(strong) NSString *script;
@property int loaded;
@end

@implementation Probe
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    NSString *line = [message.body description];
    printf("%s\n", line.UTF8String);
    fflush(stdout);
    if ([line isEqualToString:@"DONE"]) exit(0);
}
- (void)webView:(WKWebView *)panel didFinishNavigation:(WKNavigation *)navigation {
    if (++self.loaded < (int)self.panels.count) return;
    [self.panels.lastObject evaluateJavaScript:self.script completionHandler:^(id result, NSError *error) {
        if (error) { printf("script failed: %s\n", error.description.UTF8String); exit(3); }
    }];
}
- (void)webView:(WKWebView *)panel didFailProvisionalNavigation:(WKNavigation *)navigation withError:(NSError *)error {
    printf("load failed: %s\n", error.description.UTF8String);
    exit(4);
}
@end

int main(int argc, char **argv) {
    @autoreleasepool {
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        Probe *probe = [Probe new];
        probe.panels = [NSMutableArray new];
        probe.script = [NSString stringWithUTF8String:argv[3]];
        int count = atoi(argv[2]);
        WKWebViewConfiguration *config = [WKWebViewConfiguration new];
        [config.userContentController addScriptMessageHandler:probe name:@"result"];
        NSURL *url = [NSURL URLWithString:[NSString stringWithUTF8String:argv[1]]];
        // Ordered front: WebKit suspends the timers of a page in no visible window.
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100, 100, 380 * count, 600)
                                                       styleMask:NSWindowStyleMaskTitled
                                                         backing:NSBackingStoreBuffered defer:NO];
        for (int i = 0; i < count; i++) {
            WKWebView *panel = [[WKWebView alloc] initWithFrame:NSMakeRect(380 * i, 0, 380, 600) configuration:config];
            panel.navigationDelegate = probe;
            [probe.panels addObject:panel];
            [window.contentView addSubview:panel];
            [panel loadRequest:[NSURLRequest requestWithURL:url]];
        }
        [window orderFront:nil];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 25 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            puts("TIMEOUT");
            exit(2);
        });
        [NSApp run];
    }
    return 0;
}
"""

# The script's value is ignored: one that ends in a Promise fails evaluateJavaScript
# with "unsupported type", so it ends in undefined. The wait gives every panel's
# own stream time to open before the fetches compete with them.
MEASURE = """(async () => {
  const post = line => window.webkit.messageHandlers.result.postMessage(line);
  await new Promise(resolve => setTimeout(resolve, 1500));
  for (let i = 0; i < 3; i++) {
    const began = performance.now();
    const status = await Promise.race([
      fetch("/settings?token=%s").then(response => response.status),
      new Promise(resolve => setTimeout(() => resolve("timeout"), 5000))]);
    post(JSON.stringify({status, ms: Math.round(performance.now() - began)}));
  }
  post("DONE");
})(); undefined;""" % TOKEN


def window_server():
    """Is there a window server to put the panels on? Over ssh there is none."""
    graphics = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    graphics.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    session = graphics.CGSessionCopyCurrentDictionary()
    if session:
        foundation = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        foundation.CFRelease.argtypes = [ctypes.c_void_p]
        foundation.CFRelease(session)
    return bool(session)


def built_probe(tmp_path):
    """The probe compiled into tmp_path, or the test skipped where it cannot run."""
    if sys.platform != "darwin":
        pytest.skip("WKWebView is macOS only")
    if shutil.which("clang") is None:
        pytest.skip("no clang to build the probe")
    if not window_server():
        pytest.skip("no window server for the panels")
    source = tmp_path / "probe.m"
    source.write_text(PROBE)
    probe_path = tmp_path / "probe"
    built = subprocess.run(["clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "WebKit",
                            str(source), "-o", str(probe_path)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return probe_path


async def probed(tmp_path, payload, panels, script):
    """-> the lines the probe printed after `panels` panels loaded the page over `payload` and the last ran `script`."""
    probe_path = built_probe(tmp_path)
    sidebar = Sidebar(token=TOKEN, page_path=ROOT / "page.html", snapshot_fn=lambda: payload,
                      action_fn=lambda *a: None, settings_path=tmp_path / "settings.json")
    port = await Server(sidebar).start()
    probe = await asyncio.create_subprocess_exec(
        str(probe_path), f"http://127.0.0.1:{port}/?token={TOKEN}", str(panels), script,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(probe.communicate(), timeout=30)
    finally:
        if probe.returncode is None:
            probe.kill()
            await probe.wait()
    lines = out.decode().splitlines()
    print("\n".join(lines))
    assert probe.returncode == 0, (lines, err.decode()[-2000:])
    return lines


@pytest.mark.asyncio
async def test_native_webkit_six_panels_leave_room_for_a_fetch(tmp_path):
    lines = await probed(tmp_path, PAYLOAD, PANELS, MEASURE)
    timings = [json.loads(line) for line in lines if line.startswith("{")]
    assert [timing["status"] for timing in timings] == [200, 200, 200]
    assert all(timing["ms"] < 1000 for timing in timings), timings


TINT_NOTE = """(async () => {
  const post = line => window.webkit.messageHandlers.result.postMessage(line);
  await new Promise(resolve => setTimeout(resolve, 1500));
  post(JSON.stringify(document.getElementById("set-note-tab_colour")?.textContent ?? null));
  post("DONE");
})(); undefined;"""


@pytest.mark.asyncio
async def test_the_tab_tints_note_names_the_folder_iterm2_shares_its_settings_from(tmp_path):
    """The sheet is built before the first frame lands, so only a note the frame repaints names the folder."""
    payload = {"groups": [], "iterm_prefs_folder": "~/Library/Mobile Documents/com~apple~CloudDocs/iTerm2"}
    lines = await probed(tmp_path, payload, 1, TINT_NOTE)
    assert [json.loads(line) for line in lines if line != "DONE"] == [
        "Also hides iTerm2's line under the selected tab. iTerm2 shares its settings from iCloud Drive/iTerm2, so "
        "every Mac that loads them gets this too."]

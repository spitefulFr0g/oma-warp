import QtQuick
import QtTest
import "../../PanelLogic.js" as Logic

// Seam 3: Diagnostics, from the Panel logic over the shared Fixtures. The
// expected rows are the labels, values and copy settled in #8, written out
// literally.
TestCase {
  id: suite
  name: "Diagnostics"

  readonly property date now: new Date("2026-10-02T00:00:03Z")
  readonly property var labels: ["Package", "Service", "Daemon", "Registration", "Connection",
                                 "Through Cloudflare", "Location", "DNS", "Latest release"]
  property var catalog: ({})

  function readText(path) {
    var request = new XMLHttpRequest()
    request.open("GET", Qt.resolvedUrl(path), false)
    request.send()
    return request.responseText
  }

  function fixture(name) { return readText("../fixtures/" + name + ".json") }

  function say(message) {
    if (!message) return null
    return Logic.resolve(message, function(key) {
      verify(catalog.hasOwnProperty(key), "missing copy for " + key)
      return catalog[key]
    })
  }

  function variant(name, change) {
    var doc = JSON.parse(fixture(name))
    change(doc)
    return JSON.stringify(doc)
  }

  function viewOf(name, flags, at) {
    var doc = Logic.parseStatus(fixture(name))
    verify(doc !== null, name + " parses")
    return Logic.view(doc, flags || ({}), at || now)
  }

  // The table as text: one entry per row, by label, in table order.
  function table(v) {
    var rows = v.diagnostics.rows
    compare(rows.map(function(row) { return say(row.label) }), labels)
    var out = {}
    rows.forEach(function(row) {
      out[say(row.label)] = {
        value: say(row.value), detail: say(row.detail),
        fix: row.fix ? say(row.fix.label) : null, why: say(row.why), error: say(row.error)
      }
    })
    return out
  }

  // Only the cells a case names are compared; every other cell must be empty.
  function expectRow(rows, label, want) {
    var got = rows[label]
    compare(got.value, want.value, label + " value")
    compare(got.detail, want.detail || null, label + " detail")
    compare(got.fix, want.fix || null, label + " fix")
    compare(got.why, want.why || null, label + " why")
    compare(got.error, want.error || null, label + " error")
  }

  function initTestCase() {
    catalog = JSON.parse(readText("../../i18n/en.json"))
  }

  // Every Fixture, every row: "—" wherever a fact can't be known, and the
  // fix and explanation beside the row each Problem belongs to.
  function test_every_row_for_every_fixture_data() {
    var version = "2026.8.2115.0"
    var healthy = { "Package": { value: version }, "Service": { value: "Running" }, "Daemon": { value: "Responding" },
                    "Registration": { value: "Registered" } }
    var unknownBelow = { "Daemon": { value: "—" }, "Registration": { value: "—" }, "Connection": { value: "—" } }
    var noProbe = { "Through Cloudflare": { value: "—" }, "Location": { value: "—" }, "DNS": { value: "—" } }
    var off = { "Connection": { value: "Off" }, "Through Cloudflare": { value: "—" }, "Location": { value: "—" },
                "DNS": { value: "Not checked while off" } }
    var never = { "Latest release": { value: "Never checked" } }
    var verified = { "Latest release": { value: "2026.9.1180.0", detail: "verified 24 h ago" } }
    var yes = { "Through Cloudflare": { value: "Yes", detail: "checked 3 s ago" }, "Location": { value: "XXX, XX" } }
    var connected = { "Connection": { value: "Connected" } }
    var reconnectThrough = { value: "No", detail: "checked 3 s ago", fix: "Reconnect",
                             why: "WARP says it's connected, but Cloudflare sees your traffic arriving from outside WARP." }
    function rows() {
      var out = {}
      for (let i = 0; i < arguments.length; i++) for (let label in arguments[i]) out[label] = arguments[i][label]
      return out
    }
    return [
      { tag: "on", rows: rows(healthy, connected, yes, { "DNS": { value: "—" } }, never) },
      { tag: "off", rows: rows(healthy, off, never) },
      { tag: "connecting", rows: rows(healthy, { "Connection": { value: "Connecting…" } }, noProbe, never) },
      { tag: "unconfirmed", rows: rows(healthy, connected, noProbe, never) },
      { tag: "not_installed", rows: rows(unknownBelow, noProbe, never, {
          "Package": { value: "Not installed", fix: "Install",
                       why: "Install downloads the client from Cloudflare, verifies it and registers this device." },
          "Service": { value: "—" } }) },
      { tag: "service_stopped", rows: rows(unknownBelow, noProbe, never, {
          "Package": { value: version },
          "Service": { value: "Stopped", fix: "Start service", why: "The background service isn't running, so WARP can't connect." } }) },
      { tag: "daemon_unresponsive", rows: rows(healthy, unknownBelow, noProbe, never, {
          "Daemon": { value: "Not responding", fix: "Restart service", why: "The background service is running but didn't answer." } }) },
      { tag: "not_registered", rows: rows(healthy, noProbe, never, {
          "Registration": { value: "Not registered", fix: "Register", why: "WARP needs a free registration before it can connect." },
          "Connection": { value: "—" } }) },
      { tag: "outside", rows: rows(healthy, connected, never, {
          "Through Cloudflare": reconnectThrough, "Location": { value: "XXX, XX" }, "DNS": { value: "—" } }) },
      { tag: "dns_broken", rows: rows(healthy, connected, yes, never, {
          "DNS": { value: "Failing", why: "Lookups time out. Usually DNSOverTLS=yes set by hand in resolved.conf." } }) },
      { tag: "dns_bypassed", rows: rows(healthy, connected, yes, never, {
          "DNS": { value: "Bypassing WARP", fix: "Reconnect", why: "WARP lost its DNS settings, so lookups go to your usual resolver." } }) },
      { tag: "dns_shared", rows: rows(healthy, connected, yes, never, {
          "DNS": { value: "Shared", why: "Another network, such as Tailscale, also handles all domains." } }) },
      { tag: "multi", rows: rows(healthy, connected, never, {
          "Through Cloudflare": reconnectThrough, "Location": { value: "XXX, XX" },
          "DNS": { value: "Bypassing WARP", fix: "Reconnect", why: "WARP lost its DNS settings, so lookups go to your usual resolver." } }) },
      { tag: "trace_failed", rows: rows(healthy, connected, never, {
          "Through Cloudflare": { value: "Couldn't check", detail: "checked 3 s ago" }, "Location": { value: "—" }, "DNS": { value: "—" } }) },
      { tag: "dropped", rows: rows(healthy, off, never) },
      { tag: "update", rows: rows(healthy, off, verified) },
      { tag: "restart", rows: rows(healthy, off, never, { "Service": { value: "Running old version (restart needed)" } }) },
      { tag: "job", rows: rows(healthy, off, never) },
      { tag: "verify_failed", rows: rows(healthy, off, {
          "Latest release": { value: "2026.9.1180.0", detail: "verified 24 h ago",
                              error: "Last check failed verification; kept the previous release" } }) },
      { tag: "due", rows: rows(healthy, off, verified) },
    ]
  }

  function test_every_row_for_every_fixture(row) {
    var got = table(viewOf(row.tag))
    for (let i = 0; i < labels.length; i++) expectRow(got, labels[i], row.rows[labels[i]])
  }

  function rowOf(v, label) {
    var rows = v.diagnostics.rows
    for (let i = 0; i < rows.length; i++) if (say(rows[i].label) === label) return rows[i]
    fail("no row " + label)
  }

  // Values a Fixture doesn't reach, each a small step from one, and how
  // each reads: wrong facts urgent, missing ones muted, pending ones dim.
  function test_row_values_beside_the_fixtures_data() {
    var probe = { checked_at: "2026-10-01T23:58:03Z", trace: "through", ip: "203.0.113.7", colo: "XXX", country: "XX", dns: "ok" }
    return [
      { tag: "DNS through WARP", fixture: "on", change: function(d) { d.probe = probe },
        label: "DNS", value: "Through WARP", tone: "normal" },
      { tag: "checked minutes ago", fixture: "on", change: function(d) { d.probe = probe },
        label: "Through Cloudflare", value: "Yes", detail: "checked 2 min ago", tone: "normal" },
      { tag: "checked hours ago", fixture: "on", change: function(d) { d.probe.checked_at = "2026-10-01T21:00:00Z" },
        label: "Through Cloudflare", value: "Yes", detail: "checked 3 h ago", tone: "normal" },
      { tag: "outside while off", fixture: "off",
        change: function(d) { d.probe = { checked_at: "2026-10-02T00:00:00Z", trace: "outside", ip: "198.51.100.4", colo: "XXX", country: "XX", dns: null } },
        label: "Through Cloudflare", value: "No, WARP is off", detail: "checked 3 s ago", tone: "muted" },
      { tag: "outside while connected", fixture: "outside", label: "Through Cloudflare", value: "No", detail: "checked 3 s ago", tone: "bad" },
      { tag: "trace failed", fixture: "trace_failed", label: "Through Cloudflare", value: "Couldn't check", detail: "checked 3 s ago", tone: "dim" },
      { tag: "probing for the connection", fixture: "unconfirmed", flags: { probeInFlight: true },
        label: "Through Cloudflare", value: "Checking…", tone: "dim" },
      { tag: "reconnecting", fixture: "unconfirmed", flags: { toggleInFlight: "reconnect" },
        label: "Through Cloudflare", value: "Checking…", tone: "dim" },
      { tag: "probing again keeps the result", fixture: "on", flags: { probeInFlight: true },
        label: "Through Cloudflare", value: "Yes", detail: "checked 3 s ago", tone: "normal" },
      { tag: "nothing probed", fixture: "unconfirmed", label: "Through Cloudflare", value: "—", tone: "muted" },
      { tag: "location without a country", fixture: "on", change: function(d) { d.probe.country = null },
        label: "Location", value: "—", tone: "muted" },
      { tag: "release installed", fixture: "update",
        change: function(d) { d.client.version = "2026.9.1180.0"; d.update.available = false },
        label: "Latest release", value: "2026.9.1180.0 (installed)", detail: "verified 24 h ago", tone: "normal" },
      { tag: "release older than installed", fixture: "update",
        change: function(d) { d.client.version = "2026.10.100.0"; d.update.available = false },
        label: "Latest release", value: "2026.9.1180.0", detail: "verified 24 h ago", tone: "normal" },
      { tag: "check couldn't reach Cloudflare", fixture: "update", change: function(d) { d.update.last_error = "network" },
        label: "Latest release", value: "2026.9.1180.0", detail: "verified 24 h ago", error: "Last check couldn't reach Cloudflare", tone: "normal" },
      { tag: "never verified, check failed", fixture: "off", change: function(d) { d.update.last_error = "network" },
        label: "Latest release", value: "Never checked", error: "Last check couldn't reach Cloudflare", tone: "muted" },
      { tag: "not installed", fixture: "not_installed", label: "Package", value: "Not installed", tone: "bad" },
      { tag: "stopped", fixture: "service_stopped", label: "Service", value: "Stopped", tone: "bad" },
      { tag: "restart unknown", fixture: "on", change: function(d) { d.client.restart_needed = null },
        label: "Service", value: "Running", tone: "normal" },
      { tag: "not responding", fixture: "daemon_unresponsive", label: "Daemon", value: "Not responding", tone: "bad" },
      { tag: "not registered", fixture: "not_registered", label: "Registration", value: "Not registered", tone: "bad" },
      { tag: "unknown registration", fixture: "daemon_unresponsive", label: "Registration", value: "—", tone: "muted" },
      { tag: "DNS bypassed", fixture: "dns_bypassed", label: "DNS", value: "Bypassing WARP", tone: "bad" },
      { tag: "DNS off", fixture: "off", label: "DNS", value: "Not checked while off", tone: "muted" },
    ]
  }

  // Every fact a Diagnostics row reads is untrusted text: anything outside
  // the contract means a broken backend, never a value on screen.
  function test_malformed_facts_are_refused_data() {
    function on(change) { return variant("on", change) }
    return [
      { tag: "unknown DNS verdict", text: on(function(d) { d.probe.dns = "leaking" }) },
      { tag: "DNS verdict with markup", text: on(function(d) { d.probe.dns = "<b>ok</b>" }) },
      { tag: "prototype key as DNS verdict", text: on(function(d) { d.probe.dns = "constructor" }) },
      { tag: "DNS verdict not a string", text: on(function(d) { d.probe.dns = true }) },
      { tag: "no DNS key", text: on(function(d) { delete d.probe.dns }) },
      { tag: "probe time not a time", text: on(function(d) { d.probe.checked_at = "just now" }) },
      { tag: "probe time not a string", text: on(function(d) { d.probe.checked_at = 0 }) },
      { tag: "no probe time", text: on(function(d) { delete d.probe.checked_at }) },
      { tag: "unknown service state", text: on(function(d) { d.client.service = "activating" }) },
      { tag: "service not a string", text: on(function(d) { d.client.service = 1 }) },
      { tag: "no service key", text: on(function(d) { delete d.client.service }) },
      { tag: "unknown daemon state", text: on(function(d) { d.client.daemon = "slow" }) },
      { tag: "prototype key as daemon state", text: on(function(d) { d.client.daemon = "toString" }) },
      { tag: "registered as string", text: on(function(d) { d.client.registered = "true" }) },
      { tag: "no registered key", text: on(function(d) { delete d.client.registered }) },
      { tag: "restart needed as number", text: on(function(d) { d.client.restart_needed = 1 }) },
      { tag: "no restart needed key", text: on(function(d) { delete d.client.restart_needed }) },
    ]
  }

  function test_malformed_facts_are_refused(row) {
    compare(Logic.parseStatus(row.text), null)
  }

  // Status is the default view. Its hero carries ⓘ, which opens Diagnostics;
  // Diagnostics carries ← in its place, which comes back. Either way works
  // even while the backend is broken.
  function test_info_opens_diagnostics_and_back_returns_data() {
    return [
      { tag: "default", flags: {}, page: "status", glyph: "ⓘ", tooltip: "Details", to: "diagnostics" },
      { tag: "status", flags: { page: "status" }, page: "status", glyph: "ⓘ", tooltip: "Details", to: "diagnostics" },
      { tag: "diagnostics", flags: { page: "diagnostics" }, page: "diagnostics", glyph: "←", tooltip: "Back", to: "status" },
      { tag: "anything else", flags: { page: "tabs" }, page: "status", glyph: "ⓘ", tooltip: "Details", to: "diagnostics" },
      { tag: "diagnostics, backend broken", flags: { page: "diagnostics", backendError: true }, page: "diagnostics", glyph: "←", tooltip: "Back", to: "status" },
    ]
  }

  function test_info_opens_diagnostics_and_back_returns(row) {
    var views = [viewOf("on", row.flags), Logic.view(null, row.flags, now)]
    for (let i = 0; i < views.length; i++) {
      const v = views[i]
      compare(v.page, row.page)
      compare(v.hero.control.glyph, row.glyph)
      compare(say(v.hero.control.tooltip), row.tooltip)
      compare(v.hero.control.page, row.to)
      // The same hero either way: title, state phrase and switch.
      compare(say(v.hero.title), "Cloudflare WARP")
    }
    compare(say(views[0].hero.meta), "Through Cloudflare")
    compare(views[0].toggle.action, "disconnect")
  }

  // Below the table: the auto-check switch, on unless explicitly off, and
  // Check now. Check now is the user asking, so neither auto-check being
  // off nor the back-off after an abandoned check holds it; only one check
  // runs at a time, and none beside a Job or a broken backend.
  function test_check_section_data() {
    var abandoned = Date.parse("2026-10-01T23:00:03Z")
    return [
      { tag: "auto-check by default", fixture: "on", flags: {}, auto: true, label: "Check now", enabled: true, background: true },
      { tag: "auto-check on", fixture: "due", flags: { autoCheck: true }, auto: true, label: "Check now", enabled: true, background: true },
      { tag: "auto-check off", fixture: "due", flags: { autoCheck: false }, auto: false, label: "Check now", enabled: true, background: false },
      { tag: "just abandoned one", fixture: "due", flags: { checkAbandonedAt: abandoned }, auto: true, label: "Check now", enabled: true, background: false },
      { tag: "off and abandoned", fixture: "due", flags: { autoCheck: false, checkAbandonedAt: abandoned }, auto: false, label: "Check now", enabled: true, background: false },
      { tag: "not due", fixture: "update", flags: {}, auto: true, label: "Check now", enabled: true, background: false },
      { tag: "after a failed check", fixture: "verify_failed", flags: {}, auto: true, label: "Check now", enabled: true, background: false },
      { tag: "not installed", fixture: "not_installed", flags: {}, auto: true, label: "Check now", enabled: true, background: true },
      { tag: "check in flight", fixture: "due", flags: { checkInFlight: true }, auto: true, label: "Checking…", enabled: false, background: false },
      { tag: "check in flight, auto-check off", fixture: "due", flags: { checkInFlight: true, autoCheck: false }, auto: false, label: "Checking…", enabled: false, background: false },
      { tag: "Job running", fixture: "job", flags: {}, auto: true, label: "Check now", enabled: false, background: false },
      { tag: "backend broken", fixture: "due", flags: { backendError: true }, auto: true, label: "Check now", enabled: false, background: false },
    ]
  }

  function test_check_section(row) {
    var v = viewOf(row.fixture, row.flags)
    var check = v.diagnostics.check
    compare(say(check.auto.label), "Check every 12 h")
    compare(check.auto.checked, row.auto)
    compare(say(check.button.label), row.label)
    compare(check.button.enabled, row.enabled)
    compare(v.check.start, row.background)
  }

  function test_no_check_now_before_any_document() {
    var check = Logic.view(null, {}, now).diagnostics.check
    compare(check.button.enabled, false)
    compare(check.auto.checked, true)
    compare(Logic.view(null, {}, now).diagnostics.rows, [])
  }

  // The switch persists as the manifest's autoCheck setting in the Panel's
  // own shell.json entry, keeping whatever else the entry holds; the shell
  // writes the entry's id itself.
  function test_auto_check_switch_writes_its_setting_data() {
    return [
      { tag: "off, from defaults", settings: {}, on: false, entry: { autoCheck: false } },
      { tag: "on again", settings: { autoCheck: false }, on: true, entry: { autoCheck: true } },
      { tag: "other keys kept", settings: { autoCheck: true, label: "x" }, on: false, entry: { autoCheck: false, label: "x" } },
      { tag: "id left to the shell", settings: { id: "spitefulfr0g.oma-warp", autoCheck: true }, on: false, entry: { autoCheck: false } },
      { tag: "no settings yet", settings: null, on: false, entry: { autoCheck: false } },
      { tag: "settings not an object", settings: [true], on: true, entry: { autoCheck: true } },
      { tag: "only a real true is on", settings: {}, on: "yes", entry: { autoCheck: false } },
    ]
  }

  function test_auto_check_switch_writes_its_setting(row) {
    var before = JSON.stringify(row.settings)
    var entry = Logic.autoCheckSettings(row.settings, row.on)
    compare(JSON.stringify(entry), JSON.stringify(row.entry))
    compare(JSON.stringify(row.settings), before, "settings left as they were")
    // What the Panel reads back from the entry it wrote.
    compare(viewOf("due", { autoCheck: entry.autoCheck }).check.start, row.entry.autoCheck)
    compare(viewOf("due", { autoCheck: entry.autoCheck }).diagnostics.check.auto.checked, row.entry.autoCheck)
  }

  // When a check ends, the back-off is set only by one that recorded no
  // attempt, and cleared by one that did: the backend's own 12 h clock takes
  // over. So a Check now that succeeds never holds the next auto check off.
  function test_a_recorded_check_clears_the_back_off_data() {
    var verified = '{"latest": "2026.9.1180.0", "verified_at": "2026-10-02T00:00:01Z", "last_error": null, "attempted_at": "2026-10-02T00:00:01Z"}'
    var failed = '{"latest": null, "verified_at": null, "last_error": "network", "attempted_at": "2026-10-02T00:00:01Z"}'
    var earlier = Date.parse("2026-10-01T23:00:03Z")
    var at = Date.parse("2026-10-02T00:00:03Z")
    return [
      { tag: "verified after an abandoned one", before: earlier, code: 0, text: verified, after: NaN, start: true },
      { tag: "recorded failure after an abandoned one", before: earlier, code: 1, text: failed, after: NaN, start: true },
      { tag: "verified, nothing abandoned", before: NaN, code: 0, text: verified, after: NaN, start: true },
      { tag: "abandoned", before: NaN, code: -1, text: "", after: at, start: false },
      { tag: "abandoned again", before: earlier, code: 130, text: "", after: at, start: false },
    ]
  }

  function test_a_recorded_check_clears_the_back_off(row) {
    // Whatever back-off held before this check ended.
    compare(viewOf("due", { checkAbandonedAt: row.before }).check.start, isNaN(row.before))
    var after = Logic.backOffAfterCheck(row.code, row.text, Date.parse("2026-10-02T00:00:03Z"))
    if (isNaN(row.after)) verify(isNaN(after), "back-off cleared")
    else compare(after, row.after)
    compare(viewOf("due", { checkAbandonedAt: after }).check.start, row.start)
  }

  // A fix beside its row does what the same fix does on Status: a Job in a
  // floating terminal, or Reconnect as a background switch command.
  function test_fixes_beside_rows_work_data() {
    return [
      { tag: "install", fixture: "not_installed", label: "Package", action: "install", dispatch: "job" },
      { tag: "start service", fixture: "service_stopped", label: "Service", action: "start", dispatch: "job" },
      { tag: "restart service", fixture: "daemon_unresponsive", label: "Daemon", action: "restart", dispatch: "job" },
      { tag: "register", fixture: "not_registered", label: "Registration", action: "register", dispatch: "job" },
      { tag: "reconnect traffic", fixture: "outside", label: "Through Cloudflare", action: "reconnect", dispatch: "toggle" },
      { tag: "reconnect DNS", fixture: "dns_bypassed", label: "DNS", action: "reconnect", dispatch: "toggle" },
      { tag: "reconnect, second Problem", fixture: "multi", label: "DNS", action: "reconnect", dispatch: "toggle" },
    ]
  }

  function test_fixes_beside_rows_work(row) {
    var fix = rowOf(viewOf(row.fixture), row.label).fix
    compare(fix.action, row.action)
    compare(fix.enabled, true)
    compare(Logic.primaryDispatch(fix), row.dispatch)
    var launch = Logic.jobLaunch("/opt/oma-warp", fix, "abc-1")
    if (row.dispatch === "job") {
      compare(launch[0], "omarchy-launch-floating-terminal-with-presentation")
      compare(launch[1], "'/usr/bin/python3' '-I' '-B' '/opt/oma-warp/oma-warp' '" + row.action + "' '--job-id' 'abc-1'")
    } else {
      compare(launch, null)
      compare(Logic.backendCommand("/opt/oma-warp", fix.action), ["/usr/bin/python3", "-I", "-B", "/opt/oma-warp/oma-warp", "reconnect"])
    }
  }

  // The same guards as Status: nothing works while the backend is broken,
  // Reconnect waits for any other switch command, and nothing is offered
  // beside a live Job.
  function test_fixes_beside_rows_are_guarded_data() {
    return [
      { tag: "backend broken, Job", fixture: "service_stopped", flags: { backendError: true }, label: "Service", enabled: false },
      { tag: "backend broken, Reconnect", fixture: "outside", flags: { backendError: true }, label: "Through Cloudflare", enabled: false },
      { tag: "switch command in flight", fixture: "dns_bypassed", flags: { toggleInFlight: "disconnect" }, label: "DNS", enabled: false },
      { tag: "Job beside a switch command", fixture: "not_registered", flags: { toggleInFlight: "connect" }, label: "Registration", enabled: true },
      { tag: "probe in flight", fixture: "outside", flags: { probeInFlight: true }, label: "Through Cloudflare", enabled: true },
      { tag: "check in flight", fixture: "not_installed", flags: { checkInFlight: true }, label: "Package", enabled: true },
    ]
  }

  function test_fixes_beside_rows_are_guarded(row) {
    var fix = rowOf(viewOf(row.fixture, row.flags), row.label).fix
    compare(fix.enabled, row.enabled)
    if (!row.enabled) {
      compare(Logic.primaryDispatch(fix), null)
      compare(Logic.jobLaunch("/opt/oma-warp", fix, "abc-1"), null)
    }
  }

  function test_no_fix_is_offered_beside_a_live_job() {
    var text = variant("job", function(d) {
      d.client = { version: "2026.8.2115.0", service: "stopped", restart_needed: null, daemon: null, registered: null, connection: null }
      d.problems = [{ code: "service_stopped", fix: "start", blocking: true }]
    })
    var rows = table(Logic.view(Logic.parseStatus(text), {}, now))
    expectRow(rows, "Service", { value: "Stopped" })
    for (let i = 0; i < labels.length; i++) {
      compare(rows[labels[i]].fix, null, labels[i])
      compare(rows[labels[i]].why, null, labels[i])
    }
  }

  function test_row_values_beside_the_fixtures(row) {
    var text = row.change ? variant(row.fixture, row.change) : fixture(row.fixture)
    var doc = Logic.parseStatus(text)
    verify(doc !== null)
    var got = rowOf(Logic.view(doc, row.flags || ({}), now), row.label)
    compare(say(got.value), row.value)
    compare(say(got.detail), row.detail || null)
    compare(say(got.error), row.error || null)
    compare(got.tone, row.tone)
  }
}

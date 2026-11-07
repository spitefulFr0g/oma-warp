import QtQuick
import QtTest
import "../../PanelLogic.js" as Logic

// Seam 3: the Panel logic over the shared Fixtures. Expected values are the
// copy and glyph rules settled in #8, written out literally.
TestCase {
  id: suite
  name: "PanelLogic"

  readonly property string fullCloud: String.fromCodePoint(0xF015F)
  readonly property string outlinedCloud: String.fromCodePoint(0xF0163)
  readonly property string crossedCloud: String.fromCodePoint(0xF0164)
  readonly property date now: new Date("2026-10-02T00:00:03Z")
  property var catalog: ({})

  function readText(path) {
    var request = new XMLHttpRequest()
    request.open("GET", Qt.resolvedUrl(path), false)
    request.send()
    return request.responseText
  }

  function fixture(name) { return readText("../fixtures/" + name + ".json") }

  // Resolve a {key, args} message through i18n/en.json, as the Panel does.
  function say(message) {
    if (!message) return null
    return Logic.resolve(message, function(key) {
      verify(catalog.hasOwnProperty(key), "missing copy for " + key)
      return catalog[key]
    })
  }

  function viewOf(name, flags, at) {
    return Logic.view(Logic.parseStatus(fixture(name)), flags || ({}), at || now)
  }

  // A Fixture changed in place, for states that are a small step from one.
  function variant(name, change) {
    var doc = JSON.parse(fixture(name))
    change(doc)
    return JSON.stringify(doc)
  }

  function initTestCase() {
    catalog = JSON.parse(readText("../../i18n/en.json"))
  }

  function test_off() {
    var v = viewOf("off")
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.title), "Cloudflare WARP")
    compare(say(v.hero.meta), "Off")
    compare(v.toggle.checked, false)
    compare(v.toggle.enabled, true)
    compare(v.toggle.action, "connect")
    compare(v.note, null)
    compare(v.primary, null)
    compare(v.ip.visible, true)
  }

  function test_connecting() {
    var v = viewOf("connecting")
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "Connecting")
    compare(v.toggle.checked, true)
    compare(v.toggle.enabled, true)
    compare(v.toggle.action, "disconnect")
  }

  function test_unconfirmed() {
    var v = viewOf("unconfirmed")
    compare(v.bar.glyph, outlinedCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Connected · not confirmed")
    compare(v.toggle.checked, true)
    compare(v.toggle.enabled, true)
    compare(v.toggle.action, "disconnect")
  }

  // A blocking Problem: WARP can't be switched until its fix has run.
  function test_service_stopped() {
    var v = viewOf("service_stopped")
    compare(v.bar.glyph, crossedCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Needs attention")
    compare(v.toggle.enabled, false)
    compare(v.toggle.checked, false)
    compare(v.note.kind, "problem")
    compare(say(v.note.line), "The WARP service is stopped")
    compare(say(v.note.detail), "The background service isn't running, so WARP can't connect.")
    compare(say(v.primary.label), "Start service")
    compare(v.primary.action, "start")
    compare(v.primary.enabled, true)
    compare(v.ip.visible, false)
  }

  // While a Job runs the Panel only reports it: every action waits for it.
  function test_job() {
    var v = viewOf("job")
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "Working in a terminal")
    compare(v.toggle.enabled, false)
    compare(v.note.kind, "job")
    compare(say(v.note.line), "Starting the WARP service…")
    compare(say(v.note.detail), "In a terminal · started 3 s ago")
    compare(v.primary, null)
    compare(v.ip.visible, false)
  }

  // The Job outranks any Problem it is there to fix: never crossed out.
  function test_job_outranks_a_problem() {
    var text = variant("job", function(d) {
      d.problems = [{ code: "service_stopped", fix: "start", blocking: true }]
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "Working in a terminal")
    compare(v.note.kind, "job")
    compare(v.primary, null)
    compare(v.ip.visible, false)
  }

  function test_job_lines_cover_every_job_action_data() {
    return [
      { tag: "install", action: "install", line: "Installing WARP…" },
      { tag: "update", action: "update", line: "Updating WARP…" },
      { tag: "restart", action: "restart", line: "Restarting the WARP service…" },
      { tag: "start", action: "start", line: "Starting the WARP service…" },
      { tag: "register", action: "register", line: "Registering this device…" },
    ]
  }

  function test_job_lines_cover_every_job_action(row) {
    var text = variant("job", function(d) { d.job.action = row.action })
    compare(say(Logic.view(Logic.parseStatus(text), {}, now).note.line), row.line)
  }

  function test_job_hint_says_how_long_ago_it_started_data() {
    return [
      { tag: "just now", at: "2026-10-02T00:00:00Z", ago: "0 s ago" },
      { tag: "clock behind the record", at: "2026-10-01T23:59:58Z", ago: "0 s ago" },
      { tag: "59 s", at: "2026-10-02T00:00:59Z", ago: "59 s ago" },
      { tag: "a minute", at: "2026-10-02T00:01:00Z", ago: "1 min ago" },
      { tag: "a minute and a half", at: "2026-10-02T00:01:30Z", ago: "1 min ago" },
      { tag: "59 min", at: "2026-10-02T00:59:59Z", ago: "59 min ago" },
      { tag: "an hour", at: "2026-10-02T01:00:00Z", ago: "1 h ago" },
      { tag: "a day", at: "2026-10-03T00:00:00Z", ago: "24 h ago" },
    ]
  }

  function test_job_hint_says_how_long_ago_it_started(row) {
    var v = viewOf("job", {}, new Date(row.at))
    compare(say(v.note.detail), "In a terminal · started " + row.ago)
  }

  function test_no_document_yet_is_state_unknown() {
    var v = Logic.view(null, {}, now)
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "State unknown")
    compare(v.toggle.checked, false)
    compare(v.toggle.enabled, false)
    compare(v.banner, null)
  }

  // The last good document stays on screen, greyed, with every action off.
  function test_backend_error_greys_the_last_document_data() {
    return [
      { tag: "off", fixture: "off", glyph: fullCloud, opacity: 0.42, meta: "Off", checked: false },
      { tag: "connecting", fixture: "connecting", glyph: fullCloud, opacity: 0.42, meta: "Connecting", checked: true },
      { tag: "unconfirmed", fixture: "unconfirmed", glyph: outlinedCloud, opacity: 1, meta: "Connected · not confirmed", checked: true },
      { tag: "unconfirmed, toggle in flight", fixture: "unconfirmed", inFlight: "disconnect", glyph: outlinedCloud, opacity: 1, meta: "Connected · not confirmed", checked: false },
      { tag: "service stopped", fixture: "service_stopped", glyph: crossedCloud, opacity: 1, meta: "Needs attention", checked: false, fix: "Start service" },
    ]
  }

  function test_backend_error_greys_the_last_document(row) {
    var v = viewOf(row.fixture, { backendError: true, toggleInFlight: row.inFlight || null })
    compare(v.greyed, true)
    compare(say(v.banner), "Couldn't read WARP status")
    compare(v.toggle.enabled, false)
    compare(v.toggle.checked, row.checked)
    compare(v.bar.glyph, row.glyph)
    compare(v.bar.opacity, row.opacity)
    compare(say(v.hero.meta), row.meta)
    if (row.fix) {
      compare(say(v.primary.label), row.fix)
      compare(v.primary.enabled, false)
    } else {
      compare(v.primary, null)
    }
  }

  function test_backend_error_before_any_document() {
    var v = Logic.view(null, { backendError: true }, now)
    compare(v.greyed, true)
    compare(say(v.banner), "Couldn't read WARP status")
    compare(say(v.hero.meta), "State unknown")
    compare(v.toggle.enabled, false)
  }

  // parseStatus() answers null for anything the Panel must treat as a broken
  // backend; the Panel then raises the backend-error flag.
  function test_untrusted_output_is_refused_data() {
    var off = JSON.parse(readText("../fixtures/off.json"))
    function variant(change) {
      var copy = JSON.parse(JSON.stringify(off))
      change(copy)
      return JSON.stringify(copy)
    }
    return [
      { tag: "empty", text: "" },
      { tag: "not json", text: "Traceback (most recent call last):" },
      { tag: "array", text: "[]" },
      { tag: "null", text: "null" },
      { tag: "unknown schema", text: variant(function(d) { d.schema = 2 }) },
      { tag: "schema as string", text: variant(function(d) { d.schema = "1" }) },
      { tag: "no client", text: variant(function(d) { delete d.client }) },
      { tag: "client not an object", text: variant(function(d) { d.client = "connected" }) },
      { tag: "unknown connection", text: variant(function(d) { d.client.connection = "tunnelled" }) },
      { tag: "connection not a string", text: variant(function(d) { d.client.connection = { toString: 1 } }) },
      { tag: "no problems", text: variant(function(d) { delete d.problems }) },
      { tag: "problems not a list", text: variant(function(d) { d.problems = { code: "service_stopped" } }) },
      { tag: "problem not an object", text: variant(function(d) { d.problems = ["service_stopped"] }) },
      { tag: "unknown problem", text: variant(function(d) { d.problems = [{ code: "__proto__", fix: null, blocking: false }] }) },
      { tag: "unknown fix", text: variant(function(d) { d.problems = [{ code: "service_stopped", fix: "rm -rf ~", blocking: true }] }) },
      { tag: "fix not a string", text: variant(function(d) { d.problems = [{ code: "service_stopped", fix: ["start"], blocking: true }] }) },
      { tag: "blocking not a boolean", text: variant(function(d) { d.problems = [{ code: "service_stopped", fix: "start", blocking: "yes" }] }) },
      { tag: "no job key", text: variant(function(d) { delete d.job }) },
      { tag: "job not an object", text: variant(function(d) { d.job = "start" }) },
      { tag: "unknown job action", text: variant(function(d) { d.job = { action: "uninstall", started_at: "2026-10-02T00:00:00Z" } }) },
      { tag: "prototype key as job action", text: variant(function(d) { d.job = { action: "constructor", started_at: "2026-10-02T00:00:00Z" } }) },
      { tag: "job start not a time", text: variant(function(d) { d.job = { action: "start", started_at: "soon" } }) },
      { tag: "job start not a string", text: variant(function(d) { d.job = { action: "start", started_at: 0 } }) },
    ]
  }

  function test_untrusted_output_is_refused(row) {
    compare(Logic.parseStatus(row.text), null)
  }

  function test_fixtures_parse() {
    compare(Logic.parseStatus(fixture("off")).client.connection, "disconnected")
    compare(Logic.parseStatus(fixture("connecting")).client.connection, "connecting")
    compare(Logic.parseStatus(fixture("unconfirmed")).client.connection, "connected")
    compare(Logic.parseStatus(fixture("service_stopped")).problems[0].fix, "start")
    compare(Logic.parseStatus(fixture("job")).job.action, "start")
  }

  function test_healthy_documents_are_not_greyed() {
    compare(viewOf("off").greyed, false)
    compare(viewOf("unconfirmed", { toggleInFlight: "disconnect" }).banner, null)
  }

  function test_plugin_dir_comes_from_the_resolved_url() {
    compare(Logic.pluginDir("file:///opt/omarchy%20plugins/spitefulfr0g.oma-warp/"), "/opt/omarchy plugins/spitefulfr0g.oma-warp")
    compare(Logic.pluginDir("file:///srv/oma-warp"), "/srv/oma-warp")
  }

  function test_backend_commands_come_from_the_allow_list_data() {
    return [
      { tag: "status", action: "status", argv: ["status", "--json"] },
      { tag: "connect", action: "connect", argv: ["connect"] },
      { tag: "disconnect", action: "disconnect", argv: ["disconnect"] },
    ]
  }

  function test_backend_commands_come_from_the_allow_list(row) {
    compare(Logic.backendCommand("/srv/oma warp", row.action),
            ["/usr/bin/python3", "-I", "-B", "/srv/oma warp/oma-warp"].concat(row.argv))
  }

  function test_anything_else_is_refused_data() {
    return [
      { tag: "uninstall", action: "uninstall" },
      { tag: "shell text", action: "connect; rm -rf ~" },
      { tag: "prototype key", action: "constructor" },
      { tag: "empty", action: "" },
      { tag: "warp-cli", action: "warp-cli" },
    ]
  }

  function test_anything_else_is_refused(row) {
    compare(Logic.backendCommand("/srv/oma-warp", row.action), null)
    compare(Logic.backendCommand("", "status"), null)
  }

  // The fix button launches its Job in a floating terminal. The launcher
  // hands its one argument to bash -c, so every word is single-quoted.
  function test_fix_button_launches_its_job_in_a_terminal() {
    var primary = viewOf("service_stopped").primary
    compare(Logic.jobLaunch("/srv/oma-warp", primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'start' '--job-id' 'k9-x1'"])
  }

  function test_job_command_survives_any_plugin_folder() {
    var primary = viewOf("service_stopped").primary
    compare(Logic.jobLaunch("/srv/it's $(here) `x`; a b", primary, "k9-x1")[1],
            "'/usr/bin/python3' '-I' '-B' '/srv/it'\\''s $(here) `x`; a b/oma-warp' 'start' '--job-id' 'k9-x1'")
  }

  function test_nothing_launches_without_an_enabled_job_data() {
    return [
      { tag: "no button", fixture: "off", dir: "/srv/oma-warp", id: "k9-x1" },
      { tag: "backend broken", fixture: "service_stopped", flags: { backendError: true }, dir: "/srv/oma-warp", id: "k9-x1" },
      { tag: "Job already running", fixture: "job", dir: "/srv/oma-warp", id: "k9-x1" },
      { tag: "no plugin folder", fixture: "service_stopped", dir: "", id: "k9-x1" },
      { tag: "no job id", fixture: "service_stopped", dir: "/srv/oma-warp", id: "" },
      { tag: "job id with shell text", fixture: "service_stopped", dir: "/srv/oma-warp", id: "x' ; reboot '" },
    ]
  }

  function test_nothing_launches_without_an_enabled_job(row) {
    compare(Logic.jobLaunch(row.dir, viewOf(row.fixture, row.flags).primary, row.id), null)
  }

  // Ids come from the time and a random draw, and are always launchable.
  function test_job_ids_are_unique_and_launchable() {
    var primary = viewOf("service_stopped").primary
    var at = Date.UTC(2026, 9, 2)
    var ids = [Logic.jobId(at, 0), Logic.jobId(at, 0.5), Logic.jobId(at, 0.999999), Logic.jobId(at + 1, 0.5)]
    compare(ids.filter(function(id, i) { return ids.indexOf(id) === i }).length, 4)
    ids.forEach(function(id) { verify(Logic.jobLaunch("/srv/oma-warp", primary, id) !== null, id) })
  }

  // job.json lives in the backend's runtime dir; without one there is
  // nothing to watch and regular polling carries on alone.
  function test_job_record_is_watched_in_the_runtime_dir_data() {
    return [
      { tag: "runtime dir", dir: "/run/user/4242", path: "/run/user/4242/oma-warp/job.json" },
      { tag: "trailing slash", dir: "/run/user/4242/", path: "/run/user/4242/oma-warp/job.json" },
      { tag: "unset", dir: undefined, path: "" },
      { tag: "empty", dir: "", path: "" },
      { tag: "relative", dir: "run/user/4242", path: "" },
    ]
  }

  function test_job_record_is_watched_in_the_runtime_dir(row) {
    compare(Logic.jobRecordPath(row.dir), row.path)
  }

  // Reconnect is a background command, not a terminal Job.
  function test_only_job_actions_launch_a_terminal() {
    compare(Logic.jobLaunch("/srv/oma-warp", { action: "reconnect", label: null, enabled: true }, "k9-x1"), null)
    compare(Logic.jobLaunch("/srv/oma-warp", { action: "uninstall", label: null, enabled: true }, "k9-x1"), null)
  }

  function test_status_is_polled_faster_while_the_panel_is_open() {
    compare(Logic.pollInterval(true), 3000)
    compare(Logic.pollInterval(false), 15000)
  }

  // The flag names the backend command still running; the knob already
  // shows where it is going, and the switch takes no clicks until it ends.
  function test_toggle_in_flight_disables_the_switch_data() {
    return [
      { tag: "off, connecting", fixture: "off", inFlight: "connect", checked: true, meta: "Off" },
      { tag: "connecting, disconnecting", fixture: "connecting", inFlight: "disconnect", checked: false, meta: "Connecting" },
      { tag: "unconfirmed, disconnecting", fixture: "unconfirmed", inFlight: "disconnect", checked: false, meta: "Connected · not confirmed" },
    ]
  }

  function test_toggle_in_flight_disables_the_switch(row) {
    var v = viewOf(row.fixture, { toggleInFlight: row.inFlight })
    compare(v.toggle.enabled, false)
    compare(v.toggle.busy, true)
    compare(v.toggle.checked, row.checked)
    compare(say(v.hero.meta), row.meta)
  }
}

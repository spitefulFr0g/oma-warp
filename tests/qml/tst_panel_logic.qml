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

  // The rest of the blocking chain. Each is the only Problem the backend
  // reports, so the Panel reads like service_stopped with its own copy.
  function test_blocking_problem_data() {
    return [
      { tag: "not installed", fixture: "not_installed", line: "WARP isn't installed",
        detail: "Install downloads the client from Cloudflare, verifies it and registers this device.",
        fix: "Install", action: "install" },
      { tag: "daemon unresponsive", fixture: "daemon_unresponsive", line: "The WARP service isn't responding",
        detail: "The background service is running but didn't answer.",
        fix: "Restart service", action: "restart" },
      { tag: "not registered", fixture: "not_registered", line: "This device isn't registered",
        detail: "WARP needs a free registration before it can connect.",
        fix: "Register", action: "register" },
    ]
  }

  function test_blocking_problem(row) {
    var v = viewOf(row.fixture)
    compare(v.bar.glyph, crossedCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Needs attention")
    compare(v.toggle.enabled, false)
    compare(v.toggle.checked, false)
    compare(v.toggle.busy, false)
    compare(v.note.kind, "problem")
    compare(say(v.note.line), row.line)
    compare(say(v.note.detail), row.detail)
    compare(say(v.primary.label), row.fix)
    compare(v.primary.action, row.action)
    compare(v.ip.visible, false)
    compare(v.greyed, false)
    compare(v.banner, null)
  }

  // null means "can't know", never "no". Only the backend raises Problems,
  // so a fact it couldn't read leaves the state unknown and the switch
  // disabled, never a Problem the Panel made up.
  function test_unknown_facts_are_not_problems_data() {
    return [
      { tag: "package unknown", fixture: "not_installed" },
      { tag: "daemon status unknown", fixture: "daemon_unresponsive", change: function(c) { c.daemon = null } },
      { tag: "registration unknown", fixture: "not_registered", change: function(c) { c.registered = null } },
    ]
  }

  function test_unknown_facts_are_not_problems(row) {
    var text = variant(row.fixture, function(d) {
      d.problems = []
      if (row.change) row.change(d.client)
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "State unknown")
    compare(v.toggle.enabled, false)
    compare(v.toggle.checked, false)
    compare(v.note, null)
    compare(v.primary, null)
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
  function test_job_outranks_a_problem_data() {
    return [
      { tag: "not installed", code: "not_installed", fix: "install" },
      { tag: "service stopped", code: "service_stopped", fix: "start" },
      { tag: "daemon unresponsive", code: "daemon_unresponsive", fix: "restart" },
      { tag: "not registered", code: "not_registered", fix: "register" },
    ]
  }

  function test_job_outranks_a_problem(row) {
    var text = variant(row.code, function(d) {
      d.job = { action: row.fix, started_at: "2026-10-02T00:00:00Z" }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "Working in a terminal")
    compare(v.note.kind, "job")
    compare(v.primary, null)
    compare(v.ip.visible, false)
    compare(v.toggle.enabled, false)
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

  // A verified newer release is maintenance, not an alarm: a dot, nothing more.
  function test_update_available_puts_a_dot_on_the_cloud_data() {
    return [
      { tag: "update", fixture: "update", dot: true },
      { tag: "verify failed, kept release", fixture: "verify_failed", dot: true },
      { tag: "due", fixture: "due", dot: true },
      { tag: "off", fixture: "off", dot: false },
      { tag: "never checked", fixture: "not_installed", dot: false },
    ]
  }

  function test_update_available_puts_a_dot_on_the_cloud(row) {
    compare(viewOf(row.fixture).bar.dot, row.dot)
  }

  // A new client installed under the old service is maintenance too, never
  // a Problem: the cloud keeps its connection's look and gains the dot.
  function test_restart_needed_puts_a_dot_on_the_cloud() {
    var v = viewOf("restart")
    compare(v.bar.dot, true)
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "Off")
    compare(v.note, null)
    compare(v.toggle.enabled, true)
    compare(v.ip.visible, true)
  }

  // Either reason alone is enough, and the dot survives a Problem and a Job.
  function test_the_dot_shows_for_a_restart_or_an_update_data() {
    return [
      { tag: "restart only", restart: true, available: false, dot: true },
      { tag: "update only", restart: false, available: true, dot: true },
      { tag: "both", restart: true, available: true, dot: true },
      { tag: "neither", restart: false, available: false, dot: false },
      { tag: "restart unknown", restart: null, available: false, dot: false },
    ]
  }

  function test_the_dot_shows_for_a_restart_or_an_update(row) {
    ["on", "dns_broken", "job"].forEach(function(name) {
      var text = variant(name, function(d) {
        d.client.restart_needed = row.restart
        d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: row.available, last_error: null, due: false }
      })
      compare(Logic.view(Logic.parseStatus(text), {}, now).bar.dot, row.dot, name)
    })
  }

  // With nothing else to do, Update holds the full-width slot and its line
  // and versions sit above it.
  function test_update_holds_the_primary_slot_when_nothing_else_does() {
    var v = viewOf("update")
    compare(say(v.update.line), "Update available")
    compare(say(v.update.versions), "2026.8.2115.0 → 2026.9.1180.0")
    compare(v.update.primary, true)
    compare(say(v.primary.label), "Update")
    compare(v.primary.enabled, true)
    compare(v.note, null)
  }

  // A Problem's fix outranks Update, which steps down to a small row with
  // its own regular button.
  function test_update_yields_the_primary_slot_to_a_fix() {
    var text = variant("service_stopped", function(d) {
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(say(v.primary.label), "Start service")
    compare(v.primary.action, "start")
    compare(v.update.primary, false)
    compare(say(v.update.line), "Update available")
    compare(say(v.update.versions), "2026.8.2115.0 → 2026.9.1180.0")
    compare(say(v.update.button.label), "Update")
    compare(v.update.button.enabled, true)
    compare(v.bar.dot, true)
    compare(v.bar.glyph, crossedCloud)
  }

  // With no fix to offer, finishing the installed update is the one thing
  // to do: its line and detail sit above a full-width Restart that runs the
  // restart-and-restore Job in the terminal.
  function test_restart_needed_holds_the_primary_slot() {
    var v = viewOf("restart")
    compare(say(v.restart.line), "Restart to finish the update")
    compare(say(v.restart.detail), "2026.8.2115.0 installed, old service still running")
    compare(say(v.primary.label), "Restart")
    compare(v.primary.action, "restart")
    compare(v.primary.enabled, true)
    compare(v.update, null)
    compare(Logic.jobLaunch("/srv/oma-warp", v.primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'restart' '--job-id' 'k9-x1'"])
  }

  function test_no_restart_row_without_a_needed_restart_data() {
    return [
      { tag: "on", fixture: "on" },
      { tag: "update", fixture: "update" },
      { tag: "unknown", fixture: "restart", restart: null },
      { tag: "not installed", fixture: "not_installed" },
    ]
  }

  function test_no_restart_row_without_a_needed_restart(row) {
    var text = variant(row.fixture, function(d) { if (row.hasOwnProperty("restart")) d.client.restart_needed = row.restart })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.restart, null)
    verify(v.primary === null || v.primary.label.key !== "restart.button")
  }

  // Finishing an installed update comes before offering the next one: the
  // primary slot stays with the restart, and Update takes the small row.
  function test_a_needed_restart_keeps_update_out_of_the_primary_slot() {
    var text = variant("update", function(d) { d.client.restart_needed = true })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(say(v.primary.label), "Restart")
    compare(v.primary.action, "restart")
    compare(say(v.restart.line), "Restart to finish the update")
    compare(v.update.primary, false)
    compare(say(v.update.line), "Update available")
    compare(say(v.update.versions), "2026.8.2115.0 → 2026.9.1180.0")
    compare(say(v.update.button.label), "Update")
    compare(v.update.button.enabled, true)
    compare(v.bar.dot, true)
  }

  // A Problem's fix outranks the restart, which is then not offered at all;
  // an available update still steps down to its small row.
  function test_a_fix_outranks_a_needed_restart_data() {
    return [
      { tag: "Restart service", fixture: "daemon_unresponsive", fix: "Restart service", action: "restart" },
      { tag: "Start service", fixture: "service_stopped", fix: "Start service", action: "start" },
      { tag: "Register", fixture: "not_registered", fix: "Register", action: "register" },
    ]
  }

  function test_a_fix_outranks_a_needed_restart(row) {
    var text = variant(row.fixture, function(d) {
      d.client.restart_needed = true
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(say(v.primary.label), row.fix)
    compare(v.primary.action, row.action)
    compare(v.restart, null)
    compare(v.update.primary, false)
    compare(say(v.update.button.label), "Update")
    compare(v.note.kind, "problem")
    compare(v.bar.glyph, crossedCloud)
    compare(v.bar.dot, true)
  }

  // A Problem with no fix leaves the slot to the restart, under its note.
  function test_a_problem_without_a_fix_leaves_the_slot_to_the_restart() {
    var text = variant("dns_broken", function(d) { d.client.restart_needed = true })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.note.kind, "problem")
    compare(v.note.line.key, "problem.dns_broken")
    compare(say(v.restart.line), "Restart to finish the update")
    compare(say(v.primary.label), "Restart")
    compare(v.primary.action, "restart")
    compare(v.primary.enabled, true)
  }

  // A running Job offers nothing else, the restart included; once the
  // Restart Job is live the Panel shows it as the note.
  function test_no_restart_is_offered_while_a_job_runs_data() {
    return [
      { tag: "restart Job", action: "restart", line: "Restarting the WARP service…" },
      { tag: "other Job", action: "start", line: "Starting the WARP service…" },
    ]
  }

  function test_no_restart_is_offered_while_a_job_runs(row) {
    var text = variant("job", function(d) {
      d.client.restart_needed = true
      d.job.action = row.action
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.restart, null)
    compare(v.primary, null)
    compare(v.note.kind, "job")
    compare(say(v.note.line), row.line)
    compare(v.bar.dot, true)
    compare(v.bar.glyph, fullCloud)
    compare(Logic.jobLaunch("/srv/oma-warp", v.primary, "k9-x1"), null)
  }

  // A broken backend greys the restart, which then launches nothing.
  function test_a_broken_backend_disables_the_restart() {
    var v = viewOf("restart", { backendError: true })
    compare(v.greyed, true)
    compare(say(v.restart.line), "Restart to finish the update")
    compare(v.primary.action, "restart")
    compare(v.primary.enabled, false)
    compare(Logic.jobLaunch("/srv/oma-warp", v.primary, "k9-x1"), null)
    var fix = viewOf("daemon_unresponsive", { backendError: true }).primary
    compare(fix.enabled, false)
    compare(Logic.jobLaunch("/srv/oma-warp", fix, "k9-x1"), null)
  }

  // The switch and the background check carry on beside a needed restart;
  // neither a switch nor a check in flight touches the Restart button.
  function test_the_restart_leaves_the_switch_and_check_alone_data() {
    return [
      { tag: "idle", flags: {}, toggleEnabled: true, start: true },
      { tag: "connecting", flags: { toggleInFlight: "connect" }, toggleEnabled: false, start: true },
      { tag: "check in flight", flags: { checkInFlight: true }, toggleEnabled: true, start: false },
      { tag: "auto-check off", flags: { autoCheck: false }, toggleEnabled: true, start: false },
    ]
  }

  function test_the_restart_leaves_the_switch_and_check_alone(row) {
    var v = viewOf("restart", row.flags)
    compare(v.toggle.enabled, row.toggleEnabled)
    compare(v.check.start, row.start)
    compare(v.primary.action, "restart")
    compare(v.primary.enabled, true)
  }

  // While a Job runs Update is not offered from either position; the dot
  // still says a release is waiting.
  function test_no_update_is_offered_while_a_job_runs() {
    var text = variant("job", function(d) {
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.update, null)
    compare(v.primary, null)
    compare(v.bar.dot, true)
    compare(v.note.kind, "job")
  }

  function test_a_broken_backend_disables_update_from_either_position() {
    var primary = viewOf("update", { backendError: true })
    compare(primary.update.primary, true)
    compare(primary.primary.enabled, false)
    var text = variant("service_stopped", function(d) {
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var secondary = Logic.view(Logic.parseStatus(text), { backendError: true }, now)
    compare(secondary.update.primary, false)
    compare(secondary.update.button.enabled, false)
  }

  // One rule starts the background check, on Panel open and while closed
  // alike: the backend says it is due, auto-check is on, and none is in
  // flight. A failed check restarts the backend's 12 h clock, so `due`
  // clears itself.
  function test_a_due_check_runs_in_the_background_data() {
    return [
      { tag: "due, auto-check by default", fixture: "due", flags: {}, start: true },
      { tag: "due, auto-check on", fixture: "due", flags: { autoCheck: true }, start: true },
      { tag: "due, check in flight", fixture: "due", flags: { checkInFlight: true }, start: false },
      { tag: "due, auto-check off", fixture: "due", flags: { autoCheck: false }, start: false },
      { tag: "due, auto-check off and in flight", fixture: "due", flags: { autoCheck: false, checkInFlight: true }, start: false },
      { tag: "checked, update waiting", fixture: "update", flags: {}, start: false },
      { tag: "failed verification, clock restarted", fixture: "verify_failed", flags: {}, start: false },
    ]
  }

  function test_a_due_check_runs_in_the_background(row) {
    compare(viewOf(row.fixture, row.flags).check.start, row.start)
  }

  // A stale document can't say a check is due, and a live Job (an Update
  // writes the same cache) is left alone.
  function test_no_background_check_without_a_live_document_or_during_a_job() {
    compare(Logic.view(null, {}, now).check.start, false)
    compare(viewOf("due", { backendError: true }).check.start, false)
    compare(viewOf("job").update, null)
    compare(Logic.parseStatus(fixture("job")).update.due, true)
    compare(viewOf("job").check.start, false)
  }

  // A check cut off at its deadline, or one that died, records no attempt,
  // so the backend still says due. The Panel then waits the same 12 h
  // before trying again rather than retrying on every poll.
  function test_an_abandoned_check_is_not_retried_for_12_h_data() {
    return [
      { tag: "just abandoned", at: "2026-10-02T00:00:03Z", start: false },
      { tag: "an hour ago", at: "2026-10-01T23:00:03Z", start: false },
      { tag: "almost 12 h ago", at: "2026-10-01T12:00:04Z", start: false },
      { tag: "12 h ago", at: "2026-10-01T12:00:03Z", start: true },
      { tag: "a clock behind the record", at: "2026-10-02T01:00:00Z", start: false },
    ]
  }

  function test_an_abandoned_check_is_not_retried_for_12_h(row) {
    compare(viewOf("due", { checkAbandonedAt: Date.parse(row.at) }).check.start, row.start)
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
      { tag: "not installed", fixture: "not_installed", glyph: crossedCloud, opacity: 1, meta: "Needs attention", checked: false, fix: "Install" },
      { tag: "daemon unresponsive", fixture: "daemon_unresponsive", glyph: crossedCloud, opacity: 1, meta: "Needs attention", checked: false, fix: "Restart service" },
      { tag: "not registered", fixture: "not_registered", glyph: crossedCloud, opacity: 1, meta: "Needs attention", checked: false, fix: "Register" },
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
    var due = JSON.parse(readText("../fixtures/due.json"))
    function update(change) {
      var copy = JSON.parse(JSON.stringify(due))
      change(copy.update, copy)
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
      // Each code has one fix and one blocking flag, from the contract.
      { tag: "another code's fix", text: variant(function(d) { d.problems = [{ code: "not_registered", fix: "start", blocking: true }] }) },
      { tag: "fix missing", text: variant(function(d) { d.problems = [{ code: "not_installed", fix: null, blocking: true }] }) },
      { tag: "fix where there is none", text: variant(function(d) { d.problems = [{ code: "dns_broken", fix: "reconnect", blocking: false }] }) },
      { tag: "blocking Problem said not to block", text: variant(function(d) { d.problems = [{ code: "not_registered", fix: "register", blocking: false }] }) },
      { tag: "routing Problem said to block", text: variant(function(d) { d.problems = [{ code: "not_through_cloudflare", fix: "reconnect", blocking: true }] }) },
      // A blocking Problem nulls everything below it, so it is alone.
      { tag: "two blocking Problems", text: variant(function(d) {
        d.problems = [{ code: "service_stopped", fix: "start", blocking: true }, { code: "not_registered", fix: "register", blocking: true }] }) },
      { tag: "blocking Problem with a DNS Problem", text: variant(function(d) {
        d.problems = [{ code: "not_installed", fix: "install", blocking: true }, { code: "dns_bypassed", fix: "reconnect", blocking: false }] }) },
      { tag: "blocking Problem after another", text: variant(function(d) {
        d.problems = [{ code: "dns_shared", fix: null, blocking: false }, { code: "daemon_unresponsive", fix: "restart", blocking: true }] }) },
      // Precedence order, each code once.
      { tag: "out of precedence order", text: variant(function(d) {
        d.problems = [{ code: "dns_bypassed", fix: "reconnect", blocking: false }, { code: "not_through_cloudflare", fix: "reconnect", blocking: false }] }) },
      { tag: "the same Problem twice", text: variant(function(d) {
        d.problems = [{ code: "dns_shared", fix: null, blocking: false }, { code: "dns_shared", fix: null, blocking: false }] }) },
      { tag: "no job key", text: variant(function(d) { delete d.job }) },
      { tag: "job not an object", text: variant(function(d) { d.job = "start" }) },
      { tag: "unknown job action", text: variant(function(d) { d.job = { action: "uninstall", started_at: "2026-10-02T00:00:00Z" } }) },
      { tag: "prototype key as job action", text: variant(function(d) { d.job = { action: "constructor", started_at: "2026-10-02T00:00:00Z" } }) },
      { tag: "job start not a time", text: variant(function(d) { d.job = { action: "start", started_at: "soon" } }) },
      { tag: "job start not a string", text: variant(function(d) { d.job = { action: "start", started_at: 0 } }) },
      { tag: "no update", text: variant(function(d) { delete d.update }) },
      { tag: "update not an object", text: variant(function(d) { d.update = [true] }) },
      { tag: "available as string", text: update(function(u) { u.available = "true" }) },
      { tag: "available as number", text: update(function(u) { u.available = 1 }) },
      { tag: "available without latest", text: update(function(u) { u.latest = null; u.verified_at = null }) },
      { tag: "available without installed version", text: update(function(u, d) { d.client.version = null }) },
      { tag: "latest not a string", text: update(function(u) { u.latest = 2026 }) },
      { tag: "latest not a version", text: update(function(u) { u.latest = "2026.9\u202e0.1" }) },
      { tag: "latest with markup", text: update(function(u) { u.latest = "<b>2026.9</b>" }) },
      { tag: "latest overlong", text: update(function(u) { u.latest = "1." + new Array(80).join("1") }) },
      { tag: "installed not a version", text: update(function(u, d) { d.client.version = "2026.8 → 9999" }) },
      { tag: "installed not a string", text: update(function(u, d) { d.client.version = 2026.8 }) },
      { tag: "verified_at not a time", text: update(function(u) { u.verified_at = "yesterday" }) },
      { tag: "verified_at not a string", text: update(function(u) { u.verified_at = 0 }) },
      { tag: "unknown last_error", text: update(function(u) { u.last_error = "timeout" }) },
      { tag: "prototype key as last_error", text: update(function(u) { u.last_error = "constructor" }) },
      { tag: "due not a boolean", text: update(function(u) { u.due = "yes" }) },
      { tag: "no due", text: update(function(u) { delete u.due }) },
    ]
  }

  function test_untrusted_output_is_refused(row) {
    compare(Logic.parseStatus(row.text), null)
  }

  // The validator never refuses a document the backend is held to.
  function test_every_shared_fixture_parses_data() {
    return ["on", "off", "connecting", "unconfirmed", "not_installed", "service_stopped",
            "daemon_unresponsive", "not_registered", "outside", "dns_broken", "dns_bypassed",
            "dns_shared", "multi", "trace_failed", "dropped", "update", "restart", "job",
            "verify_failed", "due"].map(function(name) { return { tag: name, fixture: name } })
  }

  function test_every_shared_fixture_parses(row) {
    verify(Logic.parseStatus(fixture(row.fixture)) !== null, row.fixture)
  }

  function test_fixtures_parse() {
    compare(Logic.parseStatus(fixture("off")).client.connection, "disconnected")
    compare(Logic.parseStatus(fixture("connecting")).client.connection, "connecting")
    compare(Logic.parseStatus(fixture("unconfirmed")).client.connection, "connected")
    compare(Logic.parseStatus(fixture("service_stopped")).problems[0].fix, "start")
    compare(Logic.parseStatus(fixture("job")).job.action, "start")
    compare(Logic.parseStatus(fixture("update")).update.available, true)
    compare(Logic.parseStatus(fixture("verify_failed")).update.last_error, "verification")
    compare(Logic.parseStatus(fixture("due")).update.due, true)
    compare(Logic.parseStatus(fixture("not_installed")).update.latest, null)
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
      { tag: "check", action: "check", argv: ["check", "--json"] },
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

  // Register runs `warp-cli registration new` in the terminal, so
  // Cloudflare's terms prompt works there.
  function test_register_button_launches_the_register_job_in_a_terminal() {
    var primary = viewOf("not_registered").primary
    compare(primary.enabled, true)
    compare(Logic.jobLaunch("/srv/oma-warp", primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'register' '--job-id' 'k9-x1'"])
  }

  // A hung daemon is one click from fixed: Restart service runs the
  // restart-and-restore Job in the terminal, where sudo can prompt.
  function test_restart_service_launches_the_restart_job_in_a_terminal() {
    var primary = viewOf("daemon_unresponsive").primary
    compare(primary.enabled, true)
    compare(Logic.jobLaunch("/srv/oma-warp", primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'restart' '--job-id' 'k9-x1'"])
  }

  // Install builds, installs and registers in the terminal, so pacman's
  // confirmation and Cloudflare's terms prompt both work there.
  function test_install_button_launches_the_install_job_in_a_terminal() {
    var primary = viewOf("not_installed").primary
    compare(say(primary.label), "Install")
    compare(primary.enabled, true)
    compare(Logic.jobLaunch("/srv/oma-warp", primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'install' '--job-id' 'k9-x1'"])
  }

  function test_install_command_survives_any_plugin_folder() {
    var primary = viewOf("not_installed").primary
    compare(Logic.jobLaunch("/srv/it's $(here) `x`; a b", primary, "k9-x1")[1],
            "'/usr/bin/python3' '-I' '-B' '/srv/it'\\''s $(here) `x`; a b/oma-warp' 'install' '--job-id' 'k9-x1'")
  }

  // Install is offered only from a live document, with a launchable id and
  // the plugin folder known; otherwise it launches nothing.
  function test_install_launches_nothing_unless_it_can_run_data() {
    return [
      { tag: "backend broken", flags: { backendError: true }, dir: "/srv/oma-warp", id: "k9-x1" },
      { tag: "no plugin folder", dir: "", id: "k9-x1" },
      { tag: "no job id", dir: "/srv/oma-warp", id: "" },
      { tag: "job id not a string", dir: "/srv/oma-warp", id: 42 },
      { tag: "job id like an option", dir: "/srv/oma-warp", id: "-k9" },
      { tag: "job id in capitals", dir: "/srv/oma-warp", id: "K9-X1" },
      { tag: "job id with shell text", dir: "/srv/oma-warp", id: "x' ; reboot '" },
    ]
  }

  function test_install_launches_nothing_unless_it_can_run(row) {
    var primary = viewOf("not_installed", row.flags).primary
    compare(primary.action, "install")
    compare(Logic.jobLaunch(row.dir, primary, row.id), null)
  }

  // While Install runs the Panel only reports it: no fix, no switch, no
  // background check, even though nothing is installed and a check is due.
  function test_while_install_runs_nothing_else_is_offered() {
    var text = variant("not_installed", function(d) {
      d.job = { action: "install", started_at: "2026-10-02T00:00:00Z" }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(say(v.note.line), "Installing WARP…")
    compare(say(v.note.detail), "In a terminal · started 3 s ago")
    compare(say(v.hero.meta), "Working in a terminal")
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(v.primary, null)
    compare(v.update, null)
    compare(v.toggle.enabled, false)
    compare(v.ip.visible, false)
    compare(v.check.start, false)
    compare(Logic.jobLaunch("/srv/oma-warp", v.primary, "k9-x1"), null)
  }

  // Nothing is installed, so there is no update to offer next to Install,
  // and the backend's due check still runs beside it.
  function test_install_holds_the_primary_slot_without_an_update_row() {
    var v = viewOf("not_installed")
    compare(v.update, null)
    compare(v.bar.dot, false)
    compare(v.primary.action, "install")
    compare(v.check.start, true)
    compare(viewOf("not_installed", { autoCheck: false }).check.start, false)
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

  // The runtime dir itself is watched for the backend's folder coming and
  // going; the folder is looked at through a path only a folder satisfies.
  function test_runtime_folder_is_looked_at_from_the_runtime_dir_data() {
    return [
      { tag: "runtime dir", dir: "/run/user/4242", watched: "/run/user/4242", folder: "/run/user/4242/oma-warp/." },
      { tag: "trailing slash", dir: "/run/user/4242/", watched: "/run/user/4242", folder: "/run/user/4242/oma-warp/." },
      { tag: "unset", dir: undefined, watched: "", folder: "" },
      { tag: "relative", dir: "run/user/4242", watched: "", folder: "" },
    ]
  }

  function test_runtime_folder_is_looked_at_from_the_runtime_dir(row) {
    compare(Logic.runtimeDirPath(row.dir), row.watched)
    compare(Logic.runtimeFolderPath(row.dir), row.folder)
  }

  // The record watch only works while its folder exists, so every sighting
  // re-arms it. A folder that has just appeared may already hold a record
  // written before the watch could see it, so that sighting also polls; the
  // first look at startup does not, since the Panel polls on start anyway.
  function test_seeing_the_runtime_folder_re_arms_the_record_watch_data() {
    return [
      { tag: "first look, present", was: null, present: true, rearm: true, poll: false },
      { tag: "first look, absent", was: null, present: false, rearm: false, poll: false },
      { tag: "appeared", was: false, present: true, rearm: true, poll: true },
      { tag: "still there", was: true, present: true, rearm: true, poll: false },
      { tag: "gone", was: true, present: false, rearm: false, poll: false },
      { tag: "still gone", was: false, present: false, rearm: false, poll: false },
    ]
  }

  function test_seeing_the_runtime_folder_re_arms_the_record_watch(row) {
    compare(Logic.runtimeFolderSeen(row.was, row.present), { present: row.present, rearm: row.rearm, poll: row.poll })
  }

  // Update in the primary slot runs the Update Job in the terminal, where
  // pacman's confirmation and sudo work normally.
  function test_update_button_launches_the_update_job_in_a_terminal() {
    var primary = viewOf("update").primary
    compare(say(primary.label), "Update")
    compare(Logic.jobLaunch("/srv/oma-warp", primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'update' '--job-id' 'k9-x1'"])
  }

  function test_update_command_survives_any_plugin_folder() {
    var primary = viewOf("update").primary
    compare(Logic.jobLaunch("/srv/it's $(here) `x`; a b", primary, "k9-x1")[1],
            "'/usr/bin/python3' '-I' '-B' '/srv/it'\\''s $(here) `x`; a b/oma-warp' 'update' '--job-id' 'k9-x1'")
  }

  // Update launches only from a live document, with a launchable id and the
  // plugin folder known, from either position; otherwise it launches
  // nothing.
  function test_update_launches_nothing_unless_it_can_run_data() {
    var rows = []
    var cases = [
      { tag: "backend broken", flags: { backendError: true }, dir: "/srv/oma-warp", id: "k9-x1" },
      { tag: "no plugin folder", dir: "", id: "k9-x1" },
      { tag: "no job id", dir: "/srv/oma-warp", id: "" },
      { tag: "job id not a string", dir: "/srv/oma-warp", id: 42 },
      { tag: "job id like an option", dir: "/srv/oma-warp", id: "-k9" },
      { tag: "job id with shell text", dir: "/srv/oma-warp", id: "x' ; reboot '" },
    ]
    ;["primary", "row"].forEach(function(position) {
      cases.forEach(function(c) {
        rows.push({ tag: position + ", " + c.tag, position: position, flags: c.flags, dir: c.dir, id: c.id })
      })
    })
    return rows
  }

  function test_update_launches_nothing_unless_it_can_run(row) {
    var text = variant(row.position === "primary" ? "update" : "service_stopped", function(d) {
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var v = Logic.view(Logic.parseStatus(text), row.flags || ({}), now)
    var button = row.position === "primary" ? v.primary : v.update.button
    compare(button.action, "update")
    compare(Logic.jobLaunch(row.dir, button, row.id), null)
  }

  // While any Job runs, the Update Job included, neither position offers
  // Update, so nothing launches a second Job.
  function test_update_is_not_offered_while_a_job_runs_data() {
    return [
      { tag: "Update Job", action: "update", line: "Updating WARP…" },
      { tag: "Install Job", action: "install", line: "Installing WARP…" },
    ]
  }

  function test_update_is_not_offered_while_a_job_runs(row) {
    var text = variant("job", function(d) {
      d.job.action = row.action
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.update, null)
    compare(v.primary, null)
    compare(say(v.note.line), row.line)
    compare(v.toggle.enabled, false)
    compare(Logic.jobLaunch("/srv/oma-warp", v.primary, "k9-x1"), null)
  }

  // When a fix or a needed restart holds the primary slot, the small row's
  // own Update button runs the same Update Job, and the primary button
  // still runs its own.
  function test_update_row_launches_the_update_job_in_a_terminal_data() {
    return [
      { tag: "beside Start service", fixture: "service_stopped", restart: false, primary: "start" },
      { tag: "beside Register", fixture: "not_registered", restart: false, primary: "register" },
      { tag: "beside Restart service", fixture: "daemon_unresponsive", restart: false, primary: "restart" },
      { tag: "beside a needed restart", fixture: "on", restart: true, primary: "restart" },
    ]
  }

  function test_update_row_launches_the_update_job_in_a_terminal(row) {
    var text = variant(row.fixture, function(d) {
      d.client.restart_needed = row.restart
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.update.primary, false)
    compare(say(v.update.button.label), "Update")
    compare(Logic.jobLaunch("/srv/oma-warp", v.update.button, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' 'update' '--job-id' 'k9-x1'"])
    compare(Logic.jobLaunch("/srv/oma-warp", v.primary, "k9-x1"),
            ["omarchy-launch-floating-terminal-with-presentation",
             "'/usr/bin/python3' '-I' '-B' '/srv/oma-warp/oma-warp' '" + row.primary + "' '--job-id' 'k9-x1'"])
  }

  // Reconnect is a background command, not a terminal Job.
  function test_only_job_actions_launch_a_terminal() {
    compare(Logic.jobLaunch("/srv/oma-warp", { action: "reconnect", label: null, enabled: true }, "k9-x1"), null)
    compare(Logic.jobLaunch("/srv/oma-warp", { action: "uninstall", label: null, enabled: true }, "k9-x1"), null)
  }

  function test_a_check_is_cut_off_after_30_s() {
    compare(Logic.CHECK_DEADLINE, 30000)
  }

  // `check --json` prints the attempt it recorded, exiting 0 when it
  // verified a release and 1 when the check failed. Anything else (cut off,
  // a crash, never started, output that isn't a recorded attempt) recorded
  // nothing, so the backend still says due.
  function test_a_check_that_recorded_no_attempt_is_abandoned_data() {
    var verified = '{"latest": "2026.9.1180.0", "verified_at": "2026-10-02T00:00:01Z", "last_error": null, "attempted_at": "2026-10-02T00:00:01Z"}'
    var failed = '{"latest": null, "verified_at": null, "last_error": "network", "attempted_at": "2026-10-02T00:00:01Z"}'
    return [
      { tag: "verified", code: 0, text: verified, abandoned: false },
      { tag: "failed, recorded", code: 1, text: failed, abandoned: false },
      { tag: "crashed with exit 1", code: 1, text: "", abandoned: true },
      { tag: "exit 1, unknown error", code: 1, text: failed.replace("network", "timeout"), abandoned: true },
      { tag: "no attempt time", code: 0, text: verified.replace('"attempted_at": "2026-10-02T00:00:01Z"', '"attempted_at": null'), abandoned: true },
      { tag: "not an object", code: 0, text: "[]", abandoned: true },
      { tag: "not json", code: 0, text: "Latest verified release: 2026.9.1180.0", abandoned: true },
      { tag: "usage error", code: 2, text: "", abandoned: true },
      { tag: "interrupted at the deadline", code: 130, text: "", abandoned: true },
      { tag: "killed", code: 9, text: verified, abandoned: true },
      { tag: "never started", code: -1, text: "", abandoned: true },
    ]
  }

  function test_a_check_that_recorded_no_attempt_is_abandoned(row) {
    compare(Logic.checkAbandoned(row.code, row.text), row.abandoned)
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
      { tag: "connecting found it unregistered", fixture: "not_registered", inFlight: "connect", checked: true, meta: "Needs attention" },
      { tag: "connecting found it not installed", fixture: "not_installed", inFlight: "connect", checked: true, meta: "Needs attention" },
      { tag: "disconnecting hung the daemon", fixture: "daemon_unresponsive", inFlight: "disconnect", checked: false, meta: "Needs attention" },
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

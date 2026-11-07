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

  // Finishing an installed update comes before offering the next one: the
  // primary slot stays with the restart, and Update takes the small row.
  function test_a_needed_restart_keeps_update_out_of_the_primary_slot() {
    var text = variant("update", function(d) { d.client.restart_needed = true })
    var v = Logic.view(Logic.parseStatus(text), {}, now)
    compare(v.update.primary, false)
    compare(say(v.update.button.label), "Update")
    verify(v.primary === null || v.primary.label.key !== "update.button")
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

  // The Update Job isn't wired yet: neither position launches anything.
  function test_update_launches_nothing_yet() {
    compare(Logic.jobLaunch("/srv/oma-warp", viewOf("update").primary, "k9-x1"), null)
    var text = variant("service_stopped", function(d) {
      d.update = { latest: "2026.9.1180.0", verified_at: "2026-10-01T00:00:00Z", available: true, last_error: null, due: false }
    })
    compare(Logic.jobLaunch("/srv/oma-warp", Logic.view(Logic.parseStatus(text), {}, now).update.button, "k9-x1"), null)
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

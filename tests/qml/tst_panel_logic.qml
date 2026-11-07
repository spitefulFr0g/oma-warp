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

  // Only a trace on the current connection earns the full cloud, and only
  // then does the IP carry its Cloudflare location.
  function test_on_is_through_cloudflare() {
    var v = viewOf("on")
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Through Cloudflare")
    compare(v.toggle.checked, true)
    compare(v.toggle.enabled, true)
    compare(v.toggle.action, "disconnect")
    compare(v.note, null)
    compare(v.primary, null)
    compare(v.ip.visible, true)
    compare(say(v.ip.label), "IP")
    compare(say(v.ip.value), "203.0.113.7")
    compare(v.ip.muted, false)
    compare(say(v.ip.suffix), "· XXX, XX")
  }

  // Connected, but Cloudflare sees the traffic arrive from outside WARP: a
  // non-blocking Problem, so the switch still works beside its Reconnect.
  function test_outside_offers_reconnect() {
    var v = viewOf("outside")
    compare(v.bar.glyph, crossedCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Needs attention")
    compare(v.toggle.checked, true)
    compare(v.toggle.enabled, true)
    compare(v.toggle.action, "disconnect")
    compare(v.note.kind, "problem")
    compare(say(v.note.line), "Traffic isn't going through Cloudflare")
    compare(say(v.note.detail), "WARP says it's connected, but Cloudflare sees your traffic arriving from outside WARP.")
    compare(v.primary.action, "reconnect")
    compare(say(v.primary.label), "Reconnect")
    compare(v.primary.enabled, true)
    compare(v.ip.visible, true)
    compare(say(v.ip.value), "203.0.113.7")
    compare(v.ip.muted, true)
    compare(say(v.ip.suffix), "· not WARP")
  }

  // A failed trace is not a Problem: a neutral note, never the full cloud.
  function test_trace_failed_is_unconfirmed() {
    var v = viewOf("trace_failed")
    compare(v.bar.glyph, outlinedCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Connected · not confirmed")
    compare(v.toggle.checked, true)
    compare(v.toggle.enabled, true)
    compare(v.note.kind, "unconfirmed")
    compare(say(v.note.line), "Couldn't confirm traffic goes through Cloudflare")
    compare(v.note.detail, null)
    compare(v.primary, null)
    compare(v.ip.visible, true)
    compare(say(v.ip.value), "—")
    compare(v.ip.muted, true)
    compare(v.ip.suffix, null)
  }

  // A probe in flight only speaks where the document has no probe for the
  // current connection; a result it already has stays on screen meanwhile.
  function test_probe_in_flight_data() {
    return [
      { tag: "connected, checking", fixture: "unconfirmed", probing: true, glyph: outlinedCloud, opacity: 1,
        meta: "Connected · checking", note: null, ip: "Checking…", muted: false, suffix: null },
      { tag: "connected, nothing running", fixture: "unconfirmed", probing: false, glyph: outlinedCloud, opacity: 1,
        meta: "Connected · not confirmed", note: "Couldn't confirm traffic goes through Cloudflare", ip: "—", muted: true, suffix: null },
      { tag: "dropped, checking", fixture: "dropped", probing: true, glyph: fullCloud, opacity: 0.42,
        meta: "Off", note: null, ip: "Checking…", muted: false, suffix: null },
      { tag: "dropped, nothing running", fixture: "dropped", probing: false, glyph: fullCloud, opacity: 0.42,
        meta: "Off", note: null, ip: "—", muted: true, suffix: null },
      { tag: "through, checking again", fixture: "on", probing: true, glyph: fullCloud, opacity: 1,
        meta: "Through Cloudflare", note: null, ip: "203.0.113.7", muted: false, suffix: "· XXX, XX" },
      { tag: "trace failed, checking again", fixture: "trace_failed", probing: true, glyph: outlinedCloud, opacity: 1,
        meta: "Connected · not confirmed", note: "Couldn't confirm traffic goes through Cloudflare", ip: "—", muted: true, suffix: null },
      { tag: "outside, checking again", fixture: "outside", probing: true, glyph: crossedCloud, opacity: 1,
        meta: "Needs attention", note: "Traffic isn't going through Cloudflare", ip: "203.0.113.7", muted: true, suffix: "· not WARP" },
    ]
  }

  function test_probe_in_flight(row) {
    var v = viewOf(row.fixture, { probeInFlight: row.probing })
    compare(v.bar.glyph, row.glyph)
    compare(v.bar.opacity, row.opacity)
    compare(say(v.hero.meta), row.meta)
    compare(v.note ? say(v.note.line) : null, row.note)
    compare(v.ip.visible, true)
    compare(say(v.ip.value), row.ip)
    compare(v.ip.muted, row.muted)
    compare(say(v.ip.suffix), row.suffix)
    compare(v.toggle.enabled, true)
  }

  // A probe follows every switch command, so while one runs without a
  // probe for the connection, the Panel is checking rather than unconfirmed.
  function test_a_switch_command_in_flight_is_checking_data() {
    return [
      { tag: "reconnecting", fixture: "unconfirmed", inFlight: "reconnect", meta: "Connected · checking", ip: "Checking…", muted: false },
      { tag: "switching off", fixture: "unconfirmed", inFlight: "disconnect", meta: "Connected · checking", ip: "Checking…", muted: false },
      { tag: "switching on", fixture: "off", inFlight: "connect", meta: "Off", ip: "Checking…", muted: false },
      { tag: "reconnecting, still through", fixture: "on", inFlight: "reconnect", meta: "Through Cloudflare", ip: "203.0.113.7", muted: false },
    ]
  }

  function test_a_switch_command_in_flight_is_checking(row) {
    var v = viewOf(row.fixture, { toggleInFlight: row.inFlight })
    compare(say(v.hero.meta), row.meta)
    compare(v.note, null)
    compare(say(v.ip.value), row.ip)
    compare(v.ip.muted, row.muted)
    compare(v.toggle.busy, true)
  }

  // Location is only ever shown Through Cloudflare; any other known IP is
  // the real address and says so.
  function test_ip_row_follows_the_trace_data() {
    function probe(trace, ip) {
      return { checked_at: "2026-10-02T00:00:00Z", trace: trace, ip: ip, colo: ip ? "XXX" : null, country: ip ? "XX" : null, dns: null }
    }
    return [
      { tag: "off, outside", fixture: "off", change: function(d) { d.probe = probe("outside", "198.51.100.4") },
        ip: "198.51.100.4", muted: true, suffix: "· not WARP" },
      { tag: "off, trace failed", fixture: "off", change: function(d) { d.probe = probe("failed", null) },
        ip: "—", muted: true, suffix: null },
      { tag: "connecting, through", fixture: "connecting", change: function(d) { d.probe = probe("through", "203.0.113.7") },
        ip: "203.0.113.7", muted: true, suffix: "· not WARP" },
      { tag: "through, IPv6", fixture: "on", change: function(d) { d.probe.ip = "2001:db8::7" },
        ip: "2001:db8::7", muted: false, suffix: "· XXX, XX" },
      { tag: "through, no location", fixture: "on", change: function(d) { d.probe.colo = null; d.probe.country = null },
        ip: "203.0.113.7", muted: false, suffix: null },
    ]
  }

  function test_ip_row_follows_the_trace(row) {
    var v = Logic.view(Logic.parseStatus(variant(row.fixture, row.change)), {}, now)
    compare(v.ip.visible, true)
    compare(say(v.ip.value), row.ip)
    compare(v.ip.muted, row.muted)
    compare(say(v.ip.suffix), row.suffix)
  }

  // Reconnect is a switch command: while it or any other runs, neither the
  // switch nor Reconnect takes a click, and the knob stays where it goes.
  function test_reconnect_counts_as_a_toggle_in_flight_data() {
    return [
      { tag: "reconnecting", inFlight: "reconnect", checked: true },
      { tag: "disconnecting", inFlight: "disconnect", checked: false },
      { tag: "connecting", inFlight: "connect", checked: true },
    ]
  }

  function test_reconnect_counts_as_a_toggle_in_flight(row) {
    var v = viewOf("outside", { toggleInFlight: row.inFlight })
    compare(v.toggle.enabled, false)
    compare(v.toggle.busy, true)
    compare(v.toggle.checked, row.checked)
    compare(say(v.primary.label), "Reconnect")
    compare(v.primary.enabled, false)
    compare(say(v.note.line), "Traffic isn't going through Cloudflare")
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

  // Neither a confirmed trace nor a probe in flight outranks the Job.
  function test_job_dims_a_confirmed_cloud() {
    var text = variant("job", function(d) {
      d.client.connection = "connected"
      d.problems = []
      d.probe = JSON.parse(fixture("on")).probe
    })
    var v = Logic.view(Logic.parseStatus(text), { probeInFlight: true }, now)
    compare(v.bar.glyph, fullCloud)
    compare(v.bar.opacity, 0.42)
    compare(say(v.hero.meta), "Working in a terminal")
    compare(v.note.kind, "job")
    compare(v.ip.visible, false)
  }

  // Any Problem crosses the cloud out, even over a confirmed trace, and the
  // location still follows the trace.
  function test_a_problem_outranks_a_confirmed_trace() {
    var v = viewOf("dns_bypassed")
    compare(v.bar.glyph, crossedCloud)
    compare(v.bar.opacity, 1)
    compare(say(v.hero.meta), "Needs attention")
    compare(v.toggle.enabled, true)
    compare(say(v.ip.value), "203.0.113.7")
    compare(v.ip.muted, false)
    compare(say(v.ip.suffix), "· XXX, XX")
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
      { tag: "unconfirmed, toggle in flight", fixture: "unconfirmed", inFlight: "disconnect", glyph: outlinedCloud, opacity: 1, meta: "Connected · checking", checked: false },
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
      { tag: "no probe key", text: variant(function(d) { delete d.probe }) },
      { tag: "probe not an object", text: variant(function(d) { d.probe = "through" }) },
      { tag: "unknown trace", text: variant(function(d) { d.probe = { trace: "on", ip: null, colo: null, country: null, dns: null } }) },
      { tag: "prototype key as trace", text: variant(function(d) { d.probe = { trace: "constructor", ip: null, colo: null, country: null, dns: null } }) },
      { tag: "ip with markup", text: variant(function(d) { d.probe = { trace: "through", ip: "<b>203.0.113.7</b>", colo: "XXX", country: "XX", dns: null } }) },
      { tag: "ip not a string", text: variant(function(d) { d.probe = { trace: "through", ip: 7, colo: "XXX", country: "XX", dns: null } }) },
      { tag: "colo too long", text: variant(function(d) { d.probe = { trace: "through", ip: "203.0.113.7", colo: "XXXXXXXXXXXXXXXX", country: "XX", dns: null } }) },
      { tag: "country with markup", text: variant(function(d) { d.probe = { trace: "through", ip: "203.0.113.7", colo: "XXX", country: "<i>", dns: null } }) },
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
      { tag: "probe", action: "probe", argv: ["status", "--json", "--probe"] },
      { tag: "reconnect", action: "reconnect", argv: ["reconnect"] },
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

  // The primary button either launches its Job in a terminal or runs a
  // switch command in the background; anything else does nothing.
  function test_primary_button_dispatch_data() {
    return [
      { tag: "Reconnect", fixture: "outside", kind: "toggle" },
      { tag: "Start service", fixture: "service_stopped", kind: "job" },
      { tag: "Reconnect, backend broken", fixture: "outside", flags: { backendError: true }, kind: null },
      { tag: "Reconnect, switch busy", fixture: "outside", flags: { toggleInFlight: "disconnect" }, kind: null },
      { tag: "Start service, backend broken", fixture: "service_stopped", flags: { backendError: true }, kind: null },
      { tag: "no button", fixture: "on", kind: null },
    ]
  }

  function test_primary_button_dispatch(row) {
    compare(Logic.primaryDispatch(viewOf(row.fixture, row.flags).primary), row.kind)
  }

  function test_primary_dispatch_refuses_anything_else() {
    compare(Logic.primaryDispatch({ action: "connect", label: null, enabled: true }), null)
    compare(Logic.primaryDispatch({ action: "uninstall", label: null, enabled: true }), null)
    compare(Logic.primaryDispatch({ action: "constructor", label: null, enabled: true }), null)
    compare(Logic.primaryDispatch({ action: "reconnect", label: null, enabled: "yes" }), null)
  }

  // Reconnect is a background command, not a terminal Job.
  function test_only_job_actions_launch_a_terminal() {
    compare(Logic.jobLaunch("/srv/oma-warp", { action: "reconnect", label: null, enabled: true }, "k9-x1"), null)
    compare(Logic.jobLaunch("/srv/oma-warp", { action: "uninstall", label: null, enabled: true }, "k9-x1"), null)
  }

  // warp-cli gets 10 s per command in the backend; Reconnect runs two.
  function test_switch_commands_get_a_deadline() {
    compare(Logic.toggleDeadline("connect"), 15000)
    compare(Logic.toggleDeadline("disconnect"), 15000)
    compare(Logic.toggleDeadline("reconnect"), 25000)
  }

  // A Panel event for the probe schedule, written "type" or "type:detail":
  // "polled:<name>" reports that Fixture, "polled:broken" a failed poll,
  // and "toggleEnded:<action>" the end of that switch command.
  function probeEvent(text) {
    var parts = text.split(":")
    var event = { type: parts[0] }
    if (parts[0] === "polled") event.doc = parts[1] === "broken" ? null : Logic.parseStatus(fixture(parts[1]))
    if (parts[0] === "toggleEnded") event.action = parts[1]
    return event
  }

  // Drives the probe schedule through Panel events, as Panel.qml does, and
  // reports how many probe processes were started, the most ever running
  // at once, and whether a probe counts as in flight at the end.
  function schedule(events) {
    var state = Logic.probeIdle()
    var starts = 0
    var running = 0
    var most = 0
    events.forEach(function(text) {
      var event = probeEvent(text)
      if (event.type === "ended") running = Math.max(0, running - 1)
      var step = Logic.probeStep(state, event)
      state = step.state
      if (step.start) {
        starts += 1
        running += 1
        most = Math.max(most, running)
      }
    })
    return { starts: starts, most: most, inFlight: Logic.probeInFlight(state) }
  }

  function test_opening_the_panel_probes_once() {
    compare(schedule(["opened"]), { starts: 1, most: 1, inFlight: true })
    compare(schedule(["opened", "opened"]), { starts: 1, most: 1, inFlight: true })
  }

  // The probe only writes its result for status to report, so it is still
  // checking until a poll started after it ended has reported. A poll that
  // was already running when it ended may predate the result.
  function test_a_probe_is_in_flight_until_a_later_poll_reports_data() {
    return [
      { tag: "running", events: ["opened"], inFlight: true },
      { tag: "ended, not polled yet", events: ["opened", "ended"], inFlight: true },
      { tag: "ended, then polled", events: ["opened", "ended", "pollStarted", "polled:broken"], inFlight: false },
      { tag: "poll already running when it ended", events: ["opened", "pollStarted", "ended", "polled:broken"], inFlight: true },
      { tag: "then the queued poll", events: ["opened", "pollStarted", "ended", "polled:broken", "pollStarted", "polled:broken"], inFlight: false },
      { tag: "ended twice", events: ["opened", "ended", "ended", "pollStarted", "polled:broken"], inFlight: false },
    ]
  }

  function test_a_probe_is_in_flight_until_a_later_poll_reports(row) {
    var result = schedule(row.events)
    compare(result.starts, 1)
    compare(result.inFlight, row.inFlight)
  }

  // Every change in the polled connection probes, open or closed, starting
  // from the first one seen. A change while a probe runs makes its result
  // stale: one fresh probe follows it, never two at once.
  function test_connection_changes_probe_data() {
    var poll = ["pollStarted"]
    function polled(name) { return poll.concat(["polled:" + name]) }
    return [
      { tag: "first sighting", events: polled("on"), starts: 1, inFlight: true },
      { tag: "unchanged", events: polled("on").concat(["ended"], polled("on"), polled("on")), starts: 1, inFlight: false },
      { tag: "dropped on its own", events: polled("on").concat(["ended"], polled("on"), polled("dropped")), starts: 2, inFlight: true },
      { tag: "and back", events: polled("on").concat(["ended"], polled("dropped"), ["ended"], polled("on")), starts: 3, inFlight: true },
      { tag: "dropped during a probe", events: polled("on").concat(polled("dropped")), starts: 1, inFlight: true },
      { tag: "then that probe ends", events: polled("on").concat(polled("dropped"), ["ended"]), starts: 2, inFlight: true },
      { tag: "several changes, one fresh probe", events: polled("on").concat(polled("dropped"), polled("connecting"), polled("on"), ["ended"]), starts: 2, inFlight: true },
      { tag: "fresh probe done", events: polled("on").concat(polled("dropped"), ["ended", "ended"], polled("dropped")), starts: 2, inFlight: false },
      { tag: "a failed poll is no change", events: polled("on").concat(["ended"], polled("broken"), polled("on")), starts: 1, inFlight: false },
      { tag: "blocked, then fixed", events: polled("service_stopped").concat(["ended"], polled("off")), starts: 2, inFlight: true },
    ]
  }

  function test_connection_changes_probe(row) {
    var result = schedule(row.events)
    compare(result.starts, row.starts)
    compare(result.most, 1)
    compare(result.inFlight, row.inFlight)
  }

  // Reconnect can be over between two polls, so the connection may read the
  // same before and after: its end probes anyway. The switch's own
  // commands change the polled connection, which probes by itself.
  function test_reconnect_probes_again_data() {
    var settled = ["pollStarted", "polled:on", "ended", "pollStarted", "polled:on"]
    return [
      { tag: "reconnected", events: settled.concat(["toggleEnded:reconnect"]), starts: 2, inFlight: true },
      { tag: "switched off", events: settled.concat(["toggleEnded:disconnect"]), starts: 1, inFlight: false },
      { tag: "switched on", events: settled.concat(["toggleEnded:connect"]), starts: 1, inFlight: false },
      { tag: "reconnected during a probe", events: ["pollStarted", "polled:on", "toggleEnded:reconnect"], starts: 1, inFlight: true },
      { tag: "then that probe ends", events: ["pollStarted", "polled:on", "toggleEnded:reconnect", "ended"], starts: 2, inFlight: true },
    ]
  }

  function test_reconnect_probes_again(row) {
    var result = schedule(row.events)
    compare(result.starts, row.starts)
    compare(result.most, 1)
    compare(result.inFlight, row.inFlight)
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
      { tag: "unconfirmed, disconnecting", fixture: "unconfirmed", inFlight: "disconnect", checked: false, meta: "Connected · checking" },
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

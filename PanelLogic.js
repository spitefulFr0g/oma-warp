.pragma library

// Panel logic: the only place the Panel makes decisions. Pure JavaScript with
// no Omarchy or Quickshell imports, so every state can be tested headless.
// All text leaves as {key, args} messages resolved through i18n/en.json.

var CLOUD = String.fromCodePoint(0xF015F)          // nf-md-cloud
var CLOUD_OUTLINE = String.fromCodePoint(0xF0163)  // nf-md-cloud_outline
var CLOUD_OFF = String.fromCodePoint(0xF0164)      // nf-md-cloud_off_outline
var DIMMED = 0.42

function message(key, args) {
  return { key: key, args: args || ({}) }
}

function format(template, args) {
  return String(template).replace(/\{(\w+)\}/g, function(whole, name) {
    return args && Object.prototype.hasOwnProperty.call(args, name) ? String(args[name]) : whole
  })
}

function isMessage(value) {
  return isObject(value) && typeof value.key === "string" && isObject(value.args)
}

// A message to text, with lookup(key) giving the template. Arguments that
// are messages themselves ("started {ago}") are resolved first.
function resolve(msg, lookup) {
  var args = {}
  for (var name in msg.args) {
    var value = msg.args[name]
    args[name] = isMessage(value) ? resolve(value, lookup) : value
  }
  return format(lookup(msg.key), args)
}

// How long ago an ISO time was, as "{n} s / min / h ago". A clock behind
// the record reads as just now.
function ago(iso, now) {
  var seconds = Math.max(0, Math.floor((now.getTime() - Date.parse(iso)) / 1000))
  if (seconds < 60) return message("time.s", { n: seconds })
  if (seconds < 3600) return message("time.min", { n: Math.floor(seconds / 60) })
  return message("time.h", { n: Math.floor(seconds / 3600) })
}

// The backend is always this interpreter, isolated (-I) and writing no
// bytecode into the plugin folder (-B), and only ever one of these commands.
var PYTHON = "/usr/bin/python3"
var COMMANDS = {
  status: ["status", "--json"],
  probe: ["status", "--json", "--probe"],
  connect: ["connect"],
  disconnect: ["disconnect"],
  reconnect: ["reconnect"],
  check: ["check", "--json"]
}

// Qt.resolvedUrl(".") from the plugin folder, as a filesystem path.
function pluginDir(url) {
  return decodeURIComponent(String(url).replace(/^file:\/\//, "")).replace(/\/+$/, "")
}

function backendCommand(dir, action) {
  if (!dir || !Object.prototype.hasOwnProperty.call(COMMANDS, action)) return null
  return [PYTHON, "-I", "-B", dir + "/oma-warp"].concat(COMMANDS[action])
}

// A Job runs in a floating terminal the Panel never holds on to. The
// launcher passes its one argument to bash -c, so each word is quoted.
var LAUNCHER = "omarchy-launch-floating-terminal-with-presentation"
var JOB_ID = /^[0-9a-z][0-9a-z-]*$/

function shellQuote(word) {
  return "'" + String(word).replace(/'/g, "'\\''") + "'"
}

// The Jobs the Panel launches. Update is a Job the backend knows, but its
// button is not wired up yet.
var LAUNCHED_JOBS = ["install", "start", "restart", "register"]

// The launcher argv for the primary button's Job, or null when the button
// is missing, disabled or not a Job the Panel launches.
function jobLaunch(dir, primary, jobId) {
  if (!dir || !primary || primary.enabled !== true || LAUNCHED_JOBS.indexOf(primary.action) < 0) return null
  if (typeof jobId !== "string" || !JOB_ID.test(jobId)) return null
  var argv = [PYTHON, "-I", "-B", dir + "/oma-warp", primary.action, "--job-id", jobId]
  return [LAUNCHER, argv.map(shellQuote).join(" ")]
}

// What pressing the primary button does: "job" launches its Job in a
// terminal, "toggle" runs Reconnect in the background, null does nothing.
function primaryDispatch(primary) {
  if (!primary || primary.enabled !== true) return null
  if (LAUNCHED_JOBS.indexOf(primary.action) >= 0) return "job"
  return primary.action === "reconnect" ? "toggle" : null
}

// A fresh job id from the time in ms and a random draw in [0, 1).
function jobId(nowMs, random) {
  var draw = Math.floor(Math.min(Math.max(Number(random) || 0, 0), 1) * 0x7fffffff)
  return Math.floor(Math.abs(Number(nowMs) || 0)).toString(36) + "-" + draw.toString(36)
}

// $XDG_RUNTIME_DIR, absolute and without a trailing slash, or "" for none.
function runtimeDirPath(runtimeDir) {
  var dir = typeof runtimeDir === "string" ? runtimeDir.replace(/\/+$/, "") : ""
  return dir.charAt(0) === "/" ? dir : ""
}

// The live Job's record, watched so a Job's start and end re-poll at once.
// $XDG_RUNTIME_DIR/oma-warp/job.json, as the backend writes it.
function jobRecordPath(runtimeDir) {
  var dir = runtimeDirPath(runtimeDir)
  return dir ? dir + "/oma-warp/job.json" : ""
}

// The backend's folder in the runtime dir, spelled so that only a folder is
// found there: anything else at that name looks absent and is never read.
function runtimeFolderPath(runtimeDir) {
  var dir = runtimeDirPath(runtimeDir)
  return dir ? dir + "/oma-warp/." : ""
}

// A look at that folder. A file watch needs its folder to exist when it is
// armed and dies with it, so every sighting re-arms the record watch. A
// folder that has just appeared may already hold a record written before the
// watch could see it, so that sighting polls too. The first look (wasPresent
// null) never polls: the Panel polls on start.
function runtimeFolderSeen(wasPresent, present) {
  return { present: present, rearm: present, poll: present && wasPresent === false }
}

// How long the Panel waits on a switch command before ending it: warp-cli
// gets 10 s per command in the backend, and Reconnect runs two.
function toggleDeadline(action) {
  return action === "reconnect" ? 25000 : 15000
}

// `status --json --probe` holds itself to 5 s; the Panel ends it past this.
var PROBE_DEADLINE = 8000

// The probe schedule. The probe runs as its own process, at most one at a
// time, so it never holds up status. A probe still counts as in flight
// after it ends, until a status poll started after that reports what it
// found: the backend keeps the result only while it holds for the current
// connection, so status is the one place it is read from.
function probeIdle() {
  return { seen: false, connection: null, wanted: false, running: false, ended: false, clearing: false }
}

function probeInFlight(state) {
  return state.running || state.ended
}

// One Panel event, and whether it starts a probe process now:
//   {type: "opened"}       the Panel opened
//   {type: "ended"}        the probe process ended, however it ended
//   {type: "pollStarted"}  a status poll started
//   {type: "polled", doc}  that poll reported doc, or null when it failed
//   {type: "toggleEnded", action}  a switch command ended
// The first connection seen counts as a change, from not knowing it.
function probeStep(state, event) {
  var next = { seen: state.seen, connection: state.connection, wanted: state.wanted,
               running: state.running, ended: state.ended, clearing: state.clearing }
  if (event.type === "opened" && !probeInFlight(next)) next.wanted = true
  if (event.type === "toggleEnded" && event.action === "reconnect") next.wanted = true
  if (event.type === "ended" && next.running) {
    next.running = false
    next.ended = true
    next.clearing = false
  }
  if (event.type === "pollStarted") next.clearing = next.ended
  if (event.type === "polled" && next.clearing) {
    next.ended = false
    next.clearing = false
  }
  if (event.type === "polled" && event.doc) {
    var connection = event.doc.client.connection
    if (!next.seen || connection !== next.connection) next.wanted = true
    next.seen = true
    next.connection = connection
  }
  var start = next.wanted && !next.running
  if (start) {
    next.wanted = false
    next.running = true
  }
  return { state: next, start: start }
}

function pollInterval(opened) {
  return opened ? 3000 : 15000
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

var CONNECTIONS = [null, "connected", "connecting", "disconnected"]
var JOB_ACTIONS = ["install", "update", "restart", "start", "register"]
// Background switch commands: the Panel waits on them, one at a time.
var TOGGLE_ACTIONS = ["connect", "disconnect", "reconnect"]

// The contract's Problems in precedence order, each with its one fix and
// blocking flag. The backend classifies; the Panel only checks the list.
var PROBLEMS = [
  { code: "not_installed", fix: "install", blocking: true },
  { code: "service_stopped", fix: "start", blocking: true },
  { code: "daemon_unresponsive", fix: "restart", blocking: true },
  { code: "not_registered", fix: "register", blocking: true },
  { code: "not_through_cloudflare", fix: "reconnect", blocking: false },
  { code: "dns_broken", fix: null, blocking: false, dns: true },
  { code: "dns_bypassed", fix: "reconnect", blocking: false, dns: true },
  { code: "dns_shared", fix: null, blocking: false, dns: true }
]

// Where a Problem stands in precedence order, or -1 when it is not exactly
// one of the contract's.
function problemRank(value) {
  if (!isObject(value)) return -1
  for (var i = 0; i < PROBLEMS.length; i++) {
    var known = PROBLEMS[i]
    if (value.code === known.code) return value.fix === known.fix && value.blocking === known.blocking ? i : -1
  }
  return -1
}

// Known Problems, each once and in precedence order. A blocking Problem
// nulls every fact below it, so it is always alone, and the probe has one
// DNS verdict, so there is at most one DNS code.
function isProblemList(value) {
  if (!Array.isArray(value)) return false
  var last = -1
  var dns = 0
  for (var i = 0; i < value.length; i++) {
    var rank = problemRank(value[i])
    if (rank <= last) return false
    if (value[i].blocking && value.length !== 1) return false
    if (PROBLEMS[rank].dns && ++dns > 1) return false
    last = rank
  }
  return true
}

function isJob(value) {
  return value === null || (isObject(value) && JOB_ACTIONS.indexOf(value.action) >= 0
    && typeof value.started_at === "string" && !isNaN(Date.parse(value.started_at)))
}

// Versions in the backend's own shape, short enough for one line. Anything
// else never reaches a sink.
var VERSION = /^[0-9]+(?:\.[0-9]+)+(?:-[0-9]+)?$/
var CHECK_ERRORS = [null, "network", "verification"]

function isVersion(value) {
  return typeof value === "string" && value.length <= 40 && VERSION.test(value)
}

function isTime(value) {
  return typeof value === "string" && !isNaN(Date.parse(value))
}

// The backend's update verdict: a newer release is only ever claimed with
// both versions known.
function isUpdate(value, installed) {
  if (!isObject(value) || typeof value.due !== "boolean") return false
  if (value.latest !== null && !isVersion(value.latest)) return false
  if (value.verified_at !== null && !isTime(value.verified_at)) return false
  if (CHECK_ERRORS.indexOf(value.last_error) < 0) return false
  if (value.available === true) return value.latest !== null && installed !== null
  return value.available === false || value.available === null
}

var TRACES = ["through", "outside", "failed"]
var IP = /^[0-9A-Fa-f:.]{2,45}$/
var PLACE = /^[A-Za-z]{2,3}$/

function isNullOr(value, test) {
  return value === null || test(value)
}

function isPlace(value) {
  return typeof value === "string" && PLACE.test(value)
}

// The backend's probe for the current connection, or null for none. Its
// address and location only ever reach plain-text sinks, short as they are.
function isProbe(value) {
  if (value === null) return true
  return isObject(value) && TRACES.indexOf(value.trace) >= 0
    && isNullOr(value.ip, function(ip) { return typeof ip === "string" && IP.test(ip) })
    && isNullOr(value.colo, isPlace) && isNullOr(value.country, isPlace)
}

// `status --json` output is untrusted text. Anything that is not a schema-1
// document this Panel understands answers null: the backend is broken.
function parseStatus(text) {
  var doc
  try {
    doc = JSON.parse(String(text))
  } catch (e) {
    return null
  }
  if (!isObject(doc) || doc.schema !== 1 || !isObject(doc.client)) return null
  if (CONNECTIONS.indexOf(doc.client.connection) < 0) return null
  if (doc.client.version !== null && !isVersion(doc.client.version)) return null
  if (!isUpdate(doc.update, doc.client.version)) return null
  if (!isProblemList(doc.problems)) return null
  if (!isJob(doc.job)) return null
  if (!isProbe(doc.probe)) return null
  return doc
}

var META = { disconnected: "meta.off", connecting: "meta.connecting", connected: "meta.unconfirmed" }

// A running Job is calm, never crossed out, even over the Problem it fixes.
// Otherwise any Problem crosses the cloud out. Connected earns the outlined
// cloud until a probe confirms Through Cloudflare, which earns the full one;
// everything else is the full cloud, dimmed. Whatever the cloud, a dot says
// maintenance is waiting.
function barIcon(connection, job, problem, through, dot) {
  if (job) return { glyph: CLOUD, opacity: DIMMED, dot: dot }
  if (problem) return { glyph: CLOUD_OFF, opacity: 1, dot: dot }
  if (through) return { glyph: CLOUD, opacity: 1, dot: dot }
  if (connection === "connected") return { glyph: CLOUD_OUTLINE, opacity: 1, dot: dot }
  return { glyph: CLOUD, opacity: DIMMED, dot: dot }
}

// The backend compares versions; the Panel only reads its verdict.
function updateAvailable(doc) {
  return !!doc && doc.update.available === true
}

// A new client is installed but the old service still runs. Not a Problem;
// only an explicit true counts, as null means the backend can't know.
function restartNeeded(doc) {
  return !!doc && doc.client.restart_needed === true
}

// Maintenance is waiting: a verified newer release, or a restart to finish
// the one already installed.
function maintenanceDot(doc) {
  return updateAvailable(doc) || restartNeeded(doc)
}

function heroMeta(connection, job, problem, through, checking) {
  if (job) return "meta.job"
  if (problem) return "meta.problem"
  if (through) return "meta.through"
  if (checking && connection === "connected") return "meta.checking"
  return Object.prototype.hasOwnProperty.call(META, connection) ? META[connection] : "meta.unknown"
}

// The live Job as the note: what it does, and that it is in a terminal.
function jobNote(job, now) {
  return { kind: "job", line: message("job." + job.action), detail: message("job.hint", { ago: ago(job.started_at, now) }), more: null }
}

// problems[0] as the note: its line and one-line explanation, and a second
// Problem's line after a "+" when there is one.
function problemNote(problems) {
  var problem = problems[0]
  var more = problems.length > 1 ? message("problem.more", { line: message("problem." + problems[1].code) }) : null
  return { kind: "problem", line: message("problem." + problem.code), detail: message("why." + problem.code), more: more }
}

// Connected with nothing to confirm it: a neutral note, not a Problem.
function unconfirmedNote() {
  return { kind: "unconfirmed", line: message("unconfirmed"), detail: null, more: null }
}

// The exit IP, with Cloudflare's location only while Through Cloudflare.
function ipRow(probe, through, checking, visible) {
  var row = { visible: visible, label: message("ip.label"), value: message("ip.none"), muted: true, suffix: null }
  if (checking) {
    row.value = message("ip.checking")
    row.muted = false
  } else if (probe && probe.ip !== null) {
    row.value = message("ip.address", { ip: probe.ip })
    row.muted = !through
    if (!through) row.suffix = message("ip.notWarp")
    else if (probe.colo !== null && probe.country !== null) {
      row.suffix = message("ip.location", { colo: probe.colo, country: probe.country })
    }
  }
  return row
}

// The one thing to do now, as a full-width button. A Job the Panel can't
// launch yet still shows as the fix, disabled. Reconnect is a switch
// command, so it waits for any other to end.
function primaryButton(problem, broken, toggling) {
  if (!problem || !problem.fix) return null
  var unwired = JOB_ACTIONS.indexOf(problem.fix) >= 0 && LAUNCHED_JOBS.indexOf(problem.fix) < 0
  var waiting = problem.fix === "reconnect" && toggling
  return { action: problem.fix, label: message("fix." + problem.fix), enabled: !broken && !unwired && !waiting }
}

// The restart row: finishing an installed update, with a full-width Restart
// that runs the restart-and-restore Job. It holds the primary slot whenever
// no Problem's fix does, and is not offered beside one.
function restartRow(doc, fix, broken) {
  if (!restartNeeded(doc) || fix) return null
  return {
    line: message("restart.line"),
    detail: message("restart.detail", { v: doc.client.version }),
    button: { action: "restart", label: message("restart.button"), enabled: !broken }
  }
}

// The update row: the line and versions, and its own Update button. It
// holds the primary slot unless a fix or a needed restart outranks it. The
// button has no action yet, so it launches nothing until the Update Job is
// wired.
function updateRow(doc, fix, broken) {
  if (!updateAvailable(doc)) return null
  return {
    line: message("update.line"),
    versions: message("update.versions", { from: doc.client.version, to: doc.update.latest }),
    primary: !fix && !restartNeeded(doc),
    button: { label: message("update.button"), enabled: !broken }
  }
}

var CHECK_PERIOD = 12 * 3600 * 1000
// `check --json` runs beside status, never in its way, and gets this long.
var CHECK_DEADLINE = 30000

// `check --json` prints the attempt it recorded: exit 0 with no error when
// it verified a release, 1 with the error when the check failed. Anything
// else (cut off, a crash, never started) recorded no attempt at all. The
// output is untrusted and only ever read for this.
function checkAbandoned(exitCode, text) {
  if (exitCode !== 0 && exitCode !== 1) return true
  var attempt
  try {
    attempt = JSON.parse(String(text))
  } catch (e) {
    return true
  }
  if (!isObject(attempt) || !isTime(attempt.attempted_at)) return true
  if (CHECK_ERRORS.indexOf(attempt.last_error) < 0) return true
  return (attempt.last_error === null) !== (exitCode === 0)
}

// A check the Panel had to abandon (cut off at its deadline, or dead before
// it could record its attempt) holds the next one off for the same 12 h a
// recorded attempt would.
function recentlyAbandoned(at, now) {
  return typeof at === "number" && isFinite(at) && now.getTime() - at < CHECK_PERIOD
}

// When the backend says a check is due, auto-check is on (anything but an
// explicit false, as it defaults to on) and no check is in flight,
// `check --json` runs in the background. A stale document says nothing is
// due, and a live Job is left alone.
function backgroundCheck(doc, flags, now) {
  return !!doc && !doc.job && flags.backendError !== true && doc.update.due === true
    && flags.autoCheck !== false && flags.checkInFlight !== true
    && !recentlyAbandoned(flags.checkAbandonedAt, now)
}

function view(doc, flags, now) {
  flags = flags || ({})
  var connection = doc ? doc.client.connection : null
  var known = Object.prototype.hasOwnProperty.call(META, connection)
  var job = doc ? doc.job : null
  // Nothing else is shown or offered while a Job runs.
  var problem = doc && !job && doc.problems.length ? doc.problems[0] : null
  var on = connection === "connected" || connection === "connecting"
  var inFlight = TOGGLE_ACTIONS.indexOf(flags.toggleInFlight) >= 0 ? flags.toggleInFlight : null
  var broken = flags.backendError === true
  var probe = doc ? doc.probe : null
  // The only way to earn the full cloud: connected, and a probe on this
  // connection saw the traffic arrive through WARP.
  var through = connection === "connected" && probe !== null && probe.trace === "through"
  // A probe in flight stands in for a result only where there is none yet,
  // and one follows every switch command.
  var checking = (flags.probeInFlight === true || !!inFlight) && probe === null
  var meta = heroMeta(connection, job, problem, through, checking)
  var fix = primaryButton(problem, broken, !!inFlight)
  var restart = job ? null : restartRow(doc, fix, broken)
  var update = job ? null : updateRow(doc, fix, broken)
  return {
    greyed: broken,
    banner: broken ? message("backendError") : null,
    bar: barIcon(connection, job, problem, through, maintenanceDot(doc)),
    hero: { title: message("title"), meta: message(meta) },
    note: job ? jobNote(job, now) : problem ? problemNote(doc.problems) : meta === "meta.unconfirmed" ? unconfirmedNote() : null,
    ip: ipRow(probe, through, checking, !job && !(problem && problem.blocking)),
    primary: fix || (restart ? restart.button : update && update.primary ? update.button : null),
    restart: restart,
    update: update,
    check: { start: backgroundCheck(doc, flags, now) },
    toggle: {
      checked: inFlight ? inFlight !== "disconnect" : on,
      enabled: known && !job && !inFlight && !broken,
      busy: !!inFlight,
      action: on ? "disconnect" : "connect"
    }
  }
}

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
  connect: ["connect"],
  disconnect: ["disconnect"]
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

// The Jobs the Panel launches. Install and Restart service are Jobs the
// backend knows, but their fix buttons are not wired up yet.
var LAUNCHED_JOBS = ["start", "register"]

// The launcher argv for the primary button's Job, or null when the button
// is missing, disabled or not a Job the Panel launches.
function jobLaunch(dir, primary, jobId) {
  if (!dir || !primary || primary.enabled !== true || LAUNCHED_JOBS.indexOf(primary.action) < 0) return null
  if (typeof jobId !== "string" || !JOB_ID.test(jobId)) return null
  var argv = [PYTHON, "-I", "-B", dir + "/oma-warp", primary.action, "--job-id", jobId]
  return [LAUNCHER, argv.map(shellQuote).join(" ")]
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

function pollInterval(opened) {
  return opened ? 3000 : 15000
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

var CONNECTIONS = [null, "connected", "connecting", "disconnected"]
var JOB_ACTIONS = ["install", "update", "restart", "start", "register"]

// The contract's Problems in precedence order, each with its one fix and
// blocking flag. The backend classifies; the Panel only checks the list.
var PROBLEMS = [
  { code: "not_installed", fix: "install", blocking: true },
  { code: "service_stopped", fix: "start", blocking: true },
  { code: "daemon_unresponsive", fix: "restart", blocking: true },
  { code: "not_registered", fix: "register", blocking: true },
  { code: "not_through_cloudflare", fix: "reconnect", blocking: false },
  { code: "dns_broken", fix: null, blocking: false },
  { code: "dns_bypassed", fix: "reconnect", blocking: false },
  { code: "dns_shared", fix: null, blocking: false }
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
// nulls every fact below it, so it is always alone.
function isProblemList(value) {
  if (!Array.isArray(value)) return false
  var last = -1
  for (var i = 0; i < value.length; i++) {
    var rank = problemRank(value[i])
    if (rank <= last) return false
    if (value[i].blocking && value.length !== 1) return false
    last = rank
  }
  return true
}

function isJob(value) {
  return value === null || (isObject(value) && JOB_ACTIONS.indexOf(value.action) >= 0
    && typeof value.started_at === "string" && !isNaN(Date.parse(value.started_at)))
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
  if (!isProblemList(doc.problems)) return null
  if (!isJob(doc.job)) return null
  return doc
}

var META = { disconnected: "meta.off", connecting: "meta.connecting", connected: "meta.unconfirmed" }

// A running Job is calm, never crossed out, even over the Problem it fixes.
// Otherwise any Problem crosses the cloud out. Connected earns the outlined
// cloud until a probe confirms Through Cloudflare; everything else is the
// full cloud, dimmed.
function barIcon(connection, job, problem) {
  if (job) return { glyph: CLOUD, opacity: DIMMED }
  if (problem) return { glyph: CLOUD_OFF, opacity: 1 }
  if (connection === "connected") return { glyph: CLOUD_OUTLINE, opacity: 1 }
  return { glyph: CLOUD, opacity: DIMMED }
}

function heroMeta(connection, job, problem) {
  if (job) return "meta.job"
  if (problem) return "meta.problem"
  return Object.prototype.hasOwnProperty.call(META, connection) ? META[connection] : "meta.unknown"
}

// The live Job as the note: what it does, and that it is in a terminal.
function jobNote(job, now) {
  return { kind: "job", line: message("job." + job.action), detail: message("job.hint", { ago: ago(job.started_at, now) }) }
}

// problems[0] as the note: its line and one-line explanation.
function problemNote(problem) {
  return { kind: "problem", line: message("problem." + problem.code), detail: message("why." + problem.code) }
}

// The one thing to do now, as a full-width button. A Job the Panel can't
// launch yet still shows as the fix, disabled.
function primaryButton(problem, broken) {
  if (!problem || !problem.fix) return null
  var unwired = JOB_ACTIONS.indexOf(problem.fix) >= 0 && LAUNCHED_JOBS.indexOf(problem.fix) < 0
  return { action: problem.fix, label: message("fix." + problem.fix), enabled: !broken && !unwired }
}

function view(doc, flags, now) {
  flags = flags || ({})
  var connection = doc ? doc.client.connection : null
  var known = Object.prototype.hasOwnProperty.call(META, connection)
  var job = doc ? doc.job : null
  // Nothing else is shown or offered while a Job runs.
  var problem = doc && !job && doc.problems.length ? doc.problems[0] : null
  var on = connection === "connected" || connection === "connecting"
  var inFlight = flags.toggleInFlight === "connect" || flags.toggleInFlight === "disconnect" ? flags.toggleInFlight : null
  var broken = flags.backendError === true
  return {
    greyed: broken,
    banner: broken ? message("backendError") : null,
    bar: barIcon(connection, job, problem),
    hero: { title: message("title"), meta: message(heroMeta(connection, job, problem)) },
    note: job ? jobNote(job, now) : problem ? problemNote(problem) : null,
    ip: { visible: !job && !(problem && problem.blocking) },
    primary: primaryButton(problem, broken),
    toggle: {
      checked: inFlight ? inFlight === "connect" : on,
      enabled: known && !job && !inFlight && !broken,
      busy: !!inFlight,
      action: on ? "disconnect" : "connect"
    }
  }
}

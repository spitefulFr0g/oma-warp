pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "PanelLogic.js" as Logic

// The bar icon and the Panel. Every decision lives in PanelLogic.js; this file
// runs the backend from its allow-list, holds the flags, and binds to the
// logic's output. Backend text only ever reaches plain-text sinks. Jobs run
// detached in a floating terminal; their record only prompts a re-poll. The
// update check and the probe run beside status and never hold it up; status
// reports what they found. The Panel has two views, Status and Diagnostics,
// switched from the hero's ⓘ and ← and never by tabs.
Panel {
  id: root
  moduleName: "spitefulfr0g.oma-warp"
  ipcTarget: "spitefulfr0g.oma-warp"

  readonly property string pluginDir: Logic.pluginDir(Qt.resolvedUrl("."))

  // The last document that parsed, kept (greyed) while the backend is broken.
  property var latest: null
  property bool backendError: false
  // The switch command still running, or "" when none is.
  property string toggleInFlight: ""
  // The switch command has ended; the toggle counts as in flight until a
  // status poll started after it reports the state it left behind.
  property bool toggleEnded: false
  property bool pollClearsToggle: false
  property bool pollQueued: false
  property bool statusExited: false
  // When to probe, and whether a probe counts as in flight: see probeStep().
  property var probeState: Logic.probeIdle()
  // The background update check counts as in flight from its start until a
  // status poll started after it ended has reported, so a poll that was
  // already running when it ended can't start a second one.
  property bool checkInFlight: false
  property bool checkEnded: false
  property bool pollClearsCheck: false
  property bool checkCutOff: false
  property bool checkExited: false
  // When the Panel last abandoned a check that recorded no attempt.
  property real checkAbandonedAt: NaN
  // The view showing: "status" (the default) or "diagnostics".
  property string page: "status"

  readonly property var view: Logic.view(root.latest, root.flags(), new Date())

  function flags() {
    return {
      toggleInFlight: root.toggleInFlight !== "" ? root.toggleInFlight : null,
      probeInFlight: Logic.probeInFlight(root.probeState),
      backendError: root.backendError,
      checkInFlight: root.checkInFlight,
      checkAbandonedAt: root.checkAbandonedAt,
      autoCheck: root.setting("autoCheck", true),
      page: root.page
    }
  }

  // The host types `bar` and `Style.font` as plain QtObjects, so their
  // members are read here once rather than unchecked all over the file.
  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground // qmllint disable missing-property
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family // qmllint disable missing-property
  readonly property int displaySize: Style.font.display // qmllint disable missing-property
  readonly property int noteSize: Style.font.bodySmall // qmllint disable missing-property
  readonly property int bodySize: Style.font.body // qmllint disable missing-property
  readonly property int captionSize: Style.font.caption // qmllint disable missing-property
  readonly property color dim: Qt.darker(root.foreground, 1.4)

  // How a Diagnostics value reads: a wrong fact urgent, a missing one muted,
  // one still coming or that couldn't be had dim.
  function toneColor(tone) {
    if (tone === "bad") return Commons.Color.urgent
    if (tone === "muted") return Commons.Color.muted
    if (tone === "dim") return root.dim
    return root.foreground
  }

  Commons.Translations {
    id: strings
    directory: Qt.resolvedUrl("i18n")
  }

  function say(message) {
    return message ? Logic.resolve(message, function(key) { return strings.t(key) }) : ""
  }

  function poll() {
    if (statusProcess.running) {
      pollQueued = true
      return
    }
    var argv = Logic.backendCommand(pluginDir, "status")
    if (!argv) {
      backendError = true
      return
    }
    pollQueued = false
    pollClearsToggle = toggleEnded
    pollClearsCheck = checkEnded
    statusExited = false
    statusProcess.command = argv
    statusProcess.running = true
    statusWatchdog.restart()
    probeEvent({ type: "pollStarted" })
  }

  function statusFinished(exitCode, text) {
    statusWatchdog.stop()
    var doc = exitCode === 0 ? Logic.parseStatus(text) : null
    if (doc) {
      latest = doc
      backendError = false
    } else {
      backendError = true
    }
    if (pollClearsToggle) {
      toggleInFlight = ""
      toggleEnded = false
      pollClearsToggle = false
    }
    if (pollClearsCheck) {
      checkInFlight = false
      checkEnded = false
      pollClearsCheck = false
    }
    if (Logic.view(latest, flags(), new Date()).check.start) startCheck()
    probeEvent({ type: "polled", doc: doc })
    // Deferred so the finished process has let go of `running`.
    if (pollQueued) Qt.callLater(root.poll)
  }

  function flipSwitch() {
    if (view.toggle.enabled) runToggle(view.toggle.action)
  }

  // connect, disconnect or reconnect, one at a time, in the background.
  function runToggle(action) {
    if (toggleProcess.running || toggleInFlight !== "") return
    var argv = Logic.backendCommand(pluginDir, action)
    if (!argv) return
    toggleInFlight = action
    toggleEnded = false
    toggleProcess.command = argv
    toggleProcess.running = true
    toggleWatchdog.interval = Logic.toggleDeadline(action)
    toggleWatchdog.restart()
  }

  function toggleFinished() {
    toggleWatchdog.stop()
    if (toggleInFlight === "" || toggleEnded) return
    toggleEnded = true
    probeEvent({ type: "toggleEnded", action: toggleInFlight })
    poll()
  }

  function probeEvent(event) {
    var step = Logic.probeStep(probeState, event)
    probeState = step.state
    // Deferred so a probe that has just ended has let go of `running`.
    if (step.start) Qt.callLater(root.startProbe)
  }

  function startProbe() {
    var argv = Logic.backendCommand(pluginDir, "probe")
    if (!argv || probeProcess.running) {
      probeFinished()
      return
    }
    probeProcess.command = argv
    probeProcess.running = true
    probeWatchdog.restart()
  }

  // Whatever the probe found is read from the next status poll, which only
  // reports it while it still holds for the current connection.
  function probeFinished() {
    probeWatchdog.stop()
    if (!probeState.running) return
    probeEvent({ type: "ended" })
    poll()
  }

  // A fix button, on Status or beside its Diagnostics row: a Job in a
  // terminal, or Reconnect in the background.
  function pressFix(fix) {
    var kind = Logic.primaryDispatch(fix)
    if (kind === "job") launchJob(fix)
    else if (kind === "toggle") runToggle(fix.action)
  }

  function pressPrimary() {
    pressFix(view.primary)
  }

  // The fix beside a Diagnostics row, as the current view has it.
  function pressRowFix(id) {
    var rows = view.diagnostics.rows
    for (let i = 0; i < rows.length; i++) if (rows[i].id === id) pressFix(rows[i].fix)
  }

  // Check now: the user asked, so auto-check and the back-off don't hold it.
  function checkNow() {
    if (view.diagnostics.check.button.enabled) startCheck()
  }

  // The auto-check switch persists through the shell's plugin settings, in
  // this Panel's own shell.json entry, and takes effect at once.
  function setAutoCheck(on) {
    var entry = Logic.autoCheckSettings(root.settings, on)
    root.settings = entry
    var shell = root.bar ? root.bar.shell : null // qmllint disable missing-property
    if (shell && typeof shell.updateEntryInline === "function") shell.updateEntryInline(root.moduleName, entry)
  }

  function startCheck() {
    if (checkInFlight || checkProcess.running) return
    var argv = Logic.backendCommand(pluginDir, "check")
    if (!argv) return
    checkInFlight = true
    checkEnded = false
    checkCutOff = false
    checkExited = false
    checkProcess.command = argv
    checkProcess.running = true
    checkDeadline.restart()
  }

  // The result is read from the next status poll; the check's own output
  // only says whether it recorded an attempt at all.
  function checkFinished(exitCode, crashed, text) {
    checkDeadline.stop()
    checkKill.stop()
    if (!checkInFlight || checkEnded) return
    checkAbandonedAt = Logic.backOffAfterCheck(checkCutOff || crashed ? -1 : exitCode, text, Date.now())
    checkEnded = true
    poll()
  }

  // The one way a button starts a Job: the primary button, or the update
  // row's own Update. The Panel closes first so the terminal gets the
  // user's attention; the terminal is never a child of this Panel.
  function launchJob(jobButton) {
    var argv = Logic.jobLaunch(pluginDir, jobButton, Logic.jobId(Date.now(), Math.random()))
    if (!argv) return
    root.close()
    Quickshell.execDetached(argv)
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    page = "status"
    poll()
    probeEvent({ type: "opened" })
    Qt.callLater(function() { if (panel.loadedContent) panel.loadedContent.forceActiveFocus() })
  }

  Process {
    id: statusProcess
    running: false
    stdout: StdioCollector {
      id: statusOutput
      waitForEnd: true
    }
    onExited: function(exitCode) {
      root.statusExited = true
      root.statusFinished(exitCode, String(statusOutput.text || ""))
    }
    // A backend that never started never exits either.
    onRunningChanged: if (!running) Qt.callLater(function() {
      if (!root.statusExited && !statusProcess.running) root.statusFinished(-1, "")
    })
  }

  // status --json holds itself to 2 s; past this the backend is hung.
  Timer {
    id: statusWatchdog
    interval: 5000
    onTriggered: if (statusProcess.running) statusProcess.signal(9)
  }

  Process {
    id: probeProcess
    running: false
    onRunningChanged: if (!running) root.probeFinished()
  }

  // `status --json --probe` holds itself to 5 s; past this it is hung. This
  // also ends a probe that never started, so probing cannot stall.
  Timer {
    id: probeWatchdog
    interval: Logic.PROBE_DEADLINE
    onTriggered: if (probeProcess.running) probeProcess.signal(9)
                 else root.probeFinished()
  }

  Process {
    id: checkProcess
    running: false
    stdout: StdioCollector {
      id: checkOutput
      waitForEnd: true
    }
    onExited: function(exitCode, exitStatus) {
      root.checkExited = true
      root.checkFinished(exitCode, exitStatus !== 0, String(checkOutput.text || ""))
    }
    onRunningChanged: if (!running) Qt.callLater(function() {
      if (!root.checkExited && !checkProcess.running) root.checkFinished(-1, true, "")
    })
  }

  // At the deadline the check is interrupted, which still lets it remove
  // its scratch download; one that ignores that is killed soon after.
  Timer {
    id: checkDeadline
    interval: Logic.CHECK_DEADLINE
    onTriggered: {
      if (checkProcess.running) {
        root.checkCutOff = true
        checkProcess.signal(2)
        checkKill.restart()
      } else {
        root.checkFinished(-1, true, "")
      }
    }
  }

  Timer {
    id: checkKill
    interval: 3000
    onTriggered: if (checkProcess.running) checkProcess.signal(9)
  }

  Process {
    id: toggleProcess
    running: false
    onRunningChanged: if (!running) root.toggleFinished()
  }

  // warp-cli gets 10 s per command in the backend; this also ends a switch
  // command that never started, so the switch cannot stay disabled.
  Timer {
    id: toggleWatchdog
    interval: Logic.toggleDeadline("connect")
    onTriggered: if (toggleProcess.running) toggleProcess.signal(9)
                 else root.toggleFinished()
  }

  // A Job writes job.json as it starts and removes it as it ends: either
  // change re-polls at once.
  JobRecordWatch {
    runtimeDir: Quickshell.env("XDG_RUNTIME_DIR")
    onPollNeeded: root.poll()
  }

  Timer {
    interval: Logic.pollInterval(root.opened)
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.poll()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: root.say(root.view.hero.title) + " · " + root.say(root.view.hero.meta)
    iconComponent: Component {
      Item {
        OpticalGlyph {
          anchors.fill: parent
          text: root.view.bar.glyph
          opacity: root.view.bar.opacity
          color: button.foreground
          fontFamily: button.fontFamily
          fontSize: button.fontSize
        }

        // Maintenance is waiting: a small dot, top right, never dimmed.
        Rectangle {
          visible: root.view.bar.dot
          anchors.top: parent.top
          anchors.right: parent.right
          width: Math.max(3, Math.round(button.fontSize * 0.28))
          height: width
          radius: width / 2
          color: button.activeColor
        }
      }
    }
    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: panel.loadedContent
    contentWidth: panel.fittedContentWidth(Style.space(320))
    contentHeight: panel.fittedContentHeight(panel.loadedContentHeight, Style.space(480))

    content: PanelKeyCatcher {
      implicitHeight: column.implicitHeight
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onActivateRequested: root.flipSwitch()

      // Diagnostics can outgrow a short screen: it scrolls rather than cut.
      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        // Each view starts at its top.
        Connections {
          target: root
          function onPageChanged() { flick.contentY = 0 }
        }

        Column {
          id: column
          width: flick.width
          spacing: Style.space(12)

          BorderSurface {
            visible: root.view.banner !== null
            width: parent.width
            implicitHeight: bannerText.implicitHeight + Style.space(14)
            color: "transparent"
            borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent)
            radius: Style.cornerRadius

            Text {
              id: bannerText
              textFormat: Text.PlainText
              anchors.verticalCenter: parent.verticalCenter
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.leftMargin: Style.space(10)
              anchors.rightMargin: Style.space(10)
              text: root.say(root.view.banner)
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: root.noteSize
              wrapMode: Text.WordWrap
            }
          }

          PanelHero {
            width: parent.width
            opacity: root.view.greyed ? 0.38 : 1
            title: root.say(root.view.hero.title)
            meta: root.say(root.view.hero.meta)
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconOpacity: root.view.bar.opacity
            iconComponent: Component {
              Text {
                textFormat: Text.PlainText
                text: root.view.bar.glyph
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: root.displaySize
              }
            }
            // ⓘ opens Diagnostics, ← comes back; then the switch.
            trailingControl: Component {
              Row {
                spacing: Style.space(6)

                PanelActionButton {
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: root.view.hero.control.glyph
                  tooltipText: root.say(root.view.hero.control.tooltip)
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  onClicked: root.page = root.view.hero.control.page
                }

                ToggleSwitch {
                  anchors.verticalCenter: parent.verticalCenter
                  checked: root.view.toggle.checked
                  busy: root.view.toggle.busy
                  enabled: root.view.toggle.enabled
                  opacity: enabled ? 1 : 0.4
                  foreground: root.foreground
                  onToggled: root.flipSwitch()
                }
              }
            }
          }

          // Status: the note, the IP, and the one thing to do now.
          Column {
            visible: root.view.page === "status"
            width: parent.width
            spacing: Style.space(12)

            // A Problem: its bold urgent line and the one-line explanation.
            Column {
              visible: root.view.note !== null && root.view.note.kind === "problem"
              width: parent.width
              opacity: root.view.greyed ? 0.38 : 1
              spacing: Style.space(2)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.view.note ? root.say(root.view.note.line) : ""
                color: Commons.Color.urgent
                font.family: root.fontFamily
                font.pixelSize: root.bodySize
                font.bold: true
                wrapMode: Text.WordWrap
              }

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.view.note ? root.say(root.view.note.detail) : ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: root.noteSize
                wrapMode: Text.WordWrap
              }

              // A second Problem: its line after a "+", under the explanation.
              Text {
                visible: root.view.note !== null && root.view.note.more !== null
                width: parent.width
                topPadding: Style.space(2)
                textFormat: Text.PlainText
                text: root.view.note ? root.say(root.view.note.more) : ""
                color: Commons.Color.urgent
                font.family: root.fontFamily
                font.pixelSize: root.noteSize
                wrapMode: Text.WordWrap
              }
            }

            // The live Job: what it does, and that it runs in a terminal.
            BorderSurface {
              visible: root.view.note !== null && root.view.note.kind === "job"
              width: parent.width
              opacity: root.view.greyed ? 0.38 : 1
              implicitHeight: jobColumn.implicitHeight + Style.space(16)
              color: Qt.alpha(Commons.Color.accent, 0.08)
              borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent)
              radius: Style.cornerRadius

              Text {
                id: jobGlyph
                textFormat: Text.PlainText
                anchors.left: parent.left
                anchors.top: jobColumn.top
                anchors.leftMargin: Style.space(10)
                text: "⟳"
                color: Commons.Color.accent
                font.family: root.fontFamily
                font.pixelSize: root.bodySize
                font.bold: true
              }

              Column {
                id: jobColumn
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: jobGlyph.right
                anchors.right: parent.right
                anchors.leftMargin: Style.space(9)
                anchors.rightMargin: Style.space(10)
                spacing: Style.space(4)

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.view.note ? root.say(root.view.note.line) : ""
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: root.bodySize
                  wrapMode: Text.WordWrap
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.view.note ? root.say(root.view.note.detail) : ""
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: root.noteSize
                  wrapMode: Text.WordWrap
                }
              }
            }

            // Connected, but nothing confirms it: neutral, not a Problem.
            BorderSurface {
              visible: root.view.note !== null && root.view.note.kind === "unconfirmed"
              width: parent.width
              opacity: root.view.greyed ? 0.38 : 1
              implicitHeight: unconfirmedText.implicitHeight + Style.space(16)
              color: Qt.alpha(root.foreground, 0.04)
              borderSpec: Border.controlSpec("normal", Qt.alpha(root.foreground, 0.12), Qt.alpha(root.foreground, 0.12))
              radius: Style.cornerRadius

              Text {
                id: unconfirmedGlyph
                textFormat: Text.PlainText
                anchors.left: parent.left
                anchors.top: unconfirmedText.top
                anchors.leftMargin: Style.space(10)
                text: "?"
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: root.bodySize
                font.bold: true
              }

              Text {
                id: unconfirmedText
                textFormat: Text.PlainText
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: unconfirmedGlyph.right
                anchors.right: parent.right
                anchors.leftMargin: Style.space(9)
                anchors.rightMargin: Style.space(10)
                text: root.view.note ? root.say(root.view.note.line) : ""
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: root.bodySize
                wrapMode: Text.WordWrap
              }
            }

            // The exit IP: its location only while Through Cloudflare, muted and
            // marked "not WARP" when it is the real address.
            Item {
              visible: root.view.ip.visible
              width: parent.width
              opacity: root.view.greyed ? 0.38 : 1
              implicitHeight: Math.max(ipLabel.implicitHeight, ipValue.implicitHeight)

              Text {
                id: ipLabel
                textFormat: Text.PlainText
                anchors.left: parent.left
                anchors.baseline: ipValue.baseline
                text: root.say(root.view.ip.label)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: root.bodySize
              }

              Text {
                id: ipValue
                textFormat: Text.PlainText
                anchors.left: ipLabel.right
                anchors.right: parent.right
                anchors.leftMargin: Style.space(12)
                horizontalAlignment: Text.AlignRight
                text: root.say(root.view.ip.value) + (root.view.ip.suffix ? " " + root.say(root.view.ip.suffix) : "")
                color: root.view.ip.muted ? Commons.Color.muted : root.foreground
                font.family: root.fontFamily
                font.pixelSize: root.bodySize
                wrapMode: Text.WrapAnywhere
              }
            }

            // A verified newer release: its line and versions above the primary
            // Update button, or beside a regular Update button of its own when
            // something else holds the primary slot.
            Item {
              visible: root.view.update !== null
              width: parent.width
              opacity: root.view.greyed ? 0.38 : 1
              implicitHeight: Math.max(updateColumn.implicitHeight, updateButton.visible ? updateButton.implicitHeight : 0)

              Rectangle {
                id: updateDot
                anchors.left: parent.left
                anchors.verticalCenter: updateColumn.verticalCenter
                width: Style.space(6)
                height: width
                radius: width / 2
                color: button.activeColor
              }

              Column {
                id: updateColumn
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: updateDot.right
                anchors.right: updateButton.visible ? updateButton.left : parent.right
                anchors.leftMargin: Style.space(7)
                anchors.rightMargin: updateButton.visible ? Style.space(8) : 0
                spacing: Style.space(2)

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.view.update ? root.say(root.view.update.line) : ""
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: root.bodySize
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.view.update ? root.say(root.view.update.versions) : ""
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: root.noteSize
                  elide: Text.ElideRight
                }
              }

              Button {
                id: updateButton
                visible: root.view.update !== null && !root.view.update.primary
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                bordered: true
                enabled: root.view.update !== null && root.view.update.button.enabled
                opacity: enabled ? 1 : 0.35
                text: root.view.update ? root.say(root.view.update.button.label) : ""
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.launchJob(root.view.update ? root.view.update.button : null)
              }
            }

            // A new client under the old service: its line and detail sit right
            // above the full-width Restart, below any small Update row.
            Item {
              visible: root.view.restart !== null
              width: parent.width
              opacity: root.view.greyed ? 0.38 : 1
              implicitHeight: restartColumn.implicitHeight

              Rectangle {
                id: restartDot
                anchors.left: parent.left
                anchors.verticalCenter: restartColumn.verticalCenter
                width: Style.space(6)
                height: width
                radius: width / 2
                color: button.activeColor
              }

              Column {
                id: restartColumn
                anchors.left: restartDot.right
                anchors.right: parent.right
                anchors.leftMargin: Style.space(7)
                spacing: Style.space(2)

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.view.restart ? root.say(root.view.restart.line) : ""
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: root.bodySize
                  elide: Text.ElideRight
                }

                Text {
                  width: parent.width
                  textFormat: Text.PlainText
                  text: root.view.restart ? root.say(root.view.restart.detail) : ""
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: root.noteSize
                  // The installed version is the point of the line: it wraps
                  // rather than being cut off at the Panel's width.
                  wrapMode: Text.Wrap
                }
              }
            }

            // The one thing to do now.
            Button {
              visible: root.view.primary !== null
              width: parent.width
              bordered: true
              active: true
              enabled: root.view.primary !== null && root.view.primary.enabled
              opacity: enabled ? 1 : 0.35
              text: root.view.primary ? root.say(root.view.primary.label) : ""
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.pressPrimary()
            }
          }

          // Diagnostics: label · value · fix, one row per fact, then the update
          // check. A Problem's fix sits beside its row with the explanation
          // beneath; a check error sits under Latest release.
          Column {
            id: diagnostics
            visible: root.view.page === "diagnostics"
            width: parent.width
            opacity: root.view.greyed ? 0.38 : 1
            spacing: Style.space(12)

            Column {
              id: table
              width: parent.width
              // The label column fits the longest label.
              property real labelWidth: 0

              Repeater {
                model: root.view.diagnostics.rows

                delegate: Item {
                  id: tableRow
                  required property var modelData
                  required property int index
                  width: table.width
                  implicitHeight: rowColumn.implicitHeight

                  Rectangle {
                    visible: tableRow.index > 0
                    width: parent.width
                    height: 1
                    color: Qt.alpha(root.foreground, 0.12)
                  }

                  Column {
                    id: rowColumn
                    width: parent.width
                    topPadding: Style.space(5)
                    bottomPadding: Style.space(5)
                    spacing: Style.space(2)

                    Item {
                      width: parent.width
                      implicitHeight: Math.max(rowLabel.implicitHeight, rowValue.implicitHeight,
                                               rowFix.visible ? rowFix.implicitHeight : 0)

                      Text {
                        id: rowLabel
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: table.labelWidth
                        textFormat: Text.PlainText
                        text: root.say(tableRow.modelData.label)
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: root.noteSize
                        onImplicitWidthChanged: table.labelWidth = Math.max(table.labelWidth, implicitWidth)
                        Component.onCompleted: table.labelWidth = Math.max(table.labelWidth, implicitWidth)
                      }

                      // The value, and how fresh it is right after it.
                      Flow {
                        id: rowValue
                        anchors.left: rowLabel.right
                        anchors.right: rowFix.visible ? rowFix.left : parent.right
                        anchors.leftMargin: Style.space(10)
                        anchors.rightMargin: rowFix.visible ? Style.space(8) : 0
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Style.space(6)

                        Text {
                          width: Math.min(implicitWidth, rowValue.width)
                          textFormat: Text.PlainText
                          text: root.say(tableRow.modelData.value)
                          color: root.toneColor(tableRow.modelData.tone)
                          font.family: root.fontFamily
                          font.pixelSize: root.noteSize
                          wrapMode: Text.Wrap
                        }

                        Text {
                          visible: tableRow.modelData.detail !== null
                          width: Math.min(implicitWidth, rowValue.width)
                          textFormat: Text.PlainText
                          text: root.say(tableRow.modelData.detail)
                          color: Commons.Color.muted
                          font.family: root.fontFamily
                          font.pixelSize: root.captionSize
                          wrapMode: Text.Wrap
                        }
                      }

                      Button {
                        id: rowFix
                        visible: tableRow.modelData.fix !== null
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        bordered: true
                        fontSize: root.noteSize
                        horizontalPadding: Style.space(8)
                        verticalPadding: Style.space(3)
                        enabled: tableRow.modelData.fix !== null && tableRow.modelData.fix.enabled
                        opacity: enabled ? 1 : 0.35
                        text: tableRow.modelData.fix ? root.say(tableRow.modelData.fix.label) : ""
                        foreground: root.foreground
                        fontFamily: root.fontFamily
                        onClicked: root.pressRowFix(tableRow.modelData.id)
                      }
                    }

                    // The Problem's explanation, spanning the row.
                    Text {
                      visible: tableRow.modelData.why !== null
                      width: parent.width
                      textFormat: Text.PlainText
                      text: root.say(tableRow.modelData.why)
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: root.captionSize
                      wrapMode: Text.WordWrap
                    }

                    // A failed update check, under Latest release.
                    Text {
                      visible: tableRow.modelData.error !== null
                      width: parent.width
                      textFormat: Text.PlainText
                      text: root.say(tableRow.modelData.error)
                      color: Commons.Color.urgent
                      font.family: root.fontFamily
                      font.pixelSize: root.captionSize
                      wrapMode: Text.WordWrap
                    }
                  }
                }
              }
            }

            // Check every 12 h, and Check now.
            Item {
              width: parent.width
              implicitHeight: Math.max(autoSwitch.implicitHeight, checkButton.implicitHeight)

              ToggleSwitch {
                id: autoSwitch
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                checked: root.view.diagnostics.check.auto.checked
                foreground: root.foreground
                onToggled: root.setAutoCheck(!checked)
              }

              Text {
                anchors.left: autoSwitch.right
                anchors.right: checkButton.left
                anchors.leftMargin: Style.space(8)
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                textFormat: Text.PlainText
                text: root.say(root.view.diagnostics.check.auto.label)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: root.noteSize
                elide: Text.ElideRight
              }

              Button {
                id: checkButton
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                bordered: true
                fontSize: root.noteSize
                horizontalPadding: Style.space(8)
                verticalPadding: Style.space(3)
                enabled: root.view.diagnostics.check.button.enabled
                opacity: enabled ? 1 : 0.35
                text: root.say(root.view.diagnostics.check.button.label)
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.checkNow()
              }
            }
          }
        }
      }
    }
  }
}

pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "PanelLogic.js" as Logic

// The bar icon and the Panel. Every decision lives in PanelLogic.js; this file
// runs the backend from its allow-list, holds the flags, and binds to the
// logic's output. Backend text only ever reaches plain-text sinks. Jobs run
// detached in a floating terminal; their record only prompts a re-poll.
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

  readonly property var view: Logic.view(root.latest, {
    toggleInFlight: root.toggleInFlight !== "" ? root.toggleInFlight : null,
    backendError: root.backendError
  }, new Date())

  // The host types `bar` and `Style.font` as plain QtObjects, so their
  // members are read here once rather than unchecked all over the file.
  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground // qmllint disable missing-property
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family // qmllint disable missing-property
  readonly property int displaySize: Style.font.display // qmllint disable missing-property
  readonly property int noteSize: Style.font.bodySmall // qmllint disable missing-property
  readonly property int bodySize: Style.font.body // qmllint disable missing-property
  readonly property color dim: Qt.darker(root.foreground, 1.4)

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
    statusExited = false
    statusProcess.command = argv
    statusProcess.running = true
    statusWatchdog.restart()
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
    // Deferred so the finished process has let go of `running`.
    if (pollQueued) Qt.callLater(root.poll)
  }

  function flipSwitch() {
    if (!view.toggle.enabled || toggleProcess.running || toggleInFlight !== "") return
    var argv = Logic.backendCommand(pluginDir, view.toggle.action)
    if (!argv) return
    toggleInFlight = view.toggle.action
    toggleEnded = false
    toggleProcess.command = argv
    toggleProcess.running = true
    toggleWatchdog.restart()
  }

  function toggleFinished() {
    toggleWatchdog.stop()
    if (toggleInFlight === "" || toggleEnded) return
    toggleEnded = true
    poll()
  }

  // The Panel closes first so the terminal gets the user's attention; the
  // terminal is never a child of this Panel.
  function launchJob() {
    var argv = Logic.jobLaunch(pluginDir, view.primary, Logic.jobId(Date.now(), Math.random()))
    if (!argv) return
    root.close()
    Quickshell.execDetached(argv)
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    poll()
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
    id: toggleProcess
    running: false
    onRunningChanged: if (!running) root.toggleFinished()
  }

  // warp-cli gets 10 s in the backend; this also ends a switch command that
  // never started, so the switch cannot stay disabled.
  Timer {
    id: toggleWatchdog
    interval: 15000
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

      Column {
        id: column
        width: parent.width
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
          trailingControl: Component {
            ToggleSwitch {
              checked: root.view.toggle.checked
              busy: root.view.toggle.busy
              enabled: root.view.toggle.enabled
              opacity: enabled ? 1 : 0.4
              foreground: root.foreground
              onToggled: root.flipSwitch()
            }
          }
        }

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
          onClicked: root.launchJob()
        }
      }
    }
  }
}

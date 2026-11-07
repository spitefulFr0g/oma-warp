import QtQuick
import Quickshell
import Quickshell.Io
import "PanelLogic.js" as Logic

// Watches the live Job's record so a Job's start and end re-poll at once.
// Nothing is ever read: status reports the Job only while its process is
// alive, and regular polling stays the fallback.
//
// A FileView watches its file through the file's folder, armed once with
// whatever exists then: a missing folder is never watched, and a folder that
// is removed takes the watch with it. The backend's folder may not exist yet
// when the shell starts, so the runtime dir is watched for it coming and
// going, and each sighting re-arms the record watch (see runtimeFolderSeen).
// Changes inside the folder, like the probe cache, never reach that path.
Scope {
  id: watch

  property string runtimeDir: ""
  property var folderPresent: null

  // The record may have changed: the Panel should poll now.
  signal pollNeeded()

  function folderSeen(present) {
    var step = Logic.runtimeFolderSeen(watch.folderPresent, present)
    watch.folderPresent = step.present
    if (step.rearm) {
      record.watchChanges = false
      record.watchChanges = true
    }
    if (step.poll) watch.pollNeeded()
  }

  FileView {
    id: record
    path: Logic.jobRecordPath(watch.runtimeDir)
    preload: false
    watchChanges: true
    printErrors: false
    onFileChanged: watch.pollNeeded()
  }

  // Fires when any entry of the runtime dir is added or removed.
  FileView {
    path: Logic.runtimeDirPath(watch.runtimeDir)
    preload: false
    watchChanges: true
    printErrors: false
    onFileChanged: folder.reload()
  }

  // Only ever stats the folder: a folder fails to load as "not a file".
  FileView {
    id: folder
    path: Logic.runtimeFolderPath(watch.runtimeDir)
    printErrors: false
    onLoadFailed: function(error) { watch.folderSeen(error === FileViewError.NotAFile) }
    onLoaded: watch.folderSeen(false)
  }
}

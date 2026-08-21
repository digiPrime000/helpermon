Screenshots for INSTALL.md
==========================

INSTALL.md already points at the files below. Drop a PNG in here under the
exact name and the picture appears; no text has to be edited.

One rule, and it is the same promise the rest of the project makes: these are
pictures of Helpermon's own windows and of Windows itself. Nothing from the
game screen belongs in this folder. Numbers 07 and 11 are the two to watch --
crop LDPlayer's settings so no game artwork is in frame, and take the dry run
on the Dungeons page, whose log is text.

Everything else in the repository refuses to carry a .png at all. This folder
is the single exception, and release.py knows about it by name.

  file                            what it should show
  ------------------------------  -----------------------------------------
  01-releases-page.png            this repository's Releases page, with
                                  helpermon-x.y.zip visible under Assets
  02-unblock-zip.png              the ZIP's Properties dialog, bottom of the
                                  General tab, Unblock ticked
  03-unpacked-folder.png          Explorer in the unpacked folder, with
                                  install.bat in view
  04-install-python-question.png  the black install.bat window at the moment
                                  it asks about Python
  05-install-finished.png         install.bat's last screen, the one that
                                  says the shortcut was created
  06-desktop-shortcut.png         the Helpermon icon on the desktop. Crop it
                                  close, do not photograph the whole desktop
  07-ldplayer-adb-setting.png     LDPlayer, Settings, Other settings, with
                                  ADB debugging switched on
  08-first-run-input-dialog.png   Helpermon's first dialog, ADB or mouse,
                                  with the Check ADB now button visible
  09-first-run-legal-notice.png   the legal notice dialog
  10-start-here.png               the Start here page, Try it right now at
                                  the top, the three numbered steps below
  11-dungeons-dry-run.png         the Dungeons page after a dry run, with a
                                  few lines in the log
  12-remove-bat.png               optional. remove.bat asking its first
                                  question

Practical notes

* Full window, not the whole screen. Alt+PrtSc copies the active window
  only; the Snipping Tool (Win+Shift+S) lets you draw the crop.
* PNG, not JPG. Text stays sharp and the files stay small.
* Around 900 to 1400 pixels wide is plenty. GitHub scales anything wider
  down, so a 4K screenshot only makes the repository bigger.
* Check for your own name in the picture before saving: a title bar, a path
  in Explorer's address bar, an account name in a corner.

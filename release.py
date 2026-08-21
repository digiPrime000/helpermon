"""
Build the copy for publishing.

The `templates` and `digits` folders contain crops taken from the game, which is
third-party material. They do not belong in a published copy. This build leaves
them out, which makes the setup wizard mandatory, and that is the intent.

Building into an existing folder empties it first, but never touches the
things that live there in their own right: a `.git` folder, a `.venv`, a
`userdata`. That matters because the target is meant to be the published
checkout, and an earlier version deleted the whole folder, `.git` included,
which left a copy that had forgotten it was a repository.

  py release.py                 writes ../helpermon_release
  py release.py --target path
  py release.py --check         only show what would be excluded
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Do not ship: third-party imagery or local state.
# Every folder whose name starts with one of these prefixes is dropped. This
# covers the debug dumps, which keep appearing under new names, without anyone
# having to remember to extend a list.
EXCLUDED_FOLDER_PREFIXES = ["debug"]
# Folders that do not follow that naming convention and have to be named.
# .venv is the environment install.bat builds. It must never be copied: it
# is hundreds of megabytes and every path inside it is absolute, so it
# would not work anywhere but on this machine anyway.
EXCLUDED_FOLDERS = ["templates", "digits", "userdata", "__pycache__", ".git",
                    ".venv"]
# The starter make_shortcut.py writes is local state: it hardcodes the
# absolute path of the pythonw.exe on the machine that made it. install.bat,
# which creates it, does ship. Hence names rather than a *.bat rule.
EXCLUDED_FILES = ["calib.json", "Start Helpermon.bat", "Start bot.bat",
                  "Bot starten.bat"]
EXCLUDED_SUFFIXES = [".pyc", ".png", ".jpg", ".log"]

# Documents ship by whitelist. Everything else ending in .md is internal --
# working notes, plans, instructions for tooling -- and stays here. A list of
# what to leave out is one somebody has to remember to extend, and CLAUDE.md
# and RELEASE_PLAN.md shipped for exactly that reason. Only .md is covered, so
# requirements.txt and LICENSE.txt are unaffected.
PUBLIC_DOCS = ["README.md", "QUICKSTART.md", "INSTALL.md", "CONTRIBUTING.md"]

# The one place in the tree where an image may live: the screenshots
# INSTALL.md shows. They are pictures of Helpermon's own windows and of
# Windows itself, never of the game screen, and docs/images/READ_ME.txt says
# so where whoever adds one will read it. Everywhere else the audit below
# still refuses an image outright.
IMAGE_FOLDER = os.path.join("docs", "images")

# Present in the target and not ours to delete when rebuilding into it. The
# git repository is the one that matters; the other two are what a player
# would have there if they ran the copy.
KEEP_IN_TARGET = [".git", ".venv", "userdata"]

# The shipping promise: not one file derived from the game screen. Nothing may
# ever be included that matches this, no matter what the rules above say.
FORBIDDEN_SUFFIXES = [".png", ".jpg", ".jpeg", ".bmp"]
FORBIDDEN_NAMES = ["calib.json"]


def is_excluded_folder(name):
    return (name in EXCLUDED_FOLDERS
            or any(name.startswith(p) for p in EXCLUDED_FOLDER_PREFIXES))


def is_internal_doc(name):
    return name.lower().endswith(".md") and name not in PUBLIC_DOCS


def is_documentation_image(rel):
    """True for a path inside docs/images, the one folder images may ship from."""
    return os.path.normpath(rel).startswith(IMAGE_FOLDER + os.sep)


def clear_target(target):
    """Empty the target, keeping what belongs to it rather than to us."""
    kept = []
    for name in sorted(os.listdir(target)):
        if name in KEEP_IN_TARGET:
            kept.append(name)
            continue
        path = os.path.join(target, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    return kept


def count_files(path):
    return sum(len(files) for _, _, files in os.walk(path))


def collect():
    included, excluded = [], []
    for root, folders, files in os.walk(HERE):
        rel_root = os.path.relpath(root, HERE)
        dropped = [o for o in folders if is_excluded_folder(o)]
        folders[:] = [o for o in folders if o not in dropped]
        for name in sorted(dropped):
            path = os.path.join(root, name)
            rel = os.path.normpath(os.path.join(rel_root, name))
            excluded.append("%s%s  (%d files)" % (rel, os.sep, count_files(path)))
        for name in files:
            rel = os.path.normpath(os.path.join(rel_root, name))
            by_suffix = (any(name.endswith(e) for e in EXCLUDED_SUFFIXES)
                         and not is_documentation_image(rel))
            if (name in EXCLUDED_FILES
                    or is_internal_doc(name)
                    or by_suffix):
                excluded.append(rel)
            else:
                included.append(rel)
    return sorted(included), sorted(excluded)


def audit(included):
    """Return every included file that breaks the no-game-content promise."""
    offenders = []
    for rel in included:
        if is_documentation_image(rel):
            continue
        name = os.path.basename(rel).lower()
        if (name in FORBIDDEN_NAMES
                or any(name.endswith(e) for e in FORBIDDEN_SUFFIXES)):
            offenders.append(rel)
    return offenders


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=os.path.join(os.path.dirname(HERE),
                                                   "helpermon_release"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    included, excluded = collect()
    print("Will be shipped, %d files" % len(included))
    for name in included:
        print("   %s" % name)
    print("\nWill be excluded")
    for name in excluded:
        print("   %s" % name)
    internal = [n for n in excluded if is_internal_doc(os.path.basename(n))]
    if internal:
        print("\nHeld back as internal documents: %s" % ", ".join(internal))
        print("Shipped documents are %s." % ", ".join(PUBLIC_DOCS))

    shots = [n for n in included if is_documentation_image(n)
             and any(n.lower().endswith(e) for e in FORBIDDEN_SUFFIXES)]
    if shots:
        print("\nScreenshots for INSTALL.md, %d of them. The audit lets these"
              % len(shots))
        print("through, so they are the one thing here nobody checks but you:")
        for name in shots:
            print("   %s" % name)

    offenders = audit(included)
    if offenders:
        print("\nSTOP: these files would ship game content, nothing was written")
        for name in offenders:
            print("   %s" % name)
        print("Fix the exclusion rules in release.py before building.")
        return 1

    if args.check:
        print("\nChecked only, nothing written.")
        return 0

    if os.path.exists(args.target):
        kept = clear_target(args.target)
        if kept:
            print("\nLeft alone in the target: %s" % ", ".join(kept))
    for rel in included:
        source = os.path.join(HERE, rel)
        target = os.path.join(args.target, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)

    # Empty placeholders, so it is clear where learned images belong
    for folder in ("templates", "digits"):
        path = os.path.join(args.target, folder)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "READ_ME.txt"), "w") as fh:
            fh.write("This folder is empty on purpose.\n\n"
                     "The images the bots need are learned from your own\n"
                     "screen. To create them, run\n\n"
                     "  py setup_wizard.py\n\n"
                     "What you learn is stored in userdata, not here.\n")

    print("\nBuild written to %s" % args.target)
    print("The setup wizard is mandatory there, no images from the game "
          "are included.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

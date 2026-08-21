# Helpermon - quick start

> **An unofficial fan project.** Helpermon is not made, endorsed, sponsored or
> supported by Bandai Namco, Bandai, Toei Animation, or anyone else involved in
> Digimon UP. *Digimon* and every name, character and image belonging to the
> game are the property of their owners. Nothing from the game is contained
> here; what the bots need, they learn from your own screen.

For people seeing this program for the first time. Helpermon plays three parts
of Digimon UP for you: the dungeon list, the **Digital World Search** and the
**Midsummer Digimon Night Market**.

## What you need

* Windows
* LDPlayer with Digimon UP installed. Do **not** start LDPlayer as
  administrator, see [If Windows gets in the way](#if-windows-gets-in-the-way)
* Python 3.10 or newer. If you do not have it, the installer offers to fetch
  it for you and no administrator password is needed

## Installing

**[INSTALL.md](INSTALL.md) is the installation, step by step and with
pictures.** In short: take the newest `helpermon-x.y.zip` from **Releases**,
right-click it and tick **Unblock** in its Properties *before* unpacking,
unpack it under your own user folder, and double-click `install.bat`. It finds
or fetches Python, builds a `.venv` beside the program and puts a **Helpermon**
shortcut on your desktop. That shortcut is what you start from then on.

The unblocking is the one step that causes trouble when it is skipped, because
Windows passes the internet mark from the ZIP to every file inside it.

Prefer a terminal, or do you already keep your own environments? Then the
packages by hand and skip `install.bat` entirely:

```
py -m pip install -r requirements.txt
py app.py
```

**Updating later:** unpack the new ZIP over the old folder and run
`install.bat` again. `userdata` and `.venv` are not in the ZIP, so nothing you
have taught the bots is lost. If you use git, `git clone` and `git pull` do the
same job, and files from git carry no internet mark, so the unblocking does not
apply to them.

The first launch shows two dialogs. The first one is about **how Helpermon
reaches the emulator**, and it is the one that decides what the next hour
looks like:

* **With ADB**, Helpermon sends its taps straight to the emulator. Your mouse
  stays yours and the window may sit behind other windows. You have to switch
  it on first: in LDPlayer, **Settings → Other settings → ADB debugging**.
  Then press **Check ADB now** in that dialog, which asks the emulator instead
  of guessing.

  LDPlayer itself puts up an error when a lot is driven through ADB in one
  sitting. That is the emulator complaining, not the game — restart the
  emulator, or put that bot on mouse input for the rest of the session.
* **Without ADB**, the bot moves your real mouse. Then leave the mouse alone
  while a bot runs, or tick **Pause Bot on mouse move** at the top right of
  the window and it stops the moment you touch it. The emulator window also
  has to stay visible, in front and uncovered, and the screen must not go to
  sleep — screen capture keeps returning the last picture that was drawn, and
  a bot reading that clicks at what was there minutes ago.

The second dialog is the legal notice, which you have to read. After that you
land on **Start here**.

The first time you start each bot, it tells you in one dialog what has to be
on screen before it can do anything. That same list is on the bot's page, in
the yellow box under the heading.

The window has three parts, and they do not change:

* a **header** across the top with the emulator's state: a coloured dot and
  one line saying what was found. It reports and nothing more — the buttons
  that start the emulator live on step 1 of Start here, because a row of
  buttons repeated on every page competes with whatever that page is for. The
  one exception is top right, the mouse-movement pause, which is wanted at the
  moment a bot has just taken the mouse.
* a **sidebar** on the left listing where you can go: Start here, the three
  bots, About. A green dot next to a bot means it is ready to run, an orange
  one means it still needs setup. There is no shared Setup page: each bot is
  set up from its own page, with the button at the bottom right.
* the **page** you selected, filling the rest.

**Start here** offers you two ways in, with an **OR** between them.

At the top, while there is still setup to be done, is **Try it right now**.
The dungeon bot needs nothing taught, so that card starts the emulator and
takes you straight to it. This is the short way, and it is the one to take
first: you see the program actually working before you spend any time on it.
The card disappears once all three bots are set up, since by then you know.

Underneath is **Set everything up**, three numbered steps: start the emulator,
teach it what your screen looks like, run a bot. Each one shows how far you
have got and has the one button that moves you on. Steps you have finished get
a tick.

## Three bots, different requirements

| | Dungeons | Digital World Search | Night Market |
|---|---|---|---|
| Plays | the dungeon list | Digital World Search | Midsummer Digimon Night Market |
| Setup required | no | yes, about 5 minutes | yes, twelve icons |
| Game language | any | you teach it the banner texts | any |
| Character skin | irrelevant | **Botamon**, see below | irrelevant |
| In the sidebar | Dungeons | World Search | Night Market |

**The dungeon bot can start right away.** It recognises buttons by colour and
position, so it needs no images from the game at all and works in any language.

**Digital World Search needs setup.** It has to tell tickets, claws, pyramids
and your character apart. It crops those images from your own screen, nothing
is shipped with the program.

> **The skin matters for this one.** This bot was built and measured with the
> **Botamon** skin, and finding the figure is the part that depends on it.
> Another skin may work perfectly well. It may also make the bot miss the
> figure and steer by something else instead, and it will not always say so —
> it can simply walk the wrong way. If you use a different skin, watch the
> first run with **Dry run** before letting it click.

**The Night Market bot needs setup too, a smaller one.** It is there to grind
the items out of the seasonal missions: it plays round after round for the
mission rewards, not for a high score. It reads the order shown above the
counter, builds the same skewer from the 4x3 ingredient grid and submits it. For that it has to tell the twelve ingredients apart, so you
crop those twelve icons from your own screen once. Language does not matter,
they are pictures.

## Order of things

Follow the three steps on **Start here** and you are done. In full:

1. Start LDPlayer and open the game, or press **Start LDPlayer** in the
   header. Do not minimise the window
2. Open **Dungeons** in the sidebar and press **Dry run** first. It clicks
   nothing and only shows what it would do
3. If that looks sensible, press **Start**
4. For the other two bots, open that bot in the sidebar and press **Set up
   this bot**, bottom right. That window has that bot's steps and no others,
   so there is no way to wander into a different bot's setup by pressing
   Continue
5. After setup, open Digital World Search in the game and stay on the board,
   then **World Search** in the sidebar and press **Start**
6. For the Night Market, open it in the game and stop at its own main menu,
   the screen with the Play Game lantern — the bot presses Play Game itself.
   Then **Night Market** in the sidebar and **Start**

Every bot page works the same way: its settings, then **Start**, **Pause** and
**Stop**, then its log. **Dry run** sits below under *For testing* — it plans
everything and clicks nothing, which is what to send along if you report a
problem.

### The Night Market page

| Setting | What it does |
|---|---|
| Rounds | how many rounds to play in a row |
| Speed | the wait between clicks. 1 is full pace, lower is slower |
| Start from the main menu | clicks Play Game and Start before the first round |
| Diagnostics | reads the current screen once and clicks nothing |

Speed only changes the wait *between clicks*, never the waits for the game
itself. Full pace is 330 ms per click. It used to be 180, and at that rate the
bot was reaching for a grid the emulator had not finished redrawing — which
costs an order rather than saving time. The dial in the window only goes
downwards from full pace; if you want to try faster, `py skewer.py --go
--speed 1.2` will, and watch a real round before leaving it there.

Press **Diagnostics** whenever the bot behaves oddly. It prints what it sees
right now, ingredient by ingredient, and saves the crops it read from into
`debug_skewer/`.

## Creating the templates

**The program ships with no images from the game.** Every picture the bots
match against is one you create yourself, once, from your own screen. That is
deliberate: game artwork is someone else's material and does not belong in a
published copy.

Press **Set up this bot** at the bottom right of a bot's page and a window
opens with that bot's steps and nothing else — Continue past the last one
finishes. That is the only way in from the window, on purpose. To walk every
step of every bot in one go, run `py setup_wizard.py` from a terminal. The
eight steps and who owns them:

| Step | Belongs to | What it learns | What must be on screen |
|---|---|---|---|
| Overview | the full wizard only | nothing, it shows what is present and what is missing | anything |
| Counters | World Search | digit images, from seven numbers you type in | the minigame board |
| Objects | World Search | tickets, claws, paws, fireballs | the minigame board |
| Pyramid | World Search | the pyramid obstacle | the minigame board |
| Banners | World Search | the two banner texts, in your game language | the minigame board |
| Skewer | Night Market | the twelve ingredient icons | the Night Market |
| Game icon | Dungeons | where the game's icon is, so Instant AFK can start it | the emulator's home screen |
| Open cases | World Search | rare finds the bot collected while running | anything |

Two things are worth knowing:

* Press **Grab a new frame** after switching what is on screen. The board steps
  need a board on screen, the Skewer step needs the cooking minigame instead.
* In the Skewer step the **names are yours to choose**. The first time, the
  boxes hold guesses taken from a screenshot; type what the ingredient
  actually is, or leave them. After that the boxes offer the names you
  already used, so saving again replaces those icons instead of adding more.
* **Never give one ingredient two names.** Two names for the same picture
  leave the matcher no way to choose between them, and it will refuse to name
  that cell at all — which stops the bot from reading an order. The wizard
  notices this after saving and offers to move the leftovers aside.
* **Test match** reads every cell back afterwards, and each one should name
  itself. A cell showing `?` is the warning sign.

Everything learned is stored under `userdata/`, next to the program, never in
the program folder itself. That means:

* a program update deletes nothing you taught it
* deleting `userdata/` resets the setup completely
* backing up that one folder backs up your whole setup

**Redo the setup after a skin change or a game update.** The images are crops
of what your screen looked like at the time. A new character skin, a redrawn
icon or a different UI scale makes them stop matching, and the wizard is a few
minutes' work.

Rare power-ups do not show up in a short session. The bot collects what it
cannot identify while it runs, and you label those later under **Open cases**.

## If Windows gets in the way

Helpermon reads the screen, moves the mouse and listens for a hotkey. That is
the same list of abilities as a piece of spyware, so Windows watches for it.
Everything below is Windows doing its job, not something being wrong.

| What you see | What it is | What to do |
|---|---|---|
| "Windows protected your PC" or "the publisher could not be verified" when starting `install.bat` | the internet mark on the unpacked files | unblock the ZIP as in step 2 and unpack it again, or click **More info**, **Run anyway** |
| a bot runs, the log looks right, but nothing happens in the game | LDPlayer is running as administrator and Helpermon is not. Windows lets no ordinary program send clicks or keys into an elevated window, and it reports no error for the attempt | start LDPlayer normally, without administrator. If it has to be elevated, start Helpermon elevated too. Or use ADB, which does not go through Windows input at all |
| the pause hotkey does nothing | the same cause | the same answer |
| a firewall box when ADB starts | the ADB server opens a port on your own machine | allow it for **private networks**, take the tick off **public** |
| your antivirus quarantines something | rare with the source code, since nothing here is a packaged program | exclude the Helpermon folder in your antivirus, and tell us which file it named |

There is deliberately no packaged `.exe`. A single file containing a screen
reader, an input injector and a keyboard hook is exactly the shape of thing
virus scanners are built to flag, and an unsigned one carries a SmartScreen
warning until enough people have downloaded it. The source and one `.bat` avoid
all of it, at the price of installing Python once.

## If something does not work

| Symptom | Likely cause |
|---|---|
| no emulator window found | LDPlayer is not running or is minimised |
| character not found | different character skin, relearn it in the wizard |
| bot clicks the wrong spot | the window was not in the foreground |
| list does not scroll | raise Patience on the Dungeons page |
| unknown banner text | learn text 2 in the wizard |
| Night Market bot refuses to start | the twelve icons are not learned yet, run the wizard's Skewer step |
| Night Market bot builds the wrong order | press Diagnostics and check what it reads; relearn any icon that names itself wrongly |
| Night Market bot misses clicks | Speed is too high for your machine, lower it |

Pause and emergency stop are available in all three bots. They take effect
between two actions, so within about a second, never in the middle of a click.

## Uninstalling

**Double-click `remove.bat`.** It asks twice, because the two halves are not
the same decision:

1. **The installation** — the `.venv` folder with the packages in it, the
   starter and the desktop shortcut. Around 400 MB, and `install.bat` puts all
   of it back in a few minutes. The shortcut is checked before it goes: one
   that points at a different copy of Helpermon is left alone.
2. **What you taught it** — the `userdata` folder and your settings. This is
   the part that cannot be downloaded again. Say no if you are reinstalling or
   moving the folder somewhere else.

What is left afterwards is text files. Delete the folder to finish; the file
cannot delete the folder it is running from. Python itself is not touched,
since other things on your machine may be using it.

## Important notice

The publisher's terms of service explicitly prohibit bots and emulators in
section 11 g. Anyone using this program risks having their game account
suspended. The decision and its consequences are yours.

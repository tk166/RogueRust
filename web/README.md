# `web/` — the wasm spike's front end

A **single static file**, `index.html`, with inline CSS and JS and **no CDN, no worker, no
`SharedArrayBuffer`**. It loads `rd_wasm.wasm` with a plain `WebAssembly.instantiate` and reads the
whole game state out of the 122 `i32`s that `rd_env_observe_buf()` points at.

## Files

| file | what it is | tested by |
|---|---|---|
| `index.html` | the page: markup, CSS, click handlers, measurements. Loads `ui_render.js` first | gates 14 and 15 |
| `ui_render.js` | **the semantics**: observation layout, four describers (`RD_UI.describe`), the **step diff** (`diffObservations`), its log (`logLines`) and its animation plan (`animationPlan`). Classic script, no build step | gate 15 |
| `ui_test.mjs` | drives the describers with the real `.wasm` and compares **every printed quantity** with its observation cell | gate 15 |
| `smoke.mjs` | the artifact is a fresh build; every script parses; only real exports are called; offsets tile | gates 13–14 |
| `map.html` | the run/map page: the same `.wasm`, the other export family (`env-abi.md` §11) | gate 16 |
| `map_render.js` | **the map's semantics**: run layout + node fields + `describeMap`/`svgMarkup`, both pure | gate 16 |
| `map_test.mjs` | drives the map describers with the real `.wasm`, node by node, **after every step of a full walk** | gate 16 |
| `rd_wasm.wasm` | build artifact, **git-ignored** | gates 13–14 |

The split exists because of a measured hole: the page used to hold every "which number goes in
which cell" decision inline, and **no gate could see a wrong cell** — writing `o[H.HP_MAX]` where
`o[H.HP]` belongs kept all fourteen gates green. `docs/spec/ui-plan.md` U0 moved those decisions
into `ui_render.js` so they can be asserted, and they are, cell by cell.

`map.html` draws the Act 1 map: one `<circle>` per node, one `<path>` per edge, the reachable set
lit, the cursor ringed, and a click walks the map. ⚠️ **It walks; it does not settle** — no fight
starts, no rest site heals, no chest opens (`env-abi.md` §11.5 says so, and the page says so on
screen). And it does **not** yet mark "walked but not settled", which §11.5 requires; that is a
known debt.

### Layout: one column, a hero bar, a row of enemies

Everything stacks in reading order — hero, enemies, hand, log, measurements — because the hero is a
single horizontal bar and the enemies are a row of targets, so a two-column grid left one tall panel
beside half an empty screen.

The enemies are laid out **in a row** (`flex` + `wrap`, each one bordered like a card) for one
reason: the interaction is "drag a card onto one of them". A row puts every enemy the same short
distance from the hand and lines the drop targets up with the cards; the column it replaced made the
first and second enemy different distances away.

### The battle animation (U2)

Every step is turned into an **event list** by `RD_UI.diffObservations(before, after, wasEndTurn)`:
damage (with the Block it was absorbed by), heals, Block gains, the end-of-turn Block clear,
deaths, energy spent, cards drawn and cards that left the hand, status changes, turn changes and
the result. `logLines` turns that into the battle log, and `animationPlan` into "float this number
there, shake that panel, collapse that enemy" -- both pure, both asserted against the real fight in
gate 15, and each with a mutation that makes it red (9 of them).

⚠️ **The events are derived from the observation, not from an engine event stream.** `env-abi.md`
§4 gives two vectors per step and no events, so the diff reconstructs them by subtraction. That
covers everything visible, and it cannot recover one thing: whether a Block decrease was damage
*absorbed* or the end-of-turn *clear*. The caller says which kind of step it was, and the two are
reported separately rather than merged into a number that would be wrong half the time. A real
event stream would be better; it is a recorded follow-up.

### Card faces

A card shows its cost, its **title** and its **description** — `Defend` / `Gain 5 Block.` — plus
whether it can be played and whether it is being aimed. Both strings come out of the content
image: `rd_env_card_title_*` reads `CARD.NameKey` and `rd_env_card_text_*` reads
`CARD.DescriptionKey`. They are **the content's own sentences**, not a table in the page, so a card
cannot end up describing something it does not do.

⚠️ That is also why the module embeds the **full** `content.sts.rdcf` (11,140 B) rather than its
9,580 B core mirror: the core build **strips those two cells** (`ABSENT16`), so every card face came
back empty until the image was switched. Measured, not assumed — see the `IMAGE` doc comment in
`kernel/rd-wasm/src/lib.rs`. The cost is +1,560 B of wasm.

⚠️ Still missing from a card face: the **type** (Attack/Skill/Power). Our content carries it as a
tag (`"attack"` in `CARD.Tags`), which is a `TERM` handle to a wrapped list, and reading it needs a
tag walker rather than a string cell. Written down, not approximated.

### Playing a card: click *and* drag

A click still works: a single-option card plays, a card with several options arms the enemy picker.
Dragging is the second path and it goes through **one decision function** —
`RD_UI.actionFor(options, handSlot, targetSlot)` — which returns `-1` for a drop that means nothing.
That `-1` is load-bearing: a drop that misses every enemy a card can reach must do **nothing**,
because "pick a target for the player" is the exact bug this page shipped once already (above).
The pointer plumbing is ~40 lines; which enemy lights up is `RD_UI.dropSlots`, also pure.

A drag also fires a click on release, so the page swallows exactly one click after a real drag —
otherwise every drag would play two cards.

### Sound: no files

`RD_UI.soundPlan(diff)` returns ids (`hit-hero`, `hit-enemy`, `block`, `heal`, `death`, `cost`,
`draw`, `whoosh`, `turn`, and a single `victory`/`defeat` that *replaces* the rest). The page
renders them with Web Audio oscillators — a short frequency-swept blip each, so there is **not one
audio file in the repository** and the page stays a single directory. `AudioContext` is created on
the first gesture, because browsers refuse earlier than that.

⚠️ **The DOM half is still only checked by eye.** A refactor that renders perfectly but whose click
handlers reference a variable that no longer exists passes all fifteen gates — that happened, and
only clicking in a browser found it. `ui_test.mjs` prints this warning itself.

## What is on the page

The fight is **built from content**, not typed into the Rust file: the module embeds
`tools/contentc/packages/sts/out/content.sts.core.rdcf` (9,580 B) and calls
`battle::build_fight_from_content`, so

* the **deck** is the document's own (`Characters[0].Start.Deck` → 5×strike, 4×defend, 1×bash);
* the **enemies** are the encounter `enc_small_slimes` (`acid_slime_m` 28 HP + `spike_slime_s`
  10 HP, ids straight out of `ENCT`);
* the **intent** column is computed live with `intent::select_action` + the `EACT` program's
  literal damage (`acid_slime_m.corrosive_spit | Attack | 7 dmg`);
* one **结束回合** ends the hero's turn, then lets *each* enemy take its own turn
  (`battle::Step::EndOneTurn` in a loop), then gives the round back to the hero.

## Run it

`file://` will not work — a browser refuses to `fetch` a `.wasm` from a file URL. Serve a
directory over HTTP instead:

```powershell
# from the repo root; any static server works
C:\Users\TK11\miniforge3\python.exe -m http.server 8765 --bind 0.0.0.0 --directory D:\Vibe\sts-tui
```

Then open `http://<your-LAN-IP>:8765/web/index.html` (or `http://localhost:8765/web/index.html`).
`--bind 0.0.0.0` is what makes the LAN IP work; `--bind 127.0.0.1` limits it to the local machine.

Clicking a card is one `rd_env_step`; **结束回合** is one `rd_env_step` with the end-turn action.

## Build the module

```powershell
& D:\Vibe\sts-tui\tools\cargo.ps1 build -p rd-wasm --release --target wasm32-unknown-unknown
Copy-Item D:\Vibe\sts-tui\kernel\target\wasm32-unknown-unknown\release\rd_wasm.wasm D:\Vibe\sts-tui\web\
```

`rd_wasm.wasm` next to this file is a **build artifact, and it is deliberately not in git**
(`.gitignore` has `web/*.wasm`; the repository's first commit was told to exclude compiled
binaries). So a clone has to run the two commands above once. Every byte count below is a
*local* measurement, not something `git show` can produce.

Current: **382,995 B** (374.0 KiB) built from this tree (before this round it was 559,504 B of
*roguedeck* content — the table lists the levers).

| build | bytes | what changed |
|---|---:|---|
| previous local copy | 559,504 | stale artifact (546 KiB), `roguedeck` image, `NextRound` end-turn, no intent |
| same tree, `rd-wasm` before this round | 418,758 | rebuilt from `main`, still `roguedeck` (85,616 B image) |
| this round | 378,962 | `sts` core image (9,580 B, −76,036 B of data) **+** intent/damage preview code **+** `EndOneTurn` loop |
| this round, after `GOLDEN32` became `pub` | 378,962 | **same size, different sha256** — see the note below |
| after `currentHealth`/`maxHealth` + card lifecycle programs | **382,995** | +4,033 B of real kernel code; `CombatState` unchanged at 213,224 B, and the page still wins in 10 steps with round-1 preview 12 = HP lost |

⚠️ The last row is why the gate compares **bytes**: making one constant `pub` in `rd-core`
changed nothing observable (the page still wins in 10 steps; the round-1 preview is still
12 = the HP actually lost) yet reordered the data section. A size check and an mtime check
would both have called the two builds identical.

The image is the biggest single lever after `CombatState` itself (213,224 B of linear memory):
embedding the `sts` mirror instead of the `roguedeck` one is what pays for the new code.

The page tries `./rd_wasm.wasm` first and falls back to
`../kernel/target/wasm32-unknown-unknown/release/rd_wasm.wasm`, so serving the repo root works even
without the copy — and a stale copy is visible as a byte count mismatch in the on-page measurements.

## Smoke test (no browser needed)

```powershell
node D:\Vibe\sts-tui\web\smoke.mjs
```

It reads the **artifact sitting next to it** (a local, git-ignored build), checks `WebAssembly.validate`, instantiates it with **no
imports**, asserts every export `index.html` touches exists, and plays the fight out (round-1
preview must equal the HP actually lost — that is what proves *both* enemies acted). Then it checks
the artifact is **byte-identical to a fresh build**, and checks the **page**: the inline script
parses, every `ex.*` it calls is a real export, and its hard-coded 122-slot offsets still tile. It
prints `WEB_SMOKE PASS` plus the byte count, the two enemies with their intents, the step count,
the artifact sha, and the page's export/offset tally.

It is gate 14 of `tools\acceptance.ps1` (gate 13 is the rebuild it compares against), and each of
its four page/artifact checks has been shown to go red by a deliberate mutation — a one-character
syntax error, `OFF_HAND` drifting by 2, calling a non-existent export, and flipping one byte of the
artifact. It now loads **every** script the page references (inline and `src=`) and reads the
observation layout from whichever file declares it — which since U0 is `ui_render.js`, not the page.

⚠️ It is not a browser: no DOM, no `Content-Type`, no `instantiateStreaming`, no `performance.now`,
and **no Rust ↔ page offset check** — see the end of the next section.

## What the page measures on load

The **Measurements** panel times: fetch+instantiate, 1000 steps, 1000 resets, 1000 bookkeeping
refreshes, 1000 fight-only steps, and 1000 observation reads. It also reports the `Content-Type` the
server sent and which loader path was taken (`instantiateStreaming` vs the `arrayBuffer` fallback),
because those two are the things that break first when a page moves off `localhost`.

## Verified in a real browser (2026-10-19)

This was the one item the README kept calling unverified, so it got measured instead of assumed.
Served by `python -m http.server 8765 --bind 127.0.0.1`, opened in
`Chrome/152.0.7977.76` on Windows:

| what the smoke test cannot see | measured |
|---|---|
| `Content-Type` the server sent | `application/wasm` (python's `http.server` *does* know `.wasm` via the registry) |
| loader path | **`instantiateStreaming`** — the fast path, not the `arrayBuffer` fallback |
| fetch + instantiate + first observe | 10–40 ms (varies 4× between a cold and a warm cache) |
| linear memory | 1,408 KiB |
| DOM | renders, all 122 slots land in the right cells, cards are clickable |

Then the fight was **played by clicking**, not by script: 21 clicks to `Victory` in round 7, and the
HP lost on the first end-turn matched the two previewed intents (7 + 5 = 12) exactly.

Re-run after the U0 split (`ui_render.js` + the rewired click handlers): **22 clicks to `Victory`
in round 7**, both enemies showing `(down)`, `reward 4.00` — the same fight, with the rendering
layer swapped out underneath it. That second run is also what caught the click handlers still
reading the deleted module-level `playOptions`: the page rendered perfectly and every gate was
green, but **no click did anything at all**.

Two things the session found that no gate could have:

1. **The card target was never sent.** `env-abi.md` §5 emits one play action per *(card × live
   enemy slot)*, and the page was picking `playByHand.get(h)` — the **first** one — so every
   attack hit enemy 0 no matter what the player wanted. The page now arms a target picker: a card
   with several actions highlights the enemies it can reach, and clicking one spends the action
   that names that slot.
2. **Two debug fields were on screen**: `def_slot N` as its own line under every card, and the raw
   `reward` integer (`-12030`, which is −12.03 in the 1/1000 unit `env-abi.md` §7 defines). The
   first moved to `title=`, the second is now divided by 1000.

Both are fixed. The deeper lesson is the one that became gates 13, 14 and (later) 15 of
`tools\acceptance.ps1`:
**`web/index.html` was not looked at by anything.** A syntax error in it passed all twelve gates,
because every gate stopped at the `.wasm`. `smoke.mjs` now also parses the page's inline script,
cross-checks every `ex.*` the page calls against the module's real exports, re-derives the 122-slot
offset arithmetic, and asserts `web/rd_wasm.wasm` is **byte-identical** to a fresh
`cargo build -p rd-wasm --release --target wasm32-unknown-unknown` (byte equality, not mtime:
`Copy-Item` restores mtime, and a one-line comment edit makes an artifact look older than it is).

⚠️ Still **not** covered: Rust ↔ page offset drift. The page hard-codes the layout; if the kernel
moves a block, the page reads the wrong cells and only a browser shows it. Publishing the offsets
over the ABI would close that, and it is not done.



## Server requirements

Just one: serve `.wasm` as `application/wasm`. If the server guesses
`application/octet-stream`, the page still works — it falls back to
`WebAssembly.instantiate(await res.arrayBuffer())` and says so in the Measurements panel (it costs
roughly a doubling of load time, nothing else).

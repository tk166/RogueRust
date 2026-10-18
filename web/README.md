# `web/` — the wasm spike's front end

A **single static file**, `index.html`, with inline CSS and JS and **no CDN, no worker, no
`SharedArrayBuffer`**. It loads `rd_wasm.wasm` with a plain `WebAssembly.instantiate` and reads the
whole game state out of the 122 `i32`s that `rd_env_observe_buf()` points at.

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

Current: **378,962 B** (370.1 KiB) built from this tree (before this round it was 559,504 B of
*roguedeck* content — the table lists the levers).

| build | bytes | what changed |
|---|---:|---|
| previous local copy | 559,504 | stale artifact (546 KiB), `roguedeck` image, `NextRound` end-turn, no intent |
| same tree, `rd-wasm` before this round | 418,758 | rebuilt from `main`, still `roguedeck` (85,616 B image) |
| this round | 378,962 | `sts` core image (9,580 B, −76,036 B of data) **+** intent/damage preview code **+** `EndOneTurn` loop |
| this round, after `GOLDEN32` became `pub` | 378,962 | **same size, different sha256** — see the note below |

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
artifact.

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

Two things the session found that no gate could have:

1. **The card target was never sent.** `env-abi.md` §5 emits one play action per *(card × live
   enemy slot)*, and the page was picking `playByHand.get(h)` — the **first** one — so every
   attack hit enemy 0 no matter what the player wanted. The page now arms a target picker: a card
   with several actions highlights the enemies it can reach, and clicking one spends the action
   that names that slot.
2. **Two debug fields were on screen**: `def_slot N` as its own line under every card, and the raw
   `reward` integer (`-12030`, which is −12.03 in the 1/1000 unit `env-abi.md` §7 defines). The
   first moved to `title=`, the second is now divided by 1000.

Both are fixed. The deeper lesson is the one that became gates 13 and 14 of `tools\acceptance.ps1`:
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

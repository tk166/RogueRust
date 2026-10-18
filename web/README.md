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

`rd_wasm.wasm` next to this file is a **build artifact**: **378,962 B** (370.1 KiB) as committed,
built from this tree (before this round it was 559,504 B of *roguedeck* content — the numbers below
are the two levers that changed).

| build | bytes | what changed |
|---|---:|---|
| previous committed copy | 559,504 | stale artifact (546 KiB), `roguedeck` image, `NextRound` end-turn, no intent |
| same tree, `rd-wasm` before this round | 418,758 | rebuilt from `main`, still `roguedeck` (85,616 B image) |
| **this round** | **378,962** | `sts` core image (9,580 B, −76,036 B of data) **+** intent/damage preview code **+** `EndOneTurn` loop |

The image is the biggest single lever after `CombatState` itself (213,224 B of linear memory):
embedding the `sts` mirror instead of the `roguedeck` one is what pays for the new code.

The page tries `./rd_wasm.wasm` first and falls back to
`../kernel/target/wasm32-unknown-unknown/release/rd_wasm.wasm`, so serving the repo root works even
without the copy — and a stale copy is visible as a byte count mismatch in the on-page measurements.

## Smoke test (no browser needed)

```powershell
node D:\Vibe\sts-tui\web\smoke.mjs
```

It reads the **committed artifact**, checks `WebAssembly.validate`, instantiates it with **no
imports**, asserts every export `index.html` touches exists, and plays the fight out (round-1
preview must equal the HP actually lost — that is what proves *both* enemies acted). It prints
`WEB_SMOKE PASS` plus the byte count, the two enemies with their intents, and the step count.

⚠️ It is not a browser: no DOM, no `Content-Type`, no `instantiateStreaming`, no `performance.now`.
Those are exactly the things the Measurements panel exists to report, and they are still
unverified on this machine.

## What the page measures on load

The **Measurements** panel times: fetch+instantiate, 1000 steps, 1000 resets, 1000 bookkeeping
refreshes, 1000 fight-only steps, and 1000 observation reads. It also reports the `Content-Type` the
server sent and which loader path was taken (`instantiateStreaming` vs the `arrayBuffer` fallback),
because those two are the things that break first when a page moves off `localhost`.

## Server requirements

Just one: serve `.wasm` as `application/wasm`. If the server guesses
`application/octet-stream`, the page still works — it falls back to
`WebAssembly.instantiate(await res.arrayBuffer())` and says so in the Measurements panel (it costs
roughly a doubling of load time, nothing else).

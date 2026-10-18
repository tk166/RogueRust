# `web/` — the wasm spike's front end

A **single static file**, `index.html`, with inline CSS and JS and **no CDN, no worker, no
`SharedArrayBuffer`**. It loads `rd_wasm.wasm` with a plain `WebAssembly.instantiate` and reads the
whole game state out of the 122 `i32`s that `rd_env_observe_buf()` points at.

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

`rd_wasm.wasm` next to this file is a **build artifact** (546 KiB). The page tries
`./rd_wasm.wasm` first and falls back to `../kernel/target/wasm32-unknown-unknown/release/rd_wasm.wasm`,
so serving the repo root works even without the copy — and a stale copy is visible as a byte count
mismatch in the on-page measurements.

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

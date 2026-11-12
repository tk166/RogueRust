import { writeFileSync } from "node:fs";
const trace = await (async () => {
  const { readFile } = await import("node:fs/promises");
  const bytes = await readFile("D:\\Vibe\\sts-tui\\web\\rd_wasm.wasm");
  const { instance } = await WebAssembly.instantiate(bytes, {});
  const ex = instance.exports;
  const O = { floor: 0, node: 1, health: 2, healthMax: 3, gold: 4, deckSize: 5, relicCount: 6, potionCount: 7 };
  const trace = [];
  const snap = (label) => {
    const fields = {};
    for (const [name, index] of Object.entries(O)) fields[name] = ex.rd_run_observe(index);
    trace.push({ label, fields });
  };
  ex.rd_run_start(7, 0);
  snap("start");
  ex.rd_run_choose_start(1);
  snap("blessing");
  ex.rd_run_step(0);
  snap("walked");
  ex.rd_run_begin_node();
  snap("begun");
  ex.rd_run_fight_begin();
  snap("fight-begin");
  for (let n = 0; n < 3; n += 1) {
    if (ex.rd_env_action_count() === 0) break;
    ex.rd_env_step(0);
    snap("play-" + n);
  }
  return trace;
})();
writeFileSync("D:\\Vibe\\sts-tui\\.git\\parity-trace.json", JSON.stringify(trace));
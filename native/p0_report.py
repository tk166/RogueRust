"""重写 `native/ui_abi_dump.mjs` 的 `report()`（整段替换，不再打补丁）。

## 三个坑（都是这一轮真踩到的）

1. **战斗没打完就 `fight_end`** ⇒ 没有结果、节点不结算 ⇒ 后续每一步 `rd_run_step` 被
   `NodeNotSettled` 拒 ⇒ "商店/宝箱/事件 400 个种子走不到"（**一个夹具缺陷伪装成三个不可达**）。
2. **站在战斗节点上 `begin_node` 什么都不做**（战斗靠 `fight_begin`/`fight_end` 结算，不是
   `begin_node`）⇒ 我的"站在未结算节点就先 begin_node"分支**空转 26 跳**。
3. **落到商店那一格立刻被 `leave` 掉** ⇒ 搜索永远"没到达"。

## 结构

* `walkToPending(want)`：走到 `pending === want`（商店 2 / 宝箱 3 / 事件 5）。
* `walkToFightNode()`：停在"站在战斗节点上、还没开打"（= `SC-03` 那一屏）。
* `settleFightNode(win)`：开打 → 打到底 → `fight_end`（赢 ⇒ 奖励屏；故意输 ⇒ 局终）。
* 战斗节点在 `walkToPending` 里**必须**用 `settleFightNode` 结算，不能 `begin_node`。
"""

import io

PATH = 'native/ui_abi_dump.mjs'


def sub(old, new, label):
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d' % (label, t.count(old))
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① 战斗节点的判定 + 结算助手（插在 walkTo 之前）──────────────────────────
sub('''/// `pending` → 该走哪种节点（`Pending` 的判别值 → `NodeKind`）。''',
    '''/// 这个节点是不是**一场战斗**（三个来源：节点种类、`?` 房掷出怪物、事件引来的伏击）。
function isFightNode() {
  const kind = ex.rd_run_node_kind();
  if (kind === 1 || kind === 2 || kind === 7) return true;
  if (kind === 5 && ex.rd_run_observe(18) === 2) return true;
  return ex.rd_run_event_fight() > 0;
}

/// 站在战斗节点上：开打 → 打到底 → `fight_end`。`win = false` 时只结束回合（故意输）。
/// 返回 `rd_run_fight_end()` 的返回值。
function settleFightNode(win = true) {
  if (ex.rd_run_fight_begin() !== 0) return -2;
  if (win) playOutFight();
  else loseFight();
  return ex.rd_run_fight_end();
}

/// `pending` → 该走哪种节点（`Pending` 的判别值 → `NodeKind`）。''', 'fight node helpers')

# ── ② walkTo：战斗节点用 settleFightNode，不能 begin_node ───────────────────
sub('''    if (ex.rd_run_pending() === 0) {
      // 站在一个还没结算的节点上 ⇒ 先问它要什么（可能正好就是目标）。
      if (ex.rd_run_node_kind() >= 0 && ex.rd_run_node_resolved() === 0) {
        ex.rd_run_begin_node();
        continue;
      }''',
    '''    if (ex.rd_run_pending() === 0) {
      if (ex.rd_run_node_kind() >= 0 && ex.rd_run_node_resolved() === 0) {
        // ⚠️ 战斗节点**不能** `begin_node`：它对战斗什么都不做（返回 0、pending 仍是 0），
        // 于是"站在未结算节点就先 begin_node"会**空转**。战斗要用 `settleFightNode`。
        if (isFightNode()) {
          settleFightNode(true);
          continue;
        }
        ex.rd_run_begin_node();
        continue;
      }''', 'walkTo fight branch')

# ── ③ 整段替换 report() ──────────────────────────────────────────────────
OLD_START = 'async function report() {'
OLD_END = 'async function check() {'

t = io.open(PATH, encoding='utf-8').read()
start = t.index(OLD_START)
end = t.index(OLD_END)
NEW_REPORT = '''async function report() {
  const P = await loadPanels();
  const scenes = [];

  // ① 未开局
  scenes.push(captureRun("SC-00-no-run", "no session at all"));

  // ② 祝福 / ③ 地图
  if (ex.rd_run_start(7, 0) !== 0) fail("rd_run_start refused");
  scenes.push(captureRun("SC-01-blessing", "pending 6 right after start"));
  finishBlessing();
  scenes.push(captureRun("SC-02-map", "blessing done, standing on floor 1"));

  // ④ 战斗待开始 → ⑤ 战斗中 → ⑥ 奖励
  {
    let reached = false;
    for (let s = 1; s <= 200 && !reached; s++) {
      ex.rd_run_start(s, 0);
      finishBlessing();
      reached = walkToFightNode();
      if (reached) {
        scenes.push(captureRun("SC-03-pre-fight", `seed ${s}, standing on a fight node`));
        if (ex.rd_run_fight_begin() === 0) {
          scenes.push(captureCombat("SC-03b-combat", `seed ${s}, first turn`));
          scenes.push(captureRun("SC-03b-run-facts", "run-layer facts while the fight runs"));
          const result = playOutFight();
          if (ex.rd_run_fight_end() >= 0) {
            scenes.push(captureRun("SC-04-reward", `fight result ${result} (1 = victory)`));
          }
        }
      }
    }
    if (!reached) scenes.push({ label: "SC-03-pre-fight", note: "UNREACHED within 200 seeds", raw: null });
  }

  // ⑥b 局终：**故意输一场**（只结束回合）—— 真实到达，不伪造。
  {
    let lost = false;
    for (let s = 1; s <= 200 && !lost; s++) {
      ex.rd_run_start(s, 0);
      finishBlessing();
      if (!walkToFightNode()) continue;
      const verdict = settleFightNode(false);
      if (verdict >= 0 && ex.rd_run_over() === 1) {
        scenes.push(captureRun("SC-12b-defeat", `seed ${s}, lost on purpose`));
        lost = true;
      }
    }
    if (!lost) scenes.push({ label: "SC-12b-defeat", note: "UNREACHED within 200 seeds", raw: null });
  }

  // ⑥c 幕通关（SC-12a）：要打穿一幕的 Boss ⇒ **显式标记为合成**。
  scenes.push({
    label: "SC-12a-act-clear",
    note: "SYNTHETIC -- clearing an act needs the boss fight; the 18 synthetic fixtures in --check cover it",
    raw: null,
  });

  // ⑦ 商店 / ⑧ 宝箱 / ⑨ 事件：各找一个种子走到那一屏
  for (const [want, label] of [[2, "SC-05-shop"], [3, "SC-07-treasure"], [5, "SC-08-event"]]) {
    let reached = false;
    for (let s = 1; s <= 300 && !reached; s++) {
      ex.rd_run_start(s, 0);
      finishBlessing();
      reached = walkTo(want);
      if (reached) scenes.push(captureRun(label, `seed ${s}, pending ${want}`));
    }
    if (!reached) scenes.push({ label, note: `UNREACHED within 300 seeds (pending ${want})`, raw: null });
  }

  // ⑩ 遗物欠账：直接授予"欠两次删牌"的遗物，看内核是否记账
  ex.rd_run_start(7, 0);
  finishBlessing();
  const cage = new TextEncoder().encode("empty_cage");
  const ptr = Number(ex.rd_env_scratch_buf());
  new Uint8Array(ex.memory.buffer, ptr, cage.length).set(cage);
  const granted = ex.rd_run_grant_relic(ptr, cage.length);
  const debt = ex.rd_run_pickup_picks() > 0;
  scenes.push({
    ...captureRun("SC-11a-pickup-debt", `granted empty_cage (verdict ${granted})`),
    note: debt
      ? "the kernel owes deck edits after the grant"
      : "UNREACHED by granting empty_cage -- pickupPicks stayed 0 (synthetic fixture needed)",
  });

  // 场景 parity：每个真实快照都要落到**预期的那个**场景
  const expected = {
    "SC-00-no-run": "SC-00",
    "SC-01-blessing": "SC-01",
    "SC-02-map": "SC-02",
    "SC-03-pre-fight": "SC-03",
    "SC-03b-run-facts": "SC-03b",
    "SC-04-reward": "SC-04",
    "SC-05-shop": "SC-05",
    "SC-07-treasure": "SC-07",
    "SC-08-event": "SC-08",
    "SC-12b-defeat": "SC-12b",
    "SC-11a-pickup-debt": null, // 覆盖层压在底屏上（这里是 SC-02），不单独成 base
  };
  for (const scene of scenes) {
    if (!scene.raw || !scene.facts) continue;
    const want = expected[scene.label];
    scene.scene = P.resolveScene(scene.facts);
    if (want && scene.scene.base !== want) {
      scene.sceneMismatch = `want ${want}, got ${JSON.stringify(scene.scene)}`;
    }
  }

  await mkdir(FIXTURES, { recursive: true });
  const payload = {
    note: "P0 raw ABI dumps. Values are exactly what the wasm said; nothing here is interpreted.",
    contentFingerprint: `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`,
    runObserveLen: ex.rd_run_observe_len(),
    combatObserveLen: ex.rd_env_observe_len(),
    scenes,
  };
  await writeFile(join(FIXTURES, "p0-scenes.json"), JSON.stringify(payload, null, 1) + "\\n", "utf8");

  console.log(
    `UI_ABI_REPORT content=${payload.contentFingerprint} runObs=${payload.runObserveLen} combatObs=${payload.combatObserveLen}`
  );
  for (const scene of scenes) {
    const state = !scene.raw ? "UNREACHED" : scene.sceneMismatch ? "MISMATCH" : "ok";
    const where = scene.scene
      ? `${scene.scene.base}${scene.scene.overlays.length ? "+" + scene.scene.overlays.join("+") : ""}`
      : "-";
    console.log(`  ${scene.label.padEnd(24)} ${state.padEnd(9)} ${where.padEnd(14)} ${scene.note}`);
  }
  const bad = scenes.filter((s) => s.sceneMismatch);
  if (bad.length) fail(`${bad.length} scene(s) did not land on the expected base scene`);
  console.log("UI_ABI_REPORT PASS");
}

'''
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t[:start] + NEW_REPORT + t[end:])
print('report() rewritten')

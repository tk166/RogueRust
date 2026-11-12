"""闸门 36 重构成"多段旅程"：单一种子走不到所有屏（商店/事件的位置由地图生成决定）。"""

import io

P = 'native/ui_next_p4_check.mjs'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# 1) 种子列表
sub(
    '''// seed 3：第 2 层的 `?` 房掷出事件（`shining_light`），所以这一段旅程**必定**能覆盖事件屏。
// 扫描见 `native/_dbg_eventscan.mjs`（一次性探针，不进闸门）。
const SEED = 3;''',
    '''// 走**多段旅程**：单一种子不保证每一屏都在路上（商店/事件的位置由地图生成决定，
// 而生成有硬规则：第 1–5 层没有篝火、第 9 层全是宝箱、第 15 层全是篝火）。
// 扫描见 `native/_dbg_eventscan.mjs` / `_dbg_p4scan2.mjs`（一次性探针，不进闸门）。
//   * seed 3：第 2 层的 `?` 房掷出**事件**（`shining_light`）；
//   * seed 1：第 2 层有**商店**。
const SEEDS = [3, 1];''',
    'seeds list',
)

# 2) 把"开局 + 主循环"包进 per-seed 函数：用一个标记把 `while` 拆出来
sub(
    '''// ── 开局 ──────────────────────────────────────────────────────────────────
await ev(`window.__run.start(${SEED}, 0)`);
let current = await guard("开局");

// 祝福：选一个**不需要选牌**的；如果没有，就选第一个并用牌组选择器（顺带测选择器）。
const blessings = await ev("window.__run.blessings()");
const simple = blessings.find((blessing) => !/card/.test(blessing.id));
if (simple) {
  const picked = await click(`[data-blessing='${simple.slot}']`);
  check(picked.clicked, "祝福页可点", picked.text);
} else if (blessings.length > 0) {
  await click(`[data-blessing='${blessings[0].slot}']`);
}
await sleep(80);
current = await guard("选祝福");

// 如果祝福要求选牌（`SC-01b`），用牌组选择器走完 —— 这也顺便测了选择器。
if (current.base === "SC-01b") {
  const rows = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
  check(rows > 0, "祝福选牌：牌组选择器画出了牌", String(rows));
  const picked = await click("[data-deck-pick='0']");
  check(picked.clicked, "祝福选牌：能点第一张", picked.text);
  await sleep(80);
  mark("deck-picker");
  current = await guard("祝福选牌后");
}
check(current.base === "SC-02", "开局后进入地图", current.base);

// ── 旅程主循环 ────────────────────────────────────────────────────────────
let loops = 0;
while (loops < 120) {''',
    '''const required = ["shop", "rest", "chest", "event", "deck-picker"];
const covered = () => required.every((id) => summary.screens.includes(id));

/** 开一局并选祝福（必要时用牌组选择器），直到站在地图上。 */
async function openRun(seed) {
  await ev(`window.__run.start(${seed}, 0)`);
  let current = await guard(`seed ${seed} 开局`);
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((blessing) => !/card/.test(blessing.id));
  if (simple) {
    const picked = await click(`[data-blessing='${simple.slot}']`);
    check(picked.clicked, "祝福页可点", picked.text);
  } else if (blessings.length > 0) {
    await click(`[data-blessing='${blessings[0].slot}']`);
  }
  await sleep(80);
  current = await guard(`seed ${seed} 选祝福`);
  if (current.base === "SC-01b") {
    const rows = await ev(`document.querySelectorAll("[data-deck-pick]").length`);
    check(rows > 0, "祝福选牌：牌组选择器画出了牌", String(rows));
    const picked = await click("[data-deck-pick='0']");
    check(picked.clicked, "祝福选牌：能点第一张", picked.text);
    await sleep(80);
    mark("deck-picker");
    current = await guard(`seed ${seed} 祝福选牌后`);
  }
  check(current.base === "SC-02", `seed ${seed}：开局后进入地图`, current.base);
}

// ── 旅程主循环（每个种子一段）─────────────────────────────────────────────
for (const seed of SEEDS) {
  if (covered()) break;
  console.log(`\\n== 旅程 seed=${seed}（已覆盖 ${summary.screens.join(",") || "无"}）==`);
  await openRun(seed);
  let current = await guard(`seed ${seed} 地图`);
  let loops = 0;
while (loops < 120) {''',
    'per-seed open',
)

# 3) 主循环结束处：闭合 for，并把 current 的作用域处理好
sub(
    '''  // 其它屏（战斗内等）：不该在旅程主循环里出现。
  check(false, `旅程里出现了没处理的场景 ${base}`, JSON.stringify(current));
  break;
}

// ── 覆盖断言（少一屏就红）────────────────────────────────────────────────
const required = ["shop", "rest", "chest", "event", "deck-picker"];
const missing = required.filter((id) => !summary.screens.includes(id));''',
    '''  // 其它屏（战斗内等）：不该在旅程主循环里出现。
  check(false, `旅程里出现了没处理的场景 ${base}`, JSON.stringify(current));
  break;
}
}

// ── 覆盖断言（少一屏就红）────────────────────────────────────────────────
const missing = required.filter((id) => !summary.screens.includes(id));''',
    'close for',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('gate36: multi-seed')

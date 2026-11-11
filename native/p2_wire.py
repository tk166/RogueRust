"""收尾 P2 第一步：
① `sync-wasm.mjs` 同时写进 `dist/`（`dist` 入库，但 wasm 不入库 ⇒ 闸门必须先同步）；
② 闸门 28 自己跑同步（自包含，不依赖谁先跑过）；
③ 闸门 27 加 `decodeCombat` 的**合成向量**测试（X 费、空槽 -1、敌人计数不符要炸）；
④ `.gitignore` 加 wasm 与 manifest；⑤ 接进 acceptance。
"""

import io
import json
import os

SYNC = 'web-next/scripts/sync-wasm.mjs'
GATE28 = 'native/ui_wasm_check.mjs'
PURE = 'native/ui_pure_check.mjs'
GITIGNORE = '.gitignore'
ACC = 'tools/acceptance.ps1'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① 同步脚本也写 dist/ ───────────────────────────────────────────────────
edit(
    SYNC,
    '''const sha256 = createHash("sha256").update(bytes).digest("hex");
await mkdir(PUBLIC, { recursive: true });
await copyFile(SOURCE, TARGET);''',
    '''const sha256 = createHash("sha256").update(bytes).digest("hex");
await mkdir(PUBLIC, { recursive: true });
await copyFile(SOURCE, TARGET);
// `dist/` 入库，但 wasm 不入库 ⇒ 已构建的产物目录也要放一份，否则闸门 28 打开页面时 404。
const DIST = join(WEB_NEXT, "dist");
try {
  await copyFile(SOURCE, join(DIST, "rd_wasm.wasm"));
} catch {
  /* 还没 build 过：build 时 vite 会把 public/ 拷进 dist/，这里只是提前一份 */
}''',
    'sync dist',
)

# ── ② 闸门 28 自包含：先同步 ───────────────────────────────────────────────
edit(
    GATE28,
    '''import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";''',
    '''import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

// 自包含：把**同一份** `web/rd_wasm.wasm` 同步进 web-next（public/ 与 dist/）。
// 不依赖"谁先跑过 wasm-rebuild"，但源不存在时会给出明确报错（验收里 wasm-rebuild 在前）。
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch (error) {
  console.error("UI_WASM FAIL: 同步 wasm 失败（先跑一次内核构建 / wasm-rebuild 闸门）");
  console.error(String(error.stdout ?? "") + String(error.stderr ?? ""));
  process.exit(1);
}''',
    'gate28 sync',
)

# ── ③ 闸门 27 加 decodeCombat 合成向量测试 ────────────────────────────────
edit(
    PURE,
    '''      "src/stage/combatLayout.ts",
      "src/stage/layout.ts",''',
    '''      "src/stage/combatLayout.ts",
      "src/stage/layout.ts",
      "src/wasm/snapshot.ts",''',
    'pure compile list',
)

edit(
    PURE,
    '''  const combat = await import(pathToFileURL(join(out, "stage/combatLayout.js")).href);''',
    '''  const combat = await import(pathToFileURL(join(out, "stage/combatLayout.js")).href);
  const snapshotMod = await import(pathToFileURL(join(out, "wasm/snapshot.js")).href);''',
    'pure import snapshot',
)

edit(
    PURE,
    '''  // ── 状态机 ──────────────────────────────────────────────────────────────''',
    '''  // ── 观察向量解码（合成向量，不需要 wasm）────────────────────────────────
  // 布局与 `kernel/rd-wasm/src/lib.rs` 的 `OFF_*` 一致：header 12 / 英雄状态 5 /
  // 敌人 6×8 / 敌人状态 6×5 / 手牌 10×4 / 牌堆 5 / 保留 8 = 148。
  const OBS = 148;
  const makeObs = () => {
    const obs = new Int32Array(OBS).fill(-1);
    for (let index = 135; index < 140; index += 1) obs[index] = 0; // 牌堆是计数，0 有意义
    return obs;
  };
  const decode = snapshotMod.decodeCombat;

  const obs = makeObs();
  obs[0] = 3; // round
  obs[1] = 2; // turn
  obs[2] = 1; // phase inProgress
  obs[3] = 0; // ongoing
  obs[4] = 61; obs[5] = 80; obs[6] = 5; obs[8] = 2; obs[9] = 3;
  obs[10] = 2; // hand count
  obs[11] = 1; // enemy count
  obs[12] = 2; // hero strength
  // 敌人槽 0：alive, hp 30/44, block 4, ward -1, intent 1/9, statuses 1
  obs[17] = 1; obs[18] = 30; obs[19] = 44; obs[20] = 4; obs[21] = -1; obs[22] = 1; obs[23] = 9; obs[24] = 1;
  // 手牌：槽 0 数字费 3；槽 1 是 X 费（-2）
  obs[95] = 1; obs[96] = 3; obs[97] = 7; obs[98] = 0;
  obs[99] = 1; obs[100] = snapshotMod.X_COST_DISPLAY; obs[101] = 8; obs[102] = 0;
  obs[135] = 4; obs[136] = 2; obs[137] = 1;

  const decoded = decode(obs, [
    snapshotMod.decodeAction(0, 0, 0, 0),
    snapshotMod.decodeAction(1, 1, -1, -1),
  ]);
  check(decoded.round === 3 && decoded.turn === 2 && decoded.phase === "inProgress", "解码：头部字段");
  check(decoded.hero.hp === 61 && decoded.hero.block === 5 && decoded.hero.energy === 2, "解码：英雄");
  check(decoded.hero.statuses.strength === 2, "解码：英雄状态轴（ABI 顺序）");
  check(decoded.enemies.length === 1 && decoded.enemies[0].hp === 30, "解码：只解出**存在**的敌人槽（其余是 -1）");
  check(decoded.enemies[0].intentKind === 1 && decoded.enemies[0].intentDamage === 9, "解码：敌人意图");
  check(
    decoded.hand.length === 2 && decoded.hand[0].cost === 3 && decoded.hand[1].cost === "X",
    "解码：数字费与 X 费（-2 ⇒ \\"X\\"）",
    JSON.stringify(decoded.hand.map((card) => card.cost))
  );
  check(
    decoded.piles.draw === 4 && decoded.piles.hand === 2 && decoded.piles.discard === 1,
    "解码：牌堆计数（0 有意义，不是 -1）"
  );
  check(decoded.actions[1].kind === "endTurn" && decoded.actions[1].handSlot === -1, "解码：动作表 endTurn");

  const mismatch = makeObs();
  mismatch[11] = 2; // header 说 2 个敌人，但一个槽都没有
  let threwMismatch = false;
  try {
    decode(mismatch, []);
  } catch (error) {
    threwMismatch = error instanceof RangeError;
  }
  check(threwMismatch, "解码：header 敌人计数与槽位不符 ⇒ RangeError（不渲染幽灵敌人）");

  // ── 状态机 ──────────────────────────────────────────────────────────────''',
    'pure decode tests',
)

edit(
    PURE,
    '''  console.log(`UI_PURE PASS formation=0..6 hit=5 machine=4 layout=6`);''',
    '''  console.log(`UI_PURE PASS formation=0..6 hit=5 machine=4 layout=6 decode=8`);''',
    'pure evidence',
)

# ── ④ .gitignore ──────────────────────────────────────────────────────────
t = io.open(GITIGNORE, encoding='utf-8').read()
addition = '''# 子集字体是 `native/ui_font_measure.py` 的产物，字节数记在 font-measure.json 里
docs/ui-next-p1/subset-*
# P2：`web-next` 用的 wasm 是**复制**自 `web/rd_wasm.wasm` 的（唯一构建产物），不入库
web-next/public/rd_wasm.wasm
web-next/public/wasm.json
web-next/dist/rd_wasm.wasm
'''
old = '''# 子集字体是 `native/ui_font_measure.py` 的产物，字节数记在 font-measure.json 里
docs/ui-next-p1/subset-*
'''
assert t.count(old) == 1
io.open(GITIGNORE, 'w', encoding='utf-8', newline='\n').write(t.replace(old, addition))

# ── ⑤ 接进 acceptance（闸门 28）───────────────────────────────────────────
t = io.open(ACC, encoding='utf-8').read()
assert len(t) > 15000
old = '''Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
new = '''Write-Output "`n[28/28] P2 WASM 接线：装载校验 / 观察解码 / 动作表 / 走一步 / 拒绝不变 / 打到终局"
# 为什么必须是一道闸门：plan P2 的两条退出条件（"相同输入得到正确动作与结果"、"拒绝操作不产生
# 成功演出"）只有对着**真 wasm** 跑才成立。这道闸门驱动 `web-next/dist/p2.html` 的探针：
# 装载校验（导出/长度/哨兵/指纹）、开局走到战斗、按 (手牌槽位,目标槽位) 找内核给的动作、
# 断言"只有被指的敌人掉血"、越界动作返回 -1 且观察向量**逐字节不变**、一路打到终局。
$results += Invoke-Gate -Name 'ui-wasm' -Exe 'C:\\Program Files\\nodejs\\node.exe' `
  -ArgLine (Join-Path $ROOT 'native\\ui_wasm_check.mjs') -Workdir $ROOT `
  -MustMatch 'UI_WASM PASS exports=\\d+ content=0x[0-9a-f]{8} hand=\\d+ enemies=\\d+ steps=\\d+ result=(victory|defeat) rejected-unchanged=1' `
  -TimeoutSec 300

Write-Output "`n" + ("-" * 78)
Write-Output ("{0,-18}{1,6}  {2,-22}{3}" -f '闸门', '退出', '证据', '备注')'''
assert t.count(old) == 1, 'acceptance 锚点 %d' % t.count(old)
t = t.replace(old, new)

import re
count = 0


def bump(match):
    global count
    count += 1
    return '%s/28]' % match.group(1)


t = re.sub(r'(\[\d+)/27\]', bump, t)

marker = "'(UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+ layout=\\d+)'" + ")) {"
assert t.count(marker) == 1, 'evidence pattern 锚点 %d' % t.count(marker)
t = t.replace(
    marker,
    "'(UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+ layout=\\d+)'," + chr(10) +
    "                     # P2：真 wasm 接线" + chr(10) +
    "                     '(UI_WASM PASS exports=\\d+ content=0x[0-9a-f]{8} hand=\\d+ enemies=\\d+)'" + ")) {",
)

# 闸门 27 的证据串要跟着加 decode=8
t = t.replace(
    'UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+ layout=\\d+',
    'UI_PURE PASS formation=0\\.\\.6 hit=\\d+ machine=\\d+ layout=\\d+ decode=\\d+',
)

temp = ACC + '.tmp'
io.open(temp, 'w', encoding='utf-8', newline='\n').write(t)
assert os.path.getsize(temp) > 28000, '写出后大小异常 %d' % os.path.getsize(temp)
os.replace(temp, ACC)
print('gate 28 wired, %d bytes, bumped %d headers' % (os.path.getsize(ACC), count))

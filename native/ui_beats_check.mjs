// 闸门 37 `ui-beats`：Beat 演出**导演**的纯函数回归（不需要浏览器）。
//
// 这一层守的是 plan P5 的退出条件：
//
//   > 关闭动画也能完整游戏；播放动画的最终状态与内核完全一致；没有因动画丢失而卡住待决流程。
//
// 所以它证明的是**结构性**的事：
//
// 1. **导演是纯函数**：`planBeats` 不改输入、同样输入同样输出；`advance(state, dt)` 只产出新状态。
//    ⇒ "最终状态与内核一致"不是因为动画小心同步，而是因为**演出层根本不持有状态**。
// 2. **13 种 kind 都有话说**（编号是 ABI）；**未知 kind 不中断**，降级成中性飘字并**计数**。
// 3. **`dropped` 记在账上**（内核因容量丢 beat 时，界面必须能说出来）。
// 4. **关动画**只是"一条都不播"，`dropped`/`unknown` 仍然记账。
// 5. **`advance` 的余量结转**：慢帧率下动画不会拖长（一条播完把余下的 dt 给下一条）。

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const GATE = "UI_BEATS";
const WEB_NEXT = fileURLToPath(new URL("../web-next/", import.meta.url));
const out = await mkdtemp(join(tmpdir(), "rd-beats-"));

let bad = 0;
/** 摘要用（`try` 里的 `const` 在外面看不见 —— 闸门 33 踩过同一个坑）。 */
const summary = { assets: 0 };
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) bad += 1;
  return ok;
};

/** 造一条 beat（字段顺序与 `rd_env_beat_field` 一致）。 */
const beat = (kind, { actor = -1, target = 0, flags = 0, a = 0, b = 0, c = 0, def = "" } = {}) => ({
  kind, actor, target, flags, a, b, c, def,
});

try {
  const tscJs = join(WEB_NEXT, "node_modules", "typescript", "bin", "tsc");
  if (!existsSync(tscJs)) throw new Error(`找不到 ${tscJs}；先在 web-next 里 npm ci`);
  execFileSync(
    process.execPath,
    [
      tscJs,
      "--target", "es2022",
      "--module", "es2022",
      "--moduleResolution", "bundler",
      "--skipLibCheck",
      "--rootDir", "src",
      "--outDir", out,
      "src/combat/beats.ts",
      "src/stage/assets.ts",
    ],
    { cwd: WEB_NEXT, stdio: "pipe" }
  );

  const b = await import(pathToFileURL(join(out, "combat/beats.js")).href);
  const opts = { reducedMotion: false };

  // ── 1. 13 种 kind 都有话说（编号是 ABI，逐个钉住）────────────────────────
  const expected = {
    1: { tone: "damage", text: "-6" },
    2: { tone: "block", text: "格挡 +5" },
    3: { tone: "heal", text: "+7" },
    4: { tone: "buff", text: "力量 +2" },
    5: { tone: "neutral", text: "易伤 消失" },
    6: { tone: "block", text: "虚弱 被挡下" },
    7: { tone: "down", text: "倒下" },
    8: { tone: "neutral", text: "逃走" },
    9: { tone: "card", text: "打出 bash" },
    10: { tone: "turn", text: "回合开始" },
    11: { tone: "turn", text: "回合结束" },
    12: { tone: "summon", text: "召唤（12 血）" },
    13: { tone: "down", text: "被移出战斗" },
  };
  for (const [kind, want] of Object.entries(expected)) {
    const planned = b.planBeats(
      [beat(Number(kind), { a: kind === "1" ? 6 : kind === "2" ? 5 : kind === "3" ? 7 : 2, b: kind === "12" ? 12 : 0, def: kind === "4" ? "力量" : kind === "5" ? "易伤" : kind === "6" ? "虚弱" : kind === "9" ? "bash" : "" })],
      0,
      opts
    );
    const effect = planned.effects[0];
    check(
      effect && effect.tone === want.tone && effect.text === want.text,
      `kind ${kind} → ${want.tone}「${want.text}」`,
      effect ? `${effect.tone}「${effect.text}」` : "没有产出"
    );
  }

  // 伤害被格挡：文字要把"格挡了多少"说出来（否则玩家以为伤害算错了）。
  const blocked = b.planBeats([beat(1, { a: 4, b: 6 })], 0, opts).effects[0];
  check(blocked.text.includes("格挡 6"), "伤害带格挡量时文案说清", blocked.text);
  const dot = b.planBeats([beat(1, { a: 3, flags: 1 })], 0, opts).effects[0];
  check(dot.tone === "dot", "持续伤害（flags bit0）走 dot 基调", dot.tone);

  // ── 2. 未知 kind：不抛、不静默、被计数 ───────────────────────────────────
  let threw = false;
  let plannedUnknown = null;
  try {
    plannedUnknown = b.planBeats([beat(99, { a: 1 })], 0, opts);
  } catch {
    threw = true;
  }
  check(!threw, "未知 kind 不抛异常");
  check(
    plannedUnknown && plannedUnknown.unknownKinds.join(",") === "99",
    "未知 kind 被计数",
    JSON.stringify(plannedUnknown?.unknownKinds)
  );
  check(
    plannedUnknown && plannedUnknown.effects[0].text === "?99" && plannedUnknown.effects[0].tone === "neutral",
    "未知 kind 降级成中性飘字",
    JSON.stringify(plannedUnknown?.effects[0])
  );

  // ── 3. dropped 记在账上 ─────────────────────────────────────────────────
  const withDropped = b.planBeats([beat(2, { a: 5 })], 3, opts);
  check(withDropped.dropped === 3, "内核丢的 beat 数被带出来", String(withDropped.dropped));

  // ── 4. 锚点：伤害飘在被作用的人头上，出牌/回合飘在行动者身上 ─────────────
  const dmg = b.planBeats([beat(1, { actor: -1, target: 2, a: 5 })], 0, opts).effects[0];
  check(dmg.at === 2, "伤害锚在 target", String(dmg.at));
  const card = b.planBeats([beat(9, { actor: -1, target: 2, def: "strike" })], 0, opts).effects[0];
  check(card.at === -1, "出牌锚在 actor", String(card.at));

  // ── 5. 纯函数：不改输入、同输入同输出 ───────────────────────────────────
  const input = [beat(1, { a: 5 }), beat(2, { a: 3 })];
  const snapshot = JSON.stringify(input);
  const first = b.planBeats(input, 0, opts);
  const second = b.planBeats(input, 0, opts);
  check(JSON.stringify(input) === snapshot, "planBeats 不改输入");
  check(JSON.stringify(first) === JSON.stringify(second), "planBeats 是确定性的");

  // ── 6. 时长上限 ─────────────────────────────────────────────────────────
  const capped = b.planBeats([beat(7)], 0, { reducedMotion: false, maxDuration: 100 }).effects[0];
  check(capped.duration <= 100, "maxDuration 生效", String(capped.duration));

  // ── 7. 导演：入队 / 推进 / 结转 / 跳过 ──────────────────────────────────
  let state = b.createDirector(opts);
  check(!b.isBusy(state), "新建的导演是空闲的");

  state = b.enqueue(state, b.planBeats([beat(2, { a: 5 }), beat(1, { a: 6 })], 0, opts));
  check(b.isBusy(state), "入队之后忙起来");
  check(state.playing?.kind === 2, "第一条立刻开始播", String(state.playing?.kind));
  check(state.queue.length === 1, "第二条在队列里", String(state.queue.length));

  // 推进不到一条的时长：还在同一条上，elapsed 增加。
  const part = b.advance(state, 100);
  check(part.playing?.kind === 2 && part.elapsed === 100, "推进 100ms 仍在第一条", `${part.playing?.kind}/${part.elapsed}`);

  // 推进超过剩余时长：换到下一条，**余量结转**。
  const rest = part.playing.duration - part.elapsed;
  const carried = b.advance(part, rest + 60);
  check(carried.playing?.kind === 1, "播完换下一条", String(carried.playing?.kind));
  check(Math.abs(carried.elapsed - 60) < 0.001, "余量结转到下一条", String(carried.elapsed));

  // 再推一大步：队列清空。
  const done = b.advance(carried, 10000);
  check(!b.isBusy(done), "推足够久之后队列清空");

  // 跳过：立刻清空，但 dropped/unknown 仍记账。
  let withGarbage = b.enqueue(b.createDirector(opts), b.planBeats([beat(99), beat(1, { a: 5 })], 2, opts));
  const skipped = b.skipAll(withGarbage);
  check(!b.isBusy(skipped), "skipAll 立刻清空");
  check(skipped.dropped === 2 && skipped.unknownKinds.includes(99), "skipAll 不清账（dropped/unknown 仍在）");

  // ── 8. 关动画：一条都不播，但账还在 ─────────────────────────────────────
  const off = b.createDirector({ reducedMotion: true });
  const offQueued = b.enqueue(off, b.planBeats([beat(1, { a: 5 }), beat(2, { a: 3 })], 1, { reducedMotion: true }));
  check(!b.isBusy(offQueued), "关动画：队列为空（一条都不播）");
  check(offQueued.dropped === 1, "关动画：dropped 仍然记账", String(offQueued.dropped));
  const offAdvanced = b.advance(offQueued, 500);
  check(!b.isBusy(offAdvanced), "关动画：advance 也不会冒出东西");

  // 关动画 + 未知 kind：账仍然在（降级不能被"关动画"吞掉）。
  const offUnknown = b.enqueue(b.createDirector({ reducedMotion: true }), b.planBeats([beat(77)], 0, { reducedMotion: true }));
  check(offUnknown.unknownKinds.includes(77), "关动画：未知 kind 仍然记账");

  // ── 9. 资源降级（未知 enemyId 不抛、被计数）──────────────────────────────
  const assets = await import(pathToFileURL(join(out, "stage/assets.js")).href);
  assets.resetUnknownEnemyAssets();
  const cultist = assets.enemyLook("cultist");
  check(cultist.shape === "humanoid" && cultist.tint.startsWith("#"), "已知敌人有外观", JSON.stringify(cultist));
  check(assets.enemyLook("slime_boss").boss === true, "Boss 被标成 boss", JSON.stringify(assets.enemyLook("slime_boss")));
  let assetThrew = false;
  let ghost = null;
  try {
    ghost = assets.enemyLook("not_a_real_enemy");
  } catch {
    assetThrew = true;
  }
  check(!assetThrew, "未知 enemyId 不抛异常");
  check(ghost && ghost.shape === "placeholder", "未知 enemyId 降级成 placeholder", JSON.stringify(ghost));
  check(
    assets.unknownEnemyAssets().join(",") === "not_a_real_enemy",
    "未知 enemyId 被计数",
    JSON.stringify(assets.unknownEnemyAssets())
  );
  assets.resetUnknownEnemyAssets();
  check(assets.unknownEnemyAssets().length === 0, "reset 之后计数清零");
  check(assets.knownEnemyAssets() >= 15, "外观表覆盖 >= 15 个 id", String(assets.knownEnemyAssets()));
  summary.assets = assets.knownEnemyAssets();

  // ── 10. 诊断串 ──────────────────────────────────────────────────────────
  const text = b.describeDirector(state);
  check(text.includes("playing=") && text.includes("dropped="), "诊断串可用", text);
} finally {
  await rm(out, { recursive: true, force: true });
}

console.log("");
if (bad > 0) {
  console.error(`${GATE} FAIL: ${bad} 条`);
  process.exit(1);
}
console.log(
  `UI_BEATS PASS kinds=13 unknown=degraded dropped=counted skip=clears reduced=quiet assets=${summary.assets}`
);

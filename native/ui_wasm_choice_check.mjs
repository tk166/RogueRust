// 闸门 30 `ui-wasm-choice`：待决选牌（`rd_env_choice_*`）与 beat（`rd_env_beat_*`）。
//
// ## 为什么需要药水来造夹具
//
// 会问句的牌（`armaments` / `warcry` / `headbutt` / `exhume` / `dual_wield` / `nightmare` /
// `true_grit+`）都不在起手牌里，而起手牌是随机的 ⇒ "打几把看看能不能碰到"不是夹具，是赌博。
// 所以用 `rd_run_grant_potion` + `rd_env_use_potion`：**Elixir** 一喝就问"要消耗哪几张"，
// 局面确定、可复现。这条路径用的是真内核，不是合成向量。
//
// ## 断言

import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_WASM_CHOICE";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};

const { execFileSync } = await import("node:child_process");
try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/p2.html",
  query: "",
  gate: GATE,
  waitFor: "Boolean(window.__p2 && window.__p2.ready)",
});
const evaluate = (expression) => page.evaluate(expression);

check((await evaluate("window.__p2.load()"))?.ok === true, "装载成功");

// ── 1. 没有问句时：`choice()` 是 null，两个入口都返回 -1（不是崩）──────────
const started = await evaluate('window.__p2.startFight(1, "elixir")');
check(started?.fightCode === 0, "进入战斗", String(started?.fightCode));
check((await evaluate("window.__p2.choice()")) === null, "普通战斗中 choice() 是 null");
const idleConfirm = await evaluate("window.__p2.choiceConfirm()");
check(idleConfirm.code === -1, "没有问句时 confirm 返回 -1（不是崩、不是静默成功）", String(idleConfirm.code));
const idlePick = await evaluate("window.__p2.choicePick(0, true)");
check(idlePick.code === -1, "没有问句时 pick 返回 -1", String(idlePick.code));

const potions = await evaluate("window.__p2.potions()");
check(
  potions.some((potion) => potion.id === "elixir"),
  "背包里有 Elixir（`rd_run_grant_potion` 生效）",
  JSON.stringify(potions.map((potion) => potion.id))
);

// ── 2. 喝 Elixir ⇒ 真实问句：source=1（手牌）、kind=1（消耗）────────────────
const beforeUse = await evaluate("window.__p2.snapshot()");
const used = await evaluate("window.__p2.usePotion(0, -1)");
check(used.code === 0, "喝药水成功", String(used.code));
const choice = used.choice;
check(choice !== null, "喝下去后出现问句");
if (choice) {
  check(choice.source === 1, "问句来源是**手牌堆**（source = 1）", String(choice.source));
  check(choice.kind === 1, "回答之后**消耗**（kind = 1）", String(choice.kind));
  check(
    choice.options.length === beforeUse.handCount,
    "选项数 == 手牌数（每个选项就是一张手牌）",
    `${choice.options.length} vs ${beforeUse.handCount}`
  );
  check(
    choice.options.every((option) => option.title.length > 0),
    "每个选项都有标题（来自 `rd_env_pile_card_title_*`）",
    JSON.stringify(choice.options.map((option) => option.title))
  );
  check(choice.max >= 1, "上限至少 1（可以消耗一张）", `min=${choice.min} max=${choice.max}`);
}

// ── 3. 勾选 → 确认 ⇒ 内核真的消耗了那张牌 ─────────────────────────────────
const picked = await evaluate("window.__p2.choicePick(0, true)");
check(picked.code === 0 && picked.choice.options[0].selected === true, "勾选第 0 项", JSON.stringify(picked.code));
const confirmed = await evaluate("window.__p2.choiceConfirm()");
check(confirmed.code === 0, "确认被接受", String(confirmed.code));
check(confirmed.choice === null, "确认后问句消失");
check(
  confirmed.snapshot.piles.exhaust === beforeUse.piles.exhaust + 1,
  "消耗堆 +1（内核真的消耗了那张牌）",
  `${beforeUse.piles.exhaust} -> ${confirmed.snapshot.piles.exhaust}`
);
check(
  confirmed.snapshot.handCount === beforeUse.handCount - 1,
  "手牌 -1",
  `${beforeUse.handCount} -> ${confirmed.snapshot.handCount}`
);
check(confirmed.unchanged === false, "确认确实改变了状态（不是空操作）");

// ── 4. 清空：勾两张再清空，选中数归零 ─────────────────────────────────────
const again = await evaluate('window.__p2.startFight(2, "elixir")');
check(again?.fightCode === 0, "重开一场（用于清空路径）", String(again?.fightCode));
await evaluate("window.__p2.usePotion(0, -1)");
await evaluate("window.__p2.choicePick(0, true)");
const twoPicks = await evaluate("window.__p2.choicePick(1, true)");
check(twoPicks.choice.options.filter((option) => option.selected).length === 2, "勾了两张", JSON.stringify(twoPicks.code));
const cleared = await evaluate("window.__p2.choiceClear()");
check(
  cleared.choice !== null && cleared.choice.options.every((option) => !option.selected),
  "清空后选中数归零，且问句还在",
  JSON.stringify(cleared.choice?.options.map((option) => option.selected))
);

// ── 5. Beat：出牌后内核给出演出日志，且没有丢弃 ───────────────────────────
await evaluate("window.__p2.choiceClear()");
// 先确认掉问句（Elixir 的 min 是 0，空选也能确认）
await evaluate("window.__p2.choiceConfirm()");
const action = await evaluate(`(() => {
  const s = window.__p2.snapshot();
  return s.actions.find((a) => a.kind === "play") ?? null;
})()`);
check(action !== null, "确认后又能出牌了（动作表恢复）", JSON.stringify(action));
if (action) {
  await evaluate(`window.__p2.dispatch(${action.handSlot}, ${action.targetSlot})`);
  const beats = await evaluate("window.__p2.beats()");
  check(beats.beats.length > 0, "出牌后 beat 非空", JSON.stringify(beats.beats.slice(0, 3)));
  check(beats.dropped === 0, "没有丢弃的 beat（`beats_dropped = 0` 是唯一好答案）", String(beats.dropped));
  check(
    beats.beats.some((beat) => beat.kind === 9),
    "beat 里有一条「打出牌」（kind 9）",
    JSON.stringify(beats.beats.map((beat) => beat.kind))
  );
  check(
    beats.beats.every((beat) => beat.actor >= -2 && beat.actor <= 5),
    "beat 的墙位槽在 `-2..5` 之间（`-1` 英雄 / `0..5` 敌人）",
    JSON.stringify(beats.beats.map((beat) => beat.actor))
  );
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_WASM_CHOICE PASS source=${choice?.source} kind=${choice?.kind} options=${choice?.options.length} ` +
    `exhaust=${beforeUse.piles.exhaust}->${confirmed.snapshot.piles.exhaust} beats=ok`
);

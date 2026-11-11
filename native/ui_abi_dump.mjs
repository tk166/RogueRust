// P0：**真实 WASM 的 ABI 基线 dump + 契约断言 + 场景 parity**（UI 计划 §11 P0）。
//
// WHY THIS FILE EXISTS
// --------------------
// 新 UI 的第一份契约基线。它做三件事，而且**只做这三件**：
//
//   1. `--check`  契约断言：已知导出都在、观察向量长度是它自己说的那个数、哨兵语义与代码一致、
//                 `resolveScene` 对 18 个合成夹具与 `ui_panels.js` 的判据一致。
//   2. `--report` 用真实 wasm 把**十个场景**跑一遍，把**原始导出值**（不是类型化快照）落成
//                 `native/ui_fixtures/*.json`，并打印一张"到达了/没到达"的表。
//   3. `--check-fixtures` 把 `--report` 的结果与盘上的 fixture 比对（陈旧就红）。
//
// ⚠️ 为什么产物是**原始 dump** 而不是 `GameSnapshot`：`GameSnapshot` 是 P2 的 `SnapshotReader`
// 的事。P0 若依赖 P2，P0 就永远做不完（计划 §11 的循环依赖）。这里只记"wasm 说了什么"，
// 由 P2 去解释。
//
// ⚠️ 这里**不碰** `web/`：老页面仍是默认入口，`web/rd_wasm.wasm` 由闸门 15 守着字节。
// 本脚本只读它。
//
// 跑法（bash）：
//   node native/ui_abi_dump.mjs --check
//   node native/ui_abi_dump.mjs --report
//   node native/ui_abi_dump.mjs --check-fixtures

import { readFile, writeFile, mkdir, rename } from "node:fs/promises";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const WASM = join(ROOT, "web", "rd_wasm.wasm");
const FIXTURES = join(HERE, "ui_fixtures");

const fail = (message) => {
  console.error("UI_ABI FAIL: " + message);
  process.exit(1);
};

// ---------------------------------------------------------------------------------------------
// wasm 装载
// ---------------------------------------------------------------------------------------------
const bytes = await readFile(WASM);
/// wasm 的 sha256。**`--check-fixtures` 要比它**：内容指纹只看镜像，看不出"内核代码变了、
/// 内容没变"（第十二轮 Review P1-B）。
const WASM_SHA256 = createHash("sha256").update(bytes).digest("hex");
const { instance } = await WebAssembly.instantiate(bytes, {});
const ex = instance.exports;
if (!ex.memory) fail("the module must export `memory` (the page reads it through this)");

/// `_len` / `_into` 一对：**先问长度，再写进自己的缓冲**（ABI 的规矩，见 ui-state-model §8）。
function readText(lenFn, intoFn, ...args) {
  const len = lenFn(...args);
  if (len < 0) return null;
  if (len === 0) return "";
  // 用模块自己的 scratch（1 KiB）：这是它存在的理由，不要猜 `__heap_base`。
  const ptr = Number(ex.rd_env_scratch_buf());
  if (len > 1024) fail(`text of ${len} bytes does not fit the 1 KiB scratch`);
  const written = intoFn(ptr, ...args);
  if (written !== len) fail(`_into wrote ${written}, _len said ${len}`);
  return new TextDecoder().decode(new Uint8Array(ex.memory.buffer, ptr, len));
}

const runText = (name, ...args) =>
  readText(ex[`rd_run_${name}_len`], ex[`rd_run_${name}_into`], ...args);

// ---------------------------------------------------------------------------------------------
// 观察向量：**复制**出来（不把 Int32Array View 传出去 —— memory.grow 会让它失效）
// ---------------------------------------------------------------------------------------------
function combatObservation() {
  const len = ex.rd_env_observe_len();
  const ptr = Number(ex.rd_env_observe_buf());
  return Array.from(new Int32Array(ex.memory.buffer, ptr, len));
}

function runObservation() {
  const len = ex.rd_run_observe_len();
  const out = [];
  for (let i = 0; i < len; i++) out.push(ex.rd_run_observe(i));
  return out;
}

// ---------------------------------------------------------------------------------------------
// 动作表 / 地图
// ---------------------------------------------------------------------------------------------
const runActions = () => {
  const count = ex.rd_run_action_count();
  const out = [];
  for (let i = 0; i < count; i++) out.push({ index: i, kind: ex.rd_run_action(i), node: ex.rd_run_action_arg(i, 0) });
  return out;
};

const combatActions = () => {
  const count = ex.rd_env_action_count();
  const out = [];
  for (let i = 0; i < count; i++) {
    out.push({ index: i, kind: ex.rd_env_action_kind(i), arg0: ex.rd_env_action_arg(i, 0), arg1: ex.rd_env_action_arg(i, 1) });
  }
  return out;
};

const NODE_KIND = 2; // `rd_run_map_node(index, 2)` = kind（`env-abi.md` §11.2）
const nodeKind = (node) => ex.rd_run_map_node(node, NODE_KIND);

/// 本步可进入的节点里，第一个 kind == `kind` 的动作下标；没有就 `-1`。
function actionTo(kind) {
  for (const a of runActions()) {
    if (a.node >= 0 && nodeKind(a.node) === kind) return a.index;
  }
  return -1;
}

// ---------------------------------------------------------------------------------------------
// 场景快照：**十个原始字段**（这就是 Adapter 的头十行，先在这里定型）
//
// `ui_panels.js` 的 `resolveScene` 只吃这十个字段。它们是**内核事实**，没有一个是页面历史。
// ---------------------------------------------------------------------------------------------
function runFacts() {
  const obs = runObservation();
  return {
    noRun: ex.rd_run_exists() !== 1,
    inFight: ex.rd_run_in_fight() === 1,
    runOver: ex.rd_run_over() === 1,
    runOverWhy: ex.rd_run_over_why(),
    cleared: !(ex.rd_run_over() === 1) && ex.rd_run_boss_beaten() === 1,
    pending: ex.rd_run_pending(),
    kind: ex.rd_run_node_kind(),
    unknownRoom: obs[18],
    eventFight: ex.rd_run_event_fight(),
    pickupPicks: ex.rd_run_pickup_picks(),
    pickupAdd: ex.rd_run_pickup_add(),
    actionCount: ex.rd_run_action_count(),
    // 只给 `resolveScene` 用；其余字段按需读。
    floor: obs[0],
    hp: obs[2],
    hpMax: obs[3],
    gold: obs[4],
  };
}

/// 把 `ui_panels.js` 的 `SCENES` / `resolveScene` 装进一个 vm 上下文（它是**纯**的，无 DOM）。
async function loadPanels() {
  const source = await readFile(join(ROOT, "web", "ui_panels.js"), "utf8");
  const context = vm.createContext({});
  new vm.Script(source, { filename: "ui_panels.js" }).runInContext(context);
  const P = context.RD_PANELS;
  if (!P) fail("ui_panels.js did not define RD_PANELS");
  return P;
}

// ---------------------------------------------------------------------------------------------
// 场景驱动
// ---------------------------------------------------------------------------------------------
function finishBlessing() {
  // 祝福（pending 6）→ 可能还欠一次选牌（7）。
  if (ex.rd_run_pending() === 6) ex.rd_run_choose_start(0);
  for (let guard = 0; guard < 4 && ex.rd_run_pending() === 7; guard++) ex.rd_run_pick_blessing_card(0);
}

/// 这个节点是不是**一场战斗**（三个来源：节点种类、`?` 房掷出怪物、事件引来的伏击）。
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

/// 走到"**站在战斗节点上、还没开打**"（= `SC-03` 那一屏）；返回是否到达。
///
/// 判据是三个内核事实：`pending === 0`、`isFightNode()`、`node_resolved() === 0`。
/// ⚠️ 不 `begin_node`：战斗节点上它什么都不做（见 `walkTo` 的注释）。
function walkToFightNode(hops = 26) {
  for (let hop = 0; hop < hops; hop++) {
    if (ex.rd_run_over() === 1) return false;
    if (ex.rd_run_pending() === 0 && isFightNode() && ex.rd_run_node_resolved() === 0) return true;
    if (ex.rd_run_pending() === 0) {
      if (ex.rd_run_node_kind() >= 0 && ex.rd_run_node_resolved() === 0) {
        if (isFightNode()) return true;
        ex.rd_run_begin_node();
        continue;
      }
      if (ex.rd_run_step(0) !== 0) return false;
      continue;
    }
    if (!settleHere()) return false;
  }
  return ex.rd_run_pending() === 0 && isFightNode() && ex.rd_run_node_resolved() === 0;
}

/// `pending` → 该走哪种节点（`Pending` 的判别值 → `NodeKind`）。
///
/// `?` 房（kind 5）掷出什么由内核决定：`Event` 才是 pending 5，`Monster`/`Shop`/`Treasure`
/// 分别是别的值。所以这里只负责"走到一个 `?` 房"，**是不是事件要下一跳才知道**。
const KIND_FOR_PENDING = { 1: 3, 2: 4, 3: 6, 5: 5 };

/// 走到 `pending === want` 的那一屏；返回是否到达。
///
/// ⚠️ 第一版写成"看到目标节点就 `begin_node` 然后返回 true"，于是**落到商店那一格后立刻
/// 把它 `leave` 掉**（`settleHere` 的 case 2），三个场景永远"走不到"。现在每跳顶部先检查
/// `pending`，站在未结算的节点上就先 `begin_node` —— 顺序反过来就够。
function walkTo(want, hops = 26) {
  for (let hop = 0; hop < hops; hop++) {
    // ⚠️ 局终了就别再找场景：`runOver` 压过一切 `pending`，捕获下来的会是 `SC-12b`
    // （分类器是对的，是夹具错了 —— 这一条是 `--report` 当场抓出来的）。
    if (ex.rd_run_over() === 1) return false;
    if (ex.rd_run_pending() === want) return true;
    if (ex.rd_run_pending() === 0) {
      if (ex.rd_run_node_kind() >= 0 && ex.rd_run_node_resolved() === 0) {
        // ⚠️ 战斗节点**不能** `begin_node`：它对战斗什么都不做（返回 0、pending 仍是 0），
        // 于是"站在未结算节点就先 begin_node"会**空转**。战斗要用 `settleFightNode`。
        if (isFightNode()) {
          settleFightNode(true);
          continue;
        }
        ex.rd_run_begin_node();
        continue;
      }
      const kind = KIND_FOR_PENDING[want];
      const action = kind === undefined ? -1 : actionTo(kind);
      if (action >= 0 && ex.rd_run_step(action) === 0) continue;
      if (ex.rd_run_step(0) !== 0) return false;
      continue;
    }
    if (!settleHere()) return false;
  }
  return ex.rd_run_pending() === want;
}

/// 把当前这场战斗打到**有结果**：能出牌就出牌，否则结束回合。返回 `rd_env_result()`。
///
/// ⚠️ 第一版在 `fight_begin` 之后**立刻** `fight_end`，那时战斗还没有结果 ⇒ 没有奖励屏、
/// 节点也没结算 ⇒ 后面每一步 `rd_run_step` 都被 `NodeNotSettled` 拒掉，于是"商店/宝箱/事件
/// 400 个种子都走不到" —— **一个夹具缺陷伪装成三个场景不可达**。
function playOutFight(maxSteps = 600) {
  for (let step = 0; step < maxSteps; step++) {
    if (ex.rd_env_done() !== 0) return ex.rd_env_result();
    const actions = combatActions();
    const play = actions.find((a) => a.kind === 0);
    const end = actions.find((a) => a.kind === 1);
    const pick = play || end;
    if (!pick) return -1;
    if (ex.rd_env_step(pick.index) !== 0) {
      // 被拒（例如目标过期）：退一步只结束回合；两个都不行就放弃。
      if (!end || ex.rd_env_step(end.index) !== 0) return -1;
    }
  }
  return -1;
}

/// 故意**输**：只结束回合、从不出牌。用来真实到达"战败"那一屏（`SC-12b`）。
function loseFight(maxSteps = 600) {
  for (let step = 0; step < maxSteps; step++) {
    if (ex.rd_env_done() !== 0) return ex.rd_env_result();
    const end = combatActions().find((a) => a.kind === 1);
    if (!end) return -1;
    if (ex.rd_env_step(end.index) !== 0) return -1;
  }
  return -1;
}

/// 结算脚下这一格（把"待决"走完、或把战斗收掉），返回是否前进了一步。
function settleHere() {
  const pending = ex.rd_run_pending();
  switch (pending) {
    case 1: return ex.rd_run_rest() === 0;
    case 2: return ex.rd_run_leave() === 0;
    case 3: { ex.rd_run_open_chest(); return ex.rd_run_leave() === 0; }
    case 4: return ex.rd_run_skip_reward() === 0;
    case 5: return ex.rd_run_choose(0) === 0;
    case 7: return ex.rd_run_pick_blessing_card(0) === 0;
    case 8: return ex.rd_run_pick_event_card(0) === 0;
    case 9: return ex.rd_run_event_offer_take(0) === 0;
    case 0: {
      // 战斗节点：**打到有结果**再收（见 `playOutFight`：立刻收会让节点不结算）。
      if (ex.rd_run_fight_begin() === 0) {
        playOutFight();
        ex.rd_run_fight_end();
        return true;
      }
      return ex.rd_run_step(0) === 0;
    }
    default: return false;
  }
}

// ---------------------------------------------------------------------------------------------
// 一个场景的记录：**原始导出值**，一个字段都不解释
// ---------------------------------------------------------------------------------------------
function captureRun(label, note) {
  const facts = runFacts();
  return {
    label,
    note: note || "",
    facts,
    raw: {
      runExists: ex.rd_run_exists(),
      seed: ex.rd_run_seed(),
      act: ex.rd_run_act(),
      ascension: ex.rd_run_ascension(),
      inFight: ex.rd_run_in_fight(),
      over: ex.rd_run_over(),
      overWhy: ex.rd_run_over_why(),
      bossBeaten: ex.rd_run_boss_beaten(),
      nodeResolved: ex.rd_run_node_resolved(),
      restHeal: ex.rd_run_rest_heal(),
      removalAvailable: ex.rd_run_removal_available(),
      bossId: runText("boss_id"),
      eventId: runText("event_id"),
      encounterId: runText("encounter_id"),
      startOfferCount: ex.rd_run_start_offer_count(),
      deckCount: ex.rd_run_deck_count(),
      relicCount: ex.rd_run_observe(6),
      potionCount: ex.rd_run_potion_count(),
      wingBoots: ex.rd_run_wing_boots(),
      campfire: ex.rd_run_campfire_options(),
      giryaLifts: ex.rd_run_girya_lifts(),
      removePrice: ex.rd_run_remove_price(),
      observe: runObservation(),
      actions: runActions(),
      map: { len: ex.rd_run_map_len(), rows: ex.rd_run_map_rows() },
      shop: {
        cards: ex.rd_run_shop_card_count(),
        colorless: ex.rd_run_shop_colorless_count(),
        potions: ex.rd_run_shop_potion_count(),
        relics: ex.rd_run_shop_relic_count(),
        prices: [
          ex.rd_run_shop_card_count() > 0 ? ex.rd_run_shop_card_price(0) : null,
          ex.rd_run_shop_colorless_count() > 0 ? ex.rd_run_shop_colorless_price(0) : null,
          ex.rd_run_shop_potion_count() > 0 ? ex.rd_run_shop_potion_price(0) : null,
          ex.rd_run_shop_relic_count() > 0 ? ex.rd_run_shop_relic_price(0) : null,
        ],
      },
      reward: { gold: ex.rd_run_reward_gold(), cards: ex.rd_run_reward_card_count() },
      event: {
        text: runText("event_text"),
        options: ex.rd_run_event_option_count(),
      },
      pickup: { picks: ex.rd_run_pickup_picks(), add: ex.rd_run_pickup_add(), offer: ex.rd_run_pickup_offer_count() },
    },
  };
}

function captureCombat(label, note) {
  return {
    label,
    note: note || "",
    raw: {
      observeLen: ex.rd_env_observe_len(),
      observe: combatObservation(),
      actions: combatActions(),
      beatCount: ex.rd_env_beat_count(),
      beatsDropped: ex.rd_env_beats_dropped(),
      choicePending: ex.rd_env_choice_pending(),
      activeSlot: ex.rd_env_active_slot(),
      done: ex.rd_env_done(),
      result: ex.rd_env_result(),
      piles: [ex.rd_env_pile_len(0), ex.rd_env_pile_len(1), ex.rd_env_pile_len(2)],
    },
  };
}

// ---------------------------------------------------------------------------------------------
// `--report`：把十个场景跑一遍
// ---------------------------------------------------------------------------------------------
async function report() {
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
      reached = walkTo(want) && ex.rd_run_over() !== 1;
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

  // ── 场景判定：**计划驱动**，不是"有 mismatch 才红" ──────────────────────────
  //
  // 第十二轮 Review P1-A：第一版只检查 `sceneMismatch`，于是 `raw: null`（UNREACHED）的条目
  // **被跳过** —— 少采几个场景照样 `UI_ABI_REPORT PASS`。现在每条场景先声明它是
  // `real`（必须真实到达）还是 `synthetic`（允许合成，但要写明理由），没到达就 FAIL。
  //
  // `SC-11a` 的判据是**覆盖层真的出现在 `overlays` 里**（`pickupPicks > 0` 只是前提，
  // 不是"这一屏画对了"）。
  const SCENE_PLAN = [
    { label: "SC-00-no-run", expect: "SC-00", kind: "real" },
    { label: "SC-01-blessing", expect: "SC-01", kind: "real" },
    { label: "SC-02-map", expect: "SC-02", kind: "real" },
    { label: "SC-03-pre-fight", expect: "SC-03", kind: "real" },
    { label: "SC-03b-combat", expect: null, kind: "real" }, // 战斗向量本身，没有运行层 base
    { label: "SC-03b-run-facts", expect: "SC-03b", kind: "real" },
    { label: "SC-04-reward", expect: "SC-04", kind: "real" },
    { label: "SC-05-shop", expect: "SC-05", kind: "real" },
    { label: "SC-07-treasure", expect: "SC-07", kind: "real" },
    { label: "SC-08-event", expect: "SC-08", kind: "real" },
    { label: "SC-11a-pickup-debt", expect: null, overlay: "SC-11a", kind: "real" },
    { label: "SC-12b-defeat", expect: "SC-12b", kind: "real" },
    { label: "SC-12a-act-clear", expect: "SC-12a", kind: "synthetic", why: "needs the boss fight" },
  ];

  const byLabel = new Map(scenes.map((scene) => [scene.label, scene]));
  for (const plan of SCENE_PLAN) {
    const scene = byLabel.get(plan.label);
    if (!scene || !scene.raw) {
      plan.state = "UNREACHED";
      continue;
    }
    if (scene.facts) scene.scene = P.resolveScene(scene.facts);
    if (plan.expect && scene.scene && scene.scene.base !== plan.expect) {
      plan.state = "INVALID";
      plan.detail = `want ${plan.expect}, got ${JSON.stringify(scene.scene)}`;
      continue;
    }
    if (plan.overlay && !(scene.scene && scene.scene.overlays.includes(plan.overlay))) {
      plan.state = "INVALID";
      plan.detail = `want overlay ${plan.overlay}, got ${JSON.stringify(scene.scene)}`;
      continue;
    }
    plan.state = "REAL";
  }

  const broken = SCENE_PLAN.filter(
    (plan) => plan.kind === "real" && plan.state !== "REAL"
  );
  const synthetic = SCENE_PLAN.filter((plan) => plan.kind === "synthetic");

  // ── 先验证、再原子写（P2-A：失败的采集不许覆盖上一份有效 fixture）──────────
  const payload = {
    note:
      "P0 ABI dumps. `raw` is exactly what the wasm exports returned (uninterpreted); " +
      "`facts` and `scene` are DERIVED by this script -- see `provenance`.",
    provenance: {
      raw: "verbatim return values of the wasm exports",
      facts: "derived from raw by this script (the ten Adapter fields); not an ABI claim",
      scene: "computed by web/ui_panels.js resolveScene() from facts",
    },
    wasmSha256: WASM_SHA256,
    contentFingerprint: `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`,
    runObserveLen: ex.rd_run_observe_len(),
    combatObserveLen: ex.rd_env_observe_len(),
    plan: SCENE_PLAN,
    scenes,
  };

  console.log(
    `UI_ABI_REPORT content=${payload.contentFingerprint} wasm=${WASM_SHA256.slice(0, 12)} ` +
    `runObs=${payload.runObserveLen} combatObs=${payload.combatObserveLen}`
  );
  for (const plan of SCENE_PLAN) {
    const scene = byLabel.get(plan.label);
    const where = scene && scene.scene
      ? `${scene.scene.base}${scene.scene.overlays.length ? "+" + scene.scene.overlays.join("+") : ""}`
      : "-";
    const note = plan.detail || (scene ? scene.note : "") || plan.why || "";
    console.log(`  ${plan.label.padEnd(24)} ${plan.state.padEnd(9)} ${where.padEnd(14)} ${note}`);
  }

  if (broken.length) {
    // ⚠️ **不写盘**：失败的采集不能污染上一份有效 fixture。
    fail(
      `${broken.length} required-real scene(s) not proven: ` +
      broken.map((plan) => `${plan.label}=${plan.state}`).join(", ")
    );
  }

  await mkdir(FIXTURES, { recursive: true });
  const target = join(FIXTURES, "p0-scenes.json");
  const temp = `${target}.tmp`;
  await writeFile(temp, JSON.stringify(payload, null, 1) + "\n", "utf8");
  await rename(temp, target);

  if (synthetic.length) {
    console.log(
      `  (synthetic, allowed: ${synthetic.map((plan) => `${plan.label} -- ${plan.why}`).join("; ")})`
    );
  }
  console.log(`UI_ABI_REPORT PASS (real ${SCENE_PLAN.length - synthetic.length}/${SCENE_PLAN.length - synthetic.length})`);
}

async function check() {
  const P = await loadPanels();
  const problems = [];

  // ① 已知必须存在的导出（新 UI 的第一层依赖；少一个就说明 ABI 被删了）
  const REQUIRED = [
    "rd_run_exists", "rd_run_seed", "rd_run_act", "rd_run_pending", "rd_run_node_kind",
    "rd_run_in_fight", "rd_run_over", "rd_run_over_why", "rd_run_rest_heal",
    "rd_run_removal_available", "rd_run_boss_beaten", "rd_run_node_resolved",
    "rd_run_boss_id_len", "rd_run_boss_id_into", "rd_run_event_id_len", "rd_run_event_id_into",
    "rd_run_encounter_id_len", "rd_run_encounter_id_into",
    "rd_run_action_count", "rd_run_action", "rd_run_action_arg", "rd_run_step",
    "rd_run_observe", "rd_run_observe_len", "rd_run_map_len", "rd_run_map_rows", "rd_run_map_node",
    "rd_run_start", "rd_run_choose_start", "rd_run_begin_node", "rd_run_fight_begin", "rd_run_fight_end",
    "rd_run_pickup_picks", "rd_run_pickup_add", "rd_run_start_offer_count",
    "rd_run_campfire_options", "rd_run_remove_price",
    "rd_env_observe_len", "rd_env_observe_buf", "rd_env_observe_into",
    "rd_env_action_count", "rd_env_action_kind", "rd_env_action_arg", "rd_env_step",
    "rd_env_beat_count", "rd_env_beat_field", "rd_env_beats_dropped",
    "rd_env_choice_pending", "rd_env_active_slot", "rd_env_done", "rd_env_result",
    "rd_content_fingerprint",
  ];
  for (const name of REQUIRED) {
    if (typeof ex[name] !== "function") problems.push(`missing export: ${name}`);
  }
  if (problems.length) fail(problems.join("\n  "));

  // ② 观察向量长度：**由模块自己说**，而页面/Adapter 不许写死
  const runLen = ex.rd_run_observe_len();
  const combatLen = ex.rd_env_observe_len();
  if (runLen !== 19) problems.push(`rd_run_observe_len() = ${runLen}, the ABI says 19`);
  if (combatLen !== 148) problems.push(`rd_env_observe_len() = ${combatLen}, the ABI says 148`);
  // 无局时 run 向量越界必须给 `i32::MIN`（不是 0）
  if (ex.rd_run_observe(runLen) !== -2147483648) {
    problems.push("rd_run_observe(len) must be i32::MIN, not 0");
  }

  // ③ 哨兵语义（§348 / §344 / §349 的三条，都是"曾经搞错过"的）
  if (ex.rd_run_exists() !== 0) problems.push("with no session, rd_run_exists() must be 0");
  if (ex.rd_run_seed() !== -2147483648) problems.push("with no session, rd_run_seed() must be i32::MIN");
  if (ex.rd_run_over() !== -1) problems.push("with no session, rd_run_over() must be -1");
  if (ex.rd_run_rest_heal() !== -1) problems.push("with no session, rd_run_rest_heal() must be -1");
  if (ex.rd_run_removal_available() !== -1) problems.push("with no session, removal_available must be -1");
  if (ex.rd_env_active_slot() !== -3) problems.push("with no combat session, active_slot must be -3");
  if (ex.rd_env_observe_len() !== combatLen) problems.push("observe_len is not stable");

  // ④ `i32::MIN` 是**合法 seed**：用开局那一局必须被认成"有局"（§348 的教训）
  if (ex.rd_run_start(-2147483648, 0) !== 0) problems.push("i32::MIN must be a legal seed");
  if (ex.rd_run_exists() !== 1) problems.push("a run started with i32::MIN must still EXIST");
  if (ex.rd_run_boss_id_len() !== 0) {
    problems.push("before any boss fight, boss_id must be empty (0), not the pool head");
  }

  // ⑤ 场景表 parity：18 个合成夹具 → `resolveScene` 的 base 必须与 `classifyScene` 一致
  //    （有覆盖层时 `classifyScene` 报覆盖层、`resolveScene` 报底屏 —— 这正是 §349 的分工）
  const BASE = {
    noRun: false, inFight: false, runOver: false, runOverWhy: 0, cleared: false, pending: 0,
    kind: -1, unknownRoom: 0, eventFight: 0, pickupPicks: 0, pickupAdd: 0, actionCount: 0,
  };
  const FIXTURES_18 = [
    ["SC-00", { noRun: true, pending: -1 }],
    ["SC-03b", { inFight: true, kind: 1, actionCount: 1 }],
    ["SC-11a", { pending: 4, pickupPicks: 2 }],
    ["SC-11b", { pending: 4, pickupAdd: 2 }],
    ["SC-12b", { runOver: true }],
    ["SC-12a", { cleared: true, kind: 7 }],
    ["SC-01", { pending: 6 }],
    ["SC-01b", { pending: 7 }],
    ["SC-09", { pending: 8 }],
    ["SC-10", { pending: 9 }],
    ["SC-04", { pending: 4 }],
    ["SC-08", { pending: 5 }],
    ["SC-07", { pending: 3, kind: 6 }],
    ["SC-05", { pending: 2, kind: 4 }],
    ["SC-06", { pending: 1, kind: 3 }],
    ["SC-03", { kind: 1, actionCount: 1 }],
    ["SC-02b", { kind: 3, actionCount: 0 }],
    ["SC-02", { kind: 4, actionCount: 2 }],
  ];
  for (const [want, overrides] of FIXTURES_18) {
    const facts = { ...BASE, ...overrides };
    const resolved = P.resolveScene(facts);
    const overlay = P.isOverlay(want);
    const ok = overlay
      ? resolved.overlays.includes(want) && resolved.base !== want
      : resolved.base === want && resolved.overlays.length === 0;
    if (!ok) problems.push(`scene parity ${want}: ${JSON.stringify(resolved)}`);
    if (P.classifyScene(facts) !== want) problems.push(`classifyScene ${want}: ${P.classifyScene(facts)}`);
  }
  // 表外 pending：必须显式 `SC-??` 并带回那个值
  const unknown = P.resolveScene({ ...BASE, pending: 99 });
  if (unknown.base !== "SC-??" || unknown.unknownPending !== 99) {
    problems.push(`unknown pending: ${JSON.stringify(unknown)}`);
  }
  // 18 条顺序：数组即优先级
  const ORDER = FIXTURES_18.map(([id]) => id);
  const got = P.SCENES.map((s) => s.id);
  if (JSON.stringify(got) !== JSON.stringify(ORDER)) {
    problems.push(`SCENES order drifted:\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(ORDER)}`);
  }

  if (problems.length) fail(problems.join("\n  "));
  console.log(
    `UI_ABI_CHECK PASS (exports ${REQUIRED.length}, runObs ${runLen}, combatObs ${combatLen}, ` +
    `content 0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}, scenes ${FIXTURES_18.length})`
  );
}

// ---------------------------------------------------------------------------------------------
// `--check-fixtures`：盘上的 dump 是否还新鲜
// ---------------------------------------------------------------------------------------------
async function checkFixtures() {
  const path = join(FIXTURES, "p0-scenes.json");
  if (!existsSync(path)) fail("no fixtures yet -- run `--report` first");
  const onDisk = JSON.parse(await readFile(path, "utf8"));
  const live = `0x${(ex.rd_content_fingerprint() >>> 0).toString(16).padStart(8, "0")}`;

  // ⚠️ 第十二轮 Review P1-B：**内容指纹看不出"内核代码变了、内容没变"**。
  // 所以这里比三样：wasm sha256（代码）、内容指纹（内容）、两个向量长度（形状）。
  // 三种"新鲜"是不同的事，报错要说清是哪一种：
  //   metadata current  ≠  语义一致  ≠  场景仍可达
  const drift = [];
  if (onDisk.wasmSha256 !== WASM_SHA256) {
    drift.push(`wasm sha256 ${String(onDisk.wasmSha256).slice(0, 12)} -> ${WASM_SHA256.slice(0, 12)} (the kernel changed)`);
  }
  if (onDisk.contentFingerprint !== live) {
    drift.push(`content ${onDisk.contentFingerprint} -> ${live} (the image changed)`);
  }
  if (onDisk.runObserveLen !== ex.rd_run_observe_len()) drift.push("runObserveLen drifted");
  if (onDisk.combatObserveLen !== ex.rd_env_observe_len()) drift.push("combatObserveLen drifted");
  if (drift.length) {
    fail(
      "fixtures are stale:\n  " + drift.join("\n  ") +
      "\n  re-run `--report` (this check proves *metadata* freshness only, not semantic equality)"
    );
  }
  const real = (onDisk.plan || []).filter((plan) => plan.kind === "real");
  const proven = real.filter((plan) => plan.state === "REAL").length;
  console.log(
    `UI_ABI_FIXTURES PASS (metadata current: wasm ${WASM_SHA256.slice(0, 12)}, content ${live}, ` +
    `${proven}/${real.length} required-real scenes were REAL when captured)`
  );
}

// ---------------------------------------------------------------------------------------------
const mode = process.argv[2] || "--check";
if (mode === "--check") await check();
else if (mode === "--report") await report();
else if (mode === "--check-fixtures") await checkFixtures();
else fail(`unknown mode ${mode} (use --check / --report / --check-fixtures)`);

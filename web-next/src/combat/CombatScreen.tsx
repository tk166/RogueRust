// **战斗屏**：Canvas + HUD + DOM 覆盖层 + 模态。
//
// 从 `App.tsx` 抽出来的（P3）。抽的理由是**闸门必须测到玩家真正在用的那一份**：
// P2 的闸门 28–32 打的是这个组件，P3 的玩家用的也是这个组件 —— 如果 P3 另写一份手势接线，
// 闸门就变成了"测另一份代码"，那是最坏的一种假绿（见 docs/port-plan.md §4 的工具形态）。
//
// **唯一权威是 `MachineStore`**：所有输入（鼠标/触摸/键盘/取消）都归一化成状态机事件再进去，
// 3D 组件不直接改局面（§纪律 2：一个元素一个写者；plan P1 的退出条件也要求
// "3D Card 渲染组件不直接调用 ex.rd_env_step"，P1 里对应的是"不直接改 scene"）。
//
// ## 两种用法
//
// | 用法 | `mode` | 谁提供 host | 行为 |
// |---|---|---|---|
// | P1/P2 回归（`index.html`） | `"auto"` / `"mock"` | 组件自己装载并走到第一场战斗 | 与 P2 完全一致 |
// | P3 运行层（`run.html`） | `"wasm"` | 外层 `RunStore` 给 | 不自动装载、不自动走路，战斗结束由外层收尾 |

import { Canvas } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Hud } from "../hud/Hud";
import { initialScene, liveEnemySlots, type MockCard, type MockScene } from "../mock/scene";
import { viewFromMock, viewFromWasm, type CombatView } from "../view/combatView";
import { ChoiceModal } from "../overlay/ChoiceModal";
import { describeBeats } from "../view/beatText";
import type { PendingChoice } from "../wasm/snapshot";
import { WasmHost } from "../wasm/host";
import { GameStore } from "../wasm/store";
import { TextOverlay } from "../overlay/TextOverlay";
import { Stage } from "../stage/Stage";
import { layout } from "../stage/layout";
import { enemyAtScreen, cardAtScreen } from "../input/hitTest";
import { MachineStore } from "../store";
import type { DropOption } from "../input/pointerMachine";
import { installProbe } from "../probe";

/** 一张牌此刻的合法落点表（P2 换成真实 `rd_env_action_*`）。 */
export function optionsFor(card: MockCard, scene: MockScene, handSlot: number): DropOption[] {
  if (!card.targeted) {
    return [{ slot: -1, actionIndex: handSlot * 10, label: `打出 ${card.name}` }];
  }
  return liveEnemySlots(scene).map((slot) => ({
    slot,
    actionIndex: handSlot * 10 + slot + 1,
    label: `${card.name} → 敌人 ${slot}`,
  }));
}

/**
 * `?debug` 下的测试局面：`enemies=N`（1..6）与 `hand=N`（1..12）。
 *
 * ⚠️ 两个参数**各自独立**判断。第一版写成"先看 enemies，没有就 return"，而 hand 的处理在
 * 那个早退之后 —— 于是 `?debug&hand=12`（不带 enemies）永远执行不到（§4.19 的
 * "守卫装在切口下游"）。抽成纯函数也是为了能单测"URL 怎么解释"。
 *
 * 只在 `?debug` 存在时生效；正式路径不暴露造怪/造牌。
 */
export function debugScene(search: string): MockScene {
  const base = initialScene();
  const query = new URLSearchParams(search);
  if (!query.has("debug")) return base;

  let scene = base;
  const handRaw = query.get("hand");
  if (handRaw !== null) {
    const handCount = Number(handRaw);
    if (Number.isInteger(handCount) && handCount >= 1 && handCount <= 12) {
      scene = {
        ...scene,
        hand: Array.from({ length: handCount }, (_, i) => scene.hand[i % scene.hand.length]),
      };
    }
  }
  const enemyRaw = query.get("enemies");
  if (enemyRaw !== null) {
    const count = Number(enemyRaw);
    if (Number.isInteger(count) && count >= 1 && count <= 6) {
      scene = {
        ...scene,
        enemies: Array.from({ length: count }, (_, i) => ({
          ...scene.enemies[i % scene.enemies.length],
          slot: i,
          id: `debug_enemy_${i}`,
          name: `演示敌人 ${i + 1}`,
          hp: 25 + i * 4,
          maxHp: 25 + i * 4,
          intent: `攻击 ${6 + i}`,
        })),
      };
    }
  }
  return scene;
}

export interface CommitLogEntry {
  readonly handSlot: number;
  readonly actionIndex: number;
  readonly targetSlot: number;
  readonly card: string;
}

/** `?mock` ⇒ 确定局面（P1 的渲染/手势回归）；默认 ⇒ 真 wasm（P2 的数据源回归）。 */
const URL_SAYS_MOCK = new URLSearchParams(window.location.search).has("mock");

/**
 * 装载期间的**空局面**。
 *
 * ⚠️ 为什么不回退到 Mock：plan P2 要求"失配时显示诊断，不进入半可用状态"。第一版在
 * `wasmView === null` 时静默用 Mock，于是闸门 29 看到的是 10 张演示牌 + 72 血 —— 一副能拖能打
 * 却与内核毫无关系的牌。宁可空屏 + 状态条。
 */
const EMPTY_VIEW: CombatView = {
  mode: "wasm",
  hero: { name: "铁甲战士", hp: 0, hpMax: 0, block: 0, energy: 0, maxEnergy: 0 },
  enemies: [],
  hand: [],
  turn: 0,
  round: 0,
  result: "ongoing",
  epoch: -1,
  optionsFor: () => [],
  endTurnOption: () => null,
};

export interface CombatScreenProps {
  /**
   * `"auto"`：自己装载 wasm 并走到第一场战斗（P2 的回归行为，**不要改**）。
   * `"mock"`：确定局面（P1 的渲染/手势回归）。
   * `"wasm"`：由外层提供 `host` / `game`（P3 的运行层），本组件只负责这一场战斗。
   */
  readonly mode: "auto" | "mock" | "wasm";
  /** `mode === "wasm"` 时必须给：运行层的宿主（同一个 wasm 实例）。 */
  readonly host?: WasmHost;
  /** `mode === "wasm"` 时必须给：`RunStore` 持有的那个 `GameStore`。 */
  readonly game?: GameStore;
  /** `?mock` 的确定局面（P1 闸门用）；不给就是 `initialScene()`。 */
  readonly mockScene?: MockScene;
  /**
   * 战斗有结果之后玩家点"继续"时调用（P3 用它 `fight_end()` → 奖励屏）。
   *
   * ⚠️ 不给这个回调时**不显示**"继续"按钮：P2 的回归页没有下一屏，画一个死按钮
   * 就是 §4.22 那种"按类型点名的接口"。
   */
  readonly onFinish?: () => void;
}

export function CombatScreen(props: CombatScreenProps) {
  const store = useMemo(() => new MachineStore(), []);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  /** Mock 侧的局面。`mode === "mock"` 时由 URL 造（P1 的 `?debug&enemies=N`）。 */
  const MOCK_MODE = props.mode === "mock" || (props.mode === "auto" && URL_SAYS_MOCK);
  const [scene, setScene] = useState<MockScene>(() =>
    props.mockScene ?? debugScene(window.location.search)
  );
  /** 真 wasm 的宿主与商店；`null` = 还没装载好（或装载失败）。 */
  const [wasm, setWasm] = useState<{ host: WasmHost; game: GameStore } | null>(null);
  const [wasmError, setWasmError] = useState<string | null>(null);
  /** 待决选牌的问句（`rd_env_choice_*`）。`null` = 没有问句。 */
  const [choice, setChoice] = useState<PendingChoice | null>(null);
  /** 致命错误（ABI 违约 / 驱动损坏）：一旦设置就冻结操作并显示诊断。 */
  const [fatal, setFatal] = useState<string | null>(null);
  /** 上一次"确认"被拒的原因（内核 `-2`：数量不对）。 */
  const [choiceRefusal, setChoiceRefusal] = useState<string | null>(null);
  /** wasm 侧的视图；Mock 侧由 `scene` 派生。 */
  const [wasmView, setWasmView] = useState<CombatView | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [detailSlot, setDetailSlot] = useState(-1);
  // [P1-UX] Hover 仅为表现层状态，不影响游戏规则与 Action 列表。
  const [hoverCardSlot, setHoverCardSlot] = useState(-1);
  const [hoveredEnemySlot, setHoveredEnemySlot] = useState(-1);
  const [notice, setNotice] = useState("");
  const [noticeKind, setNoticeKind] = useState<"success" | "warning" | null>(null);
  const activePointer = useRef<{
    id: number; type: string; startX: number; startY: number;
    longPressTimer: number | null; handSlot: number;
  } | null>(null);
  const noticeTimer = useRef<number | null>(null);
  const flash = useCallback((message: string, kind: "success" | "warning" | null = null) => {
    setNotice(message);
    setNoticeKind(kind);
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => { setNotice(""); setNoticeKind(null); }, 850);
  }, []);
  /** 按下那一刻的动作表版本号（P1-B：松手时若变了，这次手势作废）。 */
  const pressEpoch = useRef(0);
  const commits = useRef<CommitLogEntry[]>([]);
  const rebounds = useRef<string[]>([]);

  const liftedSlot = state.phase === "idle" ? -1 : state.handSlot;

  // ── 视图：渲染层只认识 `CombatView`，不关心数据来自 Mock 还是 wasm ─────────
  const view: CombatView = useMemo(
    () => (MOCK_MODE ? viewFromMock(scene) : (wasmView ?? EMPTY_VIEW)),
    [scene, wasmView]
  );

  // 装载真 wasm：开局 → 走到战斗 → 建 store。失败就把诊断显示出来（**不进入半可用**）。
  useEffect(() => {
    if (MOCK_MODE) return;
    // P3：外层（`RunStore`）已经装好并走到了战斗，这里**不**再装载、不再走路。
    if (props.mode === "wasm") {
      if (!props.host || !props.game) {
        setWasmError("运行层没有给 host/game：这是接线错误，不是内核问题");
        return;
      }
      setWasm({ host: props.host, game: props.game });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const host = await WasmHost.load("./rd_wasm.wasm");
        if (cancelled) return;
        // 固定种子 + 固定的走路方式：同一个构建 ⇒ 同一场战斗（闸门要可复现）。
        host.startRun(1, 0);
        for (let hop = 0; hop < 40; hop += 1) {
          const raw = host.runRaw();
          if (raw.over === 1) break;
          if (raw.pending === 0) {
            if (raw.nodeKind >= 0 && raw.nodeResolved === 0) {
              const isFight = raw.nodeKind === 1 || raw.nodeKind === 2 || raw.nodeKind === 7;
              if (isFight) break;
              host.beginNode();
              continue;
            }
            if (host.runStep(0) !== 0) break;
            continue;
          }
          if (!host.settlePendingRun()) break;
        }
        if (host.fightBegin() !== 0) throw new Error("fight_begin 被拒绝");
        const game = new GameStore(host);
        if (cancelled) return;
        setWasm({ host, game });
        setWasmView(viewFromWasm(game.getSnapshot()!, host, game.epoch));
        setChoice(game.choice());
      } catch (error) {
        if (!cancelled) setWasmError(error instanceof Error ? error.message : String(error));
      }
    })();
    return () => {
      cancelled = true;
    };
    // `props.host` / `props.game` 在 P3 里是稳定的（由 RunStore 持有整个生命周期）。
  }, [props.mode, props.host, props.game, MOCK_MODE]);

  // 每次内核状态变化就重建视图（`dispatch` 之后 store 会通知）。
  useEffect(() => {
    if (!wasm) return;
    const rebuild = () => {
      const snapshot = wasm.game.getSnapshot();
      setWasmView(snapshot ? viewFromWasm(snapshot, wasm.host, wasm.game.epoch) : null);
      // 问句是**会话级**查询（不在 148 格里），与快照一起重读。
      setChoice(wasm.game.choice());
    };
    rebuild();
    return wasm.game.subscribe(rebuild);
  }, [wasm]);

  // ── 提交：Mock 侧结算，证明"拖动 → 权威动作"这条链是通的 ────────────────────
  const applyCommit = useCallback((entry: CommitLogEntry) => {
    // ⚠️ **不要**在这里 push 提交日志：effect 里统一记一次（两个引擎都走那条路）。
    // 第一版两边都 push ⇒ 每次出牌被记两次，闸门"恰好 1 次提交"立刻红。
    setScene((current) => {
      const card = current.hand[entry.handSlot];
      const hero = { ...current.hero };
      const enemies = current.enemies.map((enemy) => ({ ...enemy }));
      if (!card) return current;
      if (card.kind === "skill") hero.block += 5;
      if (card.kind === "power") hero.block += 0;
      if (card.targeted && entry.targetSlot >= 0) {
        const target = enemies.find((enemy) => enemy.slot === entry.targetSlot);
        if (target) target.hp = Math.max(0, target.hp - 6);
      }
      return { ...current, hero, enemies };
    });
  }, []);

  // [P1-UX] 相同卡牌 + 相同目标可以连续出两次：必须按事件序号而非 JSON 载荷去重。
  const lastResultSeq = useRef(0);
  useEffect(() => {
    const result = state.lastResult;
    if (!result) return;
    if (state.resultSeq === lastResultSeq.current) return;
    lastResultSeq.current = state.resultSeq;
    if (result.kind === "commit") {
      const card = view.hand[result.handSlot];
      if (MOCK_MODE || !wasm) {
        applyCommit({
          handSlot: result.handSlot,
          actionIndex: result.actionIndex,
          targetSlot: result.targetSlot,
          card: card ? card.id : "?",
        });
        flash("已出牌 · 动作已提交", "success");
      } else {
        // 真 wasm：动作表里的 `actionIndex` 就是 `rd_env_step` 的入参，**不要**自己再映射一层。
        //
        // ⚠️ `actionIndex` 是**数字位置**，不是身份：按住期间若动作表整体换了一份，同一个
        // `index` 可能是另一张牌 / 另一个敌人。所以先比版本号，再比四元组（P1-B）。
        // ⚠️ `targetSlot` 只对**定向牌**比：无目标牌的动作被内核过度指定了敌人槽
        // （防御的每条动作 targetSlot 是 0/1），而状态机的业务目标是 -1 —— 拿 -1 去比
        // 永远匹配不上，会把每一次正常出牌都判成"过期"（第一版就是这么红的）。
        const targetedCard = view.hand[result.handSlot]?.targeted ?? false;
        const stale =
          wasm.game.epoch !== pressEpoch.current ||
          !wasm.game.actions().some(
            (candidate) =>
              candidate.index === result.actionIndex &&
              candidate.kind === "play" &&
              candidate.handSlot === result.handSlot &&
              (!targetedCard || candidate.targetSlot === result.targetSlot)
          );
        const action = stale
          ? null
          : (wasm.game.actions().find((candidate) => candidate.index === result.actionIndex) ?? null);
        if (!action) {
          // 内核没给这条动作（或动作表已换版）⇒ 不是"玩家操作非法"，是"这次手势过期了"。
          flash("动作表已变化 · 这次操作取消", "warning");
        } else {
          const outcome = wasm.game.dispatch(action);
          if (outcome.accepted) {
            // 演出文案来自内核的 beat（不再靠观察向量 diff 猜"发生了什么"）。
            const line = describeBeats(outcome.beats, outcome.beatsDropped);
            flash(line || "已出牌", "success");
          } else if (GameStore.isContractViolation(outcome)) {
            // ⚠️ 拒绝却改了观察向量 = **ABI 违约**，不是玩家操作非法。
            // 响亮失败并冻结操作，绝不显示"状态未改变"（第十四轮 Review P1-D）。
            setFatal(
              `ABI 违约：内核拒绝了这一步（code ${outcome.code}）却改变了观察向量。
` +
                "界面已冻结，避免继续在半可信状态下操作。"
            );
          } else if (GameStore.isBroken(outcome)) {
            setFatal(`内核驱动坏了（code ${outcome.code}）：这不是玩家操作问题。`);
          } else if (outcome.code === -2) {
            // `-2` = 战斗已结束（不是"被拒绝"）。
            flash("战斗已经结束", "warning");
          } else {
            flash("动作被拒绝（状态未改变）", "warning");
          }
        }
      }
      commits.current.push({
        handSlot: result.handSlot,
        actionIndex: result.actionIndex,
        targetSlot: result.targetSlot,
        card: card ? card.id : "?",
      });
      setDetailSlot(-1);
    } else {
      rebounds.current.push(result.why);
      flash("已取消 · 卡牌返回手牌", "warning");
    }
  }, [state.lastResult, state.resultSeq, view.hand, applyCommit, flash, wasm]);

  // ── 输入接线：全部走同一个状态机 ────────────────────────────────────────────
  const onCardDown = useCallback(
    (slot: number, pointer: { id: number; type: string; x: number; y: number }) => {
      if (modalOpen || fatal) return;
      if (activePointer.current) return; // [P1-UX] 第一指针独占，第二根手指不可偷走当前牌。
      const card = view.hand[slot];
      if (!card) return;
      setDetailSlot(-1);
      setHoverCardSlot(-1);
      const gesture = {
        id: pointer.id, type: pointer.type, startX: pointer.x, startY: pointer.y,
        longPressTimer: null as number | null, handSlot: slot,
      };
      activePointer.current = gesture;
      // ⚠️ 落点表来自**视图**（wasm 那边就是内核动作表），UI 不自己推"能不能打这个敌人"。
      // 同时冻结动作表版本号：松手前若另一条路径改了状态，这次手势必须作废（P1-B）。
      pressEpoch.current = wasm?.game.epoch ?? 0;
      store.send({ type: "down", handSlot: slot, options: view.optionsFor(slot) });
      if (pointer.type === "touch" || pointer.type === "pen") {
        // [P1-UX] 450ms 长按展示详情；移动超过拖拽阈值即取消定时器。
        // detail 与 commit 互斥：先 dismiss 状态机，再展示详情，松手不会误出牌。
        gesture.longPressTimer = window.setTimeout(() => {
          if (activePointer.current !== gesture) return;
          activePointer.current = null;
          store.send({ type: "dismiss" });
          setDetailSlot(slot);
          flash("卡牌详情 · 点击关闭按钮或按 Esc");
        }, 450);
      }
    },
    [modalOpen, fatal, view, store, flash]
  );

  // [P1-UX] 全局指针跟踪：即使松开时已经离开 WebGL mesh，动作仍能完成或被正确取消。
  useEffect(() => {
    const clearPointer = () => {
      const p = activePointer.current;
      if (p?.longPressTimer !== null && p?.longPressTimer !== undefined)
        window.clearTimeout(p.longPressTimer);
      activePointer.current = null;
    };
    // [P1-UX] 命中范围由 Stage 的屏幕投影提供；不要复制三维队形公式。
    const legalSlots = () =>
      new Set(store.peek().options.filter((o) => o.slot >= 0).map((o) => o.slot));
    const allEnemySlots = () => new Set(layout.enemies.map((e) => e.slot));
    /** 指针下的敌人（**任意**敌人，视觉用）。 */
    const underPointer = (x: number, y: number) => enemyAtScreen(layout.enemies, x, y, allEnemySlots());
    /** 指针下是否是**合法目标**（提交与绿环用）。 */
    const currentTarget = (x: number, y: number) => enemyAtScreen(layout.enemies, x, y, legalSlots());

    const onMove = (event: PointerEvent) => {
      if (modalOpen) return;
      // ⚠️ 常驻（不再只在按住时跑）：hover 高亮也走**同一个**屏幕命中函数。
      // 以前 hover 来自 R3F 的射线、提交来自 hitTest，两者几何不同 ⇒ 边缘自相矛盾。
      setHoveredEnemySlot(underPointer(event.clientX, event.clientY));
      setHoverCardSlot(cardAtScreen(layout.cards, event.clientX, event.clientY));

      const p = activePointer.current;
      if (p && p.id !== event.pointerId) return; // 第二根手指不改变第一根的目标
      const distance = p
        ? Math.hypot(event.clientX - p.startX, event.clientY - p.startY)
        : 999; // 没有按住时"位移"无意义；只有 target 生效（点选后再点敌人）
      if (p && distance >= 8 && p.longPressTimer !== null) {
        window.clearTimeout(p.longPressTimer);
        p.longPressTimer = null;
      }
      if (store.peek().phase === "idle") return;
      store.send({
        type: "move",
        hoverSlot: currentTarget(event.clientX, event.clientY),
        distance,
      });
    };
    const onUp = (event: PointerEvent) => {
      if (modalOpen) return;
      const p = activePointer.current;
      if (p && p.id !== event.pointerId) return;
      if (p) clearPointer();
      const current = store.peek();
      if (current.phase === "idle") return; // 长按详情已经 dismiss，不得在松手时出牌。
      const target = currentTarget(event.clientX, event.clientY);
      const distance = p ? Math.hypot(event.clientX - p.startX, event.clientY - p.startY) : 999;
      // [P1-UX] 极快拖动可能没有中间 move 事件，抬起前补一次真实距离判定。
      if (current.phase === "pressed" && distance >= 8)
        store.send({ type: "move", hoverSlot: target, distance });
      store.send({ type: "up", hoverSlot: target, distance });
    };
    const cancel = () => {
      clearPointer();
      setHoveredEnemySlot(-1);
      if (store.peek().phase !== "idle") store.send({ type: "cancel" });
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        // ⚠️ 有问句时 Esc 什么都不做：动作表此时为空，关掉弹窗等于把玩家扔进"点不动"的界面。
        if (choice) return;
        if (modalOpen) setModalOpen(false);
        else if (detailSlot >= 0) setDetailSlot(-1);
        else cancel();
      }
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerup", onUp);
    // 第二指针取消不能把第一指针的卡牌操作误撤销。
    const onCancel = (event: PointerEvent) => {
      if (activePointer.current && event.pointerId !== activePointer.current.id) return;
      cancel();
    };
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("blur", cancel);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("blur", cancel);
      window.removeEventListener("keydown", onKey);
    };
  }, [store, modalOpen, detailSlot]);
  useEffect(() => () => {
    if (activePointer.current?.longPressTimer != null) window.clearTimeout(activePointer.current.longPressTimer);
    if (noticeTimer.current !== null) window.clearTimeout(noticeTimer.current);
  }, []);

  // ── 待决选牌：勾选 / 清空 / 确认 ─────────────────────────────────────────
  const onChoicePick = useCallback(
    (index: number, on: boolean) => {
      if (!wasm) return;
      wasm.game.pickChoice(index, on);
      setChoice(wasm.game.choice());
      setChoiceRefusal(null);
    },
    [wasm]
  );

  const onChoiceClear = useCallback(() => {
    if (!wasm) return;
    wasm.game.clearChoice();
    setChoice(wasm.game.choice());
    setChoiceRefusal(null);
  }, [wasm]);

  const onChoiceConfirm = useCallback(() => {
    if (!wasm) return;
    const outcome = wasm.game.confirmChoice();
    if (outcome.accepted) {
      setChoiceRefusal(null);
      setChoice(wasm.game.choice());
      flash("已确认选择", "success");
    } else if (outcome.code === -2) {
      // `-2` = 数量不对被拒（问句还在，选中的牌也还在）⇒ 让玩家继续勾，不要静默。
      setChoiceRefusal("数量不对：请按上面要求的张数选择");
    } else {
      setChoiceRefusal("内核拒绝了这次确认");
    }
  }, [wasm, flash]);

  // 点开详情：双击抬起（P1 的第三档可读性）
  const onDetail = useCallback(
    (slot: number) => {
      if (modalOpen) return;
      setDetailSlot((current) => (current === slot ? -1 : slot));
    },
    [modalOpen]
  );

  // ── 探针：闸门读这里（不读 DOM 内部结构，只读语义）──────────────────────────
  useEffect(() => {
    installProbe({
      store,
      layout,
      scene: () => scene,
      view: () => view,
      mode: () => (MOCK_MODE ? "mock" : "wasm"),
      wasmDiagnostics: () => (wasm ? wasm.host.diagnostics : null),
      wasmError: () => wasmError,
      endTurn: () => {
        if (MOCK_MODE || !wasm) {
          setScene((current) => ({ ...current, turn: current.turn + 1 }));
          return { accepted: true, code: 0 };
        }
        const option = wasm.game.findEndTurn();
        if (!option) return { accepted: false, code: null };
        const outcome = wasm.game.dispatch(option);
        return { accepted: outcome.accepted, code: outcome.code };
      },
      commits: () => commits.current,
      rebounds: () => rebounds.current,
      detailSlot: () => detailSlot,
      modalOpen: () => modalOpen,
      choice: () => choice,
      choicePick: onChoicePick,
      choiceConfirm: onChoiceConfirm,
      choiceClear: onChoiceClear,
      hoveredCard: () => hoverCardSlot,
      hoveredEnemy: () => hoveredEnemySlot,
      openDetail: onDetail,
      setModal: (open: boolean) => setModalOpen(open),
      // `?debug` 才装（闸门要造"只剩一个敌人"的局面）。生产路径没有这个钩子。
      debugSetEnemyHp: window.location.search.includes("debug")
        ? (slot: number, hp: number) => {
            setScene((current) => ({
              ...current,
              enemies: current.enemies.map((enemy) =>
                enemy.slot === slot ? { ...enemy, hp } : enemy
              ),
            }));
          }
        : undefined,
    });
  }, [store, scene, view, wasm, wasmError, detailSlot, modalOpen, hoverCardSlot, hoveredEnemySlot,
      onDetail, choice, onChoicePick, onChoiceConfirm, onChoiceClear]);

  return (
    // `data-scene="SC-03b"`：闸门 34 用它断言"画出来的那一屏 == 算出来的那一屏"。
    // 战斗屏是唯一一个**不**由 `run/scenes/*` 画的场景（3D 那套在 P1/P2 已经建好），
    // 所以这个标记必须由它自己打。
    <div className="app" data-scene="SC-03b">
      <Canvas
        className="stage"
        shadows={false}
        dpr={[1, 2]}
        camera={{ position: [0, 0.6, 6], fov: 45, near: 0.1, far: 80 }}
        onCreated={({ camera }) => camera.lookAt(0, 0.1, 0)}
        // [P1-UX] 桌面右键详情，使用命中布局投影，避免 DOM 覆盖层拦截 3D 射线。
        onContextMenu={(event) => {
          event.preventDefault();
          const slot = cardAtScreen(layout.cards, event.clientX, event.clientY);
          if (slot >= 0 && !modalOpen) {
            store.send({ type: "dismiss" });
            onDetail(slot);
          }
        }}
        style={{ cursor: activePointer.current ? "grabbing" : hoverCardSlot >= 0 ? "grab" : "default" }}
      >
        <Stage
          scene={view}
          liftedSlot={liftedSlot}
          hoverSlot={state.hoverSlot}
          hoverCardSlot={hoverCardSlot}
          hoveredEnemySlot={hoveredEnemySlot}
          phase={state.phase}
          followPointer={activePointer.current !== null && state.phase !== "idle"}
          legalTargets={state.options.filter((o) => o.slot >= 0).map((o) => o.slot)}
          onCardDown={onCardDown}
        />
        <Hud
          hp={view.hero.hp}
          maxHp={view.hero.hpMax}
          block={view.hero.block}
          energy={view.hero.energy}
          maxEnergy={view.hero.maxEnergy}
          turn={view.turn}
          phase={state.phase}
          onEndTurn={() => {
            if (MOCK_MODE || !wasm) {
              setScene((current) => ({ ...current, turn: current.turn + 1 }));
              return;
            }
            const option = wasm.game.findEndTurn();
            if (option) wasm.game.dispatch(option);
          }}
          onOpenModal={() => setModalOpen(true)}
        />
      </Canvas>

      {/* 致命错误（ABI 违约 / 驱动损坏）：冻结操作并显示诊断，**不进半可用**。 */}
      {fatal && (
        <div className="wasm-status" data-fatal>
          {fatal}
        </div>
      )}

      {/* 装载中 / 装载失败：显示诊断，**不进半可用**。 */}
      {!MOCK_MODE && !wasmView && (
        <div className="wasm-status" data-wasm-status>
          {wasmError ? `内核装载失败：${wasmError}` : "正在装载内核…"}
        </div>
      )}

      {/*
        战斗有结果：**只有**外层给了 `onFinish` 才画"继续"（P2 回归页没有下一屏）。
        文案来自内核的 `result` 判别值，不是"我猜打赢了"。
      */}
      {view.result !== "ongoing" && props.onFinish && (
        <div className="combat-finished" data-combat-finished={view.result}>
          <h2>{view.result === "victory" ? "战斗胜利" : view.result === "defeat" ? "战败" : "战斗结束"}</h2>
          <p className="combat-finished-hint">
            {view.result === "victory" ? "敌人已被击败。" : "这一局到此为止。"}
          </p>
          <button type="button" data-combat-continue onClick={() => props.onFinish?.()}>
            {view.result === "victory" ? "领取奖励" : "结束这一局"}
          </button>
        </div>
      )}

      <TextOverlay scene={view} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}
        detailSlot={detailSlot} modalOpen={modalOpen} onCloseDetail={() => setDetailSlot(-1)} />
      {/* [P1-UX] 文本反馈与颜色高亮并行：色弱/触屏用户也能理解当前目标状态。 */}
      {!modalOpen && view.result === "ongoing" && (
        <div className={`gesture-hint${noticeKind ? ` is-${noticeKind}` : ""}`} role="status" aria-live="polite">
          {notice || (detailSlot >= 0 ? "卡牌详情 · 点击关闭按钮或按 Esc" :
            state.phase === "targeting" && hoveredEnemySlot >= 0 &&
              !state.options.some((o) => o.slot === hoveredEnemySlot) ?
              "红圈表示无效目标 · 选择蓝圈敌人" :
            state.phase === "targeting" ? "选择右侧高亮敌人 · 拖动或点按 · Esc 取消" :
            state.phase === "dragging" ? "松开使用卡牌 · 移到空白可撤销目标" :
            state.phase === "pressed" ? "拖动出牌 · 触屏长按看详情" :
            hoverCardSlot >= 0 ? "左键选牌或拖动 · 右键查看详情" :
            "左侧为我方，右侧为敌人 · 点击或拖动手牌")}
        </div>
      )}

      {choice && !modalOpen && (
        <ChoiceModal
          choice={choice}
          onPick={onChoicePick}
          onConfirm={onChoiceConfirm}
          onClear={onChoiceClear}
          refusal={choiceRefusal}
        />
      )}

      {modalOpen && (
        <div className="modal-backdrop" data-modal onClick={() => setModalOpen(false)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h2>设置</h2>
            <p>模态打开时，拖牌与目标高亮都被隔离（点空白处关闭）。</p>
            <button type="button" data-modal-close onClick={() => setModalOpen(false)}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

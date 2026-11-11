// 应用外壳：Canvas + HUD + DOM 覆盖层 + 模态。
//
// **唯一权威是 `MachineStore`**：所有输入（鼠标/触摸/键盘/取消）都归一化成状态机事件再进去，
// 3D 组件不直接改局面（§纪律 2：一个元素一个写者；plan P1 的退出条件也要求
// "3D Card 渲染组件不直接调用 ex.rd_env_step"，P1 里对应的是"不直接改 scene"）。

import { Canvas } from "@react-three/fiber";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Hud } from "./hud/Hud";
import { initialScene, liveEnemySlots, type MockCard, type MockScene } from "./mock/scene";
import { TextOverlay } from "./overlay/TextOverlay";
import { Stage } from "./stage/Stage";
import { layout } from "./stage/layout";
import { enemyAtScreen, cardAtScreen } from "./input/hitTest";
import { MachineStore } from "./store";
import type { DropOption } from "./input/pointerMachine";
import { installProbe } from "./probe";

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

export function App() {
  const store = useMemo(() => new MachineStore(), []);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [scene, setScene] = useState<MockScene>(() => debugScene(window.location.search));
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
  const commits = useRef<CommitLogEntry[]>([]);
  const rebounds = useRef<string[]>([]);

  const liftedSlot = state.phase === "idle" ? -1 : state.handSlot;

  // ── 提交：Mock 侧结算，证明"拖动 → 权威动作"这条链是通的 ────────────────────
  const applyCommit = useCallback((entry: CommitLogEntry) => {
    commits.current.push(entry);
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
      const card = scene.hand[result.handSlot];
      applyCommit({
        handSlot: result.handSlot,
        actionIndex: result.actionIndex,
        targetSlot: result.targetSlot,
        card: card ? card.id : "?",
      });
      setDetailSlot(-1);
      flash("已出牌 · 动作已提交", "success");
    } else {
      rebounds.current.push(result.why);
      flash("已取消 · 卡牌返回手牌", "warning");
    }
  }, [state.lastResult, state.resultSeq, scene.hand, applyCommit, flash]);

  // ── 输入接线：全部走同一个状态机 ────────────────────────────────────────────
  const onCardDown = useCallback(
    (slot: number, pointer: { id: number; type: string; x: number; y: number }) => {
      if (modalOpen) return;
      if (activePointer.current) return; // [P1-UX] 第一指针独占，第二根手指不可偷走当前牌。
      const card = scene.hand[slot];
      if (!card) return;
      setDetailSlot(-1);
      setHoverCardSlot(-1);
      const gesture = {
        id: pointer.id, type: pointer.type, startX: pointer.x, startY: pointer.y,
        longPressTimer: null as number | null, handSlot: slot,
      };
      activePointer.current = gesture;
      store.send({ type: "down", handSlot: slot, options: optionsFor(card, scene, slot) });
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
    [modalOpen, scene, store, flash]
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
      commits: () => commits.current,
      rebounds: () => rebounds.current,
      detailSlot: () => detailSlot,
      modalOpen: () => modalOpen,
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
  }, [store, scene, detailSlot, modalOpen, hoverCardSlot, hoveredEnemySlot, onDetail]);

  return (
    <div className="app">
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
          scene={scene}
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
          hp={scene.hero.hp}
          maxHp={scene.hero.maxHp}
          block={scene.hero.block}
          energy={scene.hero.energy}
          maxEnergy={scene.hero.maxEnergy}
          turn={scene.turn}
          phase={state.phase}
          onEndTurn={() => {
            setScene((current) => ({ ...current, turn: current.turn + 1 }));
          }}
          onOpenModal={() => setModalOpen(true)}
        />
      </Canvas>

      <TextOverlay scene={scene} liftedSlot={liftedSlot} hoverCardSlot={hoverCardSlot}
        detailSlot={detailSlot} modalOpen={modalOpen} onCloseDetail={() => setDetailSlot(-1)} />
      {/* [P1-UX] 文本反馈与颜色高亮并行：色弱/触屏用户也能理解当前目标状态。 */}
      {!modalOpen && (
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

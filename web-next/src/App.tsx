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

export interface CommitLogEntry {
  readonly handSlot: number;
  readonly actionIndex: number;
  readonly targetSlot: number;
  readonly card: string;
}

export function App() {
  const store = useMemo(() => new MachineStore(), []);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const [scene, setScene] = useState<MockScene>(() => initialScene());
  const [modalOpen, setModalOpen] = useState(false);
  const [detailSlot, setDetailSlot] = useState(-1);
  const commits = useRef<CommitLogEntry[]>([]);
  const rebounds = useRef<string[]>([]);
  // 上一帧的 hover 槽位：`pointerup` 落空时用它兜底（R3F 的 onPointerUp 只对命中的对象触发）。
  const hoverRef = useRef(-1);

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

  // 状态机 → 副作用（提交/回弹）。按**事件序号**去重，不按内容去重：
  // 同一张牌打同一个敌人的两次操作 payload 完全相同，用 JSON 当身份会把第二次吞掉（§352 P1-A）。
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
    } else {
      rebounds.current.push(result.why);
    }
  }, [state.lastResult, state.resultSeq, scene.hand, applyCommit]);

  // ── 输入接线：全部走同一个状态机 ────────────────────────────────────────────
  const onCardDown = useCallback(
    (slot: number) => {
      if (modalOpen) return; // 模态打开 ⇒ 输入隔离（闸门 25 会证明它）
      const card = scene.hand[slot];
      if (!card) return;
      store.send({ type: "down", handSlot: slot, options: optionsFor(card, scene, slot) });
    },
    [modalOpen, scene, store]
  );

  const onHover = useCallback(
    (slot: number) => {
      if (modalOpen) return;
      hoverRef.current = slot;
      const current = store.peek();
      if (current.phase === "idle") return;
      store.send({ type: "move", hoverSlot: slot, distance: 999 });
    },
    [modalOpen, store]
  );

  const onRelease = useCallback(
    (slot: number) => {
      if (modalOpen) return;
      const current = store.peek();
      if (current.phase === "idle") return;
      store.send({ type: "up", hoverSlot: slot, distance: 999 });
    },
    [modalOpen, store]
  );

  // 点按语义：抬起在空白处（R3F 没给我们 onPointerUp）时，用上一次 hover 兜底。
  useEffect(() => {
    const onUp = () => {
      const current = store.peek();
      if (current.phase === "pressed") {
        store.send({ type: "up", hoverSlot: -1, distance: 0 });
      } else if (current.phase === "targeting" || current.phase === "dragging") {
        store.send({ type: "up", hoverSlot: hoverRef.current, distance: 999 });
      }
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (modalOpen) setModalOpen(false);
        else store.send({ type: "cancel" });
      }
    };
    window.addEventListener("pointerup", onUp);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("keydown", onKey);
    };
  }, [store, modalOpen]);

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
  }, [store, scene, detailSlot, modalOpen, onDetail]);

  return (
    <div className="app">
      <Canvas
        className="stage"
        shadows={false}
        dpr={[1, 2]}
        camera={{ position: [0, 0.6, 6], fov: 45, near: 0.1, far: 80 }}
        onCreated={({ camera }) => camera.lookAt(0, 0.1, 0)}
      >
        <Stage
          scene={scene}
          liftedSlot={liftedSlot}
          hoverSlot={state.hoverSlot}
          onCardDown={onCardDown}
          onHover={onHover}
          onRelease={onRelease}
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

      <TextOverlay scene={scene} liftedSlot={liftedSlot} detailSlot={detailSlot} modalOpen={modalOpen} />

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

// 运行层外壳（`run.html`，P3）：**场景路由** + 常驻顶栏 + 对账横幅 + 事件日志。
//
// ## 场景怎么切换（这是 P3 的核心设计）
//
// 没有任何 `mode` 变量。每一帧都是：
//
//   内核导出 → `RunStore.refresh()` → `resolveScene(事实)` → 画那一屏
//
// 所以"刷新页面回到地图"、"战斗结束后没刷新"这类 bug 在结构上不存在 —— 屏幕是**算出来的**。
// 玩家动作只会做一件事：调一个权威 API（`enter_node` / `fight_begin` / `take_card` …），
// 然后重算。UI 从不"顺手把状态也改一下"。
//
// ## 顶栏为什么常驻
//
// 战斗内外 HP 的来源不同（战斗里读 148 格向量，外面读运行层观察向量），但对账要求它们**相等**
// （`RunStore.reconcile`）。顶栏永远显示运行层那一份 —— 这样"战斗里回血了但顶栏没动"会当场
// 变成一条对账失败，而不是等玩家截图对比才发现。
//
// ## 对账横幅
//
// `violations` 非空 ⇒ 界面顶部一条红条 + 冻结推进按钮。这是 ABI 违约，不是"显示小错"。

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { CombatScreen } from "../combat/CombatScreen";
import { displayName } from "../i18n/index.js";
import { WasmHost } from "../wasm/host";
import { nodeKindLabel } from "./observe.js";
import { RunStore } from "./RunStore";
import { isImplemented, sceneLabel, SCENE } from "./scene.js";
import { BlessingScene } from "./scenes/BlessingScene";
import { EndScene } from "./scenes/EndScene";
import { MapScene } from "./scenes/MapScene";
import { PreCombatScene } from "./scenes/PreCombatScene";
import { RewardScene } from "./scenes/RewardScene";
import { TitleScene } from "./scenes/TitleScene";
import { UnsupportedScene } from "./scenes/UnsupportedScene";
import { installRunProbe } from "./runProbe";
import "./run.css";

export function RunApp() {
  const [store, setStore] = useState<RunStore | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDeck, setShowDeck] = useState(false);
  /** 上一次用的种子/进阶（局终"再来一局"回填）。 */
  const [last, setLast] = useState<{ seed: number; ascension: number }>({ seed: 1, ascension: 0 });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const host = await WasmHost.load("./rd_wasm.wasm");
        if (cancelled) return;
        setStore(new RunStore(host));
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // `RunStore` 的两个读取函数是箭头字段（引用稳定），可以直接喂给 `useSyncExternalStore`。
  const state = useSyncExternalStore(
    store?.subscribe ?? (() => () => {}),
    store?.getState ?? (() => null),
    store?.getState ?? (() => null)
  );

  // 探针：闸门 34 读这里（语义，不是 DOM 内部结构）。
  useEffect(() => {
    if (!store) return;
    installRunProbe(store);
  }, [store]);

  const blocked = state?.violations.length ? true : false;

  const onEnter = useCallback(
    (index: number) => {
      if (!store || blocked) return;
      store.enterNode(index);
    },
    [store, blocked]
  );

  const onBlocked = useCallback(
    (index: number) => {
      if (!store) return;
      store.note(`第 ${index} 号节点这一步到不了：只能沿着连线往上走`, "warn");
      store.refresh();
    },
    [store]
  );

  const deckGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const id of state?.deck ?? []) counts.set(id, (counts.get(id) ?? 0) + 1);
    return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [state?.deck]);

  if (error) {
    return (
      <div className="run-shell">
        <div className="run-status" data-run-error>
          内核装载失败：{error}
        </div>
      </div>
    );
  }

  if (!store || !state) {
    return (
      <div className="run-shell">
        <div className="run-status" data-run-status>
          正在装载内核…
        </div>
      </div>
    );
  }

  const { run, map, scene } = state;
  const base = scene.base;

  return (
    <div className="run-shell" data-scene-base={base} data-scene-overlays={scene.overlays.join(",")}>
      {/* ── 常驻顶栏：HP / 金币 / 层数 / 牌组 / 遗物 / 药水 ─────────────────── */}
      <header className="run-topbar">
        <div className="run-hp" data-run-hp={run ? `${run.health}/${run.healthMax}` : ""}>
          <span className="run-hp-bar">
            <span
              className="run-hp-fill"
              style={{ width: run ? `${Math.max(0, Math.min(100, (run.health / Math.max(1, run.healthMax)) * 100))}%` : "0%" }}
            />
          </span>
          <span className="run-hp-text">
            {run ? `${run.health}/${run.healthMax}` : "—"}
          </span>
        </div>
        <div className="run-stat" data-run-gold={run?.gold ?? 0}>
          ◈ {run?.gold ?? 0}
        </div>
        <div className="run-stat" data-run-floor={run?.floor ?? 0}>
          第 {run?.floor ?? 0} 层
        </div>
        <button
          type="button"
          className="run-stat run-deck-button"
          data-deck-open
          onClick={() => setShowDeck(true)}
          disabled={!run}
        >
          牌组 {run?.deckSize ?? 0}
        </button>
        <div className="run-stat" data-run-relics={run?.relicCount ?? 0} title={(state.relics ?? []).join("、")}>
          ✦ {run?.relicCount ?? 0}
        </div>
        <div className="run-stat" data-run-potions={run?.potionCount ?? 0} title={(state.potions ?? []).map((id) => displayName("potions", id)).join("、")}>
          ⚗ {run?.potionCount ?? 0}
        </div>
        <div className="run-scene-label" data-scene-label={base}>
          {sceneLabel(base)}
          {scene.overlays.length > 0 && ` + ${scene.overlays.map(sceneLabel).join(" + ")}`}
        </div>
      </header>

      {/* ── 对账失败：**响亮**失败，并冻结推进 ─────────────────────────────── */}
      {blocked && (
        <div className="run-violation" data-run-violation>
          <b>对账失败（界面已冻结）</b>
          <ul>
            {state.violations.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ── 场景 ─────────────────────────────────────────────────────────── */}
      <main className="run-main" key={`${base}-${scene.overlays.join(",")}`}>
        {base === SCENE.title && (
          <TitleScene
            onStart={(seed, ascension) => {
              setLast({ seed, ascension });
              store.startRun(seed, ascension);
            }}
            lastSeed={last.seed}
            lastAscension={last.ascension}
          />
        )}

        {base === SCENE.blessing && (
          <BlessingScene blessings={state.blessings} onChoose={(slot) => store.chooseBlessing(slot)} />
        )}

        {base === SCENE.map && map && run && (
          <MapScene
            run={run}
            map={map}
            inert={blocked || scene.overlays.length > 0}
            onEnter={onEnter}
            onBlocked={onBlocked}
          />
        )}

        {base === SCENE.preCombat && run && (
          <PreCombatScene
            encounter={state.encounter}
            kind={run.node >= 0 && map ? (map.byIndex.get(run.node)?.kind ?? 0) : 0}
            kindLabel={
              run.node >= 0 && map ? nodeKindLabel(map.byIndex.get(run.node)?.kind ?? 0) : "战斗"
            }
            floor={run.floor}
            heroHp={run.health}
            heroHpMax={run.healthMax}
            ascension={state.ascension}
            busy={blocked}
            onBegin={() => store.fightBegin()}
          />
        )}

        {base === SCENE.combat && store.combat && (
          <CombatScreen
            mode="wasm"
            host={store.hostForCombat}
            game={store.combat}
            onFinish={() => store.fightEnd()}
          />
        )}

        {base === SCENE.reward && run && (
          <RewardScene
            gold={state.reward.gold}
            cards={state.reward.cards}
            potion={state.reward.potion}
            relic={state.reward.relic}
            deckSize={run.deckSize}
            onTakeCard={(slot) => store.takeRewardCard(slot)}
            onTakePotion={() => store.takeRewardPotion()}
            onTakeRelic={() => store.takeRewardRelic()}
            onSkip={() => store.skipReward()}
          />
        )}

        {(base === SCENE.over || base === SCENE.actCleared || base === SCENE.actEnd) && run && (
          <EndScene
            kind={base === SCENE.over ? "over" : "actCleared"}
            run={run}
            overWhy={state.overWhy}
            ascension={state.ascension}
            onRestart={() => {
              store.startRun(last.seed, last.ascension);
            }}
            onContinue={base === SCENE.actCleared ? () => store.settleDefault() : undefined}
          />
        )}

        {!isImplemented(base) && base !== SCENE.blessing && (
          <UnsupportedScene
            scene={base}
            label={sceneLabel(base)}
            pending={state.pending}
            onSettle={() => store.settleDefault()}
          />
        )}

        {base === SCENE.blessingCard && (
          <UnsupportedScene
            scene={base}
            label={sceneLabel(base)}
            pending={state.pending}
            onSettle={() => store.settleDefault()}
          />
        )}
      </main>

      {/* ── 覆盖层（`SC-11a`/`SC-11b`：遗物欠账）─────────────────────────── */}
      {scene.overlays.length > 0 && (
        <div className="run-overlay" data-run-overlay={scene.overlays.join(",")}>
          <div className="run-overlay-card">
            <h3>{scene.overlays.map(sceneLabel).join(" / ")}</h3>
            <p className="muted">遗物要求你改牌/加牌 —— 牌组选择器在 P4。</p>
            <button type="button" className="primary" data-overlay-settle onClick={() => store.settleDefault()}>
              用内核的默认动作通过
            </button>
          </div>
        </div>
      )}

      {/* ── 日志：最近 3 条 ──────────────────────────────────────────────── */}
      <footer className="run-log" data-run-log={state.log.length}>
        {state.log.slice(-3).map((entry) => (
          <div key={entry.seq} className={`run-log-line is-${entry.kind}`} data-log-kind={entry.kind}>
            {entry.text}
          </div>
        ))}
      </footer>

      {/* ── 牌组弹窗 ────────────────────────────────────────────────────── */}
      {showDeck && (
        <div className="run-overlay" data-deck-overlay onClick={() => setShowDeck(false)}>
          <div className="run-overlay-card run-deck" onClick={(event) => event.stopPropagation()}>
            <h3>牌组 · {state.deck.length} 张</h3>
            <ul className="run-deck-list">
              {deckGroups.map(([id, count]) => (
                <li key={id} data-deck-card={id}>
                  <span>{displayName("cards", id)}</span>
                  <span className="muted"> ×{count}</span>
                </li>
              ))}
            </ul>
            <button type="button" data-deck-close onClick={() => setShowDeck(false)}>
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

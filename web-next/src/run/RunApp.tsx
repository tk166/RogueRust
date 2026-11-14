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
import { Badge } from "../assets/Badge.js";
import { badgeLook } from "../assets/registry.js";
import { displayName } from "../i18n/index.js";
import { WasmHost } from "../wasm/host";
import { beltHasRoom, campfireOptionsFromMask, unknownCampfireBits, shelfRows, type DeckPickPurpose } from "./models.js";
import { BOSS_SENTINEL, nodeKindLabel } from "./observe.js";
import { RunStore } from "./RunStore";
import { endSceneFor, isImplemented, sceneLabel, SCENE } from "./scene.js";
import { BlessingScene } from "./scenes/BlessingScene";
import { BossRelicScene } from "./scenes/BossRelicScene";
import { ChestScene } from "./scenes/ChestScene";
import { EndScene } from "./scenes/EndScene";
import { EventOfferScene } from "./scenes/EventOfferScene";
import { EventScene } from "./scenes/EventScene";
import { MapScene } from "./scenes/MapScene";
import { PreCombatScene } from "./scenes/PreCombatScene";
import { RestScene } from "./scenes/RestScene";
import { RewardScene } from "./scenes/RewardScene";
import { ShopScene } from "./scenes/ShopScene";
import { TitleScene } from "./scenes/TitleScene";
import { UnsupportedScene } from "./scenes/UnsupportedScene";
import { DeckSelectOverlay } from "./overlays/DeckSelectOverlay";
import { PickupOverlay } from "./overlays/PickupOverlay";
import { PileOverlay } from "./overlays/PileOverlay";
import { PotionBar } from "./overlays/PotionBar";
import { CardTipHost } from "./overlays/CardTip";
import { tipHandlers } from "./overlays/tipStore.js";
import { SettingsOverlay } from "./overlays/SettingsOverlay";
import { ActCurtain } from "./ActCurtain";
import { CURTAIN_MS } from "./curtain.js";
import { installRunProbe } from "./runProbe";
import "./run.css";

export function RunApp() {
  const [store, setStore] = useState<RunStore | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDeck, setShowDeck] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  /** 动效偏好（`rd.motion`）：玩家在设置里选的，优先于系统偏好。 */
  const [motion, setMotion] = useState<"on" | "off" | "auto">(() => {
    try {
      const stored = window.localStorage.getItem("rd.motion");
      return stored === "on" || stored === "off" ? stored : "auto";
    } catch {
      return "auto";
    }
  });
  const [showPiles, setShowPiles] = useState(false);
  /**
   * 牌组选择器的请求（`null` = 没在选）。
   *
   * 为什么放在外壳而不是 `RunStore`：这是**界面状态**（"我现在正在挑一张牌"），不是内核事实。
   * 选完之后调哪个动作由 `purpose` 决定，`RunStore` 只提供动作本身。
   */
  const [deckRequest, setDeckRequest] = useState<{ purpose: DeckPickPurpose; price?: number } | null>(null);
  /** 正在等玩家选敌人的药水槽（`-1` = 没在选）。 */
  const [potionTargeting, setPotionTargeting] = useState(-1);
  /** 上一次用的种子/进阶（局终"再来一局"回填）。 */
  const [last, setLast] = useState<{ seed: number; ascension: number }>({ seed: 1, ascension: 0 });
  /**
   * 可继续的自动存档（`localStorage`）。**只在标题页读** —— 读一次就够，读到之后
   * `importArchive` 会把它变成当前局面。
   */
  const [resume, setResume] = useState<{ act: number; floor: number; health: number; healthMax: number; text: string } | null>(null);

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

  // 标题页要显示的"继续上次"：store 建好之后读一次（坏存档会被 store 清掉）。
  useEffect(() => {
    if (!store) return;
    setResume(store.resumeInfo());
  }, [store]);

  // 探针：闸门 34 读这里（语义，不是 DOM 内部结构）。
  useEffect(() => {
    if (!store) return;
    installRunProbe(store);
  }, [store]);

  // ⚠️ 冻结是**粘性**的：`violations` 可能变空，但 `frozen` 一旦置位就不解（见 RunStore）。
  const blocked = Boolean(state?.violations.length) || Boolean(state?.frozen);

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

  // `pending 7`（祝福选牌）/ `pending 8`（事件选牌）：这两屏**只有**牌组选择器，
  // 所以场景一到就自动弹（不是"另开一屏"，它们本来就没有别的内容）。
  useEffect(() => {
    if (!state) return;
    if (state.scene.base === SCENE.blessingCard && deckRequest?.purpose !== "blessing") {
      setDeckRequest({ purpose: "blessing" });
    } else if (state.scene.base === SCENE.eventCard && deckRequest?.purpose !== "event") {
      setDeckRequest({ purpose: "event" });
    }
  }, [state, deckRequest]);

  // 幕布：1.6 秒后自己关（与旧页面一致）。点一下也能提前关 —— 两条路都只调 `dismissCurtain`。
  const curtainSeq = state?.curtain?.seq ?? null;
  useEffect(() => {
    if (curtainSeq === null) return;
    const timer = window.setTimeout(() => store?.dismissCurtain(), CURTAIN_MS);
    return () => window.clearTimeout(timer);
  }, [curtainSeq, store]);

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
  /**
   * §391：**战斗中的顶栏要读战斗快照的 HP**，不是运行层的。
   *
   * 运行层的 `health` 在战斗里是**故意**不跟的（`RunStore.reconcile` 的注释写着：
   * 战斗结算 `end_of_combat` 才写回）。于是玩家被史莱姆老大砸了 35 点，顶栏血条纹丝不动
   * —— 看起来像"这次攻击没生效"（玩家实测报的就是这句）。
   *
   * 战斗快照里的 `hero.hp` 才是活的；战斗外两者相等（对账保证），所以这一个表达式
   * 在两种情况下都对。
   */
  const liveHp = base === SCENE.combat && state.combat ? state.combat.hero.hp : (run?.health ?? 0);
  const liveHpMax =
    base === SCENE.combat && state.combat ? state.combat.hero.hpMax : (run?.healthMax ?? 0);

  return (
    <div className="run-shell" data-scene-base={base} data-scene-overlays={scene.overlays.join(",")}>
      {/* ── 常驻顶栏：HP / 金币 / 层数 / 牌组 / 遗物 / 药水 ─────────────────── */}
      <header className="run-topbar">
        <div className="run-hp" data-run-hp={run ? `${liveHp}/${liveHpMax}` : ""}>
          <span className="run-hp-bar">
            <span
              className="run-hp-fill"
              style={{ width: run ? `${Math.max(0, Math.min(100, (liveHp / Math.max(1, liveHpMax)) * 100))}%` : "0%" }}
            />
          </span>
          <span className="run-hp-text">
            {run ? `${liveHp}/${liveHpMax}` : "—"}
          </span>
        </div>
        <div className="run-stat" data-run-gold={run?.gold ?? 0}>
          ◈ {run?.gold ?? 0}
        </div>
        {/*
          §370：**幕数必须显示**。换幕之后 `floor` 归 0，只画层数会变成"第 0 层" —— 玩家会
          以为回到开头。`act` 只能从 `rd_run_act()` 读（观察向量里没有它）。
        */}
        <div className="run-stat" data-run-act={state.act}>
          {/* 还没开局时 `act` 是 0 —— 显示"第 0 幕"会让人以为已经开始了。 */}
          {state.act > 0 ? `第 ${state.act} 幕` : "—"}
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
        <div className="run-stat" data-run-potions={run?.potionCount ?? 0} title={(state.potions ?? []).map((potion) => displayName("potions", potion.id)).join("、")}>
          ⚗ {run?.potionCount ?? 0}
        </div>
        <button
          type="button"
          className="run-stat run-deck-button"
          data-settings-open
          onClick={() => setShowSettings(true)}
        >
          设置
        </button>
        <div className="run-scene-label" data-scene-label={base}>
          {sceneLabel(base)}
          {scene.overlays.length > 0 && ` + ${scene.overlays.map(sceneLabel).join(" + ")}`}
        </div>
      </header>

      {/* ── 遗物条 + 药水腰带 + 牌堆浏览 ───────────────────────────────────── */}
      {run && (
        <div className="run-subbar">
          {/*
            §378：遗物**必须看得见**。玩家报的是"我方的药水和遗物在战场和商店 ui 里没有显示"——
            顶栏只有一个 `✦ 2`，而"我到底有什么遗物"是每一次决策的前提（回血/加金币/加能量）。
            徽章 + 名字（名字可 hover 看 id），与药水腰带同一排。
          */}
          <div className="relic-strip" data-relic-strip={state.relics.length}>
            {state.relics.map((id, index) => (
              <span
                className="relic-chip"
                key={`${id}-${index}`}
                data-relic-id={id}
                title={id}
                {...tipHandlers({ kind: "relic", id })}
              >
                <Badge look={badgeLook("relics", id)} title={id} />
                <span className="relic-chip__name">{displayName("relics", id)}</span>
              </span>
            ))}
            {state.relics.length === 0 && <span className="muted">没有遗物</span>}
          </div>
          <PotionBar
            potions={state.potions}
            inFight={base === SCENE.combat}
            enemySlots={
              base === SCENE.combat ? (state.combat?.enemies ?? []).filter((enemy) => enemy.alive).map((enemy) => enemy.slot) : []
            }
            targetingSlot={potionTargeting}
            busy={blocked}
            onUse={(slot, target) => {
              store.usePotion(slot, target);
              setPotionTargeting(-1);
            }}
            onDrop={(slot) => store.dropPotion(slot)}
            onPickTarget={(slot) => setPotionTargeting(slot)}
          />
          {base === SCENE.combat && (
            <button type="button" className="run-stat run-deck-button" data-piles-open onClick={() => setShowPiles(true)}>
              牌堆
            </button>
          )}
          {potionTargeting >= 0 && (
            <span className="run-potion-targeting" data-potion-targeting={potionTargeting}>
              点一个敌人（或按 Esc 取消）
            </span>
          )}
        </div>
      )}

      {/*
        §389：**唯一那个**详情面板。挂在这里 = 药水栏下方、战场上方（玩家点名要的位置）。
        六个调用点都只调 `showTip()`，所以不可能同时出现两个面板。
      */}
      <CardTipHost />

      {/* ── 幕间幕布（§2.3）：纯演出，不挡操作 ─────────────────────────────── */}
      {state.curtain && (
        <ActCurtain
          key={state.curtain.seq}
          act={state.curtain.act}
          seq={state.curtain.seq}
          onDismiss={() => store.dismissCurtain()}
        />
      )}

      {/* ── 战利品横幅：宝箱"打开即结束"，所以战利品要在这里说 ──────────────── */}
      {state.lastLoot && (
        <div className="run-loot" data-run-loot={state.lastLoot.source}>
          <span>
            {state.lastLoot.source}：金币 +{state.lastLoot.gold}
            {/* §396：这里以前直接印**内容 id**（截图里是"遗物 potion_belt"）。 */}
            {state.lastLoot.relic ? ` · 遗物 ${displayName("relics", state.lastLoot.relic)}` : ""}
          </span>
          <button type="button" data-loot-dismiss onClick={() => store.dismissLoot()}>
            知道了
          </button>
        </div>
      )}

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
              setResume(null);
              store.startRun(seed, ascension);
            }}
            lastSeed={last.seed}
            lastAscension={last.ascension}
            resume={resume}
            onResume={() => {
              if (!resume) return;
              const outcome = store.importArchive(resume.text);
              if (outcome.code === 0) setResume(null);
            }}
          />
        )}

        {base === SCENE.blessing && (
          <BlessingScene
            blessings={state.blessings}
            busy={blocked}
            onChoose={(slot) => store.chooseBlessing(slot)}
          />
        )}

        {base === SCENE.map && map && run && (
          <MapScene
            run={run}
            map={map}
            act={state.act}
            inert={blocked || scene.overlays.length > 0}
            bossReachable={state.bossReachable}
            bossIndex={BOSS_SENTINEL}
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
            frozen={blocked}
            onFinish={() => store.fightEnd()}
            // §411：把"正在等目标的药水槽"交给战斗屏 —— 它以前只用来显示提示文字，
            // 于是"选目标"之后点敌人没有反应（恐惧药水卡住）。
            potionTargeting={potionTargeting}
            onPotionTarget={(slot, enemySlot) => {
              store.usePotion(slot, enemySlot);
              setPotionTargeting(-1);
            }}
            onPotionCancel={() => setPotionTargeting(-1)}
          />
        )}

        {base === SCENE.reward && run && (
          <RewardScene
            gold={state.reward.gold}
            cards={state.reward.cards}
            potion={state.reward.potion}
            relic={state.reward.relic}
            deckSize={run.deckSize}
            busy={blocked}
            onTakeCard={(slot) => store.takeRewardCard(slot)}
            onTakePotion={() => store.takeRewardPotion()}
            onTakeRelic={() => store.takeRewardRelic()}
            onSkip={() => store.skipReward()}
          />
        )}

        {(() => {
          // 身份与能力都由**纯函数**给（`scene.ts::endSceneFor`），组件只负责画。
          const end = endSceneFor(base);
          if (!end || !run) return null;
          return (
            <EndScene
              sceneId={end.sceneId}
              kind={end.kind}
              run={run}
              overWhy={state.overWhy}
              ascension={state.ascension}
              busy={blocked}
              onRestart={() => {
                store.startRun(last.seed, last.ascension);
              }}
              onContinue={end.canContinue ? () => store.endAct() : undefined}
            />
          );
        })()}

        {base === SCENE.bossRelic && run && (
          <BossRelicScene
            clearedAct={Math.max(1, state.act - 1)}
            nextAct={Math.max(2, state.act)}
            relics={state.bossRelics}
            busy={blocked}
            onTake={(slot) => store.takeBossRelic(slot)}
          />
        )}

        {base === SCENE.shop && run && (
          <ShopScene
            gold={run.gold}
            shelves={[
              { kind: "card", title: "卡牌", rows: shelfRows(state.shop.cards, run.gold) },
              { kind: "relic", title: "遗物", rows: shelfRows(state.shop.relics, run.gold) },
              // §380：腰带满了 ⇒ 这一排不可买（内核会拒绝，界面必须先知道）。
              {
                kind: "potion",
                title: beltHasRoom(state.potions.length, state.potionSlots)
                  ? "药水"
                  : `药水（腰带满了 ${state.potions.length}/${state.potionSlots}）`,
                rows: shelfRows(
                  state.shop.potions,
                  run.gold,
                  beltHasRoom(state.potions.length, state.potionSlots)
                ),
              },
              { kind: "colorless", title: "无色牌", rows: shelfRows(state.shop.colorless, run.gold) },
            ]}
            removePrice={state.shop.removePrice}
            removalAvailable={state.shop.removalAvailable}
            busy={blocked}
            onBuy={(kind, slot) => store.buy(kind, slot)}
            onRemove={() => setDeckRequest({ purpose: "remove", price: state.shop.removePrice })}
            onLeave={() => store.leave()}
          />
        )}

        {base === SCENE.rest && (
          <RestScene
            options={campfireOptionsFromMask(state.rest.options)}
            unknownBits={unknownCampfireBits(state.rest.options)}
            restHeal={state.rest.heal}
            heroHp={run?.health ?? 0}
            heroHpMax={run?.healthMax ?? 0}
            giryaLifts={state.rest.giryaLifts}
            busy={blocked}
            onRest={() => store.rest()}
            onSmith={() => setDeckRequest({ purpose: "smith" })}
            onToke={() => setDeckRequest({ purpose: "toke" })}
            onLift={() => store.lift()}
            onDig={() => store.dig()}
            onRecall={() => store.recall()}
            onLeave={() => store.leave()}
          />
        )}

        {base === SCENE.chest && (
          <ChestScene busy={blocked} onOpen={() => store.openChest()} onLeave={() => store.leave()} />
        )}

        {base === SCENE.event && (
          <EventScene
            eventId={state.event.id}
            text={state.event.text}
            options={state.event.options}
            needs={state.event.needs}
            busy={blocked}
            onChoose={(slot) => store.chooseEvent(slot)}
          />
        )}

        {base === SCENE.eventOffer && (
          <EventOfferScene
            eventId={state.event.id}
            offers={state.event.offers}
            busy={blocked}
            onTake={(slot) => store.takeEventOffer(slot)}
          />
        )}

        {!isImplemented(base) && (
          <UnsupportedScene
            scene={base}
            label={sceneLabel(base)}
            pending={state.pending}
            onSettle={() => store.settleDefault()}
          />
        )}
      </main>

      {/*
        ⚠️ 这里曾经还有一个"通用覆盖层"（`data-run-overlay`），文案写着"牌组选择器在 P4"、
        带一个 `settleDefault()` 按钮。P4 做完之后它就成了**第二套**遗物模态：与下面的
        `PickupOverlay` 同时存在于 DOM，而且给了一条"用默认动作跳过欠账"的错路
        （第十五轮 Review §3）。已删除 —— 遗物欠账**只有** `PickupOverlay` 一条路。
      */}

      {/* ── 牌组选择器：`pending 7/8` 自动弹出，其余由按钮触发 ────────────── */}
      {deckRequest && (
        <DeckSelectOverlay
          purpose={deckRequest.purpose}
          price={deckRequest.price}
          deck={state.deck}
          titles={state.deckTitles}
          busy={blocked}
          // ⚠️ 只有"可以放弃"的场合才给关闭（`pending 7/8` 与遗物欠账不能放弃）。
          onClose={
            deckRequest.purpose === "blessing" ||
            deckRequest.purpose === "event" ||
            deckRequest.purpose === "pickup"
              ? undefined
              : () => setDeckRequest(null)
          }
          onPick={(index) => {
            const purpose = deckRequest.purpose;
            setDeckRequest(null);
            if (purpose === "blessing") store.pickBlessingCard(index);
            else if (purpose === "event") store.pickEventCard(index);
            else if (purpose === "smith") store.smith(index);
            else if (purpose === "toke") store.toke(index);
            else if (purpose === "remove") store.removeFromDeck(index);
            else if (purpose === "pickup") store.pickupPickCard(index);
          }}
        />
      )}

      {/* ── 遗物欠账：盖在当前屏之上，关不掉（欠账必须还）──────────────────── */}
      {(state.pickup.picks > 0 || state.pickup.add > 0) && (
        <PickupOverlay
          change={state.pickup.change}
          picks={state.pickup.picks}
          add={state.pickup.add}
          offers={state.pickup.offers}
          busy={blocked}
          onPickCard={() => setDeckRequest({ purpose: "pickup" })}
          onAddCard={(slot) => store.pickupAddCard(slot)}
          onSkipAdd={() => store.pickupSkip()}
          onMaxHpInstead={() => store.pickupMaxHp()}
        />
      )}

      {showPiles && (
        <PileOverlay piles={store.piles()} onClose={() => setShowPiles(false)} />
      )}

      {showSettings && (
        <SettingsOverlay
          state={state}
          motion={motion}
          onClose={() => setShowSettings(false)}
          onExport={() => store.exportArchive()}
          onImport={(text) => store.importArchive(text)}
          onExportReplay={() => store.exportReplay()}
          onImportReplay={(text) => store.importReplay(text)}
          onMotionChange={(value) => {
            setMotion(value);
            try {
              if (value === "auto") window.localStorage.removeItem("rd.motion");
              else window.localStorage.setItem("rd.motion", value);
            } catch {
              // 隐私模式：忽略（设置只在这一局有效）。
            }
          }}
        />
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
                  <Badge look={badgeLook("cards", id)} title={id} upgraded={id.endsWith("+")} />
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

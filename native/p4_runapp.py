"""RunApp：接上 P4 的五屏 + 牌组选择器 + 欠账覆盖层 + 设置 + 牌堆 + 药水条。"""

import io

P = 'web-next/src/run/RunApp.tsx'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# ── 1. import ────────────────────────────────────────────────────────────────
sub(
    '''import { nodeKindLabel } from "./observe.js";
import { RunStore } from "./RunStore";''',
    '''import { campfireOptionsFromMask, unknownCampfireBits, shelfRows, type DeckPickPurpose } from "./models.js";
import { nodeKindLabel } from "./observe.js";
import { RunStore } from "./RunStore";''',
    'import models',
)

sub(
    '''import { BlessingScene } from "./scenes/BlessingScene";
import { EndScene } from "./scenes/EndScene";''',
    '''import { BlessingScene } from "./scenes/BlessingScene";
import { ChestScene } from "./scenes/ChestScene";
import { EndScene } from "./scenes/EndScene";
import { EventOfferScene } from "./scenes/EventOfferScene";
import { EventScene } from "./scenes/EventScene";''',
    'import scenes a',
)

sub(
    '''import { PreCombatScene } from "./scenes/PreCombatScene";
import { RewardScene } from "./scenes/RewardScene";''',
    '''import { PreCombatScene } from "./scenes/PreCombatScene";
import { RestScene } from "./scenes/RestScene";
import { RewardScene } from "./scenes/RewardScene";
import { ShopScene } from "./scenes/ShopScene";''',
    'import scenes b',
)

sub(
    '''import { installRunProbe } from "./runProbe";''',
    '''import { DeckSelectOverlay } from "./overlays/DeckSelectOverlay";
import { PickupOverlay } from "./overlays/PickupOverlay";
import { PileOverlay } from "./overlays/PileOverlay";
import { PotionBar } from "./overlays/PotionBar";
import { SettingsOverlay } from "./overlays/SettingsOverlay";
import { installRunProbe } from "./runProbe";''',
    'import overlays',
)

# ── 2. UI 状态 ───────────────────────────────────────────────────────────────
sub(
    '''  const [showDeck, setShowDeck] = useState(false);''',
    '''  const [showDeck, setShowDeck] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showPiles, setShowPiles] = useState(false);
  /**
   * 牌组选择器的请求（`null` = 没在选）。
   *
   * 为什么放在外壳而不是 `RunStore`：这是**界面状态**（"我现在正在挑一张牌"），不是内核事实。
   * 选完之后调哪个动作由 `purpose` 决定，`RunStore` 只提供动作本身。
   */
  const [deckRequest, setDeckRequest] = useState<{ purpose: DeckPickPurpose; price?: number } | null>(null);
  /** 正在等玩家选敌人的药水槽（`-1` = 没在选）。 */
  const [potionTargeting, setPotionTargeting] = useState(-1);''',
    'ui state',
)

# ── 3. 药水/牌堆/设置按钮 + 药水条（顶栏）────────────────────────────────────
sub(
    '''        <div className="run-scene-label" data-scene-label={base}>''',
    '''        <button
          type="button"
          className="run-stat run-deck-button"
          data-settings-open
          onClick={() => setShowSettings(true)}
        >
          设置
        </button>
        <div className="run-scene-label" data-scene-label={base}>''',
    'settings button',
)

# ── 4. 场景路由：替换掉"未实现"分支 ─────────────────────────────────────────
sub(
    '''        {!isImplemented(base) && base !== SCENE.blessing && (
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
        )}''',
    '''        {base === SCENE.shop && run && (
          <ShopScene
            gold={run.gold}
            shelves={[
              { kind: "card", title: "卡牌", rows: shelfRows(state.shop.cards, run.gold) },
              { kind: "relic", title: "遗物", rows: shelfRows(state.shop.relics, run.gold) },
              { kind: "potion", title: "药水", rows: shelfRows(state.shop.potions, run.gold) },
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
          <ChestScene
            opened={state.chest.opened}
            goldGained={state.chest.goldGained}
            relicGained={state.chest.relicGained}
            busy={blocked}
            onOpen={() => store.openChest()}
            onLeave={() => store.leave()}
          />
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
        )}''',
    'route p4',
)

# ── 5. 覆盖层：牌组选择器 / 欠账 / 牌堆 / 设置 ───────────────────────────────
sub(
    '''      {/* ── 日志：最近 3 条 ──────────────────────────────────────────────── */}''',
    '''      {/* ── 牌组选择器：`pending 7/8` 自动弹出，其余由按钮触发 ────────────── */}
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

      {showSettings && <SettingsOverlay state={state} onClose={() => setShowSettings(false)} />}

      {/* ── 日志：最近 3 条 ──────────────────────────────────────────────── */}''',
    'overlays',
)

# ── 6. 药水条 + 牌堆按钮：放进顶栏下面一条 ──────────────────────────────────
sub(
    '''      {/* ── 对账失败：**响亮**失败，并冻结推进 ─────────────────────────────── */}''',
    '''      {/* ── 药水腰带 + 牌堆浏览 ───────────────────────────────────────────── */}
      {run && (
        <div className="run-subbar">
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

      {/* ── 对账失败：**响亮**失败，并冻结推进 ─────────────────────────────── */}''',
    'potion bar',
)

# ── 7. `pending 7/8` 自动弹选择器（场景判定已给出）──────────────────────────
sub(
    '''  const deckGroups = useMemo(() => {''',
    '''  // `pending 7`（祝福选牌）/ `pending 8`（事件选牌）：这两屏**只有**牌组选择器，
  // 所以场景一到就自动弹（不是"另开一屏"，它们本来就没有别的内容）。
  useEffect(() => {
    if (!state) return;
    if (state.scene.base === SCENE.blessingCard && deckRequest?.purpose !== "blessing") {
      setDeckRequest({ purpose: "blessing" });
    } else if (state.scene.base === SCENE.eventCard && deckRequest?.purpose !== "event") {
      setDeckRequest({ purpose: "event" });
    }
  }, [state, deckRequest]);

  const deckGroups = useMemo(() => {''',
    'auto picker',
)

io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('RunApp: p4 wired')

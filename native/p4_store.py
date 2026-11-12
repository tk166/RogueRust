"""RunStore：P4 的状态（商店/篝火/宝箱/事件/欠账/药水/牌堆）与动作。"""

import io

P = 'web-next/src/run/RunStore.ts'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# ── 1. 类型：状态字段 ────────────────────────────────────────────────────────
sub(
    '''  /** 牌组 / 遗物（顶栏与牌组弹窗）。 */
  readonly deck: readonly string[];''',
    '''  /** 商店（`pending == 2`）。 */
  readonly shop: {
    readonly cards: readonly { slot: number; id: string; price: number }[];
    readonly relics: readonly { slot: number; id: string; price: number }[];
    readonly potions: readonly { slot: number; id: string; price: number }[];
    readonly colorless: readonly { slot: number; id: string; price: number }[];
    readonly removePrice: number;
    readonly removalAvailable: number;
  };
  /** 篝火（`pending == 1`）。`options` 是**位掩码**，解码在 `models.ts`。 */
  readonly rest: {
    readonly options: number;
    readonly heal: number;
    readonly giryaLifts: number;
  };
  /** 宝箱（`pending == 3`）：打开前后的增量。 */
  readonly chest: {
    readonly opened: boolean;
    readonly goldGained: number;
    readonly relicGained: string;
  };
  /** 事件（`pending == 5` / `9`）。 */
  readonly event: {
    readonly id: string;
    readonly text: string;
    readonly needs: number;
    readonly options: readonly {
      slot: number;
      label: string;
      available: boolean;
      effects: readonly { kind: number; amount: number }[];
    }[];
    readonly offers: readonly { slot: number; id: string; title: string }[];
  };
  /** 遗物欠账（`SC-11a`/`SC-11b`，**不走 pending**）。 */
  readonly pickup: {
    readonly change: number;
    readonly picks: number;
    readonly add: number;
    readonly offers: readonly { slot: number; title: string }[];
  };
  /** 药水腰带（带 `effect`/`needsFight`，界面据此决定能不能用、要不要目标）。 */
  readonly potions: readonly { slot: number; id: string; effect: number; needsFight: number }[];
  /** 牌组 / 遗物（顶栏与牌组弹窗）。 */
  readonly deck: readonly string[];
  /** 牌组的显示名（与 `deck` 同序，供牌组选择器用）。 */
  readonly deckTitles: readonly string[];''',
    'state types',
)

# ── 2. 初始值 ────────────────────────────────────────────────────────────────
sub(
    '''      reward: EMPTY_REWARD,
      deck: [],''',
    '''      reward: EMPTY_REWARD,
      shop: { cards: [], relics: [], potions: [], colorless: [], removePrice: 0, removalAvailable: -1 },
      rest: { options: 0, heal: 0, giryaLifts: 0 },
      chest: { opened: false, goldGained: 0, relicGained: "" },
      event: { id: "", text: "", needs: 0, options: [], offers: [] },
      pickup: { change: 0, picks: 0, add: 0, offers: [] },
      potions: [],
      deck: [],
      deckTitles: [],''',
    'state init',
)

# ── 3. 内部字段：宝箱基线 / 打开过没有 ───────────────────────────────────────
sub(
    '''  private readonly listeners = new Set<Listener>();
  private seq = 0;''',
    '''  private readonly listeners = new Set<Listener>();
  private seq = 0;
  /**
   * 宝箱的"打开前"基线（金币 + 遗物数）。
   *
   * 内核没有"箱子里有什么"的查询，只有"打开之后局里多了什么"。所以进宝箱屏时记一次基线，
   * 打开后拿差值显示 —— 这比编一个"里面有 X"诚实。
   */
  private chestBaseline: { gold: number; relicCount: number; relics: string[] } | null = null;
  private chestOpened = false;''',
    'chest fields',
)

# ── 4. refresh：读 P4 的屏 ───────────────────────────────────────────────────
sub(
    '''      deck: raw.exists ? this.host.deckIds() : [],''',
    '''      shop:
        pending === 2
          ? {
              cards: this.host.shopCards(),
              relics: this.host.shopRelics(),
              potions: this.host.shopPotions(),
              colorless: this.host.shopColorless(),
              removePrice: this.host.removePrice(),
              removalAvailable: this.host.removalAvailable(),
            }
          : { cards: [], relics: [], potions: [], colorless: [], removePrice: 0, removalAvailable: -1 },
      rest:
        pending === 1
          ? {
              options: this.host.campfireOptions(),
              heal: this.host.restHeal(),
              giryaLifts: this.host.giryaLifts(),
            }
          : { options: 0, heal: 0, giryaLifts: 0 },
      chest: this.readChest(pending, raw.exists),
      event:
        pending === 5 || pending === 9
          ? {
              id: this.host.eventId(),
              text: this.host.eventText(),
              needs: this.host.eventNeeds(),
              options: pending === 5 ? this.host.eventOptions() : [],
              offers: pending === 9 ? this.host.eventOffers() : [],
            }
          : { id: "", text: "", needs: 0, options: [], offers: [] },
      pickup: {
        change: this.host.pickupChange(),
        picks: this.host.pickupPicks(),
        add: this.host.pickupAdd(),
        offers: this.host.pickupAdd() > 0 ? this.host.pickupOffers() : [],
      },
      potions: raw.exists
        ? Array.from({ length: this.host.potionCount() }, (_, slot) => ({
            slot,
            id: this.host.potionId(slot),
            effect: this.host.potionEffect(slot),
            needsFight: this.host.potionNeedsFight(slot),
          }))
        : [],
      deck: raw.exists ? this.host.deckIds() : [],
      deckTitles: raw.exists ? this.host.deckTitles() : [],''',
    'refresh p4',
)

# ── 5. readChest 辅助 ────────────────────────────────────────────────────────
sub(
    '''  /**
   * 对账（plan P3 的退出条件："所有 Snapshot 对账通过"）。''',
    '''  /** 宝箱屏：进屏记基线，打开后拿差值。离开（相位不再是 3）就把状态清掉。 */
  private readChest(pending: number, exists: boolean): RunState["chest"] {
    if (!exists || pending !== 3) {
      this.chestBaseline = null;
      this.chestOpened = false;
      return { opened: false, goldGained: 0, relicGained: "" };
    }
    const run = decodeRun(this.host.runObservation());
    const relics = this.host.relicIds();
    if (this.chestBaseline === null) {
      this.chestBaseline = { gold: run.gold, relicCount: run.relicCount, relics };
    }
    const base = this.chestBaseline;
    const fresh = relics.filter((id) => !base.relics.includes(id));
    return {
      opened: this.chestOpened,
      goldGained: Math.max(0, run.gold - base.gold),
      relicGained: fresh[0] ?? "",
    };
  }

  /**
   * 对账（plan P3 的退出条件："所有 Snapshot 对账通过"）。''',
    'readChest',
)

# ── 6. 动作 ──────────────────────────────────────────────────────────────────
sub(
    '''  /** 局终后重开（保持同一 seed 便于复现，玩家可改）。 */''',
    '''  // ── P4：商店 ────────────────────────────────────────────────────────────
  /**
   * 买一件东西。`kind` 与货架一一对应（`card` / `relic` / `potion` / `colorless`）。
   *
   * 返回内核的返回码：`0` 成功、`-1` 没有这个槽、`-2` 拒绝（金币不够/腰带满/相位不对）。
   * ⚠️ 失败时**不猜原因**，把码交给界面 —— 界面只显示"买不了（code N）"，
   * 而不是编一句可能是错的话。
   */
  buy(kind: "card" | "relic" | "potion" | "colorless", slot: number): number {
    const code =
      kind === "card"
        ? this.host.buyCard(slot)
        : kind === "relic"
          ? this.host.buyRelic(slot)
          : kind === "potion"
            ? this.host.buyPotion(slot)
            : this.host.buyColorless(slot);
    const names = { card: "卡牌", relic: "遗物", potion: "药水", colorless: "无色牌" } as const;
    this.note(code === 0 ? `买了${names[kind]}（槽 ${slot}）` : `买${names[kind]}失败（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  /** 付钱删一张牌（`index` 是**牌组下标**）。返回花掉的钱，`<0` 表示失败。 */
  removeFromDeck(index: number): number {
    const paid = this.host.removeCard(index);
    this.note(paid >= 0 ? `花了 ${paid} 金币删掉一张牌` : `删牌失败（code ${paid}）`, paid >= 0 ? "good" : "warn");
    this.refresh();
    return paid;
  }

  leave(): number {
    const code = this.host.leave();
    this.note(code === 0 ? "离开" : `离开被拒绝（code ${code}）`, code === 0 ? "info" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：篝火 ────────────────────────────────────────────────────────────
  rest(): number {
    const code = this.host.rest();
    this.note(code === 0 ? `休息：回复 ${this.host.restHeal()} 点生命` : `休息被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  smith(index: number): number {
    const code = this.host.smith(index);
    this.note(code === 0 ? "锻造：升级了一张牌" : `锻造被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  toke(index: number): number {
    const code = this.host.toke(index);
    this.note(code === 0 ? "抽烟斗：删掉了一张牌" : `抽烟斗被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  lift(): number {
    const code = this.host.lift();
    this.note(code === 0 ? `举重：第 ${this.host.giryaLifts()} 次` : `举重被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  dig(): number {
    const before = this.host.relicIds();
    const code = this.host.dig();
    const after = this.host.relicIds();
    const fresh = after.filter((id) => !before.includes(id));
    this.note(code === 0 ? `挖到遗物：${fresh[0] ?? "（没有新的）"}` : `挖宝被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  recall(): number {
    const code = this.host.recall();
    this.note(code === 0 ? "拿到红钥匙" : `回忆被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：宝箱 ────────────────────────────────────────────────────────────
  openChest(): number {
    const code = this.host.openChest();
    if (code === 0) this.chestOpened = true;
    this.note(code === 0 ? "打开宝箱" : `打开宝箱失败（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：事件 ────────────────────────────────────────────────────────────
  chooseEvent(slot: number): number {
    const code = this.host.choose(slot);
    this.note(code === 0 ? `事件：选了第 ${slot + 1} 项` : `事件选项被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  takeEventOffer(slot: number): number {
    const code = this.host.eventOfferTake(slot);
    this.note(code === 0 ? "事件：拿走了一张候选" : `拿候选失败（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  /** 事件问句的牌组下标答案（`Pending::EventCard`）。 */
  pickEventCard(index: number): number {
    const code = this.host.pickEventCard(index);
    this.note(code === 0 ? "事件：选了一张牌" : `事件选牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  pickBlessingCard(index: number): number {
    const code = this.host.pickBlessingCard(index);
    this.note(code === 0 ? "祝福：选了一张牌" : `祝福选牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：遗物欠账 ────────────────────────────────────────────────────────
  pickupPickCard(index: number): number {
    const code = this.host.pickupCard(index);
    this.note(code === 0 ? "遗物欠账：改了一张牌" : `改牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  pickupAddCard(slot: number): number {
    const code = this.host.pickupAddCard(slot);
    this.note(code === 0 ? "遗物欠账：加了一张牌" : `加牌被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  pickupSkip(): number {
    const code = this.host.pickupAddSkip();
    this.note(code === 0 ? "遗物欠账：跳过这一次" : `跳过被拒绝（code ${code}）`, code === 0 ? "info" : "warn");
    this.refresh();
    return code;
  }

  pickupMaxHp(): number {
    const code = this.host.pickupAddMaxHp();
    this.note(code === 0 ? "遗物欠账：换成生命上限 +2" : `换上限被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    this.refresh();
    return code;
  }

  // ── P4：药水 ────────────────────────────────────────────────────────────
  /**
   * 喝一瓶药水。
   *
   * ⚠️ `rd_env_use_potion` 的返回码：`0` 成功 / `-1` 没有这个槽 / `-2` 拒绝（带原因）。
   * 战斗外喝 run-only 的药水是**内核支持**的（§158），所以这里不按"在不在战斗"拦，
   * 由界面用 `needsFight` 决定画不画得动。
   */
  usePotion(slot: number, target: number): number {
    const code = this.host.usePotion(slot, target);
    const id = this.host.potionCount() > slot ? this.host.potionId(slot) : "";
    this.note(code === 0 ? `喝下 ${id || "药水"}` : `喝药水被拒绝（code ${code}）`, code === 0 ? "good" : "warn");
    // 战斗里喝药会改 148 格向量 ⇒ 战斗 store 也要重读（否则战斗屏还画着旧的）。
    this.combatStore?.refresh();
    this.refresh();
    return code;
  }

  dropPotion(slot: number): number {
    const id = this.host.potionCount() > slot ? this.host.potionId(slot) : "";
    const code = this.host.dropPotion(slot);
    this.note(code === 0 ? `扔掉 ${id || "药水"}` : `扔药水被拒绝（code ${code}）`, code === 0 ? "info" : "warn");
    this.refresh();
    return code;
  }

  /** 战斗中的牌堆（0 抽 / 1 弃 / 2 消耗）。没有战斗会话就返回空表。 */
  piles(): { zone: number; label: string; cards: { id: string; title: string }[] }[] {
    if (!this.host.hasCombatSession()) return [];
    const labels = ["抽牌堆", "弃牌堆", "消耗堆"];
    return [0, 1, 2].map((zone) => {
      const count = this.host.pileLen(zone);
      const cards: { id: string; title: string }[] = [];
      for (let index = 0; index < count; index += 1) cards.push(this.host.pileCard(zone, index));
      return { zone, label: labels[zone], cards };
    });
  }

  /** 局终后重开（保持同一 seed 便于复现，玩家可改）。 */''',
    'p4 actions',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('RunStore: p4 state + actions')

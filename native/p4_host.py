"""host.ts：P4 需要的读取与动作（商店/篝火/宝箱/事件/遗物欠账/药水/牌堆/牌组标题）。"""

import io

P = 'web-next/src/wasm/host.ts'
t = io.open(P, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


sub(
    '''  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */''',
    '''  /** 牌组第 `index` 张的**显示名**（`rd_run_deck_title_*`）。 */
  deckTitles(): string[] {
    const count = (this.ex.rd_run_deck_count as () => number)();
    const out: string[] = [];
    for (let index = 0; index < count; index += 1) {
      out.push(
        this.readText(
          () => (this.ex.rd_run_deck_title_len as (index: number) => number)(index),
          (ptr) =>
            (this.ex.rd_run_deck_title_into as (index: number, ptr: number) => number)(index, ptr)
        )
      );
    }
    return out;
  }

  // ── 商店（`pending == 2`）────────────────────────────────────────────────
  //
  // 四类货架各有一族 `_count` / `_id_len` / `_id_into` / `_price`。**价格由内核给**
  // （它已经算上会员卡/涨价/§332 的定价规则），页面绝不算价 —— 页面算价必然与内核漂。
  private shelf(
    prefix: string
  ): { slot: number; id: string; price: number }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call(`rd_run_${prefix}_count`);
    const out: { slot: number; id: string; price: number }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => call(`rd_run_${prefix}_id_len`, slot),
          (ptr) => call(`rd_run_${prefix}_id_into`, slot, ptr)
        ),
        price: call(`rd_run_${prefix}_price`, slot),
      });
    }
    return out;
  }

  shopCards(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_card");
  }

  shopRelics(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_relic");
  }

  shopPotions(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_potion");
  }

  /** 无色货架（§332）。 */
  shopColorless(): { slot: number; id: string; price: number }[] {
    return this.shelf("shop_colorless");
  }

  /** 现在删一张牌要多少钱（`inv:§8.2`：75，之后每次 +25）。 */
  removePrice(): number {
    return (this.ex.rd_run_remove_price as () => number)();
  }

  /** 这家店的删卡服务还能不能用：`1` 能 / `0` 这家店删过了 / `-1` 没有局（§343）。 */
  removalAvailable(): number {
    return (this.ex.rd_run_removal_available as () => number)();
  }

  buyCard(slot: number): number {
    return (this.ex.rd_run_buy_card as (slot: number) => number)(slot);
  }

  buyRelic(slot: number): number {
    return (this.ex.rd_run_buy_relic as (slot: number) => number)(slot);
  }

  buyPotion(slot: number): number {
    return (this.ex.rd_run_buy_potion as (slot: number) => number)(slot);
  }

  buyColorless(slot: number): number {
    return (this.ex.rd_run_buy_colorless as (slot: number) => number)(slot);
  }

  /** 花钱删牌组第 `index` 张。返回花掉的钱。 */
  removeCard(index: number): number {
    return (this.ex.rd_run_remove_card as (index: number) => number)(index);
  }

  // ── 篝火（`pending == 1`）────────────────────────────────────────────────
  /**
   * 篝火选项的**位掩码**（§259）：`Rest 1 | Smith 2 | Recall 4 | Lift 8 | Toke 16 | Dig 32`。
   *
   * ⚠️ 位序是**硬约定**，页面按它读。内核为什么用一个位掩码而不是六个 `is_*` 导出：
   * 一次渲染要全部六个，六个导出是六次往返，而"漏了一个"只表现为那个按钮不出现（静默）。
   */
  campfireOptions(): number {
    return (this.ex.rd_run_campfire_options as () => number)();
  }

  /** 休息能回多少血（已算上 `regal_pillow` +15 与 `eternal_feather` 每 5 张牌 +3）。 */
  restHeal(): number {
    return (this.ex.rd_run_rest_heal as () => number)();
  }

  /** `Girya` 已经举过几次（1..=3）。 */
  giryaLifts(): number {
    return (this.ex.rd_run_girya_lifts as () => number)();
  }

  smith(index: number): number {
    return (this.ex.rd_run_smith as (index: number) => number)(index);
  }

  /** `Peace Pipe`：删掉牌组第 `index` 张。 */
  toke(index: number): number {
    return (this.ex.rd_run_toke as (index: number) => number)(index);
  }

  /** `Shovel`：抽一件遗物（抽到哪件从 `relicIds()` 的增量看）。 */
  dig(): number {
    return (this.ex.rd_run_dig as () => number)();
  }

  lift(): number {
    return (this.ex.rd_run_lift as () => number)();
  }

  /** 拿红钥匙。 */
  recall(): number {
    return (this.ex.rd_run_recall as () => number)();
  }

  // ── 事件（`pending == 5` / `8` / `9`）────────────────────────────────────
  eventId(): string {
    const len = (this.ex.rd_run_event_id_len as () => number)();
    if (len <= 0) return "";
    return this.readText(() => len, (ptr) => (this.ex.rd_run_event_id_into as (ptr: number) => number)(ptr));
  }

  eventText(): string {
    const len = (this.ex.rd_run_event_text_len as () => number)();
    if (len <= 0) return "";
    return this.readText(() => len, (ptr) => (this.ex.rd_run_event_text_into as (ptr: number) => number)(ptr));
  }

  /** 这个事件还差什么：0 没有 / 1 删牌 / 2 升级 / 3 变形（与 `pickup_change` 同一套编码）。 */
  eventNeeds(): number {
    return (this.ex.rd_run_event_needs as () => number)();
  }

  /**
   * 事件按钮。**条数由内容决定**（§278：`golden_idol` 第二段是三选一），
   * **可用性由内核决定**（§279：与 `rd_run_choose` 判的是同一个函数）。
   */
  eventOptions(): {
    slot: number;
    label: string;
    available: boolean;
    effects: { kind: number; amount: number }[];
  }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call("rd_run_event_option_count");
    const out: {
      slot: number;
      label: string;
      available: boolean;
      effects: { kind: number; amount: number }[];
    }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      const effects: { kind: number; amount: number }[] = [];
      const effectCount = call("rd_run_event_effect_count", slot);
      for (let index = 0; index < effectCount; index += 1) {
        effects.push({
          kind: call("rd_run_event_effect_at", slot, index),
          amount: call("rd_run_event_amount_at", slot, index),
        });
      }
      out.push({
        slot,
        label: this.readText(
          () => call("rd_run_event_label_len", slot),
          (ptr) => call("rd_run_event_label_into", slot, ptr)
        ),
        available: call("rd_run_event_option_available", slot) === 1,
        effects,
      });
    }
    return out;
  }

  choose(slot: number): number {
    return (this.ex.rd_run_choose as (slot: number) => number)(slot);
  }

  /** 事件摊开的候选（§320：`The Library` 的 20 选 1、`Sensory Stone`）。 */
  eventOffers(): { slot: number; id: string; title: string }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call("rd_run_event_offer_len");
    const out: { slot: number; id: string; title: string }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        id: this.readText(
          () => call("rd_run_event_offer_id_len", slot),
          (ptr) => call("rd_run_event_offer_id_into", slot, ptr)
        ),
        title: this.readText(
          () => call("rd_run_event_offer_title_len", slot),
          (ptr) => call("rd_run_event_offer_title_into", slot, ptr)
        ),
      });
    }
    return out;
  }

  eventOfferTake(slot: number): number {
    return (this.ex.rd_run_event_offer_take as (slot: number) => number)(slot);
  }

  /** 事件问句的牌组下标答案（`Pending::EventCard`）。 */
  pickEventCard(index: number): number {
    return (this.ex.rd_run_pick_event_card as (index: number) => number)(index);
  }

  pickBlessingCard(index: number): number {
    return (this.ex.rd_run_pick_blessing_card as (index: number) => number)(index);
  }

  // ── 遗物欠账（`SC-11a`/`SC-11b`，**不走 pending**）──────────────────────
  /** 欠的加牌候选（`orrery` / `tiny_house`）。 */
  pickupOffers(): { slot: number; title: string }[] {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    const count = call("rd_run_pickup_offer_count");
    const out: { slot: number; title: string }[] = [];
    for (let slot = 0; slot < count; slot += 1) {
      out.push({
        slot,
        title: this.readText(
          () => call("rd_run_pickup_offer_title_len", slot),
          (ptr) => call("rd_run_pickup_offer_title_into", slot, ptr)
        ),
      });
    }
    return out;
  }

  /** 兑现一次"改牌"欠账（牌组下标）。 */
  pickupCard(index: number): number {
    return (this.ex.rd_run_pickup_card as (index: number) => number)(index);
  }

  pickupAddCard(slot: number): number {
    return (this.ex.rd_run_pickup_add_card as (slot: number) => number)(slot);
  }

  pickupAddSkip(): number {
    return (this.ex.rd_run_pickup_add_skip as () => number)();
  }

  pickupAddMaxHp(): number {
    return (this.ex.rd_run_pickup_add_max_hp as () => number)();
  }

  // ── 药水（腰带）───────────────────────────────────────────────────────────
  /** 药水 `slot` 的用法：`1` 要敌人目标 / `2` 作用于英雄或本局 / `3` 打所有敌人 / `0` 未知。 */
  potionEffect(slot: number): number {
    return (this.ex.rd_run_potion_effect as (slot: number) => number)(slot);
  }

  /** `0` = 战斗外也能用（run-only），`1` = 必须战斗内，`-1` = 没有这个槽。 */
  potionNeedsFight(slot: number): number {
    return (this.ex.rd_run_potion_needs_fight as (slot: number) => number)(slot);
  }

  dropPotion(index: number): number {
    return (this.ex.rd_run_drop_potion as (index: number) => number)(index);
  }

  // ── 战斗中的牌堆浏览（`rd_env_pile_*`）──────────────────────────────────
  /** `zone`：0 抽牌堆 / 1 弃牌堆 / 2 消耗堆。 */
  pileLen(zone: number): number {
    return (this.ex.rd_env_pile_len as (zone: number) => number)(zone);
  }

  pileCard(zone: number, index: number): { id: string; title: string } {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    return {
      id: this.readText(
        () => call("rd_env_pile_card_id_len", zone, index),
        (ptr) => call("rd_env_pile_card_id_into", zone, index, ptr)
      ),
      title: this.readText(
        () => call("rd_env_pile_card_title_len", zone, index),
        (ptr) => call("rd_env_pile_card_title_into", zone, index, ptr)
      ),
    };
  }

  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */''',
    'host p4 block',
)
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('host: p4 block')

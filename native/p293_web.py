"""§293：页面的三处改动（快照 + 面板 + 动作）。

判据形状与 §274 的 `pickupPicks` 面板完全一致：**独立于 `pending`**，面板优先级最高，
选完自然回到原来那一屏。
"""
import io

INDEX = 'D:/Vibe/sts-tui/web/index.html'
PANELS = 'D:/Vibe/sts-tui/web/ui_panels.js'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── 1. 快照：加牌的欠账 + 这一手候选 + 有没有 `singing_bowl`
    patch(INDEX, '''    pickupPicks: ex.rd_run_pickup_picks(),
    pickupChange: ex.rd_run_pickup_change(),''',
                '''    pickupPicks: ex.rd_run_pickup_picks(),
    pickupChange: ex.rd_run_pickup_change(),
    /// §293：还欠几张牌要**加**进牌组（`orrery` = 5、`tiny_house` = 1），以及这一手是哪几张。
    /// 与 `pickupPicks` 是**两件事**（那个是"改已有的一张"，这个是"从候选里加一张"）。
    pickupAdd: ex.rd_run_pickup_add(),
    pickupOffer: [],
    /// §293：`singing_bowl` 在身上吗（奖励屏与加牌问句各多一个"换成 +2 上限"的按钮）。
    singingBowl: false,''')

    # 快照填充：放在 `pickupChange` 之后、`case` 之前（独立于 pending）
    patch(INDEX, '''  return snapshot;
}''', '''  // §293：加牌的欠账独立于 `pending`（拾取可能发生在别的屏开着的时候），所以在这里填。
  if (snapshot.pickupAdd > 0) {
    for (let slot = 0, n = ex.rd_run_pickup_offer_count(); slot < n; slot++) {
      snapshot.pickupOffer.push({
        slot,
        title: readText(
          (k) => ex.rd_run_pickup_offer_title_len(k),
          (ptr, k) => ex.rd_run_pickup_offer_title_into(k, ptr),
          slot
        ),
      });
    }
    // ⚠️ 这条判据必须是"**我持有的遗物里有没有** `singing_bowl`"，不是"有没有欠账"：
    // 见 `describePickupAdd` 的注释 —— 一个永远画出来的 +2 按钮就是死按钮。
    for (let i = 0, n = ex.rd_run_observe(6); i < n; i++) {
      const id = readText((k) => ex.rd_run_relic_id_len(k),
                          (ptr, k) => ex.rd_run_relic_id_into(k, ptr), i);
      if (id === "singing_bowl") snapshot.singingBowl = true;
    }
  }
  if (snapshot.pending === 4 && !snapshot.singingBowl) {
    for (let i = 0, n = ex.rd_run_observe(6); i < n; i++) {
      const id = readText((k) => ex.rd_run_relic_id_len(k),
                          (ptr, k) => ex.rd_run_relic_id_into(k, ptr), i);
      if (id === "singing_bowl") snapshot.singingBowl = true;
    }
  }
  return snapshot;
}''')

    # ── 2. 动作
    patch(INDEX, '''  pickup_card: () =>
    showDeckPicker("选一张牌", (index) => act(() => ex.rd_run_pickup_card(index), "拾取")),''',
                '''  pickup_card: () =>
    showDeckPicker("选一张牌", (index) => act(() => ex.rd_run_pickup_card(index), "拾取")),
  // §293：加牌问句的四个动作。
  pickup_add_card: (a) => act(() => ex.rd_run_pickup_add_card(a.slot), "加牌"),
  pickup_add_skip: () => act(() => ex.rd_run_pickup_add_skip(), "跳过加牌"),
  pickup_add_max_hp: () => act(() => ex.rd_run_pickup_add_max_hp(), "换成上限"),
  take_max_hp_instead: () => act(() => ex.rd_run_take_max_hp_instead(), "换成上限"),''')

    # ── 3. 面板
    patch(PANELS, '''  function describeIdle(s) {''', '''  /// §293: a relic that owes **cards to add** (`orrery` 5, `tiny_house` 1).
  ///
  /// 与 `describePickupCard` 同一个位置、同一条理由（独立于 `pending`、优先级最高、选完回到原屏）。
  /// ★ 每个候选的按钮带的是**内核的槽号**（`slot`），不是数组下标 —— §161.8 的教训。
  function describePickupAdd(s) {
    const left = s.pickupAdd > 1 ? `（还要选 ${s.pickupAdd} 张）` : "";
    const rows = (s.pickupOffer || []).map((card) => ({
      label: card.title || `#${card.slot}`,
      sub: "",
      value: "",
      disabled: false,
      button: { label: "加这张", action: { kind: "pickup_add_card", slot: card.slot } },
    }));
    const buttons = [{ id: "skip", label: "跳过", action: { kind: "pickup_add_skip" } }];
    // ⚠️ 只在**持有 `singing_bowl`** 时画这个按钮：`pickup_add_max_hp` 没有那件遗物会
    // `UnsupportedRelic`，画出来就是一个点了没反应的死按钮。
    if (s.singingBowl) {
      buttons.unshift({ id: "max_hp", label: "+2 上限", action: { kind: "pickup_add_max_hp" } });
    }
    return {
      title: "遗物 · 挑一张牌加入牌组 " + left,
      lines: [],
      rows,
      buttons,
    };
  }

  function describeIdle(s) {''')

    patch(PANELS, '''    if (s.pickupPicks > 0) return describePickupCard(s);''',
                  '''    if (s.pickupPicks > 0) return describePickupCard(s);
    // §293：加牌的欠账压过一切面板（与上面那条同一个理由）。
    if (s.pickupAdd > 0) return describePickupAdd(s);''')

    # 奖励屏上的 `singing_bowl`
    patch(PANELS, '''    return {
      title: `战斗奖励 · 已得 ${s.rewardGold} 金 · 选一张牌`,
      lines: [],
      rows,
      buttons: [{ id: "skip", label: "跳过", action: { kind: "skip_reward" } }],
    };''', '''    const buttons = [{ id: "skip", label: "跳过", action: { kind: "skip_reward" } }];
    // §293：`singing_bowl` —— "加牌时可以不拿牌、改拿 +2 上限"。只在**牌还在**的时候画：
    // 牌已经被拿走之后，这条动作会被内核拒（`EmptyOffer`），画出来就是死按钮。
    if (s.singingBowl && (s.rewardCards || []).length > 0) {
      buttons.unshift({
        id: "max_hp",
        label: "+2 上限（不拿牌）",
        action: { kind: "take_max_hp_instead" },
      });
    }
    return {
      title: `战斗奖励 · 已得 ${s.rewardGold} 金 · 选一张牌`,
      lines: [],
      rows,
      buttons,
    };''')
    print('web done')


main()

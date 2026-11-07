"""§274 页面：拾取时的牌组选择面板（`pickupPicks > 0` 时**优先**画它）。

面板形状照 `describeEventCard`（同一类"要一个牌组下标"的问句），但它**不靠 `pending`**：
遗物欠的这几步可以叠在奖励屏/宝箱屏上，所以判据是 `pickupPicks > 0` —— 而它在 `describe`
最前面，所以它压过后面所有面板，选完自然回到原来那一屏。
"""
import io

PANELS = 'D:/Vibe/sts-tui/web/ui_panels.js'
INDEX = 'D:/Vibe/sts-tui/web/index.html'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


PANEL = '''  /// §274: a relic that owes a deck edit (`empty_cage` 2 removals, `astrolabe` 3 transforms).
  ///
  /// **不靠 `pending`**：遗物欠的这几步可以叠在奖励屏/宝箱屏上（打完 Boss 拿 Boss 遗物、还想接着
  /// 拿卡牌奖励那条路径）。所以判据是 `pickupPicks > 0`，而它在 `describe` **最前面** ——
  /// 于是它压过后面所有面板，选完自然回到原来那一屏。
  function describePickupCard(s) {
    const names = {
      1: "移除哪一张牌？",
      2: "升级哪一张牌？",
      3: "转化哪一张牌？",
      4: "转化并升级哪一张牌？",
    };
    const what = names[s.pickupChange] || "选一张牌";
    const left = s.pickupPicks > 1 ? `（还要选 ${s.pickupPicks} 张）` : "";
    return {
      title: "遗物 · " + what + left,
      lines: [],
      rows: [],
      buttons: [{ id: "pick", label: "选一张牌", action: { kind: "pickup_card" } }],
    };
  }

'''


def main():
    p = io.open(PANELS, encoding='utf-8').read()

    # ① 面板函数（放在 describeEventCard 之前）
    p = patch(p, '''  /// §143: an event choice that edits the deck leaves a pick owed (`Pending::EventCard` = 8).''',
              PANEL + '''  /// §143: an event choice that edits the deck leaves a pick owed (`Pending::EventCard` = 8).''',
              'panel fn')

    # ② describe：拾取欠账优先
    p = patch(p, '''  function describe(s) {
    if (s.cleared) return describeCleared(s);''',
              '''  function describe(s) {
    // §274：遗物欠着的牌组编辑**优先于一切面板** —— 它可能叠在奖励屏/宝箱屏上，
    // 而"还要选几张"是玩家此刻唯一能做的事。
    if (s.pickupPicks > 0) return describePickupCard(s);
    if (s.cleared) return describeCleared(s);''', 'dispatch')

    io.open(PANELS, 'w', encoding='utf-8', newline='\n').write(p)

    # ③ index.html：快照字段 + 一个动作
    i = io.open(INDEX, encoding='utf-8').read()
    i = patch(i, '''    unknownRoom: ex.rd_run_observe(18),''',
              '''    unknownRoom: ex.rd_run_observe(18),
    /// §274：遗物欠着几次牌组编辑（`empty_cage` = 2、`astrolabe` = 3），以及是哪一种。
    /// 它们是**独立于 `pending`** 的一对字段 —— 见 `ui_panels.js::describePickupCard`。
    pickupPicks: ex.rd_run_pickup_picks(),
    pickupChange: ex.rd_run_pickup_change(),''', 'snapshot')
    i = patch(i, '''  begin_fight: () => beginFight(),''',
              '''  begin_fight: () => beginFight(),
  /// §274：拾取时的牌组编辑（`pickupPicks > 0` 时面板上只有这一个按钮）。
  pickup_card: () =>
    showDeckPicker("选一张牌", (index) => act(() => ex.rd_run_pickup_card(index), "拾取")),''', 'action')
    io.open(INDEX, 'w', encoding='utf-8', newline='\n').write(i)
    print('page: pickup panel + action')


main()

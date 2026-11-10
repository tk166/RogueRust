"""§325 `web/map_test.mjs` 的 `settleHere` 改成**循环**。

这个助手已经三次跟不上内核了：§272（`?` 房会掷出四种结果）、§320/§324（候选面板与
"欠几次改牌"）、§325（事件把这一格变成战斗，且 `After` 段会回到事件）。
每次的形态都一样：助手按"我认识的那几种"分派，新的一种就**停在半途**，而下一条
`rd_run_step` 报的是"这一格还没结算" —— 错误指到地图，真因在这一行。

改成"每轮做一件事，直到无事可做"之后，加新待决只需要加一个分支，不会再漏掉"收尾之后
又出现的新状态"（`After` 段、奖励屏、欠账）。
"""

import io

PATH = 'web/map_test.mjs'

OLD_START = 'const settleHere = () => {'
OLD_END = '};\n\nconst view = () => M.describeMap(io);'

NEW = '''const settleHere = () => {
  if (ex.rd_run_node_kind() < 0) return;
  const kind = ex.rd_run_node_kind();
  if (ex.rd_run_begin_node() !== 0) return;
  // 每轮做**一件事**，直到节点结算（§325：写成循环而不是 if/else 链 —— 一次收尾之后
  // 可能又出现新的待决：`After` 段回到事件、奖励屏、事件把这一格变成战斗、拾取欠账）。
  for (let round = 0; round < 16; round++) {
    const pending = ex.rd_run_pending();
    // §320：事件摊开的候选面板（"从 n 张里选一张"）。
    if (pending === 9) {
      if (ex.rd_run_event_offer_take(0) !== 0) return;
      continue;
    }
    // §143：事件选项可能**欠一个牌组下标**（`Pending::EventCard`）。
    if (pending === 7 || pending === 8) {
      if (ex.rd_run_pick_event_card(0) !== 0) return;
      continue;
    }
    if (pending === 5) {
      // §279：★ 不能盲选槽 0 —— 它可能是一条**条件选项**（`forgotten_altar` 的
      // `[Offer: Golden Idol]` 要有金像）。盲选会点一条锁着的路，内核拒（-2），
      // 屏幕上什么都没变，于是下一格报 "step refused" 并指到地图。
      let slot = -1;
      for (let candidate = 0, n = ex.rd_run_event_option_count(); candidate < n; candidate++) {
        if (ex.rd_run_event_option_available(candidate) === 1) { slot = candidate; break; }
      }
      if (slot < 0) return;                       // 没有可用选项：留给调用方报错
      if (ex.rd_run_choose(slot) !== 0) return;   // 内核拒了：同上
      continue;
    }
    if (pending === 1) { ex.rd_run_rest(); continue; }
    if (pending === 2) { ex.rd_run_leave(); continue; }
    if (pending === 3) { ex.rd_run_open_chest(); continue; }
    // §263：一场战斗付的是**奖励屏**，它挡着下一步（"action index out of range"）。
    if (pending === 4) { ex.rd_run_skip_reward(); continue; }
    // 没有待决：还剩什么就是"这一格本身要做的事"。
    if (pending === 0) {
      // §324：拾取欠账（`transform_choose` / `empty_cage` / `astrolabe`）不占 `pending`。
      if (ex.rd_run_pickup_picks() > 0) {
        if (ex.rd_run_pickup_card(0) !== 0) return;
        continue;
      }
      // §286/§325：事件把这一格变成了一场战斗（`dead_adventurer` 的伏击、`mushrooms` 的
      // `[Stomp]`）。不打完它，节点永远不结算。
      const isFight = ex.rd_run_event_fight() > 0 || kind === 1 || kind === 2 || kind === 7 ||
        // 掷出怪物的 `?` 房：`pending` 是 0，但脚下是 kind 5。
        (kind === 5 && ex.rd_run_unknown_room() === 2);
      if (isFight) {
        if (ex.rd_run_fight_begin() !== 0) return;
        if (ex.rd_run_fight_end() !== 0) return;
        continue;
      }
    }
    return;   // 无事可做（已结算）
  }
};
'''

NEW2 = OLD_END


def main():
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(OLD_START) == 1, 'settle start'
    assert 'for (let round = 0; round < 16; round++)' not in t, 'already patched'
    start = t.index(OLD_START)
    end = t.index(OLD_END)
    t = t[:start] + NEW + t[end + len('};\n\n') :]
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
    print('settleHere rewritten as a loop')


main()

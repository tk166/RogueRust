"""幕间 UI：幕数显示 + SC-13（幕通关 + Boss 遗物三选一）。"""

import io


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. host：三个读取 + 一个动作 ────────────────────────────────────────────
patch('web-next/src/wasm/host.ts', [
    (
        'boss relic reads',
        '''  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */''',
        '''  // ── 幕间 Boss 遗物三选一（§370）────────────────────────────────────────
  /** 待选几件（`0` = 没有待选；`-1` = 没有局）。 */
  bossRelicCount(): number {
    return (this.ex.rd_run_boss_relic_count as () => number)();
  }

  /** 待选第 `slot` 件的 id（越界是空串）。 */
  bossRelicId(slot: number): string {
    const len = (this.ex.rd_run_boss_relic_id_len as (slot: number) => number)(slot);
    if (len <= 0) return "";
    return this.readText(
      () => len,
      (ptr) =>
        (this.ex.rd_run_boss_relic_id_into as (slot: number, ptr: number) => number)(slot, ptr)
    );
  }

  /** 取走第 `slot` 件。`0` 拿到 / `-1` 没有这个槽 / `-2` 拒绝（原因在 error 缓冲）。 */
  takeBossRelic(slot: number): number {
    return (this.ex.rd_run_take_boss_relic as (slot: number) => number)(slot);
  }

  /**
   * **夹具专用**：强制生成一次三选一（`?debug`）。
   *
   * 与换幕时走的是**同一个** `offer_boss_relics`，只是触发时机由调用方决定 —— 闸门要验
   * "三选一的界面与取走路径"，而打赢一场 Boss 战没法按需制造。
   */
  offerBossRelics(): number {
    return (this.ex.rd_run_offer_boss_relics as () => number)();
  }

  /** 节点 kind 的**内核名字**（`rd_run_kind_name_*`），用于诊断与"未知 kind"兜底。 */''',
    ),
])

# ── 2. scene.ts：SC-13 + 顺序（奖励之后、地图之前）────────────────────────────
patch('web-next/src/run/scene.ts', [
    (
        'scene const',
        '''  reward: "SC-04",''',
        '''  reward: "SC-04",
  /** §370：幕间 Boss 遗物三选一（也是"这一幕通关"那一屏）。 */
  bossRelic: "SC-13",''',
    ),
    (
        'scene order',
        '''  SCENE.reward,
  SCENE.event,''',
        '''  SCENE.reward,
  // §370：三选一排在奖励屏**之后** —— 打赢 Boss 那一步会先掷奖励屏（`Pending::Reward`），
  // 三选一是奖励屏关掉之后才该出现的。反过来会把奖励顶掉。
  SCENE.bossRelic,
  SCENE.event,''',
    ),
    (
        'scene input',
        '''  readonly pickupPicks: number;
  readonly pickupAdd: number;''',
        '''  readonly pickupPicks: number;
  readonly pickupAdd: number;
  /** §370：幕间待选的 Boss 遗物件数（`0` = 没有）。 */
  readonly bossRelicCount: number;''',
    ),
    (
        'scene rule',
        '''  // 14. 站在战斗节点上但还没开打（`?` 房只有掷出"怪物"才算）。''',
        '''  // 13b. 幕间三选一（§370）。排在 `pending == 0` 之后：奖励屏关掉才轮到它。
  if (input.bossRelicCount > 0) return SCENE.bossRelic;

  // 14. 站在战斗节点上但还没开打（`?` 房只有掷出"怪物"才算）。''',
    ),
    (
        'implemented',
        '''    case SCENE.reward:
    case SCENE.shop:''',
        '''    case SCENE.reward:
    case SCENE.bossRelic:
    case SCENE.shop:''',
    ),
    (
        'label',
        '''    case SCENE.reward:
      return "战斗奖励";''',
        '''    case SCENE.reward:
      return "战斗奖励";
    case SCENE.bossRelic:
      return "幕间 · Boss 遗物";''',
    ),
])
print('done')

"""把 `settlePending` 搬进 `WasmHost`：不要给探针开 `rawExport` 逃生口。

plan P2 的退出条件之一是"组件不直接触碰 `instance.exports`"。上一版为了省事加了个
`host.rawExport(name)` 给探针调 `rd_run_rest` / `rd_run_leave` / … —— 那等于把刚关上的门又开了，
而且一旦有人拿它去调 `rd_env_step`，`GameStore` 的"唯一发起动作的地方"就失效了。

改成 host 上的两个窄方法：
* `runRaw()` —— 走路需要的几个运行层字段（节点类型 / 是否结算 / 是否局终 / pending / 事件伏击）；
* `settlePendingRun()` —— 按 `pending` 取值做最小结算（1..9 每一档都要有人处理）。
"""

import io

HOST = 'web-next/src/wasm/host.ts'
PROBE = 'web-next/src/p2probe.ts'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── host：runRaw + settlePendingRun + runStep ───────────────────────────────
edit(
    HOST,
    '''  startRun(seed: number, ascension: number): void {''',
    '''  /** 走路需要的运行层字段（比 `run()` 多几个"只有遍历才用"的）。 */
  runRaw(): {
    pending: number;
    nodeKind: number;
    nodeResolved: number;
    over: number;
    eventFight: number;
  } {
    const call = (name: string) => (this.ex[name] as () => number)();
    return {
      pending: call("rd_run_pending"),
      nodeKind: call("rd_run_node_kind"),
      nodeResolved: call("rd_run_node_resolved"),
      over: call("rd_run_over"),
      eventFight: call("rd_run_event_fight"),
    };
  }

  runStep(index: number): number {
    return (this.ex.rd_run_step as (index: number) => number)(index);
  }

  /**
   * 按 `pending` 做**最小结算**（照 `native/ui_abi_dump.mjs` 的 `settleHere`）。
   *
   * `pending` 九档：1 篝火 / 2 商店 / 3 宝箱 / 4 奖励 / 5 事件 / 6 起始祝福 /
   * 7 祝福选牌 / 8 事件选牌 / 9 事件候选。**每一档都要有人处理**，否则走路会卡在那一屏
   * （P2 第一版就卡在 7）。
   *
   * 返回是否结算成功；`pending === 0`（没有待决屏）返回 false —— 那是"该 begin_node/走一步"，
   * 不是"结算"。
   */
  settlePendingRun(): boolean {
    const call = (name: string, ...args: number[]) =>
      (this.ex[name] as (...values: number[]) => number)(...args);
    switch (this.runRaw().pending) {
      case 1:
        return call("rd_run_rest") === 0;
      case 2:
        return call("rd_run_leave") === 0;
      case 3:
        call("rd_run_open_chest");
        return call("rd_run_leave") === 0;
      case 4:
        return call("rd_run_skip_reward") === 0;
      case 5:
        return call("rd_run_choose", 0) === 0;
      case 6:
        this.chooseStart(0);
        return true;
      case 7:
        return call("rd_run_pick_blessing_card", 0) === 0;
      case 8:
        return call("rd_run_pick_event_card", 0) === 0;
      case 9:
        return call("rd_run_event_offer_take", 0) === 0;
      default:
        return false;
    }
  }

  startRun(seed: number, ascension: number): void {''',
    'host runRaw/settle',
)

# ── probe：删掉本地 settlePending，改调 host 方法 ──────────────────────────
t = io.open(PROBE, encoding='utf-8').read()
start = t.index('/**\n * 非战斗 pending 的最小结算')
end = t.index('/** 摘要：只把闸门要断言的东西拿出来')
assert 'settlePending' in t[start:end] and len(t[start:end]) < 1600, 'settlePending 区块形状不符'
t = t[:start] + t[end:]
io.open(PROBE, 'w', encoding='utf-8', newline='\n').write(t)

edit(
    PROBE,
    '''      // 非战斗的 pending：用最小动作settle 掉
      const settled = settlePending(host);''',
    '''      // 非战斗的 pending：用最小动作 settle 掉（实现搬到了 host，导出不外泄）
      const settled = host.settlePendingRun();''',
    'probe settle call',
)

edit(
    PROBE,
    '''        // 没有未结算节点：走一步（选第一个可用动作）
        if (host.runStep(0) !== 0) break;''',
    '''        // 没有未结算节点：走一步（选第一个可用动作）
        if (host.runStep(0) !== 0) break;''',
    'probe runStep (unchanged)',
)
print('settle moved into host')

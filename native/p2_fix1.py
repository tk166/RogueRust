"""修三处：`_into` 的参数顺序、无战斗会话时的解码、走到战斗的路径。

## ① `_into` 的参数顺序**每个函数都不一样**

实测签名（`kernel/rd-wasm/src/{lib,run}.rs`）：

| 导出 | 签名 |
|---|---|
| `rd_env_card_name_into` / `_card_text_into` / `_enemy_name_into` | `(index, ptr)` |
| `rd_run_boss_id_into` / `_event_id_into` / `_encounter_id_into` | `(ptr)` |
| `rd_run_deck_id_into` / `_event_label_into` | `(index, ptr)` |

我原来写了一个 `readText(lenFn, intoFn, arg)` 固定按 `(ptr, arg)` 调 ⇒ `rd_env_card_name_into`
拿到 `ptr = 手牌槽位`、`index = 指针`，于是 `_into` 返回 -1。
改成**传两个闭包**（取长度 / 写进 ptr），从结构上不可能搞反。

## ② 没有战斗会话时整条向量是 **0**，不是 `-1`

"空槽 = -1"只在**有会话**时成立；没有会话时向量全 0，于是"扫 6 个槽位跳过 -1"会数出 6 个
`alive=0` 的敌人，与 header 的 0 冲突。正确做法是**先问有没有会话**（`rd_env_active_slot() !== -3`），
没有就不解码 —— 这也符合 plan 里 SC-03 / SC-03b 的区分。

## ③ 走到战斗：不能"看到节点就 begin_node"

`pending` 有 9 种取值，`begin_node` 只对节点类有效；战斗节点要用 `fight_begin`。第一版直接
`beginNode()` 循环，卡在 `pending = 7`（选祝福牌）。照 `native/ui_abi_dump.mjs` 的
`walkToFightNode` + `settleHere` 移植：**每跳顶部先看 pending**，站在未结算节点上才 `begin_node`。
"""

import io

HOST = 'web-next/src/wasm/host.ts'
PROBE = 'web-next/src/p2probe.ts'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① readText 改成闭包 ────────────────────────────────────────────────────
edit(
    HOST,
    '''  // ── 文本（`_len` / `_into` 一对：先问长度，再写进模块自己的 scratch）──────────
  private readText(lenFn: (arg: number) => number, intoFn: (ptr: number, arg: number) => number, arg: number): string {
    const len = lenFn(arg);
    if (len < 0) return "";
    if (len === 0) return "";
    if (len > SCRATCH_CAPACITY) {
      throw new RangeError(`文本 ${len} 字节，超过 1 KiB scratch`);
    }
    const ptr = Number((this.ex.rd_env_scratch_buf as () => number)());
    const written = intoFn(ptr, arg);
    if (written !== len) {
      throw new Error(`_into 写了 ${written} 字节，_len 说 ${len}`);
    }
    return this.decoder.decode(new Uint8Array(this.ex.memory.buffer, ptr, len));
  }

  /** 手牌槽位的**显示名**（presentation only；ABI 冻结的那一半是 `def_slot`）。 */
  cardName(slot: number): string {
    return this.readText(
      this.ex.rd_env_card_name_len as (arg: number) => number,
      this.ex.rd_env_card_name_into as (ptr: number, arg: number) => number,
      slot
    );
  }

  /** 手牌槽位的规则文本。 */
  cardText(slot: number): string {
    return this.readText(
      this.ex.rd_env_card_text_len as (arg: number) => number,
      this.ex.rd_env_card_text_into as (ptr: number, arg: number) => number,
      slot
    );
  }

  /** 敌人墙位槽的显示名。 */
  enemyName(slot: number): string {
    return this.readText(
      this.ex.rd_env_enemy_name_len as (arg: number) => number,
      this.ex.rd_env_enemy_name_into as (ptr: number, arg: number) => number,
      slot
    );
  }''',
    '''  // ── 文本（`_len` / `_into` 一对：先问长度，再写进模块自己的 scratch）──────────
  /**
   * 读一段文本。
   *
   * ⚠️ 参数用**闭包**而不是 `(lenFn, intoFn, arg)`：`_into` 的参数顺序**每个函数都不一样**
   * （`rd_env_card_name_into(index, ptr)` vs `rd_run_boss_id_into(ptr)`），写死一种顺序必然
   * 有一半调反 —— 症状是 `_into` 返回 -1（把槽位当成了指针）。闭包让顺序在调用点显式写出来。
   */
  private readText(getLength: () => number, writeInto: (ptr: number) => number): string {
    const len = getLength();
    if (len <= 0) return "";
    if (len > SCRATCH_CAPACITY) {
      throw new RangeError(`文本 ${len} 字节，超过 1 KiB scratch`);
    }
    const ptr = Number((this.ex.rd_env_scratch_buf as () => number)());
    const written = writeInto(ptr);
    if (written !== len) {
      throw new Error(`_into 写了 ${written} 字节，_len 说 ${len}`);
    }
    return this.decoder.decode(new Uint8Array(this.ex.memory.buffer, ptr, len));
  }

  /** 手牌槽位的**显示名**（presentation only；ABI 冻结的那一半是 `def_slot`）。 */
  cardName(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_card_name_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_card_name_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }

  /** 手牌槽位的规则文本。 */
  cardText(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_card_text_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_card_text_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }

  /** 敌人墙位槽的显示名。 */
  enemyName(slot: number): string {
    return this.readText(
      () => (this.ex.rd_env_enemy_name_len as (index: number) => number)(slot),
      (ptr) => (this.ex.rd_env_enemy_name_into as (index: number, ptr: number) => number)(slot, ptr)
    );
  }''',
    'readText closures',
)

# ── ② 会话判定 + 快照守卫 ──────────────────────────────────────────────────
edit(
    HOST,
    '''  // ── 组合：读一份完整快照 ──────────────────────────────────────────────────
  snapshot(): CombatSnapshot {
    return decodeCombat(this.combatObservation(), this.actions());
  }''',
    '''  // ── 组合：读一份完整快照 ──────────────────────────────────────────────────
  /**
   * 有没有战斗会话。
   *
   * ⚠️ 判据是 `rd_env_active_slot() !== -3`（"查询不创建会话"的哨兵），**不是** `rd_env_done()`
   * —— 后者在没有会话时返回 1（"结束了"），反过来说不出"有没有战斗"。
   */
  hasCombatSession(): boolean {
    return (this.ex.rd_env_active_slot as () => number)() !== -3;
  }

  /**
   * 读一份完整战斗快照。
   *
   * ⚠️ 没有会话时**必须拒绝**：那时整条向量是 **0**（不是 -1），"空槽 = -1"的假设不成立，
   * 硬解码会数出 6 个 `alive=0` 的幽灵敌人（闸门 28 第一版就是这么炸的）。
   */
  snapshot(): CombatSnapshot {
    if (!this.hasCombatSession()) {
      throw new Error("没有战斗会话（rd_env_active_slot() = -3）：先 fight_begin");
    }
    return decodeCombat(this.combatObservation(), this.actions());
  }''',
    'session guard',
)

# ── ③ 走到战斗：照 dump 的 walkToFightNode 移植 ─────────────────────────────
edit(
    PROBE,
    '''  startFight(seed: number) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const trail: unknown[] = [];
    host.startRun(seed, 0);
    trail.push({ step: "start", run: host.run() });

    // 祝福：pending === 6（`StartOffer`）。选第 0 个候选。
    if (host.run().pending === 6) {
      host.chooseStart(0);
      trail.push({ step: "chooseStart", run: host.run() });
    }

    // 走到一个战斗节点：地图上逐个尝试 `begin_node`，直到 `in_fight` 或走不动。
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const run = host.run();
      if (run.inFight) break;
      const before = run.pending;
      const code = host.beginNode();
      trail.push({ step: "beginNode", code, before, run: host.run() });
      if (code !== 0) break;
      if (host.run().pending === 6) {
        host.chooseStart(0);
        continue;
      }
    }

    const fightCode = host.fightBegin();
    trail.push({ step: "fightBegin", code: fightCode, run: host.run() });
    state.store = new GameStore(host);
    return { trail, fightCode, snapshot: summarise() };
  },''',
    '''  /**
   * 从"没有局"走到**站在未结算的战斗节点上**，再 `fight_begin`。
   *
   * 移植自 `native/ui_abi_dump.mjs` 的 `walkToFightNode` + `settleHere`（那条路径是 P0 用
   * 真实 wasm 跑出来的，不是猜的）。关键顺序：**每跳顶部先看 `pending`**，站在未结算节点上
   * 才 `begin_node` —— 反过来就会"落到商店那格立刻 leave 掉"或卡在选牌屏。
   */
  startFight(seed: number) {
    const host = state.host;
    if (!host) throw new Error("先 load()");
    const trail: unknown[] = [];
    host.startRun(seed, 0);
    trail.push({ step: "start", run: host.run() });

    const fightNodeKinds = new Set([1, 2, 7]); // monster / elite / boss
    const isFightNode = () => {
      const raw = host.runRaw();
      if (fightNodeKinds.has(raw.nodeKind)) return true;
      // 事件引来的伏击（`?` 房）：kind 5 且 observe(18) === 2
      return raw.nodeKind === 5 && raw.eventFight > 0;
    };

    for (let hop = 0; hop < 40; hop += 1) {
      const raw = host.runRaw();
      if (raw.over === 1) break;
      if (raw.pending === 0) {
        if (raw.nodeKind >= 0 && raw.nodeResolved === 0) {
          if (isFightNode()) break; // 站到战斗节点上了
          host.beginNode();
          trail.push({ step: "beginNode", run: host.run() });
          continue;
        }
        // 没有未结算节点：走一步（选第一个可用动作）
        if (host.runStep(0) !== 0) break;
        continue;
      }
      // 非战斗的 pending：用最小动作settle 掉
      const settled = settlePending(host);
      trail.push({ step: "settle", pending: raw.pending, settled });
      if (!settled) break;
    }

    const fightCode = host.fightBegin();
    trail.push({ step: "fightBegin", code: fightCode, run: host.run() });
    if (fightCode === 0) state.store = new GameStore(host);
    return { trail, fightCode, snapshot: state.store ? summarise() : null };
  },''',
    'startFight walk',
)

# ── ④ settlePending 辅助 ───────────────────────────────────────────────────
edit(
    PROBE,
    '''const state: {
  host: WasmHost | null;
  store: GameStore | null;
  error: string | null;
} = { host: null, store: null, error: null };''',
    '''const state: {
  host: WasmHost | null;
  store: GameStore | null;
  error: string | null;
} = { host: null, store: null, error: null };

/**
 * 非战斗 pending 的最小结算（照 `ui_abi_dump.mjs` 的 `settleHere`）。
 *
 * `pending` 的取值：1 篝火 / 2 商店 / 3 宝箱 / 4 奖励 / 5 事件 / 6 起始祝福 /
 * 7 祝福选牌 / 8 事件选牌 / 9 事件候选。**每一档都必须有人处理**，否则走路会卡在那一屏
 * （第一版就是卡在 7）。
 */
function settlePending(host: WasmHost): boolean {
  const pending = host.run().pending;
  const call = (name: string, ...args: number[]) =>
    (host.rawExport(name) as (...values: number[]) => number)(...args);
  switch (pending) {
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
      host.chooseStart(0);
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
}''',
    'settlePending',
)
print('host + probe fixed')

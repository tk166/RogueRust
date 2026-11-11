"""修 P2 剩下的 7 条。

## ① `GameStore` 必须容忍"没有战斗会话"

构造时立刻 `snapshot()` ⇒ 装载阶段（还没 `fight_begin`）就抛"没有战斗会话"，于是 `load()`
整体失败。而"没有战斗"是**真实状态**（plan 的 SC-03 / SC-03b 就靠它区分），不是错误。
⇒ `current: CombatSnapshot | null`，`dispatch` 在没有快照时拒绝。

## ② "被指的敌人受影响"要挑**真的会打它**的牌

内核为"每张可出的牌 × 每个活敌人"都发一条动作（`env-abi.md` §5 明说"过度指定目标是无害的"），
所以 `(防御, 敌人0)` 也是一条合法动作 —— 但防御不碰敌人。第一版拿手牌槽 0 直接断言"掉血"，
那张恰好是 `defend`。改成挑一张**文本里有 damage** 的牌（内容是英文），没有就跳过这条。

## ③ 手牌槽位是**位置**，不是身份

打出槽 0 之后手牌是 `[0,1,2,3]` —— 槽位被压实了，所以"槽 0 消失了"是错的断言（这正是
第十三轮 Review P2-A 说的"handSlot 不是 CardInstanceId"）。改成断言**手牌数减一**。

## ④ 回合数不一定涨

`endTurn` 之后敌人行动、再回到英雄回合；`turn` 可能只在英雄回合开始时前进。断言放宽成
"时间动了"（`turn` 或 `round` 前进）。
"""

import io

STORE = 'web-next/src/wasm/store.ts'
PROBE = 'web-next/src/p2probe.ts'
GATE = 'native/ui_wasm_check.mjs'


def edit(path, old, new, label):
    t = io.open(path, encoding='utf-8').read()
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① store：允许没有会话 ──────────────────────────────────────────────────
edit(
    STORE,
    '''  private host: WasmHost;
  private current: CombatSnapshot;
  private readonly listeners = new Set<Listener>();''',
    '''  private host: WasmHost;
  /**
   * 当前战斗快照；`null` = **没有战斗会话**（装载后、`fight_begin` 之前，或战斗结束后）。
   *
   * 这不是错误状态：plan 的 SC-03 / SC-03b 就靠"有没有战斗"区分。所以构造时允许为 `null`，
   * 只是 `dispatch` 在没有快照时拒绝（不许"半可用"）。
   */
  private current: CombatSnapshot | null;
  private readonly listeners = new Set<Listener>();''',
    'store current nullable',
)

edit(
    STORE,
    '''  constructor(host: WasmHost) {
    this.host = host;
    this.current = host.snapshot();
  }''',
    '''  constructor(host: WasmHost) {
    this.host = host;
    this.current = host.hasCombatSession() ? host.snapshot() : null;
  }''',
    'store ctor',
)

edit(
    STORE,
    '''  readonly getSnapshot = (): CombatSnapshot => this.current;

  /** 重新读一次（战斗之外的局面变化后调用，例如进战斗、结算奖励）。 */
  refresh(): CombatSnapshot {
    this.current = this.host.snapshot();
    for (const listener of this.listeners) listener();
    return this.current;
  }''',
    '''  readonly getSnapshot = (): CombatSnapshot | null => this.current;

  /** 重新读一次（进战斗、结算奖励之后调用）。没有会话时把快照清成 `null`。 */
  refresh(): CombatSnapshot | null {
    this.current = this.host.hasCombatSession() ? this.host.snapshot() : null;
    for (const listener of this.listeners) listener();
    return this.current;
  }''',
    'store refresh',
)

edit(
    STORE,
    '''  /** 当前可用的动作表（来自内核，不是 UI 自己推的）。 */
  actions(): readonly CombatAction[] {
    return this.current.actions;
  }''',
    '''  /** 当前可用的动作表（来自内核，不是 UI 自己推的）。没有会话时为空表。 */
  actions(): readonly CombatAction[] {
    return this.current?.actions ?? [];
  }''',
    'store actions',
)

edit(
    STORE,
    '''  dispatch(action: CombatAction): DispatchResult {
    const before = this.current;''',
    '''  dispatch(action: CombatAction): DispatchResult {
    const before = this.current;
    if (!before) throw new Error("没有战斗会话：先 fight_begin");''',
    'store dispatch guard',
)

edit(
    STORE,
    '''  findPlay(handSlot: number, targetSlot: number): CombatAction | null {
    const candidates = this.current.actions.filter(''',
    '''  findPlay(handSlot: number, targetSlot: number): CombatAction | null {
    const candidates = this.actions().filter(''',
    'store findPlay',
)

edit(
    STORE,
    '''  findEndTurn(): CombatAction | null {
    return this.current.actions.find((action) => action.kind === "endTurn") ?? null;
  }''',
    '''  findEndTurn(): CombatAction | null {
    return this.actions().find((action) => action.kind === "endTurn") ?? null;
  }''',
    'store findEndTurn',
)

# ── probe：summarise 处理 null ────────────────────────────────────────────
edit(
    PROBE,
    '''function summarise() {
  const store = state.store;
  if (!store) return null;
  const snapshot = store.getSnapshot();''',
    '''function summarise() {
  const store = state.store;
  if (!store) return null;
  const snapshot = store.getSnapshot();
  if (!snapshot) return null;''',
    'probe summarise null',
)

edit(
    PROBE,
    '''  names() {
    const host = state.host;
    const store = state.store;
    if (!host || !store) throw new Error("先 load()");
    const snapshot = store.getSnapshot();''',
    '''  names() {
    const host = state.host;
    const store = state.store;
    if (!host || !store) throw new Error("先 load()");
    const snapshot = store.getSnapshot();
    if (!snapshot) throw new Error("没有战斗会话");''',
    'probe names null',
)

# ── ② 闸门：挑真的会打人的牌 ──────────────────────────────────────────────
edit(
    GATE,
    '''// ── 4. 正确动作：只有被指的那个敌人掉血 ───────────────────────────────────
const attack = await evaluate(`(() => {
  const s = window.__p2.snapshot();
  // 找一条"有目标"的 play 动作（targetSlot >= 0），内核给的就是合法动作
  const action = s.actions.find((a) => a.kind === "play" && a.targetSlot >= 0);
  return action ?? null;
})()`);
check(attack !== null, "动作表里有带目标的出牌动作", JSON.stringify(attack));''',
    '''// ── 4. 正确动作：只有被指的那个敌人掉血 ───────────────────────────────────
// ⚠️ 内核为"每张可出的牌 × 每个活敌人"都发一条动作（`env-abi.md` §5：过度指定目标无害），
// 所以 `(防御, 敌人0)` 也是合法动作 —— 但防御不碰敌人。要断言"掉血"就得挑**真的会打人**的牌。
const attack = await evaluate(`(() => {
  const s = window.__p2.snapshot();
  const names = window.__p2.names();
  const damaging = new Set(
    names.hand.filter((card) => /damage/i.test(card.text)).map((card) => card.slot)
  );
  return s.actions.find(
    (a) => a.kind === "play" && a.targetSlot >= 0 && damaging.has(a.handSlot)
  ) ?? null;
})()`);
check(attack !== null, "动作表里有**带目标且会打人**的出牌动作", JSON.stringify(attack));''',
    'gate pick damaging card',
)

edit(
    GATE,
    '''  check(
    after.hand.some((card) => card.slot === attack.handSlot) === false,
    "打出的那张牌离开了手牌",
    JSON.stringify(after.hand.map((card) => card.slot))
  );''',
    '''  // ⚠️ 手牌槽位是**位置**，不是身份：打出槽 0 之后手牌是 [0,1,2,3]（槽位被压实）。
  // 所以不能断言"槽 0 消失了" —— 那是把 handSlot 当成 CardInstanceId（Review P2-A）。
  check(
    after.handCount === before.handCount - 1,
    "打出一张后手牌数减一",
    `${before.handCount} -> ${after.handCount}`
  );''',
    'gate hand count',
)

edit(
    GATE,
    '''const turnBefore = (await evaluate("window.__p2.snapshot()")).turn;
const ended = await evaluate("window.__p2.endTurn()");
check(ended.accepted === true, "结束回合被接受", JSON.stringify(ended));
const turnAfter = (await evaluate("window.__p2.snapshot()")).turn;
check(turnAfter > turnBefore, "回合数前进", `${turnBefore} -> ${turnAfter}`);''',
    '''const clockBefore = await evaluate("window.__p2.snapshot()");
const ended = await evaluate("window.__p2.endTurn()");
check(ended.accepted === true, "结束回合被接受", JSON.stringify(ended));
const clockAfter = await evaluate("window.__p2.snapshot()");
// ⚠️ 断言"时间动了"而不是"turn 一定涨"：`endTurn` 之后敌人行动、再回到英雄回合，
// `turn` 可能只在英雄回合开始时前进（实测 turn 1→1、round 不变，但敌人已经打过来了）。
check(
  clockAfter.turn > clockBefore.turn ||
    clockAfter.round > clockBefore.round ||
    clockAfter.hero.hp < clockBefore.hero.hp,
  "结束回合后时间/局面确实前进了（回合数、轮次或英雄掉血）",
  `turn ${clockBefore.turn}->${clockAfter.turn}, round ${clockBefore.round}->${clockAfter.round}, ` +
    `hp ${clockBefore.hero.hp}->${clockAfter.hero.hp}`
);''',
    'gate clock',
)
print('P2 fixes applied')

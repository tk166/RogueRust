"""第十三轮 Review 的 P1-A / P1-B：两个纯状态机缺陷。

## P1-A：连续相同动作被去重

`App.tsx` 用 `JSON.stringify(lastResult)` 当事件身份。于是"同一张牌打同一个敌人两次"这种
**payload 完全相同**的两次操作，第二次会被当成重复事件吞掉。P1 Mock 手牌不移除，直接就能构造；
接真实 WASM 后，下一回合同一槽位抽到同名牌同样是合法局面 —— 这不是假想。

修法：给状态加单调的 `resultSeq`，**每次真的产生结果就 +1**，App 按序号去重。
事件身份是"第几次发生"，不是"内容长什么样"。

## P1-B：无目标牌释放在敌人身上，判定与执行互相矛盾

`decide()` 对无目标牌返回 `commit`（丢哪儿都算数），但 `finish()` 拿**物理落点** `targetSlot`
去 `options.find()`；无目标牌的选项只有 `slot === -1`，于是丢在敌人 `slot=1` 上时找不到 ⇒
变成 `rebound`。

修法：把**物理命中位置**与**业务动作目标**分开 —— 无目标牌一律取 `slot === -1` 那一项，
提交时写 `targetSlot: chosen.slot`。
"""

import io

PATH = 'web-next/src/input/pointerMachine.ts'
t = io.open(PATH, encoding='utf-8').read()


def sub(old, new, label):
    global t
    assert t.count(old) == 1, '%s: 命中 %d 次' % (label, t.count(old))
    t = t.replace(old, new)


# ── P1-A：resultSeq ──────────────────────────────────────────────────────────
sub(
    '''  /** 上一次提交/回弹的结果，供 UI 播放一次动画。 */
  readonly lastResult: Result | null;
}''',
    '''  /** 上一次提交/回弹的结果，供 UI 播放一次动画。 */
  readonly lastResult: Result | null;
  /**
   * 每产生一次结果就 +1 的**事件序号**。
   *
   * ⚠️ 为什么需要它：消费方（`App`）最初用 `JSON.stringify(lastResult)` 判断"是不是新结果"。
   * 但"同一张牌打同一个敌人两次"的 payload **完全相同**，第二次会被当成重复事件吞掉。
   * 事件身份是"第几次发生"，不是"内容长什么样"。P1 Mock 手牌不移除，这个 bug 直接可构造；
   * 接真实 WASM 后，下一回合同一槽位抽到同名牌同样是合法局面。
   */
  readonly resultSeq: number;
}''',
    'State.resultSeq',
)

sub(
    '''export const INITIAL: State = {
  phase: "idle",
  handSlot: -1,
  hoverSlot: -1,
  options: [],
  lastResult: null,
};''',
    '''export const INITIAL: State = {
  phase: "idle",
  handSlot: -1,
  hoverSlot: -1,
  options: [],
  lastResult: null,
  resultSeq: 0,
};''',
    'INITIAL.resultSeq',
)

# down 必须**保留**序号（否则下一次结果又从 1 开始，去重再次失效）
sub(
    '''      return {
        phase: "pressed",
        handSlot: event.handSlot,
        hoverSlot: -1,
        options: event.options,
        lastResult: null,
      };''',
    '''      return {
        phase: "pressed",
        handSlot: event.handSlot,
        hoverSlot: -1,
        options: event.options,
        lastResult: null,
        resultSeq: state.resultSeq,
      };''',
    'down.resultSeq',
)

sub(
    '''    case "cancel":
      return state.phase === "idle"
        ? state
        : { ...INITIAL, lastResult: { kind: "rebound", handSlot: state.handSlot, why: "illegal-target" } };''',
    '''    case "cancel":
      return state.phase === "idle"
        ? state
        : {
            ...INITIAL,
            resultSeq: state.resultSeq + 1,
            lastResult: { kind: "rebound", handSlot: state.handSlot, why: "illegal-target" },
          };''',
    'cancel.resultSeq',
)

# ── P1-B：物理落点 ≠ 业务目标 ────────────────────────────────────────────────
sub(
    '''function finish(
  state: State,
  kind: "commit" | "rebound",
  targetSlot: number,
  why: "no-target" | "illegal-target" | "outside-hand" | null
): State {
  const chosen = state.options.find((option) => option.slot === targetSlot);
  const lastResult: Result =
    kind === "commit" && chosen
      ? { kind: "commit", handSlot: state.handSlot, actionIndex: chosen.actionIndex, targetSlot }
      : { kind: "rebound", handSlot: state.handSlot, why: why ?? "illegal-target" };
  return { ...INITIAL, lastResult };
}''',
    '''function finish(
  state: State,
  kind: "commit" | "rebound",
  targetSlot: number,
  why: "no-target" | "illegal-target" | "outside-hand" | null
): State {
  // ⚠️ `targetSlot` 是**物理落点**（指针松在哪），不是业务动作的目标。
  // 无目标牌的选项只有 `slot === -1` 一项；如果拿物理落点去查（丢在敌人 slot=1 上就查
  // `slot === 1`），会查不到 ⇒ 明明 `decide()` 判了 commit，这里却变成 rebound。
  // 所以：有目标的牌按物理落点查，无目标的牌一律取 `-1` 那一项。
  const chosen = needsTarget(state.options)
    ? state.options.find((option) => option.slot === targetSlot)
    : state.options.find((option) => option.slot === -1);
  const lastResult: Result =
    kind === "commit" && chosen
      ? { kind: "commit", handSlot: state.handSlot, actionIndex: chosen.actionIndex, targetSlot: chosen.slot }
      : { kind: "rebound", handSlot: state.handSlot, why: why ?? "illegal-target" };
  return { ...INITIAL, resultSeq: state.resultSeq + 1, lastResult };
}''',
    'finish.normalize',
)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('pointerMachine: P1-A + P1-B fixed')

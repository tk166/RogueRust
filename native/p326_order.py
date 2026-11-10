"""§326（第三个缺口）`Doubt` 的时序：回合末的 ③④ 挪到 ① 之前。

现状（`coverage-matrix.md` 里 `doubt` 那一行的偏差）：

    ① 牌在手过的生命周期节目（`Doubt` 在这里给 1 层 Weak）
    ② 弃手牌
    ③ turn-end 触发程序（**`standard.weak` 的衰减就在这里**）
    ④ 按时长的状态减 1

于是 Doubt 给的 Weak 在**同一次回合末**被自己的衰减吃掉；参考里它会留到下一回合
（StS 把 `Doubt` 的 `ApplyPowerAction` 排到队尾，衰减先跑完）。

修法：把 ③④ 提到 ① 之前 —— 顺序变成 **③ ④ ① ②**。三条已有的契约都保住：

* `Burn` / `Regret` 属于 ①，仍然在**弃手牌之前**（Regret 数的是完整手牌）—— 参考原话
  "before the end-of-turn discard, which is deferred" 说的就是这件事；
* `Doubt` 在 ① 里上的 Weak 落在衰减（③）**之后** ⇒ 活到下一回合；
* 敌人回合末给玩家上的状态（走同一个 ③）也不会被同一次回合末吃掉（与参考同侧）。

⚠️ 这是一次**顺序契约**的改动：有"同一回合末既有 ① 又有 ③"的战斗会换结果，所以先看
`golden` / `corpus` / `fight_diff` 有没有动 —— 动了就说明这条改动需要单独一轮基线重钉。
"""

import io

PATH = 'kernel/rd-core/src/turn.rs'

OLD = """    if let Some(actor) = actor {
        host.hand_turn_end_lifecycle(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        discard_hand(state, &actor, host)?;
        if stopped(state) {
            return Ok(());
        }
        host.run_turn_ended_triggers(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        host.decrease_timed_statuses(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
    }"""

NEW = """    // §326：顺序从 ①②③④ 改成 **③④①②**（见文件里"TurnEndedCombatEvent 顺序"那段注释）。
    //
    // 为什么：`Doubt` 的 `TurnEndInHand`（①）给 1 层 Weak，而 `standard.weak` 的衰减是 ③。
    // ① 在 ③ 之前 ⇒ 那一层 Weak 在**同一次**回合末被吃掉，而参考里它留到下一回合
    // （StS 把 Doubt 的 `ApplyPowerAction` 排到队尾，衰减先跑）。
    //
    // 三条既有契约都保住：`Burn`/`Regret` 仍在**弃手牌之前**（Regret 数完整手牌 ——
    // 参考原话 "before the end-of-turn discard, which is deferred"）；敌人给玩家上的
    // 回合末状态也不会被同一次回合末吃掉。
    if let Some(actor) = actor {
        host.run_turn_ended_triggers(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        host.decrease_timed_statuses(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        host.hand_turn_end_lifecycle(state, &actor)?;
        if stopped(state) {
            return Ok(());
        }
        discard_hand(state, &actor, host)?;
        if stopped(state) {
            return Ok(());
        }
    }"""


def sub(t, old, new, label):
    n = t.count(old)
    assert n == 1, '%s: %d' % (label, n)
    return t.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()
t = sub(t, OLD, NEW, 'turn end order')

# 那段"注册序"注释本身也要改：它现在写着 ① 排在最前。
t = sub(t, """    // ⚠️ ① 在参考里是**同一个事件的分发**里的一个处理器，所以它不花链号（整批只花事件那一个）；
    // 本内核把 ② ③ ④ 拆成了钩子/直接调用，① 仍然排在最前（Burn 的伤害因此在弃手牌**之前**
    // 就进了效果队列 —— 与参考"before the end-of-turn discard, which is deferred"同构）。""",
        """    // ⚠️ ① 在参考里是**同一个事件的分发**里的一个处理器，所以它不花链号（整批只花事件那一个）；
    // 本内核把 ② ③ ④ 拆成了钩子/直接调用。
    // §326：**实际执行序是 ③④①②**，与上面参考的注册序不同 —— 差的是 `Doubt` 的时序
    // （详见下面那段注释与 `docs/port-plan.md §326`）。`Burn`/`Regret` 仍在弃手牌之前，
    // 那一条与参考一致。""",
        'order comment')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('turn.rs: end-of-turn order is now ③④①②')

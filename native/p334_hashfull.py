"""§334 `hash_full`：把 `hash_golden` 之外的**模型字段**也纳入指纹。

## 为什么需要它

`hash_golden` 是参考引擎规范文本的**逐字节**复刻（`snapshot.rs`），而参考只哈希它自己的
一个子集。本项目里有几类字段**参考没有**（或者是它排掉的），于是它们**只进模型、不进指纹**：

* `PendingChoice`（§161.3：本移植把"正在等玩家选牌"做成状态，参考做成宿主委托）；
* `StatusInstance::source_combatant_id`（DoT 的出手方）；
* `ascension` / `encounter` / `heal_blocked`（本移植的 model-only 战斗事实）；
* `gold_carried_away` / `gold_gained`（跨层约定）；
* `next_combatant_number`（召唤编号，参考的哈希器不写它）；
* `cards_played_this_turn` / `cards_played_last_turn`（"本回合打了几张"）；
* `vacated_seat` / `extra_turn_for` / `forced_turn_ends`（回合机的瞬时段，但**影响以后**）。

后果是**具体的**：两个只在 `PendingChoice` 上不同的局面，`hash_golden` 相同 ⇒
"同一串动作 ⇒ 同一局"这条回放判据看不见"选牌的答案不一样"。

## 做法：严格超集

`write_full_hash_input` = `write_hash_input`（一个字节都不动）+ 一段 `--full--` 之后的内容。
这样：

* `hash_golden` 与它 85 份语料**完全不受影响**（这是加它的硬约束）；
* `hash_full` 对 `hash_golden` 的每一处差异都**敏感**（超集 ⇒ 不会漏）；
* 两个指纹都还能算，于是"这条改动该不该动基线"可以分开回答。

## 明确**不**覆盖的（每条都写理由，不留猜谜）

* 待决效果/事件/续延队列、节目帧、节目节点、循环、`chains` / `current_chain`：**瞬时执行状态**
  （`snapshot.rs` §C 第 9 条）—— 参考也按设计把它们排除在快照之外；
* `beat_log`：**已经发生过什么**的日志（§142）。两个只在日志上不同的局面，后续行为逐字相同；
* `end_turn_requested`：一个**请求**，下一次宿主调用就消费掉，不改变"以后会怎样"的判定；
* `CardPlayTurnStats` 的其余部分 / `TriggerActivity`：**模型里没有**（见下）。

⚠️ 最后一条很重要：`snapshot.rs` §A 列了 4 条"快照有、指纹没有"，其中 `CardPlayTurnStats`
的**全量**与 `TriggerActivity` 在本内核里**根本不存在**（只有 `cards_played_this/last_turn`
两个数）。所以 `hash_full` 覆盖不了它们 —— 不是"忘了"，是"没有"。那两项要等它们真的被
引入时再补，`port-plan` §334 记下这条。
"""

import io

SNAP = 'kernel/rd-core/src/snapshot.rs'
STATE = 'kernel/rd-core/src/state.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ══ 1. `StatusInstance::source_combatant_id` 的访问器（`pub` 字段已经有了，这里不用改）
# ══ 2. snapshot.rs：`write_full_hash_input` ═══════════════════════════════════
s = io.open(SNAP, encoding='utf-8').read()

ANCHOR = """pub fn write_hash_input(w: &mut TextWriter<'_>, s: &CombatState) {"""

FUNC = '''/// §334：`hash_full` 的输入文本 = [`write_hash_input`]（逐字节）+ `--full--` 之后的模型段。
///
/// 为什么是**追加**而不是另写一份：`hash_golden` 是参考规范文本的复刻，任何"顺手多写一行"
/// 都会移动 85 份语料。追加段让两个指纹各自回答各自的问题 ——
/// "与参考一致吗"（`hash_golden`）与"这一局真的相同吗"（`hash_full`）。
///
/// 段内顺序是**契约**（改顺序就换指纹），而且每条都写"有没有值"——`Option` 用 `none`/值，
/// 与规范文本里三种"没有值"的拼法无关（那三种是**参考**的格式，这里是本移植自己的）。
pub fn write_full_hash_input(w: &mut TextWriter<'_>, s: &CombatState) {
    write_hash_input(w, s);
    w.str("--full--\\n");

    // ① 本移植的 model-only 战斗事实。它们改变"以后会怎样"，参考没有这些字段。
    w.str("ascension=").i32(i32::from(s.ascension)).char('\\n');
    w.str("encounter=").u32(s.encounter).char('\\n');
    w.str("heal_blocked=").u32(u32::from(s.heal_blocked)).char('\\n');
    w.str("summon_num=").i32(s.next_combatant_number).char('\\n');
    w.str("gold_carried=").i32(s.gold_carried_away).char('\\n');
    w.str("gold_gained=").i32(s.gold_gained).char('\\n');

    // ② 回合机的三个瞬时段。它们"看起来是瞬时"，但都会改变下一次选意图/推进回合的结果：
    //    `vacated_seat` 决定席位交给谁、`extra_turn_for` 决定谁再来一次、
    //    `forced_turn_ends` 是页面读的计数。所以进 `hash_full`。
    w.str("vacated_seat=").opt_i32_blank(s.vacated_seat.map(i32::from)).char('\\n');
    w.str("extra_turn=").opt_str_none(s.extra_turn_for.as_ref().map(|id| id.as_str())).char('\\n');
    w.str("forced_ends=").i32(s.forced_turn_ends).char('\\n');

    // ③ 每回合的出牌数（§128 的 `cardsPlayedThisTurn` / `LastTurn`）。
    w.str("played_this=").i32(s.cards_played_this_turn).char('\\n');
    w.str("played_last=").i32(s.cards_played_last_turn).char('\\n');

    // ④ 状态实例的 `source_combatant_id`（DoT 的出手方）。规范文本不写它（`AppendStatus`
    //    只写七个字段），而"这一跳毒是谁下的"会改变力量加伤 ⇒ 它属于 `hash_full`。
    //    按 `(combatant, 实例 id)` 逐条写，**顺序 = 状态表顺序**（与 `s=` 行一致）。
    w.str("status_src=");
    for combatant in s.combatants().iter() {
        for instance in combatant.statuses() {
            w.str(instance.id.as_str()).char('@');
            match &instance.source_combatant_id {
                Some(source) => {
                    w.str(source.as_str());
                }
                None => {
                    w.str("none");
                }
            }
            w.char(',');
        }
    }
    w.char('\\n');

    // ⑤ **待决的选牌**（§161.3）—— 这一条是 `hash_full` 存在的主要理由。
    //
    //    `PendingChoice` 决定"玩家现在能选什么、选完发生什么"。两个只在它上面不同的局面，
    //    `hash_golden` 完全一样，而下一步的合法动作集不同 —— 回放判据看不见这种分叉。
    match s.pending_choice() {
        None => {
            w.str("choice=none\\n");
        }
        Some(choice) => {
            w.str("choice=")
                .str(choice.chooser.as_str())
                .char(':')
                .i32(i32::from(choice.source as u8))
                .char(':')
                .i32(i32::from(choice.min))
                .char(':')
                .i32(i32::from(choice.max))
                .char(':')
                .i32(choice_then_code(&choice.then))
                .char('\\n');
            // `Offered` 的候选是**卡定义**；`candidates` 是收窄后的合法实例清单（§226）。
            // 两个都写：前者决定"问什么"，后者决定"哪些能选"。
            w.str("choice_offered=");
            for definition in choice.offered.iter() {
                w.str(definition.as_str()).char(',');
            }
            w.char('\\n');
            w.str("choice_candidates=");
            for candidate in choice.candidates.iter() {
                w.str(candidate.as_str()).char(',');
            }
            w.char('\\n');
        }
    }
}

/// [`crate::state::ChoiceThen`] 的稳定编号（写进 `hash_full`，所以**不许重排**）。
///
/// `Copy` 带两个参数（`copies` / `into`），所以它比别的变体多写两格 —— 但为了指纹稳定，
/// 这里把参数**编码进同一个数**：`code = 变体号 * 256 + copies`，`into` 单独一行。
fn choice_then_code(then: &crate::state::ChoiceThen) -> i32 {
    use crate::state::ChoiceThen;
    match then {
        ChoiceThen::Exhaust => 1,
        ChoiceThen::DiscardThenDraw => 2,
        ChoiceThen::ToHand => 3,
        ChoiceThen::Copy { copies, .. } => 4 * 256 + i32::from(*copies),
        ChoiceThen::ToHandUnchanged => 5,
    }
}

'''

s = sub(s, ANCHOR, FUNC + ANCHOR, 'full hash fn')
io.open(SNAP, 'w', encoding='utf-8', newline='\n').write(s)
print('snapshot.rs: write_full_hash_input')

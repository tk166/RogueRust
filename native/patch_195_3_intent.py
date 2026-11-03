"""§195.3 (A2): weighted random intent choice with a **derived** draw, plus last-move memory left to
the content.

Why a derived draw and not a stream draw: `select_action` is called on **every observation**
(`rd-wasm::action_for` -> `select_action`), so the intent the player is looking at must be a pure
function of the state. A draw that consumed `random_step` would either change the preview on every
re-render or force a "planned action" field into the snapshot (which the reference does not have, so
every one of the 85 corpus hashes and 129 golden hashes would move).

So the seed is derived from `(seed, round, slot)`:

    step = round * 16 + slot.index          (fights are < 64 rounds, encounters <= 8 enemies)
    r    = rng::shuffled_pick_index(total_weight, seed, step)   -- uniform in [0, total_weight)

That is also *closer to StS* than one stream would be: StS rolls monster AI on a **separate**
`aiRng`, and this is the same separation without a second 8-byte state to snapshot. The deviation,
stated: the draw is not sequential -- two rules drawing in the same round do not see each other's
draws (they cannot: each rule is a pure function of round+slot). Content that wants "cannot use X
twice in a row" therefore records the **last move in a counter** (a `setCombatantCounter` in each
action's program) and excludes it with a second rule -- the same shape §194 already uses for
Guardian/The Champ/Awakened One phase flags.

Vocabulary: a rule's `Action` may be replaced by `Choice`, a list of `{Action, Weight}`:

    {"Condition": ..., "Priority": 40,
     "Choice": [{"Action": {"value": "the_collector.fireball"}, "Weight": 70},
                {"Action": {"value": "the_collector.buff"}, "Weight": 30}]}

The kernel refuses loudly instead of guessing: an empty list, a non-positive weight, a total above
255 (the pick index is a `u8`), more than `MAX_CHOICE_OPTIONS`, or an option whose action id is not
in `EACT` are all errors.
"""
import io


def sub(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new, what in pairs:
        assert src.count(old) == 1, "%s / %s: %d x %r" % (path, what, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("patched", path)


# ---------------------------------------------------------------- caps + error
sub("kernel/rd-core/src/intent.rs", [(
"""pub const MAX_INTENT_RULES: usize = 8;""",
"""pub const MAX_INTENT_RULES: usize = 8;

/// §195.3：一条规则的 `Choice` 最多几项。
///
/// 8 是**容量**，不是规则：超了报 [`IntentError::BadChoice`]，不截断 —— 截断会让"我写了 9 个
/// 权重"变成"最后那个永远不出现"，而屏幕上/战斗里都看不出来。
pub const MAX_CHOICE_OPTIONS: usize = 8;

/// §195.3：`Choice` 的权重总和上限。
///
/// [`crate::rng::shuffled_pick_index`] 的下标是 `u8`，所以 255 是抽签能覆盖的全部。超了**响亮
/// 失败**：把 `300` 悄悄截成 `255` 会让权重比例变形，而"哪个招更常见"正是这一节唯一的语义。
pub const MAX_CHOICE_WEIGHT: i32 = 255;""",
    "caps")])

sub("kernel/rd-core/src/intent.rs", [(
"""    /// 执行期错误（只有 [`execute_action`] 会产出）。
    Exec(ExecError),""",
"""    /// §195.3：规则的 `Choice` 不合法（空列表 / 权重 ≤ 0 / 总和 > 255 / 项数 > 8）。
    BadChoice,
    /// 执行期错误（只有 [`execute_action`] 会产出）。
    Exec(ExecError),""",
    "error variant")])

# ---------------------------------------------------------------- the read path
sub("kernel/rd-core/src/intent.rs", [(
"""            if condition_matches(state, content, actor, condition)? {
                let action_id = rule.str_field("Action")?.ok_or(IntentError::Missing("Action"))?;
                let reason = ChoiceReason::Rule {
                    index: rank as u16,
                    priority: priorities[index],
                };
                return Ok(Some(choice(content, action_id, reason)?));
            }""",
"""            if condition_matches(state, content, actor, condition)? {
                let reason = ChoiceReason::Rule {
                    index: rank as u16,
                    priority: priorities[index],
                };
                // §195.3：`Action`（单一）或 `Choice`（带权列表）。两者都有 ⇒ 响亮失败：
                // "同一个条件给出两个答案"没有正确的读法。
                let single = rule.str_field("Action")?;
                let weighted = rule.node_field("Choice")?;
                let action_id = match (single, weighted) {
                    (Some(_), Some(_)) => return Err(IntentError::Missing("Action")),
                    (Some(id), None) => id,
                    (None, Some(_)) => weighted_action_id(rule, state, round, at, content)?,
                    (None, None) => return Err(IntentError::Missing("Action")),
                };
                return Ok(Some(choice(content, action_id, reason)?));
            }""",
    "rule read")])

# ---------------------------------------------------------------- the pickers
sub("kernel/rd-core/src/intent.rs", [(
"""fn choice<'a>(
    content: &'a Content<'a>,
    action_id: &'a str,
    reason: ChoiceReason,
) -> Result<ActionChoice<'a>, IntentError> {""",
"""/// §195.3：`Choice` 抽一个 action id。
///
/// **派生**而不是消耗随机流：`step = round * 16 + 敌人槽位`，于是 `(seed, round, slot)` 唯一决定
/// 这一次抽签。`select_action` 每次观察都会被调（页面显示意图），所以它必须是纯函数 —— 消耗
/// `random_step` 的抽签会让"玩家看到的意图"每次重绘都可能变，或者逼出一个要进快照的
/// `planned_action` 字段（参考没有它，进快照就要动 85 份语料与 129 条 golden 的哈希）。
///
/// StS 自己在**另一条流**（`aiRng`）上掷骰，这里是同一件事的另一种实现，代价写明在
/// `port-plan.md` §195.3：两次抽签之间没有顺序关系（每条规则只是 round+slot 的函数）。
fn weighted_action_id<'a>(
    rule: crate::ir::NodeRef<'a>,
    state: &CombatState,
    round: i32,
    at: EnemySlot,
    content: &'a Content<'a>,
) -> Result<&'a str, IntentError> {
    // `Choice` is an `F_TERMLIST` of `{Action: F_STR, Weight: F_INT}` objects.
    let mut options = [0u16; MAX_CHOICE_OPTIONS];
    let count = rule.term_list_field("Choice", &mut options)?;
    if count == 0 || count > MAX_CHOICE_OPTIONS {
        return Err(IntentError::BadChoice);
    }
    let mut total: i32 = 0;
    let mut weights = [0i32; MAX_CHOICE_OPTIONS];
    let mut ids: [&'a str; MAX_CHOICE_OPTIONS] = [""; MAX_CHOICE_OPTIONS];
    for index in 0..count {
        let option = rule.child(options[index]);
        let weight = option.int_field("Weight")?.ok_or(IntentError::BadChoice)?;
        if weight <= 0 {
            return Err(IntentError::BadChoice);
        }
        total = total.saturating_add(weight);
        if total > MAX_CHOICE_WEIGHT {
            return Err(IntentError::BadChoice);
        }
        ids[index] = option.str_field("Action")?.ok_or(IntentError::BadChoice)?;
        weights[index] = weight;
    }
    let step = derived_step(round, at.index);
    let roll = crate::rng::shuffled_pick_index(total as usize, state.random_seed, step) as i32;
    let mut cursor = 0i32;
    for index in 0..count {
        cursor += weights[index];
        if roll < cursor {
            let action_id = ids[index];
            if content.lookup_in(action_id, EK_EACTION).is_none() {
                return Err(IntentError::UnknownAction);
            }
            return Ok(action_id);
        }
    }
    // `roll < total` always holds (`shuffled_pick_index` returns `[0, total)`), so reaching here means
    // the weight table itself is broken -- do **not** fall back to the last option (that would
    // silently reshape the weights).
    Err(IntentError::BadChoice)
}

/// §195.3：抽签用的 (seed, step) 里的 step。
///
/// `round * 16 + slot`：一场战斗不会超过 64 轮、一条遭遇最多 8 个敌人，所以这个映射是**单射**的
/// （同一轮里两个敌人拿到的 step 不同 ⇒ 它们不会抽到同一个数，否则"场上两只一样的怪"会永远
/// 同时出同一招，那种相关性在数值测试里看不出来）。
#[must_use]
pub fn derived_step(round: i32, slot: u16) -> i32 {
    round.saturating_mul(16).saturating_add(i32::from(slot))
}

fn choice<'a>(
    content: &'a Content<'a>,
    action_id: &'a str,
    reason: ChoiceReason,
) -> Result<ActionChoice<'a>, IntentError> {""",
    "picker")])

io.open("kernel/rd-core/src/intent.rs", "a", encoding="utf-8").close()
print("done -- now the NodeRef list helpers")

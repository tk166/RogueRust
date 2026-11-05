"""§216 kernel patch #1b: exec.rs — thread the turn's card count into the damage fold.

Positional replacement, because the same `fold(...)` tail appears four times and they are only
distinguishable by *where* they are. The two non-damage pipelines pass `NO_TURN_CARDS` (= -1), and
`fold` treats that as "this pipeline has no card count" and **fails loudly** if a spec asks for it
there -- no silent identity.
"""
import io

X = 'kernel/rd-core/src/exec.rs'
text = io.open(X, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


def nth(needle, replacements, what):
    """把 needle 的第 k 次出现替换成 replacements[k]（按出现顺序）。"""
    global text
    assert len(replacements) == text.count(needle), \
        '%s: found %d, replacements %d' % (what, text.count(needle), len(replacements))
    for new in replacements:
        index = text.find(needle)
        assert index >= 0
        text = text[:index] + new + text[index + len(needle):]


one("""    stacks: 0,
    operation: Operation::AddFlat,
    magnitude: 0,
    once_per_action: false,
    once_per_turn: false,
};""",
    """    stacks: 0,
    cards_played_this_turn: 0,
    operation: Operation::AddFlat,
    magnitude: 0,
    once_per_action: false,
    once_per_turn: false,
};

/// §216：**这条管线没有"本回合牌数"这个量**。`fold` 见到它就说明有人把 `Slow` 挂到了别的管线上
/// （格挡、回合开始抽牌/补能）—— 那是内容错误，必须响亮，而不是安静地按恒等算。
const NO_TURN_CARDS: i32 = -1;""",
    'NO_CANDIDATE + NO_TURN_CARDS')

one("""        // §210: `Intangible`'s "all damage becomes 1" -- `min(current, max(0, 1))`.
        status_bind::ModifierOp::ClampMax => Operation::ClampMax,""",
    """        // §216: `Slow`'s "+10% per card played **this turn**" -- the factor reads the kernel's
        // own counter, not the status' stacks.
        status_bind::ModifierOp::ScalePercentPerCardPlayedThisTurn => {
            Operation::ScalePercentPerCardPlayedThisTurn
        }
        // §210: `Intangible`'s "all damage becomes 1" -- `min(current, max(0, 1))`.
        status_bind::ModifierOp::ClampMax => Operation::ClampMax,""",
    'image_operation')

one("""fn damage_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    stage: ModifierTarget,
    owner: &CombatantId,
    content: Option<&'a Content<'a>>,
    kind: BindDamageKind,
) -> Result<i32, ExecError> {""",
    """fn damage_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    stage: ModifierTarget,
    owner: &CombatantId,
    content: Option<&'a Content<'a>>,
    kind: BindDamageKind,
    turn_cards: i32,
) -> Result<i32, ExecError> {""",
    'damage_stage signature')

one("""fn image_damage_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    stage: ModifierTarget,
    owner: &CombatantId,
    content: &'a Content<'a>,
    matching: StatusMatch,
    kind: BindDamageKind,
) -> Result<i32, ExecError> {""",
    """fn image_damage_stage<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    stage: ModifierTarget,
    owner: &CombatantId,
    content: &'a Content<'a>,
    matching: StatusMatch,
    kind: BindDamageKind,
    turn_cards: i32,
) -> Result<i32, ExecError> {""",
    'image_damage_stage signature')

one("""    if let Some(content) = content {
        return image_damage_stage(amount, statuses, stage, owner, content, matching, kind);
    }""",
    """    if let Some(content) = content {
        return image_damage_stage(
            amount, statuses, stage, owner, content, matching, kind, turn_cards,
        );
    }""",
    'damage_stage forward')

one("""fn fold<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    rows: &[Row<'a>],
    owner: &CombatantId,
    matching: StatusMatch,
) -> Result<i32, ExecError> {""",
    """fn fold<'a>(
    amount: i32,
    statuses: &[StatusInstance],
    rows: &[Row<'a>],
    owner: &CombatantId,
    matching: StatusMatch,
    turn_cards: i32,
) -> Result<i32, ExecError> {""",
    'fold signature')

one("""        *slot = Candidate {
            priority: row.priority,
            status_key,
            spec_index: row.spec_index,
            stacks,
            operation: row.operation,""",
    """        *slot = Candidate {
            priority: row.priority,
            status_key,
            spec_index: row.spec_index,
            stacks,
            cards_played_this_turn: turn_cards,
            operation: row.operation,""",
    'fold candidate')

# 早退之后立刻拒绝"这条管线没有牌数、却有人要牌数"。
one("""    if amount <= 0 || rows.is_empty() {
        return Ok(amount);
    }

    let mut pool = [0u8; STATUS_ID_POOL_CAP];""",
    """    if amount <= 0 || rows.is_empty() {
        return Ok(amount);
    }

    // §216：`NO_TURN_CARDS`（-1）表示"这条管线里没有本回合牌数"。见到要它的 spec ⇒ 拒绝。
    // 只写在这一个折叠器里：五条管线都从这里过，所以"挂错管线"只有这一条出口。
    if turn_cards < 0
        && rows
            .iter()
            .any(|row| row.operation == Operation::ScalePercentPerCardPlayedThisTurn)
    {
        return Err(ExecError::Modifier);
    }

    let mut pool = [0u8; STATUS_ID_POOL_CAP];""",
    'fold refusal')

# 四个 `matching,` 折叠尾：前两个是伤害（喂 turn_cards），后两个是格挡/补能（喂 -1）。
nth("""        matching,
    )""",
    ["""        matching,
        turn_cards,
    )""",
     """        matching,
        turn_cards,
    )""",
     """        matching,
        NO_TURN_CARDS,
    )""",
     """        matching,
        NO_TURN_CARDS,
    )"""],
    'matching folds')

# 两个 `StatusMatch::Exact` 折叠尾（回合开始抽牌 / 补能）⇒ -1。
nth("""        StatusMatch::Exact,
    )""",
    ["""        StatusMatch::Exact,
        NO_TURN_CARDS,
    )""",
     """        StatusMatch::Exact,
        NO_TURN_CARDS,
    )"""],
    'exact folds')

# 两处真正的伤害调用点。
one("""            amount = damage_stage(
                amount,
                source_combatant.statuses(),
                ModifierTarget::Source,
                &source,
                content,
                kind,
            )?;""",
    """            amount = damage_stage(
                amount,
                source_combatant.statuses(),
                ModifierTarget::Source,
                &source,
                content,
                kind,
                ctx.state.cards_played_this_turn,
            )?;""",
    'source stage call')

one("""        amount = damage_stage(
            amount,
            target_combatant.statuses(),
            ModifierTarget::Target,
            target,
            content,
            kind,
        )?;""",
    """        amount = damage_stage(
            amount,
            target_combatant.statuses(),
            ModifierTarget::Target,
            target,
            content,
            kind,
            ctx.state.cards_played_this_turn,
        )?;""",
    'target stage call')

# 测试里的 4 处 `damage_stage(` 调用：没有牌数可言，传 0（= 恒等，没有牌）。
for old, new in [
    ("""                damage_stage(
                    6,
                    &statuses,
                    ModifierTarget::Source,
                    &cid("hero"),
                    Some(&content),
                    BindDamageKind::Direct
                ),""",
     """                damage_stage(
                    6,
                    &statuses,
                    ModifierTarget::Source,
                    &cid("hero"),
                    Some(&content),
                    BindDamageKind::Direct,
                    0
                ),"""),
    ("""                damage_stage(
                    6,
                    &statuses,
                    ModifierTarget::Target,
                    &cid("hero"),
                    Some(&content),
                    BindDamageKind::Direct
                ),""",
     """                damage_stage(
                    6,
                    &statuses,
                    ModifierTarget::Target,
                    &cid("hero"),
                    Some(&content),
                    BindDamageKind::Direct,
                    0
                ),"""),
    ("""            damage_stage(
                6,
                &empty,
                ModifierTarget::Source,
                &cid("hero"),
                Some(&content),
                BindDamageKind::Direct
            ),""",
     """            damage_stage(
                6,
                &empty,
                ModifierTarget::Source,
                &cid("hero"),
                Some(&content),
                BindDamageKind::Direct,
                0
            ),"""),
    ("""            damage_stage(
                6,
                &empty,
                ModifierTarget::Target,
                &cid("hero"),
                Some(&content),
                BindDamageKind::Direct
            ),""",
     """            damage_stage(
                6,
                &empty,
                ModifierTarget::Target,
                &cid("hero"),
                Some(&content),
                BindDamageKind::Direct,
                0
            ),"""),
]:
    one(old, new, 'test damage_stage call')

io.open(X, 'w', encoding='utf-8', newline='\n').write(text)
print('patched', X)

"""§216 kernel patch #1: `Slow` reads the turn's card count, not status stacks (literal text edition)."""
import io

M = 'kernel/rd-core/src/modifiers.rs'
X = 'kernel/rd-core/src/exec.rs'
B = 'kernel/rd-core/src/status_bind.rs'


def patch(path, pairs):
    text = io.open(path, encoding='utf-8').read()
    for old, new, what in pairs:
        assert text.count(old) == 1, '%s: %s expected 1, found %d' % (path, what, text.count(old))
        text = text.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text)
    print('patched', path, '(%d edits)' % len(pairs))


# ── modifiers.rs ───────────────────────────────────────────────────────────────────────────────
patch(M, [
    ("""    /// 上限钳制到 `max(0, magnitude)`。
    ClampMax,""",
     """    /// §216：`current * (100 + magnitude * **本回合已出的牌数**) / 100` —— `Slow`。
    ///
    /// 与 `ScalePercentPerStack` 的区别不在算术，在**计数器属于谁**：Slow 的计数每回合归零
    /// （wiki：*"Slow resets at end of turn"*），而层数在本内核只能靠 `modifyStatusStacks` 衰减，
    /// **减到 0 会删掉实例**（参考 `StatusEffects.cs:830-838`）—— 实例一删，`CardPlayed` 触发器
    /// 就再也响不了。牌数是内核自己的账（`state.cards_played_this_turn`，`turn.rs:897` 每回合清零）。
    ScalePercentPerCardPlayedThisTurn,
    /// 上限钳制到 `max(0, magnitude)`。
    ClampMax,""",
     'enum variant'),

    ("""    pub stacks: i32,
    pub operation: Operation,
    pub magnitude: i32,""",
     """    pub stacks: i32,
    /// §216：本回合已出的牌数（`state.cards_played_this_turn`）。只有
    /// [`Operation::ScalePercentPerCardPlayedThisTurn`] 读它；其它运算忽略。
    pub cards_played_this_turn: i32,
    pub operation: Operation,
    pub magnitude: i32,""",
     'candidate field'),

    ("""            // `Math.Min(current, Math.Max(0, magnitude))`（`:211`）：幅值为负时上限就是 0。""",
     """            // §216：`Slow` —— 因子读的是**本回合已出的牌数**，不是层数。
            // 同样用 i64 中间量：`magnitude * cards` 在 i32 上会回绕。
            Operation::ScalePercentPerCardPlayedThisTurn => {
                let factor = i64::from(candidate.magnitude)
                    .saturating_mul(i64::from(candidate.cards_played_this_turn))
                    .saturating_add(100);
                let scaled = i64::from(current).saturating_mul(factor) / 100;
                scaled.clamp(i64::from(i32::MIN), i64::from(i32::MAX)) as i32
            }
            // `Math.Min(current, Math.Max(0, magnitude))`（`:211`）：幅值为负时上限就是 0。""",
     'apply arm'),

    ("""            spec_index,
            stacks,
            operation,
            magnitude,
            once_per_action: false,
            once_per_turn: false,
        }
    }""",
     """            spec_index,
            stacks,
            operation,
            magnitude,
            cards_played_this_turn: 0,
            once_per_action: false,
            once_per_turn: false,
        }
    }""",
     'test builder'),
])

# ── status_bind.rs ─────────────────────────────────────────────────────────────────────────────
patch(B, [
    ("""    /// §210：`min(current, max(0, magnitude))` —— "把所有伤害压到 1"（`Intangible`）。""",
     """    /// §216：`current * (100 + magnitude * 本回合已出的牌数) / 100`（`Slow`）。
    ///
    /// 它与 `ScalePercentPerStack` 的差别**只在一个词**：两者都以字符串存在镜像里，写错一个词
    /// 就是另一种语义，而数字看起来都合理。
    ScalePercentPerCardPlayedThisTurn,
    /// §210：`min(current, max(0, magnitude))` —— "把所有伤害压到 1"（`Intangible`）。""",
     'bind variant'),
    ("""            // §210: the reference declares it; the binding simply had no spelling for it.
            "ClampMax" => Some(ModifierOp::ClampMax),""",
     """            // §216: our own operation, like `ScalePercentPerStack` above.
            "ScalePercentPerCardPlayedThisTurn" => Some(ModifierOp::ScalePercentPerCardPlayedThisTurn),
            // §210: the reference declares it; the binding simply had no spelling for it.
            "ClampMax" => Some(ModifierOp::ClampMax),""",
     'from_wire_name'),
    ("""            ModifierOp::ScalePercentPerStack => "ScalePercentPerStack",""",
     """            ModifierOp::ScalePercentPerStack => "ScalePercentPerStack",
            ModifierOp::ScalePercentPerCardPlayedThisTurn => "ScalePercentPerCardPlayedThisTurn",""",
     'wire_name'),
])

# ── exec.rs ────────────────────────────────────────────────────────────────────────────────────
patch(X, [
    ("""    stacks: 0,
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
};""",
     'NO_CANDIDATE'),

    ("""        // §210: `Intangible`'s "all damage becomes 1" -- `min(current, max(0, 1))`.
        status_bind::ModifierOp::ClampMax => Operation::ClampMax,""",
     """        // §216: `Slow`'s "+10% per card played **this turn**" -- the factor reads the kernel's
        // own counter, not the status' stacks.
        status_bind::ModifierOp::ScalePercentPerCardPlayedThisTurn => {
            Operation::ScalePercentPerCardPlayedThisTurn
        }
        // §210: `Intangible`'s "all damage becomes 1" -- `min(current, max(0, 1))`.
        status_bind::ModifierOp::ClampMax => Operation::ClampMax,""",
     'image_operation'),

    ("""fn damage_stage<'a>(
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
     'damage_stage signature'),
    ("""        return image_damage_stage(amount, statuses, stage, owner, content, matching, kind);""",
     """        return image_damage_stage(amount, statuses, stage, owner, content, matching, kind, turn_cards);""",
     'damage_stage forward'),
    ("""fn image_damage_stage<'a>(
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
     'image_damage_stage signature'),
    ("""    let count = image_rows(content, statuses, pipeline, Some(kind), &mut rows)?;
    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
    )""",
     """    let count = image_rows(content, statuses, pipeline, Some(kind), &mut rows)?;
    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
        turn_cards,
    )""",
     'image_damage_stage fold'),

    ("""fn fold<'a>(
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
     'fold signature'),
    ("""        *slot = Candidate {
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
     'fold candidate'),

    ("""    fold(
        base,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        StatusMatch::Exact,
    )""",
     """    fold(
        base,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        StatusMatch::Exact,
        0,
    )""",
     'turn start draw fold'),
    ("""    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
    )""",
     """    fold(
        amount,
        statuses,
        rows.get(..count).unwrap_or(&[]),
        owner,
        matching,
        0,
    )""",
     'block / turn-start-energy fold'),

    ("""            amount = damage_stage(
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
     'source stage call'),
    ("""        amount = damage_stage(
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
     'target stage call'),
])

print('kernel patch #1 done')

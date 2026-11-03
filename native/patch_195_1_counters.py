"""§195.1 infrastructure: spawn-time **fixed** counters (`ENCT.Enemies[].Counters`), next to §193's
random ones (`Rolls`).

Why it is needed: a content status/rule cannot **initialise** a counter. `Rolls` solved half of it
(a random value at spawn); this solves the other half (a stated value at spawn), and with the same
ascension tiering (`{Value, AscensionMin}` -- largest eligible wins), because StS's numbers are the
same shape: The Guardian's Mode Shift budget is 30, **35 at A9, 40 at A19**.

The two mechanisms stay separate lists on purpose:

| list | value | who writes it |
|---|---|---|
| `Rolls`   | random in `Min..=Max`, consumes one `random_step` | `battle::apply_spawn_setup` |
| `Counters`| the stated `Value`, consumes nothing                | `battle::apply_spawn_setup` |

Same function, same place in the fight's life (after the combatants exist, before the first turn),
but the RNG ledger has to stay explicable: a fight with only `Counters` must not advance a step.
"""
import io


def sub(path, pairs):
    src = io.open(path, encoding="utf-8").read()
    for old, new, what in pairs:
        assert src.count(old) == 1, "%s / %s: %d x %r" % (path, what, src.count(old), old[:70])
        src = src.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("patched", path)


# ===========================================================================
# content.rs: the reader + the picker (the tier rule is shared with `spawn_rolls`)
# ===========================================================================
sub("kernel/rd-core/src/content.rs", [(
"""/// 一条敌人记录里的一条"开局掷骰"（`ENCT[i].Enemies[j].Rolls[k]`，§193）。""",
"""/// 一条敌人记录最多带几条"开局固定计数器"（§195.1）。四条是**容量**，不是规则：超了报错。
pub const MAX_SPAWN_COUNTERS: usize = 4;

/// 与 [`MAX_SPAWN_ROLL_ENTRIES`] 同一条理由：一个键可以有多个升档档位，所以"生效的键数"与
/// "内容里写了几行"是两个数。
pub const MAX_SPAWN_COUNTER_ENTRIES: usize = 2 * MAX_SPAWN_COUNTERS;

/// 一条敌人记录里的**开局固定计数器**（`ENCT[i].Enemies[j].Counters[k]`，§195.1）。
///
/// 与 §193 的 [`SpawnRoll`] 是兄弟：一个写"抽出来的数"，一个写"内容里明写的数"。两者都用
/// `{AscensionMin}` 分档、都在建战斗时落到战斗员身上，区别只在**要不要消耗一次随机步**。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpawnCounter<'a> {
    /// 计数器键。
    pub key: &'a str,
    /// 初始值。
    pub value: i32,
}

/// 一条敌人记录里的一条"开局掷骰"（`ENCT[i].Enemies[j].Rolls[k]`，§193）。""",
    "SpawnCounter type")])

sub("kernel/rd-core/src/content.rs", [(
"""    /// `Rolls`（`F_TERMLIST`，§193）：开局掷骰的条目（键 `Key` / `Min` / `Max` / `AscensionMin`）。""",
"""    /// `Counters`（`F_TERMLIST`，§195.1）：开局**固定**计数器的条目（键 `Key` / `Value` / `AscensionMin`）。
    ///
    /// 与 [`Self::rolls`] 同样的"键缺席 = 空列表"约定（opcode 按出现过的键集派生）。
    pub fn counters(&self) -> Result<SlotList<'a>, EncounterError> {
        match self.list("Counters", F_TERMLIST) {
            Err(EncounterError::MissingField("Counters")) => Ok(SlotList::empty(self.content)),
            other => other,
        }
    }

    /// `Rolls`（`F_TERMLIST`，§193）：开局掷骰的条目（键 `Key` / `Min` / `Max` / `AscensionMin`）。""",
    "EnemySpec::counters")])

# the picker: same shape as `spawn_rolls`, minus the range validation and minus the RNG
sub("kernel/rd-core/src/content.rs", [(
"""    /// 一条遭遇的**敌人名单**（`ENCT[index].Enemies`，每条是 id / 生命 / 动作 / 起始状态 / 规则）。""",
"""    /// 一条敌人记录的**开局固定计数器**，按 `ascension` 选好档位（§195.1）。
    ///
    /// 与 [`Self::spawn_rolls`] 同一条选档规则（`AscensionMin <= ascension` 里阈值最大的一行；
    /// **缺席 / 0 都是"这就是基础值"**；同键同阈值两行 ⇒ 报错）。
    ///
    /// # Errors
    ///
    /// 条目超 [`MAX_SPAWN_COUNTER_ENTRIES`] / 生效的键超 [`MAX_SPAWN_COUNTERS`] /
    /// 同键同阈值两行 ⇒ [`EncounterError::MalformedList`]；`Key` 或 `Value` 缺席 ⇒
    /// [`EncounterError::MissingField`]。
    pub fn spawn_counters(
        &'a self,
        spec: EnemySpec<'a>,
        ascension: i32,
        out: &mut [SpawnCounter<'a>; MAX_SPAWN_COUNTERS],
    ) -> Result<usize, EncounterError> {
        let entries = spec.counters()?;
        if entries.len() > MAX_SPAWN_COUNTER_ENTRIES {
            return Err(EncounterError::MalformedList("Counters"));
        }
        let mut raw: [(&'a str, i32, i32); MAX_SPAWN_COUNTER_ENTRIES] = [("", 0, 0); MAX_SPAWN_COUNTER_ENTRIES];
        let mut count = 0usize;
        for index in 0..entries.len() {
            let term = entries.term(index).ok_or(EncounterError::MalformedList("Counters"))?;
            let node = crate::ir::NodeRef::new(self, term);
            let key = node
                .str_field("Key")
                .map_err(|_| EncounterError::WrongFieldKind("Counters.Key"))?
                .ok_or(EncounterError::MissingField("Counters.Key"))?;
            let value = node
                .int_field("Value")
                .map_err(|_| EncounterError::WrongFieldKind("Counters.Value"))?
                .ok_or(EncounterError::MissingField("Counters.Value"))?;
            let threshold = node
                .int_field("AscensionMin")
                .map_err(|_| EncounterError::WrongFieldKind("Counters.AscensionMin"))?
                .unwrap_or(0);
            raw[index] = (key, value, threshold);
            count += 1;
        }
        let mut written = 0usize;
        for index in 0..count {
            let (key, value, threshold) = raw[index];
            if threshold > ascension {
                continue;
            }
            let mut shadowed = false;
            for other in 0..count {
                if other == index {
                    continue;
                }
                let (other_key, _, other_threshold) = raw[other];
                if other_key != key || other_threshold > ascension {
                    continue;
                }
                if other_threshold > threshold {
                    shadowed = true;
                } else if other_threshold == threshold {
                    return Err(EncounterError::MalformedList("Counters"));
                }
            }
            if shadowed {
                continue;
            }
            if written == MAX_SPAWN_COUNTERS {
                return Err(EncounterError::MalformedList("Counters"));
            }
            out[written] = SpawnCounter { key, value };
            written += 1;
        }
        Ok(written)
    }

    /// 一条遭遇的**敌人名单**（`ENCT[index].Enemies`，每条是 id / 生命 / 动作 / 起始状态 / 规则）。""",
    "spawn_counters picker")])

# ===========================================================================
# battle.rs: one spawn-time setup that writes both lists
# ===========================================================================
sub("kernel/rd-core/src/battle.rs", [(
"""pub fn apply_spawn_rolls(
    state: &mut CombatState,
    content: &Content<'_>,
    encounter: u32,
) -> Result<u32, SpawnRollError> {""",
"""/// §195.1：建战斗时的**计数**账本，一次跑完两条列表。
///
/// `draws = 0` 的局是常态（本内容只有两只怪掷骰）：`Counters` 是**明写的数**，一个随机步都不该花。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct SpawnSetup {
    /// `Rolls` 抽了几次（= `random_step` 涨了几个）。
    pub draws: u32,
    /// `Counters` 写了几条（不消耗随机步）。
    pub counters: u32,
}

pub fn apply_spawn_setup(
    state: &mut CombatState,
    content: &Content<'_>,
    encounter: u32,
) -> Result<SpawnSetup, SpawnRollError> {""",
    "apply_spawn_setup signature")])

sub("kernel/rd-core/src/battle.rs", [(
"""    let ascension = i32::from(state.ascension());
    let mut draws = 0u32;
    for slot in 0..enemies.len() {""",
"""    let ascension = i32::from(state.ascension());
    let mut draws = 0u32;
    let mut counters_written = 0u32;
    for slot in 0..enemies.len() {""",
    "counter local")])

sub("kernel/rd-core/src/battle.rs", [(
"""        let count = content
            .spawn_rolls(spec, ascension, &mut rolls)
            .map_err(SpawnRollError::Encounter)?;
        if count == 0 {
            continue;
        }""",
"""        // §195.1: the fixed counters first -- they cost no random step, so their order relative to
        // the rolls is unobservable; doing them first keeps the `draws` bookkeeping in one tail
        // (the RNG ledger is the thing a reader has to be able to check).
        let mut fixed = [crate::content::SpawnCounter { key: "", value: 0 };
            crate::content::MAX_SPAWN_COUNTERS];
        let fixed_count = content
            .spawn_counters(spec, ascension, &mut fixed)
            .map_err(SpawnRollError::Encounter)?;
        if fixed_count > 0 {
            let combatant = CombatantId::new(id).map_err(|_| SpawnRollError::BadCombatantId)?;
            if state.combatant(&combatant).is_none() {
                return Err(SpawnRollError::MissingCombatant);
            }
            for entry in fixed.iter().take(fixed_count) {
                let key = crate::state::CounterId::new(entry.key)?;
                state
                    .combatant_mut(&combatant)
                    .ok_or(SpawnRollError::MissingCombatant)?
                    .set_counter(key, entry.value)?;
                counters_written = counters_written.saturating_add(1);
            }
        }
        let count = content
            .spawn_rolls(spec, ascension, &mut rolls)
            .map_err(SpawnRollError::Encounter)?;
        if count == 0 {
            continue;
        }""", "counters write")])

sub("kernel/rd-core/src/battle.rs", [(
"""    Ok(draws)
}

/// [`apply_spawn_rolls`] 的失败桶。""",
"""    Ok(SpawnSetup {
        draws,
        counters: counters_written,
    })
}

/// [`apply_spawn_setup`] 的失败桶。""", "return + doc")])

# the doc comment on the function itself
sub("kernel/rd-core/src/battle.rs", [(
"""/// §193：把内容里写的**开局掷骰**落到战斗员身上（"chosen at the start of combat"）。""",
"""/// §193/§195.1：把内容里写的**开局计数**落到战斗员身上 —— 掷骰（`Rolls`）与明写的值（`Counters`）。
///
/// 两件事一起做，是因为它们的位置、失败桶、选档规则都一样，而分开写就会出现**两份**"找到这个
/// 敌人并把数写上去"的代码（§161.3 的老路）。唯一必须分开的是 RNG 账：掷骰花步、固定值不花。""",
    "fn doc")])

print("content.rs + battle.rs: spawn counters")

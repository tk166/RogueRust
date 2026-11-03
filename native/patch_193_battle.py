"""§193: `battle::apply_spawn_rolls` -- the "chosen at the start of combat" half.

Where it goes and why:

* it runs **after** the fight exists (the combatants have to be there) and **before** the first turn,
  so it sits next to `shuffle_draw_pile` in spirit: a one-shot spawn-time setup step that nobody
  re-runs;
* it writes the counter **directly** (`set_counter`), not through `EffectRequest`: nothing is on the
  effect queue yet at spawn time, and the damage node reads the counter at *enqueue* time, so a
  queued write would arrive too late (that is the §193 header's rejected design, and it deals 0);
* one draw per roll, `random_step += 1` -- the same "a draw consumes exactly one step" rule the
  start-of-fight shuffle follows, so the RNG ledger stays explainable.
"""
import io

BATTLE = "kernel/rd-core/src/battle.rs"


def sub(text, old, new, what=""):
    assert text.count(old) == 1, "%s: %d occurrences of %r" % (what, text.count(old), old[:70])
    return text.replace(old, new)


src = io.open(BATTLE, encoding="utf-8").read()

# ---------------------------------------------------------------- the function
anchor = '''/// 开局洗一次抽牌堆（`ShuffleDrawPile`，`ScenarioCombatFactory.cs:81-89`）。'''
body = '''/// §193：把内容里写的**开局掷骰**落到战斗员身上（"chosen at the start of combat"）。
///
/// 内容的一行（`ENCT[i].Enemies[j].Rolls[k]`）是 `{Key, Min, Max, AscensionMin}`；这里按
/// `state.ascension()` 选好档位（[`Content::spawn_rolls`]），抽一次，把值写进**那个敌人**的
/// 同名计数器。动作节目里的 `dealDamage{Amount: combatantCounter(source, Key)}` 之后读到的就是它。
///
/// 返回值是**抽了几次**（不是"写了几条"）：一条被升档阴影掉的条目、一个没有敌人的槽位都不抽，
/// 所以"`random_step` 涨了几个"与这个数逐个相等 —— 这是本函数唯一的可观察副作用账本。
///
/// # 为什么在**建战斗之后、开第一回合之前**
///
/// * 战斗员得先存在（要按 `ENCT` 的 id 找到它）；
/// * 值必须在第一次 `bite` 之前就在（否则第一次读到 0）；
/// * 它**不**是回合开始动作：`apply_starting_statuses`（§175b）在同一位置，理由一样。
///
/// # 为什么直接写、不排队
///
/// `EffectRequest::SetCombatantCounter` 是**入队**的，而伤害节点的 `Amount` 在**入队时**求值
/// （参考的顺序）。把掷骰也排队 ⇒ 同一段节目里"先掷后打"读到的永远是旧值（0），而且没有任何
/// 数值测试会红 —— 只有"伤害突然变成 0"这种看起来像内容错的假象。所以这里直接写。
///
/// # Errors
///
/// 内容读不出来 / 值域不合法 / 计数器容器满 ⇒ 对应的桶。**不吞**任何一条：一条读不懂的掷骰
/// 会让某一个招式的伤害静默变成 0，而那种错只会表现为"这一局有点奇怪"。
pub fn apply_spawn_rolls(
    state: &mut CombatState,
    content: &Content<'_>,
    encounter: u32,
) -> Result<u32, SpawnRollError> {
    let enemies = content
        .encounter_enemies(encounter)
        .map_err(SpawnRollError::Encounter)?;
    let ascension = i32::from(state.ascension());
    let mut draws = 0u32;
    for slot in 0..enemies.len() {
        let spec = enemies.get(slot).map_err(SpawnRollError::Encounter)?;
        let id = spec.id().map_err(SpawnRollError::Encounter)?;
        let mut rolls = [crate::content::SpawnRoll {
            key: "",
            min: 0,
            max: 0,
        }; crate::content::MAX_SPAWN_ROLLS];
        let count = content
            .spawn_rolls(spec, ascension, &mut rolls)
            .map_err(SpawnRollError::Encounter)?;
        if count == 0 {
            continue;
        }
        let combatant = CombatantId::new(id).map_err(|_| SpawnRollError::BadCombatantId)?;
        if state.combatant(&combatant).is_none() {
            // 记录里有掷骰却没有这个战斗员 ⇒ 调用方建的局与遭遇不是同一份。不猜一个目标。
            return Err(SpawnRollError::MissingCombatant);
        }
        for roll in rolls.iter().take(count) {
            let span = roll
                .max
                .checked_sub(roll.min)
                .and_then(|width| width.checked_add(1))
                .ok_or(SpawnRollError::BadRange {
                    min: roll.min,
                    max: roll.max,
                })?;
            if span < 1 || span > crate::content::MAX_SPAWN_ROLL_SPAN {
                return Err(SpawnRollError::BadRange {
                    min: roll.min,
                    max: roll.max,
                });
            }
            // 一次抽签 = 一次完整置换（`CombatRandom` 的形状），然后推进一步。
            let pick = crate::rng::shuffled_pick_index(
                span as usize,
                state.random_seed,
                state.random_step,
            );
            state.random_step = state.random_step.saturating_add(1);
            draws = draws.saturating_add(1);
            let value = roll.min + pick as i32;
            let key = CounterId::new(roll.key)?;
            state
                .combatant_mut(&combatant)
                .ok_or(SpawnRollError::MissingCombatant)?
                .set_counter(key, value)?;
        }
    }
    Ok(draws)
}

/// [`apply_spawn_rolls`] 的失败桶。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpawnRollError {
    /// 内容侧读不出来（`Rolls` 的形态/字段坏了）。
    Encounter(crate::content::EncounterError),
    /// `ENCT` 里点名的敌人不在这个局里。
    MissingCombatant,
    /// 敌人 id 不是能用的战斗员 id。
    BadCombatantId,
    /// `Max < Min`（或宽度超过 [`crate::content::MAX_SPAWN_ROLL_SPAN`]）。
    BadRange {
        /// 内容写的下界。
        min: i32,
        /// 内容写的上界。
        max: i32,
    },
    /// 计数器键不是能用的 id（太长 / 非 ASCII）。
    Counter(crate::state::CapacityError),
    /// 计数器容器满。
    Capacity(crate::state::CapacityError),
}

impl From<crate::state::CapacityError> for SpawnRollError {
    fn from(error: crate::state::CapacityError) -> Self {
        Self::Capacity(error)
    }
}

''' + anchor
src = sub(src, anchor, body, what="apply_spawn_rolls")

io.open(BATTLE, "w", encoding="utf-8", newline="").write(src)
print("battle.rs: apply_spawn_rolls")

"""§193: variable damage -- an enemy record declares a **spawn roll**, the action reads it.

The wiki says the number is not per-attack (`native/wiki_asc/louse.txt:28`,
`native/wiki_asc/darkling.txt:32`):

    Effect = Deals N damage. N = Number between (5-7;{{Asc|2|6-8}}), **chosen at the start of combat.**

So the value has to live somewhere *before* the action program runs. Two designs were rejected on
the way here, and both rejections are load-bearing:

* an int expression `randomRange` (or a `node.rollCounter`) that draws when the damage node is
  **evaluated**: `deal_damage_node` evaluates `Amount` at *enqueue* time (that is the reference's
  order), while a counter write is a queued `EffectRequest` -- a `sequence[roll, dealDamage]` would
  therefore read the counter *before* it is written and deal **0** damage, silently. Ordering bugs of
  that shape pass every numeric test that only looks at "did something happen".
* storing the roll in the *action* program at all: the wiki's variant is "+1 to the range", and an
  action program that has to carry it twice (base + A2) is two copies of one number.

What is left is the honest model of "chosen at the start of combat":

    ENCT[i].Enemies[j].Rolls = [{Key, Min, Max, AscensionMin}, ...]     -- the range, per enemy
    EACT[action].Program    = dealDamage{Amount: combatantCounter(source, Key)}   -- the read

`combatantCounter` is **the reference's own expression** (it is in `INT_KINDS`), so the program does
not grow a new node kind -- the only new thing is *who fills the counter in*. That is this patch:
`apply_spawn_rolls` writes it once, at spawn, from `(seed, random_step)`.

The tier list per `Key` uses the same rule as §192's variant list: the entry with the **largest**
`AscensionMin <= ascension` wins, and `0` means "not a tier" (never "from level 0").
"""
import io

CONTENT = "kernel/rd-core/src/content.rs"


def sub(text, old, new, what=""):
    assert text.count(old) == 1, "%s: %d occurrences of %r" % (what, text.count(old), old[:70])
    return text.replace(old, new)


src = io.open(CONTENT, encoding="utf-8").read()

# ---------------------------------------------------------------- 1. the reader
anchor = '''/// 一段槽列表（`F_TERMLIST` 或 `F_STRLIST`）的借用视图：`(AUX 起址, 个数)`。'''
added = '''/// 一条敌人记录最多带几条"开局掷骰"（§193）。四条是**容量**，不是规则：超了报错，不截断。
pub const MAX_SPAWN_ROLLS: usize = 4;

/// 一条敌人记录在**内容里**能写几条掷骰条目（每个 `Key` 可以有多个升档档位）。
///
/// 比 [`MAX_SPAWN_ROLLS`] 大是刻意的：`MAX_SPAWN_ROLLS` 是"生效的键有几个"，
/// 这个数是"内容里写了几行"（一个键 + 一个 A2 档位 = 2 行）。超了报错，不截断 ——
/// 截断会让"我多写了一个档位"变成"这个档位不存在"，而屏幕上什么都看不出来。
pub const MAX_SPAWN_ROLL_ENTRIES: usize = 2 * MAX_SPAWN_ROLLS;

/// 一次掷骰的值域宽度上限（§193）。
///
/// [`crate::rng::shuffled_pick_index`] 的下标是 `u8`（"一堆牌，不是牌库"），所以 256 个可能值
/// 就是抽签能覆盖的全部。超了**响亮失败**：把 `5..=300` 悄悄截成 `5..=260` 会让难度静默变低一档。
pub const MAX_SPAWN_ROLL_SPAN: i32 = 255;

/// 一条敌人记录里的一条"开局掷骰"（`ENCT[i].Enemies[j].Rolls[k]`，§193）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SpawnRoll<'a> {
    /// 计数器键。动作里的 `combatantCounter` 就是按这个键读。
    pub key: &'a str,
    /// 下界（**含**，`random(5, 7)` 是 5/6/7 三个值）。
    pub min: i32,
    /// 上界（**含**）。
    pub max: i32,
}

''' + anchor
src = sub(src, anchor, added, what="SpawnRoll types")

# `SlotList::empty` -- "this record declares none" without inventing a start offset.
anchor = '''    /// 这一段是哪种列表（`F_TERMLIST` / `F_STRLIST`）。
    #[must_use]
    pub const fn kind(&self) -> u8 {
        self.kind
    }
'''
src = sub(src, anchor, anchor + '''
    /// 一个空列表（0 项）。
    ///
    /// `start` 是 0 而不是某个真实偏移：**空列表的起址槽在镜像里是垃圾值**（实测 146 条
    /// `IntentRules` 就是这样存的），所以"空"必须是一种显式的构造，不能让调用方去读那个槽。
    const fn empty(content: &'a Content<'a>) -> Self {
        Self {
            content,
            start: 0,
            count: 0,
            kind: F_TERMLIST,
        }
    }
''', what="SlotList::empty")

# Reader on the enemy record. Absent key (a record shape that predates §193) is "no rolls".
anchor = '''    /// `StartingStatuses`（`F_TERMLIST`）：起始状态的 spec 对象
    /// （键 `Stacks` / `DurationTurns` / `Charges` / `Status`）。
    pub fn starting_statuses(&self) -> Result<SlotList<'a>, EncounterError> {
        self.list("StartingStatuses", F_TERMLIST)
    }
'''
src = sub(src, anchor, anchor + '''
    /// `Rolls`（`F_TERMLIST`，§193）：开局掷骰的条目（键 `Key` / `Min` / `Max` / `AscensionMin`）。
    ///
    /// ⚠️ **键缺席是合法的**（= 这条记录不掷骰），不是"形态坏了"。opcode 是按**出现过的键集**
    /// 派生的（`compile.py` 的 `Deriver`），所以一条没有 `Rolls` 的记录与一条有 `Rolls: []`
    /// 的记录是**两个 opcode**；对前者 [Self::list] 只能报 `MissingField`。把"这个键在这条记录里
    /// 不存在"当成错误，会让 roguedeck 那份内容（一条 `Rolls` 都没有）整份读不出来。
    pub fn rolls(&self) -> Result<SlotList<'a>, EncounterError> {
        match self.list("Rolls", F_TERMLIST) {
            Err(EncounterError::MissingField("Rolls")) => Ok(SlotList::empty(self.content)),
            other => other,
        }
    }
''', what="EnemySpec::rolls")

# The picker, next to the ascension-variant picker (same rule, different list).
anchor = '''    /// 一条遭遇的**敌人名单**（`ENCT[index].Enemies`，每条是 id / 生命 / 动作 / 起始状态 / 规则）。'''
picker = '''    /// 一条敌人记录的**开局掷骰**，按 `ascension` 选好档位（§193）。
    ///
    /// 写进 `out`，返回条数。每个 `Key` 只留一条：`AscensionMin <= ascension` 里阈值最大的
    /// 那一行（与 [`Self::ascension_program`] 同一条规则 —— 顺序不参与判定）。
    ///
    /// # Errors
    ///
    /// * 条目超过 [`MAX_SPAWN_ROLL_ENTRIES`] / 生效的键超过 [`MAX_SPAWN_ROLLS`] ⇒
    ///   [`EncounterError::MalformedList`]（不截断）；
    /// * `Key` 缺席、`Min` / `Max` 不是 int ⇒ [`EncounterError::WrongFieldKind`]；
    /// * 两个**生效**条目用同一个 `Key` 且阈值相同 ⇒ [`EncounterError::MalformedList`]
    ///   （"同一个键两个不同的范围"，选哪个都是猜）。
    pub fn spawn_rolls(
        &'a self,
        spec: EnemySpec<'a>,
        ascension: i32,
        out: &mut [SpawnRoll<'a>; MAX_SPAWN_ROLLS],
    ) -> Result<usize, EncounterError> {
        let entries = spec.rolls()?;
        if entries.len() > MAX_SPAWN_ROLL_ENTRIES {
            return Err(EncounterError::MalformedList("Rolls"));
        }
        // 先把行读成 (key, min, max, threshold)，读不全就是内容坏了。
        let mut raw: [(&'a str, i32, i32, i32); MAX_SPAWN_ROLL_ENTRIES] =
            [("", 0, 0, 0); MAX_SPAWN_ROLL_ENTRIES];
        let mut count = 0usize;
        for index in 0..entries.len() {
            let term = entries.term(index).ok_or(EncounterError::MalformedList("Rolls"))?;
            let node = crate::ir::NodeRef::new(self, term);
            let key = node
                .str_field("Key")
                .map_err(|_| EncounterError::WrongFieldKind("Rolls.Key"))?
                .ok_or(EncounterError::MissingField("Rolls.Key"))?;
            let min = node
                .int_field("Min")
                .map_err(|_| EncounterError::WrongFieldKind("Rolls.Min"))?
                .ok_or(EncounterError::MissingField("Rolls.Min"))?;
            let max = node
                .int_field("Max")
                .map_err(|_| EncounterError::WrongFieldKind("Rolls.Max"))?
                .ok_or(EncounterError::MissingField("Rolls.Max"))?;
            let threshold = node
                .int_field("AscensionMin")
                .map_err(|_| EncounterError::WrongFieldKind("Rolls.AscensionMin"))?
                .unwrap_or(0);
            raw[index] = (key, min, max, threshold);
            count += 1;
        }
        // 每个键取阈值最大的生效行。
        let mut written = 0usize;
        for index in 0..count {
            let (key, min, max, threshold) = raw[index];
            if threshold <= 0 || threshold > ascension {
                continue;
            }
            let mut shadowed = false;
            for other in 0..count {
                if other == index {
                    continue;
                }
                let (other_key, _, _, other_threshold) = raw[other];
                if other_key != key || other_threshold <= 0 || other_threshold > ascension {
                    continue;
                }
                if other_threshold > threshold {
                    shadowed = true;
                } else if other_threshold == threshold {
                    // 同一个键、同一个阈值、两行 —— 选哪一行都是猜。
                    return Err(EncounterError::MalformedList("Rolls"));
                }
            }
            if shadowed {
                continue;
            }
            if written == MAX_SPAWN_ROLLS {
                return Err(EncounterError::MalformedList("Rolls"));
            }
            out[written] = SpawnRoll { key, min, max };
            written += 1;
        }
        Ok(written)
    }

''' + anchor
src = sub(src, anchor, picker, what="spawn_rolls picker")

io.open(CONTENT, "w", encoding="utf-8", newline="").write(src)
print("content.rs: SpawnRoll + rolls() + spawn_rolls()")

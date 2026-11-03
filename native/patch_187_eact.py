"""§187: the `EACT` ascension dimension -- A2/A3/A4 (damage tiers) and A17/A18/A19 (move sets).

## The shape

StS's enemy moves carry **two numbers** (base and ascension), and the game picks the second when the
ascension level reaches the monster's tier: normal **2**, elite **3**, boss **4**. Move-set rules
(A17/18/19) are the same kind of thing one level up: *which* move happens, or how many cards it
shoves into the discard pile.

So the kernel needs exactly two things:

1. **`EACT` gains two cells**: `ProgramAsc` (a term, nullable -- the ascension variant of the whole
   program) and `AscensionMin` (an int, `0` = no variant). `execute_action` uses `ProgramAsc` when
   `state.ascension >= AscensionMin`.
2. **One new intent condition**: `intent.ascensionAtLeast` -- so content can say "on ascension 18+
   this enemy uses THAT rule instead". That is how a move *set* changes without a second table.

`AscensionMin` is written **by the content** (2/3/4 for damage, 17/18/19 for move sets) rather than
derived from the encounter pool, because the kernel does not know which pool an encounter came from
-- and a kernel that guessed would be wrong the first time an elite appears in an event.

## Format

`EACT` was 7 cells (`stride 16`); it becomes 9 cells (`stride 20`), so `FORMAT_VERSION` goes 4 -> 5.
`ascension` itself is **not** in the snapshot text: the reference has no such field, and putting it
there would move all 85 corpus cases (`port-plan.md` §187 has the argument).
"""
import io
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def patch(rel, edits, label):
    path = os.path.join(ROOT, rel)
    text = io.open(path, encoding="utf-8").read()
    for old, new in edits:
        # Idempotent: a re-run of this script must NOT insert a second copy (the §187 first attempt
        # did exactly that to `state.rs`, and the duplicate field only surfaced at `cargo build`).
        if new in text:
            print("  already applied in", rel + ":", label)
            continue
        assert text.count(old) == 1, (label, text.count(old), old[:70])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("patched", rel)


# ---------------------------------------------------------------- 1) state: the level itself

STATE = "kernel/rd-core/src/state.rs"
patch(STATE, [
    (
        """    pub next_program_execution_id: i64,""",
        """    pub next_program_execution_id: i64,
    /// The run's Ascension level, 0–20 (§187). **Not** in the snapshot text: the reference has no
    /// such field, so writing it into `hash_golden` would move all 85 corpus cases. It is a
    /// fight-level constant (set once at build, never mutated mid-fight), and `hash_full` must
    /// cover it when that lands.
    ///
    /// 它在这里而不是在 `FightPlan` 里：读它的是 `intent::select_action` 与
    /// `intent::execute_action`，两者都已经拿到 `&CombatState`；放进 plan 会让 49 处
    /// `FightPlan { .. }` 字面量全部要改一个字段。
    pub ascension: u8,""",
    ),
    (
        """    /// 下一个 `node.createCombatant` 造出来的战斗员的编号（分裂/召唤）。""",
        """    /// The Ascension level this fight runs at (§187). `0` = the base game.
    #[must_use]
    pub const fn ascension(&self) -> u8 {
        self.ascension
    }

    /// Sets the Ascension level (called once, right after the fight is built).
    ///
    /// ⚠️ 它不是"战斗中途可以改的数"：没有任何规则会在 fight 里改它，而 `A17/18/19` 依赖
    /// "整场一致"。做成 `pub` 字段是为了让 `build` 之后能写；不提供"中途修改"的入口。
    pub fn set_ascension(&mut self, level: u8) {
        self.ascension = level;
    }

    /// 下一个 `node.createCombatant` 造出来的战斗员的编号（分裂/召唤）。""",
    ),
], "state")

# ---------------------------------------------------------------- 2) content schema: two new cells

CONTENT = "kernel/rd-core/src/content.rs"
patch(CONTENT, [
    (
        """    EactRow, EnemyAction, EACT_SCHEMA, 16, 7, {""",
        """    EactRow, EnemyAction, EACT_SCHEMA, 20, 9, {""",
    ),
    (
        """        /// `Program`（term 句柄）。
        ("Program", F_TERM, 0) => program => 5,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 6,""",
        """        /// `Program`（term 句柄）。
        ("Program", F_TERM, 0) => program => 5,
        /// `ProgramAsc`（term 句柄，§187）：**升档后的节目**。与 `AscensionMin` 一起用。
        ("ProgramAsc", F_TERM, 0) => program_asc => 7,
        /// `AscensionMin`（`F_INT`，§187）：从哪一级起改用 `ProgramAsc`。`0` = 没有变体。
        ///
        /// 数值由**内容**写（普通 2 / 精英 3 / Boss 4；招式表则是 17/18/19），因为内核不知道
        /// 这条遭遇来自哪个池 —— 而"猜一次"在第一次"精英出现在事件里"时就会错。
        ("AscensionMin", F_INT, 0) => ascension_min => 8,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 6,""",
    ),
], "content")

# ---------------------------------------------------------------- 3) the compiler's schema + version

RDCFMT = "tools/contentc/rdcfmt.py"
patch(RDCFMT, [
    (
        """EACT_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    ("PackageId", F_STR, 0), ("Intent", F_TERM, 0), ("Program", F_TERM, 0),
    ("extra", F_TERM, 0),
]""",
        """EACT_ROW = [
    ("Id", F_STR, 0), ("NameKey", F_STR, 0), ("DescriptionKey", F_STR, 0),
    ("PackageId", F_STR, 0), ("Intent", F_TERM, 0), ("Program", F_TERM, 0),
    # §187: the ascension dimension (A2/3/4 numbers, A17/18/19 move sets). Nine cells => stride 20.
    ("ProgramAsc", F_TERM, 0), ("AscensionMin", F_INT, 0),
    ("extra", F_TERM, 0),
]""",
    ),
    (
        """FORMAT_VERSION = 4""",
        """# 5: `EACT` gained `ProgramAsc` + `AscensionMin` (§187), so that row's stride moved 16 -> 20.
FORMAT_VERSION = 5""",
    ),
], "rdcfmt")

# ---------------------------------------------------------------- 4) intent: pick the envelope + the condition

INTENT = "kernel/rd-core/src/intent.rs"
patch(INTENT, [
    # the condition kind
    (
        """    /// `intent.not`（一个内层条件）
    Not,
}""",
        """    /// `intent.not`（一个内层条件）
    Not,
    /// `intent.ascensionAtLeast`（`Value`）：本场战斗的 Ascension 等级 ≥ `Value`。
    ///
    /// 本移植自己的条件（§187）：StS 的 A17/A18/A19 是**换招式表**，而它的数据不是一个
    /// 可声明的表，是每只怪 `getMove` 里的一段 `if`。内核不给每只怪写代码，所以把那个
    /// `if` 交给内容：`AscensionMin` 管"同一个招式换数值"，这个条件管"哪条规则先生效"。
    AscensionAtLeast,
}""",
    ),
    (
        """    pub const ALL: [ConditionKind; 10] = [""",
        """    pub const ALL: [ConditionKind; 11] = [""",
    ),
    (
        """        ConditionKind::Not,
    ];""",
        """        ConditionKind::Not,
        ConditionKind::AscensionAtLeast,
    ];""",
    ),
    (
        """            ConditionKind::Not => "intent.not",""",
        """            ConditionKind::Not => "intent.not",
            ConditionKind::AscensionAtLeast => "intent.ascensionAtLeast",""",
    ),
], "intent-kinds")

# the condition evaluation + the program choice (separate patch: anchors are long)
patch(INTENT, [
    (
        """        ConditionKind::SelfHasCounter => {""",
        """        // `intent.ascensionAtLeast`（§187）：本场战斗的 Ascension 等级 ≥ `Value`。
        //
        // 它是"内容能换招式表"的唯一入口：A17/18/19 在 StS 里是每只怪 `getMove` 里的一段 `if`，
        // 我们不给每只怪写代码，而是让内容写一条**更高优先级**的 `IntentRule`。
        ConditionKind::AscensionAtLeast => {
            let value = condition
                .int_field("Value")?
                .ok_or(IntentError::Missing("Value"))?;
            Ok(i32::from(state.ascension()) >= value)
        }
        ConditionKind::SelfHasCounter => {""",
    ),
], "intent-condition")

print("part 1 done")

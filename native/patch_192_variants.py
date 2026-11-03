"""§192: `EACT.ProgramAsc` becomes a **list** of `{AscensionMin, Program}` variants.

Why: one action can carry more than one threshold. The wiki's Jaw Worm Bellow raises Strength at
A2 **and** Block at A17; the single `ProgramAsc` + `AscensionMin` pair from §187 could only hold the
earlier one (that limitation is written down in §190.4). §188 already set the precedent for turning
"one cell + one number" into "one list" (`EV.Effects0`), and the layout table is *derived from the
document*, so a list-of-objects costs no new opcode by hand.

Shapes before/after:

    before   "ProgramAsc": {envelope},  "AscensionMin": 2        -- 9 cells, stride 20
    after    "ProgramAsc": [{"AscensionMin": 2, "Program": {envelope}}]   -- 8 cells, stride 16

The `AscensionMin` **cell goes away** instead of being left behind: two places that both know a
threshold is exactly how the earlier "one vocabulary known in two places" bugs happened.

Selection rule (kernel): among the variants with `AscensionMin <= ascension`, take the **largest**
threshold; ties/order never matter (`Content::ascension_program`).
"""
import io

KERNEL = "kernel/rd-core/src/content.rs"
WRITER = "tools/contentc/rdcfmt.py"


def sub(text, old, new, count=1, what=""):
    assert text.count(old) == count, "%s: %d occurrences of %r" % (what, text.count(old), old[:60])
    return text.replace(old, new)


# ---------------------------------------------------------------- kernel: content.rs
src = io.open(KERNEL, encoding="utf-8").read()

src = sub(src, """/// 6: `EV` replaced its four `Effect*/Amount*` cells with four effect **lists** (§188): same
///    stride, different meaning -- a reader that kept version 5 would decode a term id as a string id.
pub const FORMAT_VERSION: u16 = 6;""",
"""
/// 6: `EV` replaced its four `Effect*/Amount*` cells with four effect **lists** (§188): same
///    stride, different meaning -- a reader that kept version 5 would decode a term id as a string id.
/// 7: `EACT.ProgramAsc` became a **variant list** `[{AscensionMin, Program}]` and the single
///    `AscensionMin` cell went away (§192), so that row's stride moved 20 -> 16. One action can now
///    carry two thresholds (Jaw Worm's Bellow raises Strength at A2 *and* Block at A17); a reader
///    that kept version 6 would read the list term id as if it were the one envelope.
pub const FORMAT_VERSION: u16 = 7;""", what="FORMAT_VERSION")

src = sub(src, """entity_row!(
    /// 敌人动作行（`EACT`，stride 16，7 格）。
    EactRow, EnemyAction, EACT_SCHEMA, 20, 9, {""",
"""entity_row!(
    /// 敌人动作行（`EACT`，stride 16，8 格）。
    EactRow, EnemyAction, EACT_SCHEMA, 16, 8, {""", what="EactRow header")

src = sub(src, """        /// `ProgramAsc`（term 句柄，§187）：**升档后的节目**。与 `AscensionMin` 一起用。
        ("ProgramAsc", F_TERM, 0) => program_asc => 6,
        /// `AscensionMin`（`F_INT`，§187）：从哪一级起改用 `ProgramAsc`。`0` = 没有变体。
        ///
        /// 数值由**内容**写（普通 2 / 精英 3 / Boss 4；招式表则是 17/18/19），因为内核不知道
        /// 这条遭遇来自哪个池 —— 而"猜一次"在第一次"精英出现在事件里"时就会错。
        ("AscensionMin", F_INT, 0) => ascension_min => 7,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 8,""",
"""        /// `ProgramAsc`（term 句柄，§192）：**升档变体列表** `[{AscensionMin, Program}, …]`。
        ///
        /// 每个元素的 `Program` 是与 `Program` 格**同形**的信封（`{Root, MaxProgramSteps, …}`），
        /// 不是裸 `Root`（§187 踩过：塞 `Root` 进去 ⇒ 下一跳去 `node.dealDamage` 里找 `Root`）。
        ///
        /// 阈值（普通 2 / 精英 3 / Boss 4；招式表 17/18/19）由**内容**写，因为内核不知道这条
        /// 遭遇来自哪个池 —— 而"猜一次"在第一次"精英出现在事件里"时就会错。
        ///
        /// ⚠️ §192 之前这里是"一个信封 + 一个 `AscensionMin` 格"。两格表达不了
        /// "Strength @A2 且 Block @A17"，而**留着一个不再被读的格**等于留一份会漂的第二份真相。
        ("ProgramAsc", F_TERM, 0) => program_asc => 6,
        /// schema 不认识的键（term 句柄）。
        ("extra", F_TERM, 0) => extra => 7,""", what="EACT cells")

# ---------------------------------------------------------------- kernel: the picker
anchor = """    /// 遭遇行（`ENCT`，stride 16）。
    #[must_use]
    pub fn encounter(&self, index: u32) -> Option<EnctRow<'a>> {
        EnctRow::new(self.row(Table::Encounter, index)?)
    }
"""
picker = anchor + '''
    /// 一条敌人动作在 `ascension` 级该用的**节目信封**（`EACT.ProgramAsc` 的变体列表，§192）。
    ///
    /// 列表元素是 `{AscensionMin, Program}`（term 对象）。选择规则只有一条：
    /// **在 `AscensionMin <= ascension` 的元素里取阈值最大的那个**。
    ///
    /// 为什么要"最大的"而不是"第一个命中的"：列表是内容写的，而内容里元素的顺序是**作者
    /// 顺手**的产物。按顺序取意味着"把 A17 那条往上挪一行"就悄悄换了难度 —— 而这种错在
    /// 任何数值测试里都不会红（A17 的内容在 A2 下看起来"正常偏强"）。所以顺序不参与判定，
    /// 由 `native/sts_content_check.py` 单独钉"阈值升序且不重复"。
    ///
    /// 没有变体、或所有阈值都高于 `ascension` ⇒ `Ok(None)`（调用方退回 `Program`）。
    ///
    /// # Errors
    ///
    /// * `ProgramAsc` 格不是 `_arr` ⇒ [`IrError::WrongKind`]（形状坏了，不是"没有变体"）；
    /// * 元素不是对象 / `AscensionMin` 不是 int / `Program` 不是 term ⇒ [`IrError::WrongKind`]；
    /// * 列表比 [`MAX_ASC_VARIANTS`] 长 ⇒ [`IrError::List`]（不截断：多出来的变体就是"内容写了
    ///   一条内核永远不读的档位"）。
    pub fn ascension_program(
        &self,
        action: EactRow<'a>,
        ascension: i32,
    ) -> Result<Option<NodeRef<'a>>, IrError> {
        let cell = action.program_asc();
        if cell == ABSENT16 || cell == NULL16 {
            return Ok(None);
        }
        let term = self.term(cell).ok_or(IrError::Term(cell))?;
        if term.op != OP_ARR {
            return Err(IrError::WrongKind("ProgramAsc"));
        }
        let start = term.slot(0).ok_or(IrError::Slot)?;
        let count = term.slot(1).ok_or(IrError::Slot)?;
        if count == LIST_ABSENT || count == LIST_NULL {
            return Ok(None);
        }
        if usize::from(count) > MAX_ASC_VARIANTS {
            return Err(IrError::List);
        }
        let mut best: Option<(i32, NodeRef<'a>)> = None;
        for index in 0..usize::from(count) {
            let offset = start.checked_add(index as u16).ok_or(IrError::List)?;
            let element = self.aux(offset).ok_or(IrError::List)?;
            let element = NodeRef::new(self, element);
            // 阈值为 0 的元素**永远不生效**（与 §187 同一条约定：0 是"没填"，不是"从 0 级起"）。
            // 不静默跳过是不行的 —— 跳过会让"忘了填"变成"这条变体不存在"，看起来一切正常。
            let threshold = element
                .int_field("AscensionMin")?
                .ok_or(IrError::Missing("AscensionMin"))?;
            if threshold <= 0 || threshold > ascension {
                continue;
            }
            let program = element
                .node_field("Program")?
                .ok_or(IrError::Missing("Program"))?;
            match best {
                Some((seen, _)) if seen >= threshold => {}
                _ => best = Some((threshold, program)),
            }
        }
        Ok(best.map(|(_, program)| program))
    }
'''
src = sub(src, anchor, picker, what="ascension_program insertion")
io.open(KERNEL, "w", encoding="utf-8", newline="").write(src)

# ---------------------------------------------------------------- writer: rdcfmt.py
src = io.open(WRITER, encoding="utf-8").read()
src = sub(src, """    # §187: the ascension dimension (A2/3/4 numbers, A17/18/19 move sets). Nine cells => stride 20.
    ("ProgramAsc", F_TERM, 0), ("AscensionMin", F_INT, 0),
    ("extra", F_TERM, 0),""",
"""    # §192: the ascension dimension is a **variant list** (`[{AscensionMin, Program}]`), not
    # "one envelope + one threshold": one action can carry two thresholds (Jaw Worm's Bellow raises
    # Strength at A2 and Block at A17). Eight cells => stride 16, and the version moved with it.
    ("ProgramAsc", F_TERM, 0),
    ("extra", F_TERM, 0),""", what="rdcfmt EACT_ROW")
src = sub(src, "FORMAT_VERSION = 6", "FORMAT_VERSION = 7", what="rdcfmt version")
io.open(WRITER, "w", encoding="utf-8", newline="").write(src)
print("kernel + writer patched")

"""§286 读端：选项的 `Branches`（权重表，含 A15 版）、`Fight`，以及**段**的 `EntryEffects`。

## 为什么把 §285 的 `Chance`/`NextFail` 收成 `Branches`

`Dead Adventurer` 的一次搜索是**四选一**（25% 伏击 + 三个奖励里剩下的那些），
`Chance`/`NextFail` 只有两条边 ⇒ 装不下。而"两条边"本来就是"两项权重"的特例，
所以只留一种形状：`Branches: [{Weight, Next}, ...]`，权重和 = 100。

    The Joust:  [{70, "win"}, {30, "lose"}]
    Scrap Ooze: [{25, "found"}, {75, "try2"}]
    Dead Adventurer: [{25, "ambush"}, {25, "gold"}, {25, "relic"}, {25, "nothing"}]

## 为什么 `EntryEffects` 不用改格式

`EVND` 的行格式里第 4 格是 `extra` —— 编译器把**没被 schema 消费的字段**打包成对象塞进
那一格（`compile.py: row()` 的 `leftover`）。所以给 `EVND` 节点加 `Effects`/`EffectsAsc`
字段只是多了一个 AUX 对象，**行宽与格式版本都不动**。读端也只是多解一层。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ── ① 常量
    s = patch(s, '''pub const MAX_EVENT_OPTIONS: usize = 4;''',
'''pub const MAX_EVENT_OPTIONS: usize = 4;

/// §286：一个选项最多几条**权重分支**。四条是因为最宽的那个事件（`Dead Adventurer`）是
/// "25% 伏击 + 三个奖励里剩下的那些" = 1 + 3。
pub const MAX_EVENT_BRANCHES: usize = 4;''')

    # ── ② EventOption：roll → branches（+ A15 版）+ fight
    s = patch(s, '''    /// §285：**概率分支**。`Some((chance, fail_step))` = 这个选项要掷一次骰：
    /// `chance`% 成功（走 `next`），否则去 `fail_step`。`None` = 一定成功（绝大多数选项）。
    ///
    /// 为什么放在选项上而不是效果里：掷骰决定的是"**去哪一段**"，那是树的结构，不是效果。
    pub roll: Option<(u8, &'a str)>,''',
'''    /// §286：**权重分支**（取代 §285 的 `Chance`/`NextFail`）。
    /// `(权重, 目标段)` 的列表，权重和为 100；空 = 不掷骰（一定走 `next`）。
    ///
    /// 为什么放在选项上而不是效果里：掷骰决定的是"**去哪一段**"，那是树的结构，不是效果。
    pub branches: [(u8, &'a str); MAX_EVENT_BRANCHES],
    /// 有效分支条数。
    pub branches_len: u8,
    /// A15 版分支（`Dead Adventurer` 的伏击率 25% → 35%）。空 = 用基础表。
    pub branches_asc: [(u8, &'a str); MAX_EVENT_BRANCHES],
    /// A15 版有效条数。
    pub branches_asc_len: u8,
    /// §286：**这个选项是一场战斗**。`0` = 不是，`1` = 普通怪，`2` = 精英。
    /// 选了它，事件就**收尾**（房间由那一场战斗结算），战后不回到事件。
    pub fight: u8,''')

    # `effects_at` 旁边加 `branches_at`
    s = patch(s, '''    /// §279/§280：这个选项在镜像里的 term''',
'''    /// §286：`ascension` 下该用哪张分支表（A15 那一版优先）。
    #[must_use]
    pub fn branches_at(&self, ascension: u8, a15: u8) -> &[(u8, &'a str)] {
        if self.branches_asc_len > 0 && ascension >= a15 {
            &self.branches_asc[..usize::from(self.branches_asc_len)]
        } else {
            &self.branches[..usize::from(self.branches_len)]
        }
    }

    /// §279/§280：这个选项在镜像里的 term''')

    # EMPTY 里的字段
    s = patch(s, '''            next: "",
            roll: None,
            term: ABSENT16,''','''            next: "",
            branches: [(0, ""); MAX_EVENT_BRANCHES],
            branches_len: 0,
            branches_asc: [(0, ""); MAX_EVENT_BRANCHES],
            branches_asc_len: 0,
            fight: 0,
            term: ABSENT16,''')

    # ── ③ EventStep：段自己的进入效果
    s = patch(s, '''pub struct EventStep<'a> {
    /// 这一段的正文。
    pub text: &'a str,''','''pub struct EventStep<'a> {
    /// 这一段的正文。
    pub text: &'a str,
    /// §286：**进入这一段时**要应用的效果。这是"奖赏在到达时兑"的那一半 ——
    /// 有了它，赢下的赌注不必再让玩家多点一次 `[Leave]`。
    pub entry: [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    /// 有效条数。
    pub entry_count: u8,
    /// A15 版进入效果。空 = 用基础表。
    pub entry_asc: [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    /// A15 版有效条数。
    pub entry_asc_count: u8,''')

    s = patch(s, '''    /// `Empty` 实现要一个 const：一个"没有正文也没有选项"的段。
    pub const EMPTY: Self = Self {
        text: "",''','''    /// §286：`ascension` 下进入这一段要应用的效果。
    #[must_use]
    pub fn entry_at(&self, ascension: u8, a15: u8) -> &[EffectSpec<'a>] {
        if self.entry_asc_count > 0 && ascension >= a15 {
            &self.entry_asc[..usize::from(self.entry_asc_count)]
        } else {
            &self.entry[..usize::from(self.entry_count)]
        }
    }

    /// `Empty` 实现要一个 const：一个"没有正文也没有选项"的段。
    pub const EMPTY: Self = Self {
        text: "",
        entry: [EffectSpec { effect: "nothing", amount: 0 }; MAX_EVENT_EFFECTS],
        entry_count: 0,
        entry_asc: [EffectSpec { effect: "nothing", amount: 0 }; MAX_EVENT_EFFECTS],
        entry_asc_count: 0,''')

    # ── ④ option_list：读 Branches / BranchesAsc / Fight
    s = patch(s, '''                // §285：`Chance` 与 `NextFail` 必须**成对**出现（一条有概率却没有失败分支的
                // 选项是内容错误，交给内容门拦；这里只在两者都读得出来时才算"要掷骰"）。
                roll: match (
                    node.int_field("Chance").ok().flatten(),
                    node.str_field("NextFail").ok().flatten(),
                ) {
                    (Some(chance), Some(fail)) if (1..=100).contains(&chance) && !fail.is_empty() => {
                        Some((chance as u8, fail))
                    }
                    _ => None,
                },''','''                // §286：权重分支。读不出来（形状不对）就当"没有分支"—— 内容门另有判据，
                // 而这里的兜底必须是**不掷骰**（宁可少一次随机，也不要随机到一段空的）。
                branches: [(0, ""); MAX_EVENT_BRANCHES],
                branches_len: 0,
                branches_asc: [(0, ""); MAX_EVENT_BRANCHES],
                branches_asc_len: 0,
                // §286：`Fight: "elite"` ⇒ 2，`"monster"` ⇒ 1。别的字 ⇒ 0（内容门拦）。
                fight: match node.str_field("Fight").ok().flatten().unwrap_or("") {
                    "monster" => 1,
                    "elite" => 2,
                    _ => 0,
                },''')

    # 分支表的解析：插在 option.count/asc_count 之后
    s = patch(s, '''            option.count = self.effect_list_from_terms(&base_terms, base_count, &mut option.effects)?;
            option.asc_count = self.effect_list_from_terms(&asc_terms, asc_count, &mut option.asc)?;''',
'''            option.count = self.effect_list_from_terms(&base_terms, base_count, &mut option.effects)?;
            option.asc_count = self.effect_list_from_terms(&asc_terms, asc_count, &mut option.asc)?;
            // §286：`Branches` / `BranchesAsc` 是 term 列表，元素 `{Weight, Next}`。
            option.branches_len =
                self.branch_list(&node, "Branches", &mut option.branches);
            option.branches_asc_len =
                self.branch_list(&node, "BranchesAsc", &mut option.branches_asc);''')

    # 新的解析函数：放在 option_list 之后
    s = patch(s, '''    /// 一个列表 term 的 `(起址, 条数)`；缺席/null ⇒ `Some((0, 0))`，形状不对 ⇒ `None`。''',
'''    /// §286：读一张权重分支表（`[{Weight, Next}, ...]`）。返回条数。
    ///
    /// 缺席 = 空表（"这个选项不掷骰"）。**超过 [`MAX_EVENT_BRANCHES`] 直接 0**：截断会让
    /// 权重和不再等于 100，而"和不是 100"的掷骰是一颗永远落不到最后一档的骰子。
    fn branch_list(
        &'a self,
        node: &crate::ir::NodeRef<'a>,
        field: &str,
        out: &mut [(u8, &'a str); MAX_EVENT_BRANCHES],
    ) -> u8 {
        let mut terms = [0u16; MAX_EVENT_BRANCHES];
        let count = node
            .term_list_field(field, &mut terms)
            .or_else(|_| node.term_list_field_or_empty(field, &mut terms))
            .unwrap_or(0);
        if count > MAX_EVENT_BRANCHES {
            return 0;
        }
        for (index, element) in terms.iter().enumerate().take(count) {
            let branch = crate::ir::NodeRef::new(self, *element);
            let weight = branch.int_field("Weight").ok().flatten().unwrap_or(0);
            let next = branch.str_field("Next").ok().flatten().unwrap_or("");
            out[index] = (u8::try_from(weight.max(0)).unwrap_or(0), next);
        }
        count as u8
    }

    /// 一个列表 term 的 `(起址, 条数)`；缺席/null ⇒ `Some((0, 0))`，形状不对 ⇒ `None`。''')

    # ── ⑤ event_step：读 extra 里的 Effects / EffectsAsc
    s = patch(s, '''            step.count = self.option_list(row.options(), &mut step.options)?;''',
'''            step.count = self.option_list(row.options(), &mut step.options)?;
            // §286：`Effects` / `EffectsAsc` 落在行的 `extra` 格里（编译器把没被 schema
            // 消费的字段打包成对象），所以这里解一层：`extra` → 对象 → 两个列表。
            let extra = crate::ir::NodeRef::new(self, row.extra());
            let mut entry_terms = [0u16; MAX_EVENT_EFFECTS];
            let entry_count = extra
                .term_list_field("Effects", &mut entry_terms)
                .or_else(|_| extra.term_list_field_or_empty("Effects", &mut entry_terms))
                .unwrap_or(0);
            let mut entry_asc_terms = [0u16; MAX_EVENT_EFFECTS];
            let entry_asc_count = extra
                .term_list_field("EffectsAsc", &mut entry_asc_terms)
                .or_else(|_| extra.term_list_field_or_empty("EffectsAsc", &mut entry_asc_terms))
                .unwrap_or(0);
            step.entry_count =
                self.effect_list_from_terms(&entry_terms, entry_count, &mut step.entry)?;
            step.entry_asc_count =
                self.effect_list_from_terms(&entry_asc_terms, entry_asc_count, &mut step.entry_asc)?;''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-core: Branches/Fight/EntryEffects')
    print('NEXT: EvndRow 需要 extra() getter，EventStep 的 derive 与 EMPTY 要一起改')


main()

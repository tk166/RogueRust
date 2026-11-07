"""§257 内核：给意图条件加一条 `intent.enemyAliveCount`。

## 为什么必须有它

`Reptomancer` 的规则是 wiki 原话：

> Only 4 Daggers can be in play at any time. If Spawn Dagger was chosen with 4 Daggers in play,
> it will use Snake Strike instead.

"在场几只"**不是**任何一个已有条件的形状：`selfHasCounter` 读的是**自己身上的计数器**，
而匕首会死、会新召，计数器没法自洽（匕首死了谁来减？`Downed` 的 bearer 是**倒下的那个**，
它身上的状态跟着一起没了）。

而这条规则又**必须落在选择层**：`Snake Strike` 与 `Spawn Dagger` 的意图图标不一样，
把判断塞进动作节目里会让界面显示"召唤"却打出蛇击 —— 正是本仓库最恨的那类"看着正常"。

⇒ 加一个条件：**敌方阵营里还活着的战斗员个数**（**含出手者自己**）。

    Condition = {kind: "intent.enemyAliveCount", value: {Op: "GreaterOrEqual", Value: 5}}

`Reptomancer + 4 把匕首 = 5` ⇒ "匕首已满"就是 `>= 5`。这个口径下 `= 5` 而不是
"匕首 >= 4"，是因为**数得出来**的东西（活着的战斗员）才是内核真有的东西；"哪些是匕首"
要按定义名过滤，而定义名在本内核里不是战斗员的字段。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/intent.rs'

EDITS = [
    # 1) 枚举成员
    ('''    /// 本移植自己的条件（§187）：StS 的 A17/A18/A19 是**换招式表**，而它的数据不是一个
    /// 可声明的表，是每只怪 `getMove` 里的一段 `if`。内核不给每只怪写代码，所以把那个
    /// `if` 交给内容：`AscensionMin` 管"同一个招式换数值"，这个条件管"哪条规则先生效"。
    AscensionAtLeast,
}''',
     '''    /// 本移植自己的条件（§187）：StS 的 A17/A18/A19 是**换招式表**，而它的数据不是一个
    /// 可声明的表，是每只怪 `getMove` 里的一段 `if`。内核不给每只怪写代码，所以把那个
    /// `if` 交给内容：`AscensionMin` 管"同一个招式换数值"，这个条件管"哪条规则先生效"。
    AscensionAtLeast,
    /// `intent.enemyAliveCount`（`Op, Value`）：**敌方阵营里还活着的战斗员个数**，**含出手者**。
    ///
    /// 本移植自己的条件（§257），为 `Reptomancer` 的"最多 4 把匕首，满了就改用 Snake Strike"
    /// 而加。为什么不复用 `selfHasCounter`：匕首会死、会新召，而"匕首死了谁来减计数器"没有答案
    /// —— `Downed` 的 bearer 是**倒下的那个**，它身上的状态随它一起没了。
    ///
    /// 口径是"**数得出来**的东西"：活着的战斗员个数。`Reptomancer + 4 匕首 = 5`，
    /// 所以"匕首已满"写成 `GreaterOrEqual 5`。
    EnemyAliveCount,
}'''),
    # 2) ALL 数组
    ('''    pub const ALL: [ConditionKind; 11] = [''',
     '''    pub const ALL: [ConditionKind; 12] = ['''),
    ('''        ConditionKind::AscensionAtLeast,
    ];''',
     '''        ConditionKind::AscensionAtLeast,
        ConditionKind::EnemyAliveCount,
    ];'''),
    # 3) wire_name
    ('''            ConditionKind::AscensionAtLeast => "intent.ascensionAtLeast",
        }''',
     '''            ConditionKind::AscensionAtLeast => "intent.ascensionAtLeast",
            ConditionKind::EnemyAliveCount => "intent.enemyAliveCount",
        }'''),
    # 4) 求值
    ('''        ConditionKind::SelfHasCounter => {
            let counter = condition
                .str_field("Counter")?''',
     '''        // `intent.enemyAliveCount`（§257）：敌方阵营里**还活着**的战斗员个数（含出手者）。
        //
        // 出手者自己不在状态里 ⇒ `false`（与 `selfHasCounter` 的 `:89-90` 同一条约定：
        // 状态层查不到就不匹配，不是错误）。
        ConditionKind::EnemyAliveCount => {
            let Some(actor_state) = state.combatant(actor) else {
                return Ok(false);
            };
            let op = compare_op(condition)?;
            let value = condition
                .int_field("Value")?
                .ok_or(IntentError::Missing("Value"))?;
            let team = actor_state.team_id;
            let alive = state
                .combatants()
                .iter()
                .filter(|other| {
                    other.team_id == team
                        && other.lifecycle_state == crate::state::CombatantLifecycleState::Alive
                })
                .count();
            let alive = i32::try_from(alive).unwrap_or(i32::MAX);
            Ok(op.apply(alive, value))
        }
        ConditionKind::SelfHasCounter => {
            let counter = condition
                .str_field("Counter")?'''),
]


def main():
    src = io.open(PATH, encoding='utf-8').read()
    for old, new in EDITS:
        assert src.count(old) == 1, (src.count(old), old[:60])
        src = src.replace(old, new)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(src)
    print('intent.rs: ConditionKind::EnemyAliveCount added')


main()

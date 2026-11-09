"""§313（一）：内核的两块新零件。

## 1. `sel.alliesWithDefinition` —— "按**定义**挑一只友军"

`Centurion` 的 `Protect` 要给 **Mystic** 挂格挡（wiki 原文："Mystic gains 15 Block. If alone,
instead gains 15 Block."）。已有的 `sel.lowestHealthAlly` 不能替代它：Centurion 血量掉到比
Mystic 低时，最低血的友军就是它自己 —— 那不是这条规则。所以加一个**定义过滤**：先取
`AllAlliesOfSource`（含自己），再按 `CombatantDefinitionId` 筛。

形状与 `StatusFilter` 完全一样（`inner` + 一个 id 引用），因为它们是同一类东西：
"对一棵子树的结果再筛一遍"。不新造叶子选择器 —— 那会把"筛"变成"选"，将来还要再来一次。

## 2. `intent.allyMissingHealth` —— "**某个**友军缺了 ≥ N 血"

`Mystic` 的 `Heal` 在"有敌人缺 16 血"时优先使用（wiki: "If an enemy is missing 16 (21 19) or
more HP, Mystic will use Heal, up to twice in a row"）。已有的 `intent.healthPercent` 只看出手者
自己 —— 写成"自己缺 16 血"是**另一条规则**（而且 Mystic 常在后排，那条规则几乎不触发）。

所以加一条条件：存活阵营（含自己）里**有没有人** `health_max - health_current >= Value`。
`Op` 复用其它条件的比较算子，`Value` 是**绝对血量**（不是百分比）。
"""
import io

TARGETS = 'D:/Vibe/sts-tui/kernel/rd-core/src/targets.rs'
SEL = 'D:/Vibe/sts-tui/kernel/rd-core/src/sel.rs'
INTENT = 'D:/Vibe/sts-tui/kernel/rd-core/src/intent.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # ── targets.rs：节点 + 求值 ─────────────────────────────────────────────────────────────
    patch(TARGETS, '''    StatusFilter { op: StatusFilter, inner: u16, status_id: IdRef },''',
'''    StatusFilter { op: StatusFilter, inner: u16, status_id: IdRef },
    /// §313：`DefinitionFilter { inner, definition_id }` —— inner 里**定义 id 等于它**的那些。
    ///
    /// 与 `StatusFilter` 同一类（先取子树、再筛一遍），所以不新造叶子选择器：那个位置
    /// 属于"从哪里开始选"，而"按定义筛"是在**已经选出来的集合**上做减法。
    DefinitionFilter { inner: u16, definition_id: IdRef },''')

    patch(TARGETS, '''        SelectorNode::StatusPick { op, inner, status_id } => {''',
'''        SelectorNode::DefinitionFilter { inner, definition_id } => {
            // 定义 id 与状态 id 同样：**进子树之前**校验，坏 id 是表自己的结构错误。
            let definition = id_bytes(id_pool, definition_id)?;
            let set = eval(table, ctx, id_pool, inner, on_path, depth + 1)?;
            // 存活过滤放在这里是有意的：`Protect`/`Heal` 只认活着的友军；倒下的那只
            // 已经不在战场上（`AllAlliesOfSource` 自己也筛过一次，这里幂等）。
            Ok(filter(state, set, |c| {
                is_alive(c) && c.definition_id.as_str() == definition
            }))
        }
        SelectorNode::StatusPick { op, inner, status_id } => {''')

    # ── sel.rs：把 `sel.alliesWithDefinition` 编译成 叶子 + 定义过滤 ─────────────────────────
    patch(SEL, '''            // 剩下两种下场，**没有第三种**（尤其没有"当成空集"）：''',
'''            // §313：`AllAlliesOfSourceWithDefinitionCombatantTargetSelector` ——
            // "按**定义**挑一只友军"（`Centurion` 的 `Protect` 给 `Mystic`）。
            // 与 `alliesWithStatus` 同一形状：固定叶子 + 一层过滤，只是过滤键是**定义 id**。
            "sel.alliesWithDefinition" => {
                let definition = node
                    .str_field("CombatantDefinitionId")?
                    .ok_or(SelError::MissingStatusId)?;
                let child = self.alloc()?;
                self.set(child, SelectorNode::Leaf(LeafSelector::AllAlliesOfSource))?;
                let definition_id = self.intern(definition)?;
                self.set(
                    slot,
                    SelectorNode::DefinitionFilter {
                        inner: child,
                        definition_id,
                    },
                )
            }
            // 剩下两种下场，**没有第三种**（尤其没有"当成空集"）：''')

    # ── intent.rs：新条件 ──────────────────────────────────────────────────────────────────
    patch(INTENT, '''    /// `intent.enemyAliveCount`（`Op, Value`）：**敌方阵营里还活着的战斗员个数**，**含出手者**。''',
'''    /// `intent.allyMissingHealth`（`Op, Value`）：**出手者自己的阵营里有没有人缺了 ≥ Value 血**。
    ///
    /// 本移植自己的条件（§313），为 `Mystic` 的 "If an enemy is missing 16 or more HP, use Heal"
    /// 而加。为什么不复用 `intent.healthPercent`：那条只看出手者**自己**，而 `Mystic` 是在
    /// 后排的奶妈 —— 写成"自己缺 16 血"几乎是另一条规则（它自己被打了才治疗）。
    /// `Value` 是**绝对血量**（wiki 的 16 / A21 那种数字），不是百分比。
    AllyMissingHealth,
    /// `intent.enemyAliveCount`（`Op, Value`）：**敌方阵营里还活着的战斗员个数**，**含出手者**。''')

    patch(INTENT, '''        ConditionKind::EnemyAliveCount,
    ];''', '''        ConditionKind::EnemyAliveCount,
        ConditionKind::AllyMissingHealth,
    ];''')

    patch(INTENT, '''            ConditionKind::EnemyAliveCount => "intent.enemyAliveCount",''',
'''            ConditionKind::EnemyAliveCount => "intent.enemyAliveCount",
            ConditionKind::AllyMissingHealth => "intent.allyMissingHealth",''')

    patch(INTENT, '''        // `intent.enemyAliveCount`（§257）：敌方阵营里**还活着**的战斗员个数（含出手者）。''',
'''        // §313：**自己的阵营里有没有人缺了 ≥ Value 血**（含出手者自己）。
        //
        // 存活才算：倒下的那只的 health_current 是 0，把它算进来会让"缺了 ≥ N 血"永远为真，
        // 于是 Mystic 会一直治疗一具尸体。
        ConditionKind::AllyMissingHealth => {
            let op = compare_op(condition)?;
            let value = condition.int_field("Value")?.ok_or(IntentError::Missing("Value"))?;
            let Some(actor) = state.combatant(actor) else {
                return Ok(false);
            };
            let team = actor.team_id;
            let mut missing = 0;
            let mut found = false;
            for combatant in state.combatants() {
                if combatant.team_id != team || !combatant.is_alive() {
                    continue;
                }
                missing = combatant.health_max - combatant.health_current;
                if op.apply(missing, value) {
                    found = true;
                    break;
                }
            }
            // `missing` 在这里只为了让"没有任何存活友军"时也走一遍比较 —— 那不可能发生
            // （出手者自己就在这个集合里），所以直接返回 found。
            let _ = missing;
            Ok(found)
        }
        // `intent.enemyAliveCount`（§257）：敌方阵营里**还活着**的战斗员个数（含出手者）。''')
    print('kernel: definition filter + allyMissingHealth')


main()

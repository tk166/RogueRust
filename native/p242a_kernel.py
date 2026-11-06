"""§242 内核：最后三张红卡的载体。

1. `spot_weakness` —— "If the enemy intends to attack"。意图是 `intent::select_action` 的
   **纯函数**结果（页面显示意图就用它），但它需要 `encounter`；而 `CombatState` 没有这一格
   （住在 wasm session 里）。⇒ 给 `CombatState` 加 `encounter`（model-only：`hash_golden` 是
   参考规范文本的逐字节复刻，参考没有这个字段，所以基线一个字节都不动），并给 `ExprContext`
   加 `content`（按值，`Content` 变 `Copy` —— 它只有 `&[u8]` + 两个整数）。
2. `blood_for_blood` —— "Costs 1 less for each time you lose HP this combat"。
   ⇒ `Combatant::hp_losses` 计数（与 `cards_played_this_turn` 同一类内核记账）+ 一条费用阶段，
   卡用 **tag** 声明"我的费用按掉血次数减"（与 `x_cost` 同一种做法）。
3. `corruption` —— "Skills cost 0. Whenever you play a Skill, Exhaust it."
   ⇒ 两条内核规则，键是**内容里的状态 id**（与 `standard.free_next_card` 等 4 条既有常量同形）：
   一条费用阶段（技能归 0）、一条落区规则（技能打完进消耗堆）。
"""
import io

K = 'D:/Vibe/sts-tui/kernel/rd-core/src/'


def patch(name, pairs):
    path = K + name
    s = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert s.count(old) == 1, (name, old[:70], s.count(old))
        s = s.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print('patched', name)


# ============================================================ content.rs：Content 变 Copy
patch('content.rs', [
    ('''/// 一份已解析的镜像。所有表都是对 `blob` 的借用。
pub struct Content<'a> {''',
     '''/// 一份已解析的镜像。所有表都是对 `blob` 的借用。
///
/// §242：`Copy` —— 三个字段都是 `Copy`（一个切片 + 两个整数），而 `ExprContext` 需要**按值**带着它
/// 进表达式求值（"这张牌能不能打"要问敌人的意图，而意图查询要内容）。按值带省掉一个生命周期参数，
/// 否则 `ExprContext<'a>` 得变成 `<'a, 'c>` 并波及几十个签名。
#[derive(Clone, Copy)]
pub struct Content<'a> {'''),
])

# ============================================================ state.rs：encounter + hp_losses
patch('state.rs', [
    ('''    pub current_round: i32,''',
     '''    pub current_round: i32,
    /// §242：这场战斗来自哪个**遭遇**（`ENCT` 行号）。
    ///
    /// 为什么需要它：`spot_weakness` 要问"敌人这回合是不是打算攻击"，而那件事是
    /// `intent::select_action(content, encounter, slot, actor, round)` 的**纯函数**结果 ——
    /// 页面显示意图用的就是它。没有 `encounter` 就定位不到敌人槽位。
    ///
    /// ⚠️ **model-only**：参考没有这个字段，`hash_golden` 是参考规范文本的逐字节复刻
    /// （`snapshot.rs`），所以加它**不移动任何基线**。`u32::MAX` = "没有遭遇"（纯内核测试的默认值）
    /// ⇒ 意图查询一律解不出，`intent.*` 事实为假 —— 响亮而安全的那一侧。
    pub encounter: u32,'''),
])

s = io.open(K + 'state.rs', encoding='utf-8').read()
# 构造时把 encounter 初始化成"没有遭遇"
assert s.count('''            current_round: 0,''') >= 1
s = s.replace('''            current_round: 0,''', '''            current_round: 0,
            // §242：纯内核测试没有遭遇 ⇒ 意图查询一律解不出（见字段文档）。
            encounter: u32::MAX, ''', 1)
io.open(K + 'state.rs', 'w', encoding='utf-8', newline='\n').write(s)
print('patched state.rs (encounter)')

# ============================================================ expr.rs：content 进上下文
patch('expr.rs', [
    ('''    pub event_flags: u16,''',
     '''    /// §242：内容（"敌人的意图"要查 `ENCT`/`EACT` 表）。按值 —— `Content` 是 `Copy`。
    ///
    /// `None` = 这个求值点没有内容（纯表达式单测）。需要内容的表达式在 `None` 时**响亮失败**
    /// （`UnsupportedKind`），绝不"当成假"——那会让一张牌在某种调用路径上安静地不生效。
    pub content: Option<crate::content::Content<'a>>,
    pub event_flags: u16,'''),
])

# ============================================================ exec.rs：context 构造 + hp_losses 记账
s = io.open(K + 'exec.rs', encoding='utf-8').read()
old = '''            event_flags: self.event_flags,'''
assert s.count(old) == 1
s = s.replace(old, '''            content: self.content.copied(),
            event_flags: self.event_flags,''')
io.open(K + 'exec.rs', 'w', encoding='utf-8', newline='\n').write(s)
print('patched exec.rs (expr context)')
print('done (part 1)')

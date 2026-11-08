"""§296 A3：`chemical_x` —— X 费牌的 X 加 2。

## 为什么是"内核规则 + 内容载体"（与 §263 的三件同一条路）

`x.cost` 是**节目里的表达式**（`whirlwind` 的 `repeat.Count`），它读的是 `ExecContext::x_cost`，
而那个数在 `play.rs` 里由"这一次真的付掉多少"算出。节目没法表达"X 再加 2"，
所以这必须是一条**内核规则** —— 与 `the_boot` / `torii` / `tungsten_rod`（§263）完全同族：
**内核认这个状态 id，数字是 wiki 的常量，内容那一行是"载体 + 页面显示"**。

## 顺序

X 的**语义**是"你为这张 X 费牌付了多少"。`chemical_x` 改的是**效果里用的那个 X**，
不是付的钱：付 3 点、`whirlwind` 打 5 次。所以加成加在 `x_cost` 上（其后所有读
`x.cost` 的地方自动一致），**不**动 `paid`（钱照付、状态照算）。

## 与已知偏差的关系

§161.5 之后已知：每副本价格（`standard.card_cost_delta`）对 X 费牌**看不见** ——
X 费牌走 `x_cost_payment`（全部能量），所以"打个折"没有意义。`chemical_x` 恰恰相反：
它加的是**效果**不是**价格**，所以在 X 费牌上它是有效的，这条不对称继续成立。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'
PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
CATALOG = 'D:/Vibe/sts-tui/kernel/rd-core/src/status_catalog.rs'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
RUNSTATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(path, old, new, count=1):
    s = io.open(path, encoding='utf-8').read()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(s.replace(old, new))


def main():
    # ── 1. 常量（与 §263 那三条放在一起：同一族）
    patch(EXEC, '''const THE_BOOT: (&str, i32, i32) = ("standard.the_boot", 4, 5);''',
                '''/// §296：`chemical_x` —— "The effects of your cost X cards are increased by 2"。
/// 与下面三条同族：内核认这个状态 id，数字是 wiki 的常量，内容那一行是"载体 + 页面显示"。
pub const CHEMICAL_X: (&str, i32) = ("standard.chemical_x", 2);
const THE_BOOT: (&str, i32, i32) = ("standard.the_boot", 4, 5);''')

    # `carries_status` 要给 play.rs 用 ⇒ 公开
    patch(EXEC, '''fn carries_status(state: &CombatState, id: &CombatantId, definition: &str) -> bool {''',
                '''pub fn carries_status(state: &CombatState, id: &CombatantId, definition: &str) -> bool {''')

    # ── 2. `play.rs`：X 上加成
    patch(PLAY, '''    let x_cost = {
        let mut total = 0i32;
        for index in 0..paid.len() {
            if let Some(entry) = paid.get(index) {
                total = total.saturating_add(entry.amount);
            }
        }''',
               '''    // §296：`chemical_x` —— "The effects of your cost X cards are increased by 2"。
    // 加在**效果里用的那个 X**上（`x.cost`），不是付的钱：付 3 点、`whirlwind` 打 5 次。
    // 与 §263 的三件同一条路：内核认状态 id，数字是 wiki 的常量。
    let x_bonus = if crate::exec::carries_status(state, &card.source, crate::exec::CHEMICAL_X.0) {
        crate::exec::CHEMICAL_X.1
    } else {
        0
    };
    let x_cost = {
        let mut total = x_bonus;
        for index in 0..paid.len() {
            if let Some(entry) = paid.get(index) {
                total = total.saturating_add(entry.amount);
            }
        }''')

    # ── 3. 内容：载体状态（没有修饰器、没有触发器 —— 规则在内核）
    import json
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    ids = {row['Id'] for row in doc['Statuses']}
    if 'standard.chemical_x' not in ids:
        doc['Statuses'].append({
            'Id': 'standard.chemical_x',
            'PackageId': 'sts',
            'NameKey': 'Chemical X',
            'DescriptionKey': 'The effects of your cost X cards are increased by 2.',
            'Polarity': 'Buff',
            'UsesStacks': True,
            'UsesDuration': False,
            'UsesCharges': False,
            'StackingBehavior': 'MergeWithExistingInstance',
            'Tags': ['buff'],
            'PassiveModifiers': [],
            'Triggers': [],
        })
    relics = {row['Id'] for row in doc['Relics']}
    if 'chemical_x' not in relics:
        doc['Relics'].append({
            'Id': 'chemical_x',
            'DisplayName': 'Chemical X',
            'RunPrograms': None,
            'CombatRules': None,
            'Rarity': 'Shop',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('statuses', len(doc['Statuses']), 'relics', len(doc['Relics']))

    # ── 4. rd-run 表项
    patch(RUNSTATE, '''            "hand_drill" => Some(RelicEffect::StartCombatStatus("standard.hand_drill", 1)),''',
                     '''            "hand_drill" => Some(RelicEffect::StartCombatStatus("standard.hand_drill", 1)),
            // §296：`chemical_x` —— 同样是开战挂一条内容状态；规则在内核（`x.cost` 上加 2）。
            "chemical_x" => Some(RelicEffect::StartCombatStatus("standard.chemical_x", 1)),''')

    # ── 5. status_catalog：这条**有**内核规则（`play.rs` 读 id），所以进 has_behaviour
    patch(CATALOG, '''            // §295: `hand_drill` —— 行为全在内容的 `BlockBroken` 触发器里。
            | "standard.hand_drill"''',
                   '''            // §295: `hand_drill` —— 行为全在内容的 `BlockBroken` 触发器里。
            | "standard.hand_drill"
            // §296: `chemical_x` —— 规则**在内核**（`play.rs` 按 id 看"有没有"，给 X 加 2）。
            // 内容那一行没有修饰器也没有触发器：它像 §231 的 `standard.no_draw`，是个**开关**。
            | "standard.chemical_x"''')

    # ── 6. 内容门的三张表
    patch(GATE, '''    # §295: +1 (`standard.hand_drill` —— `BlockBroken` 触发器).
    "statuses": 132,''', '''    # §295: +1 (`standard.hand_drill` —— `BlockBroken` 触发器)。
    # §296: +1 (`standard.chemical_x` —— 内核规则的开关，内容那一行是载体).
    "statuses": 133,''')
    patch(GATE, '''    # §295：行为全在 `BlockBroken` 触发器里。
    "standard.hand_drill": [],''', '''    # §295：行为全在 `BlockBroken` 触发器里。
    "standard.hand_drill": [],
    # §296：`chemical_x` 的规则**在内核**（`play.rs` 给 X 加 2），内容这一行是开关。
    "standard.chemical_x": [],''')
    patch(GATE, '''                     "standard.hand_drill"):''',
                  '''                     "standard.hand_drill",
                     "standard.chemical_x"):''')
    patch(GATE, '''                        "standard.hand_drill": ["BlockBroken"]}[sid]''',
                  '''                        "standard.hand_drill": ["BlockBroken"],
                        # §296：`chemical_x` 没有触发器（规则在内核）。
                        "standard.chemical_x": []}[sid]''')
    patch(GATE, '''                      "hand_drill",''', '''                      "hand_drill",
                      # §296：X 费牌的 X 加 2。
                      "chemical_x",''')
    print('wired')


main()

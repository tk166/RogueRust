"""§380：商店的药水货架在**腰带满**时必须不可买（内核已经会拒绝，界面没问）。

## 怎么发现的

`web-soak`（随机点击 172 次的那道闸门）在 seed 103 上抓到一条 **dead control**：

    买药水 被拒 · Capacity

也就是"界面给了一个能点的按钮，内核拒绝它"。这条与玩家报的"状态看不见"是同一类：
**界面不知道自己处在什么局面**（腰带 3/3 满）。

## 修法（两条，缺一不可）

1. 内核把 `potion_slots()` 导出（`rd_run_potion_slots`）—— 容量是**规则**（A11 减一格、
   `potion_belt` 加两格），UI 不许自己算；
2. 商店的药水货架在 `已带瓶数 >= 容量` 时**不可点**，并写清原因（"腰带满了"）。
   与"买不起"一样：**能点但不给理由**是最糟的那一档。

⚠️ 只有药水这一排需要它：卡/遗物没有容量上限。
"""

import io

# ── 1. 内核导出 ────────────────────────────────────────────────────────────
PATH = 'kernel/rd-wasm/src/run.rs'
t = io.open(PATH, encoding='utf-8').read()

ANCHOR = '''/// `env-abi.md` §11.2. `i32::MIN` for an out-of-range index or field.'''
assert t.count(ANCHOR) == 1

BLOCK = '''/// 药水腰带**能装几瓶**（§380）。规则在 `RunState::potion_slots`：3 格，A11 减 1，
/// `potion_belt` 加 2 —— 界面**不许**自己算（同一份规则两处认识就会漂）。
///
/// 用途：商店的药水货架在腰带满时必须不可点。旧版没问这一格，于是"点了被内核拒绝"
/// （`web-soak` 抓到的 dead control：`买药水 被拒 · Capacity`）。
#[no_mangle]
pub extern "C" fn rd_run_potion_slots() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |session| i32::from(session.state.potion_slots()))
}

'''
t = t.replace(ANCHOR, BLOCK + ANCHOR)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('kernel: rd_run_potion_slots')

# ── 2. host 绑定 ───────────────────────────────────────────────────────────
PATH = 'web-next/src/wasm/host.ts'
t = io.open(PATH, encoding='utf-8').read()
OLD = '''  "rd_run_potion_count",
  "rd_run_potion_id_len",'''
NEW = '''  "rd_run_potion_count",
  // §380：腰带容量（3 / A11 减 1 / potion_belt 加 2）。界面不许自己算。
  "rd_run_potion_slots",
  "rd_run_potion_id_len",'''
assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

OLD2 = '''  potionCount(): number {
    return (this.ex.rd_run_potion_count as () => number)();
  }'''
NEW2 = '''  potionCount(): number {
    return (this.ex.rd_run_potion_count as () => number)();
  }

  /** 腰带容量（`rd_run_potion_slots`，§380）。`-1` = 没有局。 */
  potionSlots(): number {
    return (this.ex.rd_run_potion_slots as () => number)();
  }'''
assert t.count(OLD2) == 1
t = t.replace(OLD2, NEW2)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('host: potionSlots()')

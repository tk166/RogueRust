"""§280：事件效果新增四个原子 + 百分比改成**千分**（支持 12.5%）。

为什么需要（都来自真内容）：

* `the_cleric` 的两个选项是"**花**金币"（35 / 50，A15 的 Purify 是 75）。旧词表里的 `gold`
  只有正值，而 `adjust_gold(-75)` 在只有 50 金币时会把金币**夹到 0** —— 玩家白拿了服务。
  所以"付钱"要一个会**响亮拒绝**的原子：`gold_cost:<n>`。
* `the_cleric` 的 Heal 是"回复最大 HP 的 **25%**" —— 需要 `heal_pct:<n>`。
* `the_moai_head` 的 `[Jump Inside]` 是"**回满血**，再失去最大 HP 的 12.5%（A15 18%）" ——
  需要 `heal_full`，而 12.5% 说明百分比的内部单位必须是**千分**（整数的 1% 表达不了）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ---------------------------------------------------------------- 文档表
    s = patch(s, '''/// | `damage_pct:<n>` | lose `floor(max HP × n / 100)` HP (the wiki's *Smash*, A15 rides in the `...Asc` list) |
/// | `max_hp_pct:<n>` | lose `max(1, floor(max HP × n / 100))` **max** HP (the wiki's *Hide*) |''',
'''/// | `damage_pct:<n>` | lose `floor(max HP × n / 100)` HP (the wiki's *Smash*, A15 rides in the `...Asc` list) |
/// | `max_hp_pct:<n>` | lose `max(1, floor(max HP × n / 100))` **max** HP (the wiki's *Hide*) |
/// | `gold_cost:<n>` | **pay** `n` gold; refused when short (the wiki's *Cleric*) |
/// | `heal_pct:<n>` | heal `floor(max HP × n / 100)` HP (the Cleric's *Heal*) |
/// | `heal_full` | heal to the maximum (the Moai Head's *Jump Inside*) |
///
/// ⚠️ `damage_pct` / `max_hp_pct` / `heal_pct` 的 `<n>` **允许一位小数**（`12.5`），内部按
/// **千分**存。原因：真内容里就有 12.5%（`The Moai Head` 的 Jump Inside），而整数百分比
/// 表达不了它 —— 而"四舍五入到 12%"是**另一个规则**，不是同一个规则的近似。''')

    # ---------------------------------------------------------------- 枚举
    s = patch(s, '''    /// §278：按**最大 HP 的百分比**掉血（`damage_pct`）。`Golden Idol` 的 Smash 25%（A15 35%）。
    LoseHealthPercent(i32),
    /// §278：按**最大 HP 的百分比**扣上限（`max_hp_pct`）。`Golden Idol` 的 Hide 8%（A15 10%）。
    LoseMaxHealthPercent(i32),''',
'''    /// §278：按**最大 HP 的千分比**掉血（`damage_pct`）。`Golden Idol` 的 Smash 25%（A15 35%）。
    ///
    /// §280 起单位是**千分**（`250` = 25%），因为真内容里有 12.5%。
    LoseHealthPercent(i32),
    /// §278：按**最大 HP 的千分比**扣上限（`max_hp_pct`）。`Golden Idol` 的 Hide 8%（A15 10%）。
    LoseMaxHealthPercent(i32),
    /// §280：**付** `n` 金币（`gold_cost`）。不够就拒绝 —— 不是"扣到 0 为止"。
    GoldCost(i32),
    /// §280：按**最大 HP 的千分比**回血（`heal_pct`）。`The Cleric` 的 Heal 25%。
    HealPercent(i32),
    /// §280：回满血（`heal_full`）。`The Moai Head` 的 Jump Inside。
    HealFull,''')

    # ---------------------------------------------------------------- 解析
    s = patch(s, '''                    "damage_pct" => match payload.parse::<i32>() {
                        Ok(percent) if percent > 0 && percent <= 100 => {
                            (Self::LoseHealthPercent(percent), None)
                        }
                        _ => return None,
                    },
                    "max_hp_pct" => match payload.parse::<i32>() {
                        Ok(percent) if percent > 0 && percent <= 100 => {
                            (Self::LoseMaxHealthPercent(percent), None)
                        }
                        _ => return None,
                    },''',
'''                    "damage_pct" => match parse_permille(payload) {
                        Some(tenths) => (Self::LoseHealthPercent(tenths), None),
                        None => return None,
                    },
                    "max_hp_pct" => match parse_permille(payload) {
                        Some(tenths) => (Self::LoseMaxHealthPercent(tenths), None),
                        None => return None,
                    },
                    // §280：**付钱**。与 `gold`（正增量）是两条不同的路：那一条随手就可能
                    // 把金币夹到 0，而"花 75 只有 50"必须响亮拒绝。
                    "gold_cost" => match parse_permille(payload) {
                        // 金币是整数，不能有小数；`parse_permille` 顺带把 `12.5` 变成 `125`，
                        // 所以这里只接受**整百分**（千分值是 10 的倍数）。
                        Some(tenths) if tenths % 10 == 0 && tenths > 0 => {
                            (Self::GoldCost(tenths / 10), None)
                        }
                        _ => return None,
                    },
                    "heal_pct" => match parse_permille(payload) {
                        Some(tenths) => (Self::HealPercent(tenths), None),
                        None => return None,
                    },''')

    # `heal_full` 是裸词，放在裸词那一组里
    s = patch(s, '''            "nothing" => (Self::Nothing, None),''',
              '''            "nothing" => (Self::Nothing, None),
            // §280：`The Moai Head` 的 `[Jump Inside]`："Heal to full HP".
            "heal_full" => (Self::HealFull, None),''')

    # ---------------------------------------------------------------- 应用
    s = patch(s, '''            EventEffect::LoseHealthPercent(percent) => {
                let loss = percent_of(self.health_max, percent);
                self.adjust_health(-loss);
            }
            EventEffect::LoseMaxHealthPercent(percent) => {
                let loss = percent_of(self.health_max, percent).max(1);''',
'''            EventEffect::LoseHealthPercent(tenths) => {
                let loss = permille_of(self.health_max, tenths);
                self.adjust_health(-loss);
            }
            EventEffect::HealPercent(tenths) => {
                let amount = permille_of(self.health_max, tenths);
                self.heal_after_combat(amount);
            }
            // §280："Heal to full HP" —— 不是"回 999"，而是"回到上限"（上限是会变的）。
            EventEffect::HealFull => {
                let full = self.health_max;
                self.heal_after_combat(full);
            }
            EventEffect::GoldCost(cost) => {
                if self.gold < cost {
                    // **响亮**：夹到 0 会让"花 75 只有 50"变成"白拿服务"，而屏幕上一切正常。
                    return Err(RunError::NotEnoughGold {
                        price: cost,
                        gold: self.gold,
                    });
                }
                self.adjust_gold(-cost);
            }
            EventEffect::LoseMaxHealthPercent(tenths) => {
                let loss = permille_of(self.health_max, tenths).max(1);''')

    # ---------------------------------------------------------------- 助手
    s = patch(s, '''/// §278：`floor(base × percent / 100)`，用整数算（内核不碰浮点）。
fn percent_of(base: i32, percent: i32) -> i32 {
    base.saturating_mul(percent) / 100
}''',
'''/// §280：`floor(base × tenths / 1000)`，用整数算（内核不碰浮点）。
///
/// 参数是**千分比**（`250` = 25%，`125` = 12.5%）。§278 时它是百分比；改成千分是因为真内容
/// 里就有 12.5%（`The Moai Head`）。名字一起改了 —— 留着 `percent_of` 而语义变成千分，
/// 是那种"看着对、算出来差十倍"的错。
fn permille_of(base: i32, tenths: i32) -> i32 {
    base.saturating_mul(tenths) / 1000
}

/// §280：把 `"25"` / `"12.5"` 这样的**百分字符串**解成千分值（`250` / `125`）。
///
/// 只接受：1..=100 的百分比、可选**一位**小数、没有符号。`None` = 词表外（调用方拒绝）。
/// 为什么不用 `f32`：内核 `no_std` 里不碰浮点（这条纪律让"同一个内容在任何平台算出同一个数"
/// 是**结构上**成立的，而不是靠约定）。
fn parse_permille(text: &str) -> Option<i32> {
    let (whole, fraction) = match text.split_once('.') {
        Some((whole, fraction)) => (whole, Some(fraction)),
        None => (text, None),
    };
    if whole.is_empty() || whole.len() > 2 {
        return None;
    }
    let whole: i32 = whole.parse().ok()?;
    let tenths = match fraction {
        None => 0,
        Some(fraction) => {
            // 恰好一位小数；`12.50` 与 `12.` 都是词表外（它们表达同一件事的不同拼法，
            // 而两套拼法迟早会有一处被忘掉）。
            if fraction.len() != 1 {
                return None;
            }
            fraction.parse::<i32>().ok()?
        }
    };
    if !(1..=100).contains(&whole) {
        return None;
    }
    if whole == 100 && tenths > 0 {
        return None;
    }
    let total = whole.checked_mul(10)?.checked_add(tenths)?;
    Some(total)
}''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('§280 atoms: gold_cost / heal_pct / heal_full + permille')


main()

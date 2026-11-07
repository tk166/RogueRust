"""§278：事件的百分比效果原子（`damage_pct:<n>` / `max_hp_pct:<n>`）。

为什么需要：`Golden Idol` 的巨石分支是**按最大 HP 的百分比**扣血/扣上限（Smash 25%，
A15 35%；Hide 8%，A15 10%）。原来的闭词表只有**定值**，于是那一支只能写成一个凭空
挑的数字（旧内容写的就是 20 —— 与 wiki 的"25% of 80" 恰好相同，但换一副牌就不对了）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ------------------------------------------------------------------ 文档表
    s = patch(s, '''/// | `curse:<card id>` | add that card to the deck (the id must be in the pool) |''',
              '''/// | `damage_pct:<n>` | lose `floor(max HP × n / 100)` HP (the wiki's *Smash*, A15 rides in the `...Asc` list) |
/// | `max_hp_pct:<n>` | lose `max(1, floor(max HP × n / 100))` **max** HP (the wiki's *Hide*) |
/// | `curse:<card id>` | add that card to the deck (the id must be in the pool) |''')

    # ------------------------------------------------------------------ 枚举
    s = patch(s, '''    /// Lose HP -- an event can hurt.
    LoseHealth(i32),''','''    /// Lose HP -- an event can hurt.
    LoseHealth(i32),
    /// §278：按**最大 HP 的百分比**掉血（`damage_pct`）。`Golden Idol` 的 Smash 25%（A15 35%）。
    LoseHealthPercent(i32),
    /// §278：按**最大 HP 的百分比**扣上限（`max_hp_pct`）。`Golden Idol` 的 Hide 8%（A15 10%）。
    LoseMaxHealthPercent(i32),''')

    # ------------------------------------------------------------------ 解析
    s = patch(s, '''                match kind {
                    "curse" => (Self::GainCurse, Some(payload)),
                    "relic" => (Self::GainRelic, Some(payload)),
                    _ => return None,
                }''','''                match kind {
                    "curse" => (Self::GainCurse, Some(payload)),
                    "relic" => (Self::GainRelic, Some(payload)),
                    // §278：`damage_pct:25` —— **数字在词里**（`Amount` 那一格与它无关），
                    // 因为 A15 的 35% 是另一条效果，而不是同一个数字换了值。
                    "damage_pct" => match payload.parse::<i32>() {
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
                    },
                    _ => return None,
                }''')

    # ------------------------------------------------------------------ 应用
    s = patch(s, '''            EventEffect::LoseHealth(n) => self.adjust_health(-n),''',
              '''            EventEffect::LoseHealth(n) => self.adjust_health(-n),
            // §278：百分比在**应用时**才乘最大 HP（内容里写 `25`，不是写死 "20"）。
            // `floor` 而不是四舍五入：wiki 的 Hide 明说 "the larger of 1 and Max HP × 8%",
            // 也就是下限 1 的**向下取整** —— Smash 用同一个取整，否则两处会给出不同的数。
            EventEffect::LoseHealthPercent(percent) => {
                let loss = percent_of(self.health_max, percent);
                self.adjust_health(-loss);
            }
            EventEffect::LoseMaxHealthPercent(percent) => {
                let loss = percent_of(self.health_max, percent).max(1);
                self.health_max -= loss;
                if self.health > self.health_max {
                    self.health = self.health_max;
                }
            }''')

    # ------------------------------------------------------------------ 助手
    s = patch(s, '''impl EventEffect {''','''/// §278：`floor(base × percent / 100)`，用整数算（内核不碰浮点）。
fn percent_of(base: i32, percent: i32) -> i32 {
    base.saturating_mul(percent) / 100
}

impl EventEffect {''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('percent atoms added')


main()

"""§310（四）：`removeDebuffs` 的极性要从**定义**查（不是从实例字段）。

第一版用 `instance.polarity`，判据当场红了：清完之后力量/敏捷/荆棘也全没了。
根因是**实例上的极性可以撒谎** —— 测试助手 `status()` 给每一条都写 `Debuff`，
而运行期它是由内容定义在 `apply_status` 那一刻抄进去的。内核里早就有一个唯一的入口
`status_polarity(definition_id, content)`（内容优先、目录兜底，Artifact 也用它），
所以这里改成查定义。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch('''    for target in targets.iter().take(count) {
        let Some(combatant) = ctx.state.combatant_mut(target) else {
            continue;
        };
        let mut doomed = [0usize; crate::state::MAX_STATUSES_PER_COMBATANT];
        let mut doomed_len = 0;
        for (index, instance) in combatant.statuses().iter().enumerate() {
            if instance.polarity == crate::state::StatusPolarity::Debuff {
                doomed[doomed_len] = index;
                doomed_len += 1;
            }
        }
        for offset in 0..doomed_len {
            combatant.remove_status(doomed[doomed_len - 1 - offset]);
        }
    }''',
'''    for target in targets.iter().take(count) {
        // 极性查**定义**而不是实例字段：实例上的那个值是 `applyStatus` 那一刻抄进去的，
        // 谁都可能把它写成别的（测试助手就是）。`status_polarity` 是内核里的唯一入口
        // （内容 `STAT.Polarity` 优先、目录兜底），Artifact 的判定也用它。
        let mut doomed = [0usize; crate::state::MAX_STATUSES_PER_COMBATANT];
        let mut doomed_len = 0;
        {
            let Some(combatant) = ctx.state.combatant(target) else {
                continue;
            };
            for (index, instance) in combatant.statuses().iter().enumerate() {
                if status_polarity(instance.definition_id.as_str(), ctx.content)?
                    == crate::state::StatusPolarity::Debuff
                {
                    doomed[doomed_len] = index;
                    doomed_len += 1;
                }
            }
        }
        if doomed_len == 0 {
            continue;
        }
        let Some(combatant) = ctx.state.combatant_mut(target) else {
            continue;
        };
        for offset in 0..doomed_len {
            combatant.remove_status(doomed[doomed_len - 1 - offset]);
        }
    }''')
    print('polarity source fixed')


main()

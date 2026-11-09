"""§309（二）：剩下四处合并循环也走 `add_status`（同一份规则只许存在一次）。"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    # (a) per-curse
    patch('''                Some(RelicEffect::StartCombatStatusPerCurse(id, stacks)) => {
                    // §261：与上一支同样的合并规则（两件遗物给同一条状态要相加）。
                    let mut merged = false;
                    for entry in bonus.per_curse_statuses.iter_mut().take(bonus.per_curse_status_count)
                    {
                        if let Some(existing) = entry {
                            if existing.id == id {
                                existing.stacks += stacks;
                                merged = true;
                                break;
                            }
                        }
                    }
                    if !merged {
                        let _ = bonus.push_per_curse_status(id, stacks);
                    }
                }''',
'''                Some(RelicEffect::StartCombatStatusPerCurse(id, stacks)) => {
                    // §261/§309：同一处规则（相加，不覆盖）。
                    add_status(
                        &mut bonus.per_curse_statuses,
                        &mut bonus.per_curse_status_count,
                        id,
                        stacks,
                        "per-curse",
                    );
                }''')

    # (b) 主表的 StartCombatStatus
    patch('''                Some(RelicEffect::StartCombatStatus(id, stacks)) => {
                    // Two relics granting the same status must **merge**, not overwrite: the same
                    // rule the kernel uses when a status is applied twice.
                    let mut merged = false;
                    for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                        if let Some(existing) = entry {
                            if existing.id == id {
                                existing.stacks += stacks;
                                merged = true;
                                break;
                            }
                        }
                    }
                    if !merged {
                        let _ = bonus.push_status(id, stacks);
                    }
                }''',
'''                Some(RelicEffect::StartCombatStatus(id, stacks)) => {
                    // Two relics granting the same status must **merge**, not overwrite: the same
                    // rule the kernel uses when a status is applied twice. §309: one place only.
                    add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
                }''')

    # (c) ancient_tea_set
    patch('''            {
                let mut merged = false;
                for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                    if let Some(existing) = entry {
                        if existing.id == id {
                            existing.stacks += stacks;
                            merged = true;
                            break;
                        }
                    }
                }
                if !merged {
                    let _ = bonus.push_status(id, stacks);
                }
            }''',
'''            {
                add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
            }''')

    # (d) RELIC_SECOND_HALVES
    patch('''            if !self.holds_relic(relic) {
                continue;
            }
            let mut merged = false;
            for entry in bonus.statuses.iter_mut().take(bonus.status_count) {
                if let Some(existing) = entry {
                    if existing.id == id {
                        existing.stacks += stacks;
                        merged = true;
                        break;
                    }
                }
            }
            if !merged {
                let _ = bonus.push_status(id, stacks);
            }
        }''',
'''            if !self.holds_relic(relic) {
                continue;
            }
            add_status(&mut bonus.statuses, &mut bonus.status_count, id, stacks, "hero");
        }''')

    print('four more sites converted')


main()

"""§342 负控：三条，每条都必须让**指定的**判据红。

1. `rd_run_shop_colorless_price` 改回挂牌价 ⇒ `the_page_price_is_the_price_the_kernel_charges` 红。
2. `restock_relic_slot` 改回硬编码 Common 档 ⇒ `restocked_relics_are_priced_by_their_own_rarity` 红。
3. `remove_card_price` 改回 `shop_price(marked_up(50))` ⇒
   `smiling_mask_locks_removal_at_fifty_whatever_the_discounts` 红。

⚠️ 每条都断言**具体失败文本**：只断言"有测试红了"的话，一条编译错会让三条全部假装成功。
"""

import io
import subprocess
import sys

RUN = 'kernel/rd-wasm/src/run.rs'
STATE = 'kernel/rd-run/src/state.rs'


def run(pkg, test_name):
    p = subprocess.run(['cargo', 'test', '-p', pkg, '--release', '--', '--test-threads=1', test_name]
                       if pkg == 'rd-wasm'
                       else ['cargo', 'test', '-p', pkg, '--release', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def case(label, path, pkg, pairs, test_name, needle):
    raw = io.open(path, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run(pkg, test_name)
        ok = needle in out and test_name in out
        print('  %-48s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line or 'test result' in line:
                    print('      ', line.strip()[:140])
                    break
    finally:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① 无色价改回挂牌价
ok &= case(
    '① 无色 ABI 改回挂牌价',
    RUN, 'rd-wasm',
    [('''            if offer.price < 0 {
                return offer.price;
            }
            session.state.shop_price(offer.price)
        })
}

/// §332：买无色货架第 `slot` 张。''',
      '''            offer.price
        })
}

/// §332：买无色货架第 `slot` 张。''')],
    'the_page_price_is_the_price_the_kernel_charges',
    'must be charged',
)

# ② 遗物补货改回 Common 档
ok &= case(
    '② 遗物补货改回 Common 硬编码',
    STATE, 'rd-run',
    [('''        let (low, high) = relic_price_band(rarity);
        let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;''',
      '''        let _ = rarity;
        let price = 143 + self.rng.roll(RunStream::Shop, 15)? as i32;''')],
    'restocked_relics_are_priced_by_their_own_rarity',
    'its band is',
)

# ③ Smiling Mask 改回打折
ok &= case(
    '③ Smiling Mask 改回 shop_price(marked_up(50))',
    STATE, 'rd-run',
    [('''        if self.holds_relic_effect(RelicEffect::RemovePriceFlat(50)) {
            return SHOP_REMOVE_FLAT;
        }''',
      '''        if self.holds_relic_effect(RelicEffect::RemovePriceFlat(50)) {
            return self.shop_price(self.marked_up(SHOP_REMOVE_FLAT));
        }''')],
    'smiling_mask_locks_removal_at_fifty_whatever_the_discounts',
    'must all be 50',
)

# ④ 入口退回旧签名（药水池为空）⇒ 那条"四排必须从入口就摆满"的守卫必须红。
#    这条钉住的正是 §342 最贵的一处发现：§332 的四排在真实路径上只有两排，
#    而所有既有判据都**绕过了入口**（直接调 `stock_shop`）。
ok &= case(
    '④ 入口退回 begin_node（空药水池）',
    RUN, 'rd-wasm',
    [('    let kind = match session.state.begin_node_stocked(&cards, &relics, &potions) {',
      '    let _ = &potions;\n    let kind = match session.state.begin_node(&cards, &relics) {')],
    'the_page_price_is_the_price_the_kernel_charges',
    '3 potions',
)

out = run('rd-run', '')
print('  还原后 rd-run：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)

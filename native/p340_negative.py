"""§340 负控：四条，每条都必须让**指定的**判据红，且失败消息各不相同。

1. 补货恢复 `marked_up` ⇒ `restocked_items_are_not_marked_up_by_ascension_16` 红
   （消息里是 "costs the **base** band"）。
2. `buy_colorless` 不补货 ⇒ `the_courier_restocks_all_four_shelves` 红在
   "the colourless shelf must not shrink"。
3. `buy_potion` 不补货 ⇒ 同一个测试红在 "the potion shelf must not shrink"
   （②③ 用**不同消息**区分，否则"某一排没补"与"另一排没补"看起来一样）。
4. 去掉回滚 ⇒ `a_failed_restock_unwinds_the_whole_purchase` 红。

⚠️ 每条都断言**具体失败文本**：只断言"有测试红了"的话，一条编译错会让四条全部假装成功。
"""

import io
import subprocess
import sys

PATH = 'kernel/rd-run/src/state.rs'


def run(test_name):
    p = subprocess.run(['cargo', 'test', '-p', 'rd-run', '--release', test_name],
                       cwd='kernel', capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def mutate(label, pairs, test_name, needle):
    raw = io.open(PATH, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run(test_name)
        ok = needle in out and test_name in out
        print('  %-50s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'panicked' in line or 'error[' in line or 'test result' in line:
                    print('      ', line.strip()[:130])
                    break
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① 补货恢复 A16 涨价
ok &= mutate(
    '① 补货恢复 marked_up（A16 涨价）',
    [('''            // §340：**补货不施加 A16 涨价**（wiki：*"Any item re-stocked by The Courier will not be
            // affected by the 10% price increased 16"*）。首次铺货才走 `marked_up`。
            // 折扣仍然在付款时算（`shop_price`），与陈列时同一条规矩。
            price,''',
      '''            price: self.marked_up(price),''')],
    'restocked_items_are_not_marked_up_by_ascension_16',
    'costs the **base** band',
)

# ② 无色不补货
ok &= mutate(
    '② buy_colorless 不补货',
    [('''        if self.holds_relic("the_courier") {
            if let Err(error) = self.restock_colorless_slot(slot, card_pool) {
                *self = before;
                return Err(error);
            }
        }
        Ok(())''',
      '''        Ok(())''')],
    'the_courier_restocks_all_four_shelves',
    'the colourless shelf must not shrink',
)

# ③ 药水不补货
ok &= mutate(
    '③ buy_potion 不补货',
    [('''        if self.holds_relic("the_courier") {
            if let Err(error) = self.restock_potion_slot(slot, potion_pool) {
                *self = before;
                return Err(error);
            }
        }
        Ok(())''',
      '''        Ok(())''')],
    'the_courier_restocks_all_four_shelves',
    'the potion shelf must not shrink',
)

# ④ 去掉回滚（保留 Err，但状态已经改了）
ok &= mutate(
    '④ 补货失败不回滚',
    [('''            if let Err(error) = self.restock_card_slot(slot, card_pool) {
                // §340：补货失败 ⇒ **整笔交易**回滚（金币、牌、货架一起），不留半个提交。
                *self = before;
                return Err(error);
            }''',
      '''            if let Err(error) = self.restock_card_slot(slot, card_pool) {
                return Err(error);
            }''')],
    'a_failed_restock_unwinds_the_whole_purchase',
    'must leave the run byte-identical',
)

out = run('')
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)

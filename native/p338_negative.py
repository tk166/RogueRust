"""§338 负控：三处各弄坏一次，每条都必须让**对应**判据红。

1. `shop_price` 改回加法 ⇒ `shop_discounts_stack_multiplicatively_and_round_up` 红。
2. `buy_card` 的校验改回挂牌价 ⇒ `every_purchase_charges_the_price_the_page_shows` 红。
3. `buy_relic` 把 `due` 挪到 `push_relic` 之后 ⇒ `buying_the_discount_relic_does_not_discount_itself` 红。

⚠️ 每条负控都必须命中**指定的那个**测试名 —— 只要"有测试红了"就算过的话，
一条无关的红（比如编译错）会让三条负控全部假装成功。
"""

import io
import subprocess
import sys

PATH = 'kernel/rd-run/src/state.rs'


def run(test_name):
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-run', '--release', test_name],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    out = p.stdout + p.stderr
    return out


def mutate(label, pairs, test_name):
    raw = io.open(PATH, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: %r 命中 %d' % (label, old[:60], broken.count(old))
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run(test_name)
        # 判据：那个测试名必须出现，且整体不是 ok。
        named = test_name in out
        red = 'test result: FAILED' in out or ' FAILED' in out
        ok = named and red
        print('  %-46s %s' % (label, 'RED（正确）' if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'error[' in line or 'panicked' in line or 'test result' in line:
                    print('      ', line.strip()[:130])
                    break
    finally:
        io.open(PATH, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

# ① 加法（旧的错公式）
ok &= mutate(
    '① shop_price 改回加法',
    [('''                numerator *= i64::from(100 - discount.clamp(0, 100));''',
      '''                numerator = 1; // 负控：把乘法退回"加法"（这里等价于只留最后一个折扣）
                let _ = discount;''')],
    'shop_discounts_stack_multiplicatively_and_round_up',
)

# ② 校验用挂牌价
ok &= mutate(
    '② buy_card 校验改回挂牌价',
    [('''        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        // §160: **提交点只有一个，而且失败的那一半在前面。**''',
      '''        let due = self.shop_price(offer.price);
        if self.gold < offer.price {
            return Err(RunError::NotEnoughGold {
                price: offer.price,
                gold: self.gold,
            });
        }
        // §160: **提交点只有一个，而且失败的那一半在前面。**''')],
    'every_purchase_charges_the_price_the_page_shows',
)

# ③ due 挪到 push_relic 之后（自己给自己打折）
ok &= mutate(
    '③ buy_relic 的 due 挪到 push_relic 之后',
    [('''        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-due);''',
      '''        let due = self.shop_price(offer.price);
        if self.gold < due {
            return Err(RunError::NotEnoughGold {
                price: due,
                gold: self.gold,
            });
        }
        // §160: the same commit-point rule as `buy_card` -- the failing half must come first.
        self.push_relic(offer.id.as_str(), card_pool)?;
        self.adjust_gold(-self.shop_price(offer.price));''')],
    'buying_the_discount_relic_does_not_discount_itself',
)

out = run('')
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)

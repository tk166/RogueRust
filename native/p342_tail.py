"""§342 收尾两件：第 4 条负控 + "无色牌不进有色格"的断言。

## 第 4 条负控为什么必须存在

§342 里最贵的一处发现是：**§332 的四排货架在真实路径上只有两排**（无色与药水从入口就空着）。
而所有既有判据都**绕过了入口**（直接调 `stock_shop` 并传两个池子），所以一直是绿的。
负控把入口退回旧签名，那条"四排必须从入口就摆满"的守卫必须红 —— 否则它只是装饰。

## 为什么还要一条"无色牌不进有色格"

为了让无色那一排有候选，入口现在传的是**带无色**的池子；而 `restock_card_slot` 也用同一个池子。
于是"补货把无色牌补进有色格"成了一个新的可能 —— 而 §183/§185 的原话是
*"colorless cards never enter a deck"*（商人卖一张就进去了）。
"""

import io

NEG = 'native/p342_negative.py'
STATE = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 负控加第 4 条 ─────────────────────────────────────────────────────────
t = io.open(NEG, encoding='utf-8').read()

ANCHOR = """out = run('rd-run', '')
print('  还原后 rd-run：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))"""

FOURTH = '''# ④ 入口退回旧签名（药水池为空）⇒ 那条"四排必须从入口就摆满"的守卫必须红。
#    这条钉住的正是 §342 最贵的一处发现：§332 的四排在真实路径上只有两排，
#    而所有既有判据都**绕过了入口**（直接调 `stock_shop`）。
ok &= case(
    '④ 入口退回 begin_node（空药水池）',
    RUN, 'rd-wasm',
    [(CHR3 + '    let kind = match session.state.begin_node_stocked(&cards, &relics, &potions) {' + CHR3,
      CHR3 + '    let _ = &potions;\\n    let kind = match session.state.begin_node(&cards, &relics) {' + CHR3)],
    'the_page_price_is_the_price_the_kernel_charges',
    '3 potions',
)

'''

# 用三引号常量避免在补丁脚本里再套三引号
t = sub(t, ANCHOR, FOURTH + ANCHOR, 'fourth case')
t = sub(t, '''RUN = 'kernel/rd-wasm/src/run.rs\'''',
        '''CHR3 = chr(39) * 3

RUN = 'kernel/rd-wasm/src/run.rs\'''', 'CHR3 helper')
io.open(NEG, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 无色牌不进有色格 ──────────────────────────────────────────────────────
s = io.open(STATE, encoding='utf-8').read()
s = sub(s, '''        run.buy_card(0, PoolCard::plain(first_id.as_str()), &pool)
            .expect("buy a card");
        assert_eq!(live(&run).0, before.0, "the coloured shelf must not shrink");''',
        '''        run.buy_card(0, PoolCard::plain(first_id.as_str()), &pool)
            .expect("buy a card");
        assert_eq!(live(&run).0, before.0, "the coloured shelf must not shrink");
        // §342：补货**不许**把无色牌补进有色格 —— 调用方现在传的是**带无色**的池子
        // （无色那一排要用它），所以这条不变量必须显式钉住。§183/§185 的原话：
        // "colorless cards never enter a deck"，而商人卖一张就进去了。
        for offer in run.shop().cards() {
            if offer.price < 0 {
                continue;
            }
            let colorless = pool
                .iter()
                .find(|card| card.id == offer.id.as_str())
                .is_some_and(|card| card.colorless);
            assert!(
                !colorless,
                "the coloured shelf must never restock a colourless card ({:?})",
                offer.id.as_str()
            );
        }''', 'colourless leak assertion')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
print('4th negative control + colourless-leak assertion')

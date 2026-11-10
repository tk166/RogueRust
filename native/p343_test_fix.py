"""§343：把 `buying_and_removing_are_paid_for_and_never_silent` 的后半段改成新规则。

原来那条判据在同一家店里删完之后，**又删一次**并期待 `NotEnoughGold { price: 100 }` ——
那正是 §343 要禁止的事（wiki: "Can only be used once per Shop"）。现在第二次是 `RemovalUsed`。

改法（三段，各问一件事）：

1. 同一家店第二次 ⇒ `RemovalUsed`，且**整局不变**（`RunState: PartialEq`）；
2. **换一家店** ⇒ 额度恢复（`removal_available()`），而**价格继续累计**（+25/次跨店）——
   这两件事必须分开验，否则"把两者合成一个字段"的实现也会绿；
3. 新店里空钱包 ⇒ `NotEnoughGold { price: 100 }`（原来那条意图保留，只是换到能删的店里）。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

OLD = '''        // And the price has to be payable: an empty purse refuses and changes nothing.
        run.adjust_gold(-9999);
        assert_eq!(run.gold(), 0);
        let deck_now: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert!(matches!(
            run.remove_card(0).unwrap_err(),
            RunError::NotEnoughGold { price: 100, gold: 0 }
        ));
        let deck_after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(deck_now, deck_after, "a refused purchase must not change the deck");'''

NEW = '''        // §343：**同一家店只能删一次**（wiki.gg / fandom：*"Can only be used once per Shop"*）。
        // 第二次必须被拒，而且**整局一个字节都不改** —— `RunState` 派生 `PartialEq`，
        // 所以判据可以直接比整个结构体（§8 的纪律）。
        let before = run;
        assert_eq!(run.remove_card(0), Err(RunError::RemovalUsed));
        assert!(
            run == before,
            "a refused removal must leave the run byte-identical"
        );
        assert!(!run.removal_available(), "the shop's one removal is spent");

        // **换一家店**：额度恢复，但**价格继续累计**（"+25 each time it is bought at a shop"
        // 是跨店的）。这两件事必须分开验 —— 把"涨价"与"本次额度"合成一个字段的实现会在这里红。
        run.pending = Pending::Shop;
        run.enter_shop(&basic_pool(), &RELICS, &POTIONS)
            .expect("a second shop");
        assert!(run.removal_available(), "a new shop allows one more removal");
        assert_eq!(
            run.remove_card_price(),
            100,
            "+25 per use, across shops (the price does NOT reset with the shop)"
        );

        // And the price has to be payable: an empty purse refuses and changes nothing.
        run.adjust_gold(-9999);
        assert_eq!(run.gold(), 0);
        let deck_now: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert!(matches!(
            run.remove_card(0).unwrap_err(),
            RunError::NotEnoughGold { price: 100, gold: 0 }
        ));
        let deck_after: Vec<String> = run.deck().iter().map(|id| id.as_str().to_string()).collect();
        assert_eq!(deck_now, deck_after, "a refused purchase must not change the deck");
        // 而且"钱不够"**没有**把这次额度用掉（拒绝不改状态）。
        assert!(run.removal_available(), "a refused removal does not spend the shop's one use");'''

t = sub(t, OLD, NEW, 'removal test')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('§343: removal test rewritten')

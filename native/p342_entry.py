"""§342 的第二半：**§332 的四排货架，从 ABI 入口只走得到两排。**

## 怎么发现的

给 P1-1 写 ABI 级判据时，负控抓不到"无色价改回挂牌价" —— 打印一看：

```
DEBUG shelf cards: count=5     ← 有
DEBUG shelf colorless: count=0 ← 空
DEBUG shelf potions: count=0   ← 空
DEBUG shelf relics: count=3    ← 有
```

两个原因，都在 `rd-wasm` 的入口，而**屏幕上完全看不出来**（页面按 `count()` 画行，0 就是没画）：

1. `rd_run_begin_node` 调 `full_pool(content, **false**)` —— 那个 `false` 是 §183/§185 留下的
   "无色牌永不进牌组"过滤器，于是 `stock_shop` 的**无色那一排**永远没有候选。
2. 同一个函数调的是 `state.begin_node(&cards, &relics)` —— 旧签名，**没有药水池**
   （`begin_node` 委托给 `begin_node_stocked(.., &[])`），于是**药水那一排**永远空着。
   §332 加这个货架时专门写了 `begin_node_stocked` 并在注释里说"忘了传池子不会编译不过、
   但会**看得见**" —— 它确实看得见，只是没人看。

⇒ §332 的"四排齐全"在真实路径上是**两排**。§332 的判据直接调 `stock_shop` 并传了两个池子，
**绕过了入口**，所以一直是绿的。

## 修法

* `rd_run_begin_node`：`full_pool(content, true)` + `begin_node_stocked(&cards, &relics, &potions)`。
  有色那一排本来就 `if card.colorless { continue }`（§332），所以把无色牌放进池子**不会**
  让商人把无色牌当有色牌卖（§185 那次的教训）。
* `restock_card_slot`：**显式**跳过无色牌 —— 补货也不能把无色牌补进有色格（同一条理由）。
* 三个 `buy_*` 的补货池：`full_pool(content, true)`，否则无色货架补不出东西。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
STATE = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 入口：池子带上无色牌，并且把药水池传进去 ──────────────────────────────
t = io.open(RUN, encoding='utf-8').read()

t = sub(t, '''    let content = content();
    let cards = match full_pool(content, false) {
        Ok(cards) => cards,
        Err(message) => return fail(session, &message),
    };
    let relics = relic_pool(content);
    // The kind comes back from `begin_node` itself: calling `rd_run_node_kind()` here would take the
    // run slot a second time while `session` is already borrowed (the aliasing bug from round 51).
    let kind = match session.state.begin_node(&cards, &relics) {''',
        '''    let content = content();
    // §342：**`true`** —— 商店的**无色那一排**要从这个池子里抽。§183/§185 的 `false` 是
    // "无色牌永不进牌组"的过滤器，而 `stock_shop` 的有色那一排本来就 `if card.colorless { continue }`
    // （§332），所以把无色牌放进来不会让商人把它当有色牌卖。
    let cards = match full_pool(content, true) {
        Ok(cards) => cards,
        Err(message) => return fail(session, &message),
    };
    let relics = relic_pool(content);
    // §342：**药水池也要传**。这里原来调的是旧签名 `begin_node(&cards, &relics)`，它委托给
    // `begin_node_stocked(.., &[])` ⇒ **药水货架永远是空的**，而页面按 `count()` 画行，0 就是没画，
    // 屏幕上完全看不出来（§332 的注释原话："忘了传池子不会编译不过、但会看得见"）。
    let potions = potion_pool_of(content);
    // The kind comes back from `begin_node` itself: calling `rd_run_node_kind()` here would take the
    // run slot a second time while `session` is already borrowed (the aliasing bug from round 51).
    let kind = match session.state.begin_node_stocked(&cards, &relics, &potions) {''',
        'begin_node pools')

# ── ② 三个 buy_* 的补货池：带上无色牌 ──────────────────────────────────────
n = t.count('full_pool(content(), false)')
print('buy_* 里的 full_pool(false) 出现', n, '次')
t = t.replace('full_pool(content(), false)', 'full_pool(content(), true)')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ 有色补货不接无色牌 ────────────────────────────────────────────────────
t = io.open(STATE, encoding='utf-8').read()
t = sub(t, '''        for index in 0..card_pool.len() {
            if matches!(
                card_pool[index].rarity,
                Rarity::Status | Rarity::Curse | Rarity::Special
            ) {
                continue;
            }''',
        '''        for index in 0..card_pool.len() {
            // §342：**无色牌不进有色格**（补货也一样）。调用方现在传的是**带无色**的池子
            // （无色那一排要用它），所以这一条必须显式写在这里 —— 否则持 Courier 时
            // 买一张有色牌、补出一张无色牌，而"无色牌永不进牌组"（§183/§185）就破了。
            if card_pool[index].colorless
                || matches!(
                    card_pool[index].rarity,
                    Rarity::Status | Rarity::Curse | Rarity::Special
                )
            {
                continue;
            }''', 'restock excludes colorless')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('§342: shop entry passes colorless+potions; coloured restock excludes colorless')

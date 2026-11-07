"""§273 第二批：`buy_card`/`buy_relic` 接受池子（补货要它）+ 穷尽 match。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ① 签名：加 `card_pool` / `relic_pool`
    s = patch(s, '    pub fn buy_card(&mut self, slot: usize, card: PoolCard<\'_>) -> Result<(), RunError> {',
              '''    /// §273：`card_pool` 是**补货**用的（`the_courier`）—— 买走一格就补一格，而补什么只有池子
    /// 知道。没有这件遗物时它不被读到，但签名统一（一处规则、一个入口）。
    pub fn buy_card(
        &mut self,
        slot: usize,
        card: PoolCard<'_>,
        card_pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''', 'buy_card signature')

    s = patch(s, '    pub fn buy_relic(&mut self, slot: usize) -> Result<(), RunError> {',
              '''    /// §273：`relic_pool` 同上（`the_courier` 的补货）。
    pub fn buy_relic(
        &mut self,
        slot: usize,
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {''', 'buy_relic signature')

    # ② 穷尽 match（两处：`push_relic` 的"其余不做事" + 两张链）
    NEW = ['RelicEffect::CourierRestock']
    lines = s.split('\n')
    out = []
    chained = inline = 0
    for line in lines:
        st = line.strip()
        ind = line[:len(line) - len(line.lstrip())]
        if st == '| RelicEffect::RestCardReward,':
            for a in NEW:
                out.append(ind + '| ' + a)
            chained += 1
        elif st == '| RelicEffect::RestCardReward => {}':
            for a in NEW:
                out.append(ind + '| ' + a)
            inline += 1
        out.append(line)
    assert (chained, inline) == (3, 1), 'sites %d/%d' % (chained, inline)
    s = '\n'.join(out)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)

    # ③ 测试里的两个调用点
    t = io.open(STATE, encoding='utf-8').read()
    t = patch(t, '''    fn buy_card_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        let id = run
            .shop()
            .cards()
            .get(slot)
            .map_or(RunId::EMPTY, |offer| offer.id);
        run.buy_card(slot, PoolCard::plain(id.as_str()))
    }''',
              '''    fn buy_card_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        let id = run
            .shop()
            .cards()
            .get(slot)
            .map_or(RunId::EMPTY, |offer| offer.id);
        run.buy_card(slot, PoolCard::plain(id.as_str()), &TYPED_CARDS)
    }

    /// §273：买**遗物**那一格（补货要池子，所以这里也带一份）。
    fn buy_relic_at(run: &mut RunState, slot: usize) -> Result<(), RunError> {
        run.buy_relic(slot, &RELICS)
    }''', 'buy_card_at helper')
    t = t.replace('            run.buy_relic(0),', '            buy_relic_at(&mut run, 0),')
    t = t.replace('refused!(&mut run, run.buy_relic(0), "buy a relic without a shop");',
                  'refused!(&mut run, buy_relic_at(&mut run, 0), "buy a relic without a shop");')
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)

    # ④ wasm 调用点
    w = io.open(WASM, encoding='utf-8').read()
    w = patch(w, '    let outcome = session.state.buy_card(slot as usize, card).map(|_| 0i32);',
              '''    let pool = match full_pool(content) {
        Ok(pool) => pool,
        Err(_) => return -1,
    };
    let outcome = session
        .state
        .buy_card(slot as usize, card, &pool)
        .map(|_| 0i32);''', 'wasm buy_card')
    w = patch(w, '    let outcome = session.state.buy_relic(slot as usize).map(|_| 0i32);',
              '''    let outcome = session
        .state
        .buy_relic(slot as usize, &relic_pool(content))
        .map(|_| 0i32);''', 'wasm buy_relic')
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(w)
    print('signatures + call sites done')


main()

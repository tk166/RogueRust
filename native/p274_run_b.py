"""§274 第二批：`TransformAndUpgrade` 落地 + 所有 `push_relic` 调用点带池子。"""
import io
import re

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


def main():
    # ---- ① `TransformAndUpgrade`
    src = io.open(P, encoding='utf-8').read()
    src = patch(src, '''            DeckChange::Transform => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
            }''',
                '''            DeckChange::Transform => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
            }
            // §274：`astrolabe` —— 改造**然后**升级。升级目标是"刚被塞进来的那一张"，
            // 而它一定在牌组**末尾**（`grant_random_cards` 是 append）—— 所以这里按下标取
            // 那个末尾格，而不是"再找一张同名的"（改造可能给出与别处重名的牌）。
            DeckChange::TransformAndUpgrade => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
                let last = self.deck_len as usize - 1;
                self.upgrade_at(last, pool)?;
            }''', 'transform and upgrade')

    # ---- ② 签名：open_chest / buy_relic / take_relic 收卡池
    src = patch(src, '    pub fn open_chest(&mut self, relic_pool: &[PoolRelic<\'_>]) -> Result<ChestOutcome, RunError> {',
                '''    /// §274：`card_pool` 是给 `push_relic` 的（拾取类遗物要看牌的类型与 `+` 行）。
    pub fn open_chest(
        &mut self,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<ChestOutcome, RunError> {''', 'open_chest signature')
    src = patch(src, '                self.push_relic(picked.as_str())?;',
                '                self.push_relic(picked.as_str(), card_pool)?;', 'open_chest call')

    src = patch(src, '''    pub fn buy_relic(
        &mut self,
        slot: usize,
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {''',
                '''    pub fn buy_relic(
        &mut self,
        slot: usize,
        card_pool: &[PoolCard<'_>],
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {''', 'buy_relic signature')
    src = patch(src, '        self.push_relic(offer.id.as_str())?;',
                '        self.push_relic(offer.id.as_str(), card_pool)?;', 'buy_relic call')

    src = patch(src, '    pub fn take_relic(&mut self) -> Result<(), RunError> {',
                '''    /// §274：`pool` 给 `push_relic`（拾取类遗物要看牌的类型与 `+` 行）。
    pub fn take_relic(&mut self, pool: &[PoolCard<'_>]) -> Result<(), RunError> {''',
                'take_relic signature')
    src = patch(src, '''        self.push_relic(id.as_str())?;
        self.reward.relic = RunId::EMPTY;''',
                '''        self.push_relic(id.as_str(), pool)?;
        self.reward.relic = RunId::EMPTY;''', 'take_relic call')

    # 事件 & black_star
    src = patch(src, '                self.push_relic(id)?;',
                '                self.push_relic(id, pool)?;', 'event call')
    src = patch(src, '                    let _ = self.push_relic(id.as_str());',
                '                    let _ = self.push_relic(id.as_str(), card_pool);', 'black_star call')

    # ---- ③ 测试/探针调用点：批量补 `&TYPED_CARDS`
    src, n = re.subn(r'push_relic\("([a-z_+\']+)"\)', r'push_relic("\1", &TYPED_CARDS)', src)
    print('test call sites rewritten in state.rs:', n)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)

    # hash.rs / archive.rs 的探针
    for path, repl in ((HASH, '&[]'), (ARCH, '&[]')):
        s = io.open(path, encoding='utf-8').read()
        s, n = re.subn(r'push_relic\(("(?:[a-z_+\']+)"|relic)\)', r'push_relic(\1, %s)' % repl, s)
        io.open(path, 'w', encoding='utf-8', newline='\n').write(s)
        print('%s: %d call sites' % (path.split('/')[-1], n))

    # ---- ④ wasm 调用点
    w = io.open(WASM, encoding='utf-8').read()
    w = patch(w, '    let outcome = session.state.take_relic().map(|_| 0i32);',
              '''    let pool = match full_pool(content()) {
        Ok(pool) => pool,
        Err(_) => return -1,
    };
    let outcome = session.state.take_relic(&pool).map(|_| 0i32);''', 'wasm take_relic')
    w = patch(w, '''    let relics = relic_pool(content());
    let outcome = session
        .state
        .buy_relic(slot as usize, &relics)
        .map(|_| 0i32);''',
              '''    let relics = relic_pool(content());
    let pool = match full_pool(content()) {
        Ok(pool) => pool,
        Err(_) => return -1,
    };
    let outcome = session
        .state
        .buy_relic(slot as usize, &pool, &relics)
        .map(|_| 0i32);''', 'wasm buy_relic')
    w = patch(w, '    let outcome = session.state.open_chest(&relics);',
              '''    let pool = match full_pool(content()) {
        Ok(pool) => pool,
        Err(_) => return -1,
    };
    let outcome = session.state.open_chest(&pool, &relics);''', 'wasm open_chest')
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(w)
    print('wasm call sites done')


main()

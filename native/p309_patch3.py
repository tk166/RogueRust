"""§309（三）：拾取类操作的**失败原子性**（审阅报告 §3）。

`push_relic("tiny_house", pool)` 先加金币 / 上限 / 当前血 / 欠一瓶药水 / 欠一张牌，
再 `roll_pickup_offer(pool)?` —— 池子不合格时前面那些改动**留在原地**，而遗物本身没进腰带。
`orrery` 的 `pickup_add_card` 同形（加一张牌、递减欠账，再抽下一手，抽失败就半改）。

修法不是给每条 `?` 补回滚（那样要写十几处，而且下一次加一行又会漏），而是**一次快照**：
`RunState` 派生 `Copy`（§162），失败时整体写回。判据直接比整个结构体 —— 与 `archive::restore`
的"拒绝 ⇒ 一个字节都不改"同一条纪律（FACT §8）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch('''    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        let Some(effect) = Self::relic_effect(relic_id) else {''',
'''    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        // §309：**失败 ⇒ 一个字节都不改**。§274/§293 的拾取类遗物会先动金币/上限/欠账，再抽
        // 一手牌（`roll_pickup_offer` 可以失败）；不回滚的话，一次被拒的拾取会留下"钱加了、
        // 遗物没到手"的局面。`RunState` 是 `Copy`，所以回滚是一次结构体赋值，不是一套事务框架。
        let snapshot = *self;
        let outcome = self.push_relic_inner(relic_id, pool);
        if outcome.is_err() {
            *self = snapshot;
        }
        outcome
    }

    fn push_relic_inner(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        let Some(effect) = Self::relic_effect(relic_id) else {''')

    patch('''    pub fn pickup_add_card(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pickup_add == 0 {''',
'''    pub fn pickup_add_card(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        // §309：同 [`Self::push_relic`] —— 加一张牌之后再抽下一手，抽失败必须整体回滚，
        // 否则"那张牌进了牌组、欠账却没按规矩走"（§274 的 `pickup_card` 踩过同一个坑）。
        let snapshot = *self;
        let outcome = self.pickup_add_card_inner(slot, pool);
        if outcome.is_err() {
            *self = snapshot;
        }
        outcome
    }

    fn pickup_add_card_inner(
        &mut self,
        slot: usize,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        if self.pickup_add == 0 {''')

    print('atomicity wrappers installed')


main()

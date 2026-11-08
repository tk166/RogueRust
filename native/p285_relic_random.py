"""§285（续）：`relic_random` 原子 —— 事件"随机给一件遗物"（Scrap Ooze）。

wiki：`Scrap Ooze` 找到遗物时是"a **random** relic"（50% Common / 33% Uncommon / 17% Rare）。
运行层已经有这条规则（`pick_relic(stream, pool)`：按稀有度权重、跳过已持有），
所以这里只加一个原子，**不写第二套**抽签。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    s = patch(s, '''/// | `relic_lose:<relic id>` | **drop** that relic (the id must be held — the wiki's `Forgotten Altar` exchange) |''',
'''/// | `relic_lose:<relic id>` | **drop** that relic (the id must be held — the wiki's `Forgotten Altar` exchange) |
/// | `relic_random:<rarity>/<id>` | grant a **random** relic (Scrap Ooze: the pool is the content's relics) |''')

    s = patch(s, '''    /// §279：**失去**旁边那件遗物（`relic_lose:<id>`）。`Forgotten Altar` 的
    /// `[Offer: Golden Idol]` 就是"失去金像、得到血像"。
    LoseRelic,''',
'''    /// §279：**失去**旁边那件遗物（`relic_lose:<id>`）。`Forgotten Altar` 的
    /// `[Offer: Golden Idol]` 就是"失去金像、得到血像"。
    LoseRelic,
    /// §285：**随机**得一件遗物（`relic_random`，payload 是"哪条流"）。
    /// 抽签本身走 [`RunState::pick_relic`]（按稀有度权重、跳过已持有），不另写一套。
    GainRandomRelic(RunStream),''')

    # 解析：`relic_random:event`（流名）。
    # ⚠️ 流名在 `EventEffect::parse` 里不该认识 `RunStream`（那是运行层的类型）——
    # 但 `EventEffect` 就在 rd-run 里，所以可以直接解析。
    s = patch(s, '''                    "relic_lose" => (Self::LoseRelic, Some(payload)),''',
'''                    "relic_lose" => (Self::LoseRelic, Some(payload)),
                    // §285：`relic_random:event` —— payload 是**随机流的名字**（今天只有
                    // `event`；写成别的就是内容错误，响亮拒绝）。
                    "relic_random" => match payload {
                        "event" => (Self::GainRandomRelic(RunStream::Event), None),
                        _ => return None,
                    },''')

    # 应用：需要遗物池（`&[PoolRelic]`）—— 而 `apply_event_effect` 只有卡池。
    # 所以这里走"待补"：事件层拿不到遗物池时**响亮拒绝**，不静默。
    s = patch(s, '''            EventEffect::LoseRelic => {''',
'''            EventEffect::GainRandomRelic(stream) => {
                // ⚠️ 遗物池是**内容**的东西，而 `apply_event_effect` 手上只有卡池。调用方
                // （`resolve_event_effects` 的 `relic_pool` 参数）必须把它带下来；没带就是
                // 内容写了一条这个内核兑现不了的选项 —— 响亮拒绝，不静默给一件错的。
                let Some(pool) = relic_pool else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                let picked = self.pick_relic(stream, pool)?;
                if picked.as_str().is_empty() {
                    // 池子里没有可抽的（全都持有了 / 全是不可掉落稀有度）⇒ 不是错误，
                    // 但也不该静默：wiki 的事件在那种情况下仍然给"什么都没有"。
                    return Ok(());
                }
                self.push_relic(picked.as_str(), card_pool_for_relics)?;
            }
            EventEffect::LoseRelic => {''')
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('event effect: relic_random (needs pool plumbing)')
    print('NEXT: 把 relic 池 / 卡池接进 apply_event_effect 的签名')


main()

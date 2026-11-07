"""§279：`relic_lose:<id>` 效果原子 + `RunState::remove_relic`。

`Forgotten Altar` 的 `[Offer: Golden Idol]` 是"**失去**金像、得到血像" —— 旧词表里只有
`relic:<id>`（得到），没有"失去"，所以那一支根本写不出来。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ---------------------------------------------------------------- 文档表
    s = patch(s, '''/// | `relic:<relic id>` | grant that relic (the id must have an implemented effect) |''',
              '''/// | `relic:<relic id>` | grant that relic (the id must have an implemented effect) |
/// | `relic_lose:<relic id>` | **drop** that relic (the id must be held — the wiki's `Forgotten Altar` exchange) |''')

    # ---------------------------------------------------------------- 枚举
    s = patch(s, '''    /// Grant the relic named beside this effect.
    GainRelic,''','''    /// Grant the relic named beside this effect.
    GainRelic,
    /// §279：**失去**旁边那件遗物（`relic_lose:<id>`）。`Forgotten Altar` 的
    /// `[Offer: Golden Idol]` 就是"失去金像、得到血像"。
    LoseRelic,''')

    # ---------------------------------------------------------------- 解析
    s = patch(s, '''                match kind {
                    "curse" => (Self::GainCurse, Some(payload)),
                    "relic" => (Self::GainRelic, Some(payload)),''','''                match kind {
                    "curse" => (Self::GainCurse, Some(payload)),
                    "relic" => (Self::GainRelic, Some(payload)),
                    "relic_lose" => (Self::LoseRelic, Some(payload)),''')

    # ---------------------------------------------------------------- 应用（放在 GainRelic 之后）
    s = patch(s, '''            EventEffect::GainRelic => {
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };''','''            EventEffect::LoseRelic => {
                // §279：**必须真的持有**才允许"失去"。一条 `relic_lose:` 指向一件不在手上的
                // 遗物时，静默什么都不做就等于"这个选项白点了"；而它通常是内容里
                // 条件（`Requires`）写错的第一征兆 —— 让它在事件屏上就响亮。
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };
                self.remove_relic(id)
            }
            EventEffect::GainRelic => {
                let Some(id) = named else {
                    return Err(RunError::UnsupportedEventEffect);
                };''')

    # ---------------------------------------------------------------- remove_relic
    s = patch(s, '''    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''','''    /// §279：**失去**一件遗物（`relic_lose:<id>` / `Forgotten Altar` 的交换）。
    ///
    /// 三条约束：
    /// * 不持有 ⇒ [`RunError::NoSuchRelic`]（不是静默成功：那会让"条件写错"变成"按钮白点"）；
    /// * 拾取时给过一次性的东西（`omamori` 的 2 次、`girya` 的层数）**不回收** —— 参考实现
    ///   也没有"撤销拾取效果"的概念，而凭空发明一条回收规则会让"失去遗物"变成一次反向触发；
    /// * 后面的遗物**往前挪**（保持顺序 = 拿到的顺序），于是 `relics()` 的切片始终连续。
    pub fn remove_relic(&mut self, relic_id: &str) -> Result<(), RunError> {
        let id = RunId::new(relic_id).map_err(|_| RunError::BadId)?;
        let len = self.relics_len as usize;
        let Some(slot) = self.relics[..len].iter().position(|held| *held == id) else {
            return Err(RunError::NoSuchRelic);
        };
        for index in slot..len.saturating_sub(1) {
            self.relics[index] = self.relics[index + 1];
        }
        self.relics_len -= 1;
        self.relics[len - 1] = RunId::EMPTY;
        Ok(())
    }

    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('relic_lose + remove_relic')


main()

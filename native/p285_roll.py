"""§285（续）：`resolve_event_effects` 收 `roll` —— 掷骰决定**去哪一段**。

`EventRoll { chance, on_success, on_fail }`：run 层用 `RunStream::Event` 掷一次，
`< chance` 走成功段，否则走失败段。掷骰在**写任何东西之前**，所以 `Err` 时局面一个字节不动。
"""
import io

P_RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    s = io.open(P_RUN, encoding='utf-8').read()

    # ① 类型
    s = patch(s, '''impl EventEffect {''',
'''/// §285：一次**事件掷骰** —— 成功去 `on_success`，失败去 `on_fail`。
///
/// 传进 [`RunState::resolve_event_effects`]，由**运行层**掷（`RunStream::Event`）：
/// 事件的随机是一局的账，不该消耗战斗的 `(seed, step)`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventRoll<'a> {
    /// 成功概率（1..=100）。
    pub chance: u8,
    /// 成功时去的段（与选项的 `Next` 同一个 id 空间）。
    pub on_success: &'a str,
    /// 失败时去的段。
    pub on_fail: &'a str,
}

impl EventEffect {''')

    # ② 签名：多一个 roll 参数
    s = patch(s, '''    pub fn resolve_event_effects(
        &mut self,
        effects: &[(EventEffect, Option<&str>)],
        next: Option<&str>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''',
'''    pub fn resolve_event_effects(
        &mut self,
        effects: &[(EventEffect, Option<&str>)],
        next: Option<&str>,
        roll: Option<EventRoll<'_>>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''')

    # ③ 掷骰：在算 `next_id` 的同时决定它
    s = patch(s, '''        // `next` 在动手之前就要验：一个坏 id 必须在**一个字节都没改**之前被拒。
        let next_id = match next {
            Some(next) => RunId::new(next).map_err(|_| RunError::NoSuchEvent)?,
            None => RunId::EMPTY,
        };''',
'''        // `next` 在动手之前就要验：一个坏 id 必须在**一个字节都没改**之前被拒。
        //
        // §285：带 `roll` 时，先去**掷一次**（同样是"写之前"）—— 掷骰本身会推进随机流，
        // 所以它必须在所有 `self` 写入之前，和 `roll_unknown_room` 同一条纪律。
        let target = match roll {
            Some(roll) => {
                let rolled = self
                    .rng
                    .roll(RunStream::Event, 100)
                    .map_err(|_| RunError::Capacity)?;
                Some(if rolled < u32::from(roll.chance) {
                    roll.on_success
                } else {
                    roll.on_fail
                })
            }
            None => next,
        };
        let next_id = match target {
            Some(next) => RunId::new(next).map_err(|_| RunError::NoSuchEvent)?,
            None => RunId::EMPTY,
        };''')

    io.open(P_RUN, 'w', encoding='utf-8', newline='\n').write(s)
    print('§285: resolve_event_effects takes a roll')
    print('NEXT: 改所有调用点（测试 + wasm）')


main()

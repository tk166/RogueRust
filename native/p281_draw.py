"""§281：`CombatState::draw_in_range` —— **战斗随机流的唯一入口**。

为什么需要（这是这一节的全部理由）：代码里原本有**两套**战斗随机：

1. 洗牌走 `rng::shuffle_indexes(seed, step)` + `step += 1`（镜像里的 8 字节随机状态，
   `random_seed` 不变、`random_step` 推进）；
2. **`Snecko Oil` 的价格随机化**在 `rd-wasm` 里手抄了一遍：`next_u32(&mut seed) % 4`，
   并且**同时**写回 `random_seed` 与 `random_step`。

第 2 条不只是"抄了一份"：它把 `random_seed` 也改了，于是下一次抽取的
`initial_state(seed, step)` 与洗牌那条路的约定**分家**（洗牌只动 step）。两套账迟早有一处错，
而错的表现是"同样的种子两次跑出不同的牌序"，那是最难查的一类。

所以：把抽取收成**一个方法**（`CombatState::draw_in_range`），Snecko Oil 改走它，
表达式层的 `randomInt` 也走它。
"""
import io

P_RNG = 'D:/Vibe/sts-tui/kernel/rd-core/src/rng.rs'
P_STATE = 'D:/Vibe/sts-tui/kernel/rd-core/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    # ---------------------------------------------------------------- rng：纯函数
    s = io.open(P_RNG, encoding='utf-8').read()
    s = patch(s, '''/// Fills `out` with `0..out.len()` shuffled by `(seed, step)`.''',
'''/// **一次抽取**：`(seed, step)` → 一个 32 位数。纯函数 —— 不碰任何状态。
///
/// 与 [`shuffle_indexes`] 用同一份 `(seed, step)` 派生（`initial_state` + `next_u32`），
/// 所以"同一个种子 ⇒ 同一个序列"这条性质对**两种**随机都成立，而不是只有洗牌有。
#[inline]
#[must_use]
pub fn draw_u32(seed: i32, step: i32) -> u32 {
    let mut state = initial_state(seed, step);
    next_u32(&mut state)
}

/// Fills `out` with `0..out.len()` shuffled by `(seed, step)`.''')
    io.open(P_RNG, 'w', encoding='utf-8', newline='\n').write(s)

    # ---------------------------------------------------------------- state：唯一入口
    r = io.open(P_STATE, encoding='utf-8').read()
    old = '''    pub fn reshuffle_discard_into_draw(&mut self, owner: &CombatantId) -> StateResult<usize> {'''
    new = '''    /// §281：**一次**战斗随机抽取，返回 `min..=max`（含两端）。
    ///
    /// 这是战斗随机流的**唯一入口**：`random_step` 推进一次，`random_seed` **不动** ——
    /// 与洗牌同一条约定（`(seed, step)` 派生，见 `crate::rng`）。之前的 `Snecko Oil` 在
    /// `rd-wasm` 里手抄了这条规则，而且**同时改 seed**，于是两条路会分家。
    ///
    /// `max <= min` ⇒ 直接返回 `min` 且**不推进** step（没有掷骰就没有消耗）：
    /// 内容写 `randomInt(3,3)` 是"常数"而不是"一次随机"，让它消耗随机流会让同一个种子
    /// 因为一句无害的内容改写而整局偏移。
    ///
    /// ⚠️ 取模有**偏置**（`value % span`）：`span` 不是 2 的幂时低值略多。参考实现的
    /// `Random.Next(min, max)` 也带同样的偏置形态，而"除以 `u32::MAX` 再缩放"会引入浮点。
    /// 这条偏差**写在测试里**（只钉"每一档都到过"与"同种子同序列"，不钉分布均匀性）。
    pub fn draw_in_range(&mut self, min: i32, max: i32) -> i32 {
        if max <= min {
            return min;
        }
        let value = crate::rng::draw_u32(self.random_seed, self.random_step);
        self.random_step = self.random_step.saturating_add(1);
        // i64 算跨度：`max - min + 1` 在 `min = i32::MIN` 时会溢出。
        let span = (i64::from(max) - i64::from(min) + 1) as u64;
        let offset = (u64::from(value) % span) as i64;
        let answer = i64::from(min) + offset;
        i32::try_from(answer).unwrap_or(max)
    }

    pub fn reshuffle_discard_into_draw(&mut self, owner: &CombatantId) -> StateResult<usize> {'''
    assert r.count(old) == 1
    r = r.replace(old, new)
    io.open(P_STATE, 'w', encoding='utf-8', newline='\n').write(r)
    print('rng::draw_u32 + CombatState::draw_in_range')


main()

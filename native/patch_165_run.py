"""rd-run: `draw_distinct` -- the run owns the RNG, so it owns "three distinct cards".

The wasm layer can filter the pool by tag (it has the content); it cannot roll the run's streams
(`RunState.rng` is private, on purpose). The shop already does this exact shuffle idiom, so the
order of consumption stays one place per stream.
"""
import io

PATH = "kernel/rd-run/src/state.rs"

ANCHOR = """    /// Draw a potion from `pool` by **rarity weight** (65/25/10, §156)."""

METHOD = '''    /// 从 `pool` 里**不重复**地抽 `count` 张，把 id 写进 `out`，返回实际抽出几张。
    ///
    /// §161.5：Attack / Skill Potion 要"从卡池随机三张**不同的**牌里选一张"。抽牌的人必须是
    /// **运行层**，因为它持有 RNG（`RunState.rng` 是私有的，正是为了让"谁推进了哪个流"只有一处）；
    /// 按标签过滤是**内容**的事，所以调用方传进来的 `pool` 已经滤过。
    ///
    /// 用 `RunStream::Reward`：参考把"从卡池取牌给你挑"记在**奖励**那个流上（卡奖励与这次抽三张
    /// 是同一件事的两半），而 `Potion` 那个流已经用来决定"掉不掉药水"了 —— 混用会让掉率与
    /// "抽到哪三张"互相干扰，那是确定性最贵的一种错。
    ///
    /// 池子比 `count` 短时**返回实际张数**（不是错误）：StS 里牌池不够就少给几张，
    /// 而"少于 3 张"要不要拒绝是**调用方**的决定（它知道该不该喝这瓶药）。
    pub fn draw_distinct(
        &mut self,
        pool: &[PoolCard<'_>],
        count: usize,
        out: &mut [RunId],
    ) -> Result<usize, RunError> {
        Self::pool_fits(pool.len())?;
        let wanted = count.min(out.len()).min(pool.len());
        if wanted == 0 {
            return Ok(0);
        }
        let mut order = [0u8; MAX_POOL];
        for (index, slot) in order.iter_mut().take(pool.len()).enumerate() {
            // `MAX_POOL` 是 64，所以 `as u8` 丢不掉信息（`pool_fits` 已经拦住更长的池子）。
            *slot = index as u8;
        }
        self.rng.shuffle(RunStream::Reward, &mut order[..pool.len()]);
        for (at, slot) in order.iter().take(wanted).enumerate() {
            out[at] = RunId::new(pool[*slot as usize].id).map_err(|_| RunError::BadId)?;
        }
        Ok(wanted)
    }

    /// Draw a potion from `pool` by **rarity weight** (65/25/10, §156).'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn draw_distinct" not in text, "already inserted"
    text = text.replace(ANCHOR, METHOD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("rd-run: draw_distinct")


if __name__ == "__main__":
    main()

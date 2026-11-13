"""幕间（三）：内核补「Boss 遗物三选一」。

## 为什么必须在内核

StS 的节奏是：打赢 Boss → 回满血 → **三选一 Boss 遗物** → 下一幕。现在内核只做了"回满血 +
换幕"，遗物那一半没有。放在 UI 里做（`rd_run_grant_relic` 硬塞）会绕过"运行层决定"的纪律，
而且存档/回放/指纹都看不见它。

## 改了什么

1. `RunState`：`boss_relic_offer[3]` + `len`，三个方法（读 / 生成 / 取走）。
2. 指纹与档案：都带上它（否则回档会丢"我还欠你一个三选一"）。
3. `rd-wasm`：`apply_fight_outcome` 里换幕之后生成三选一；四个导出（count/id/take + fixture）。

## 判据（`cargo test -p rd-run`）

* 只有**非最终幕**换幕时才生成（第 3 幕 Boss 倒了就是通关，没有下一幕的遗物）；
* 候选**只含 Boss 档**且**排除已持有**；
* 抽 3 个**互不重复**；
* `take_boss_relic` 拿到手就清空；越界/没有 offer ⇒ 响亮拒绝（`WrongPhase`/`BadSlot`）；
* 档案往返之后 offer 还在。
"""

import io
import re

STATE = 'kernel/rd-run/src/state.rs'
HASH = 'kernel/rd-run/src/hash.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
WASM = 'kernel/rd-wasm/src/run.rs'


def patch(path, pairs):
    t = io.open(path, encoding='utf-8').read()
    for label, old, new in pairs:
        assert t.count(old) == 1, '%s %s: 命中 %d 次' % (path, label, t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', path)


# ── 1. 常量 ─────────────────────────────────────────────────────────────────
patch(STATE, [
    (
        'const',
        'pub const MAX_RUN_POTIONS: usize = 5;',
        '''pub const MAX_RUN_POTIONS: usize = 5;

/// Boss 遗物三选一的**固定**三个槽（StS 每幕 Boss 后正好三选一）。
pub const BOSS_RELIC_OFFER: usize = 3;''',
    ),
    # ── 2. 字段 ─────────────────────────────────────────────────────────────
    (
        'fields',
        '''    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,''',
        '''    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,
    /// 幕间三选一的 Boss 遗物（`boss_relic_offer_len == 0` = 没有待选）。
    ///
    /// 与 `Pending` **分开**：打赢 Boss 的那一步会先掷奖励屏（`Pending::Reward`），
    /// 而三选一是在奖励屏关掉**之后**才该出现的 —— 塞进 `pending` 会把奖励屏顶掉（§329 记过
    /// 同一类顺序问题）。
    boss_relic_offer: [RunId; BOSS_RELIC_OFFER],
    boss_relic_offer_len: u8,''',
    ),
    # ── 3. 初始化 ───────────────────────────────────────────────────────────
    (
        'init',
        '''            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,''',
        '''            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,
            boss_relic_offer: [RunId::EMPTY; BOSS_RELIC_OFFER],
            boss_relic_offer_len: 0,''',
    ),
])

# ── 4. 三个方法（插在 push_relic 之前）───────────────────────────────────────
patch(STATE, [
    (
        'methods',
        '''    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''',
        '''    /// 幕间待选的 Boss 遗物（空切片 = 没有待选）。
    #[must_use]
    pub fn boss_relic_offer(&self) -> &[RunId] {
        &self.boss_relic_offer[..self.boss_relic_offer_len as usize]
    }

    /// 换幕之后生成三选一（**只含 Boss 档、排除已持有、互不重复**）。
    ///
    /// 为什么自己抽而不是 `pick_relic`：那个入口会先把**不可掉落的档位**（`Boss`/`Shop`/`Event`）
    /// 过滤掉 —— 它们不在 `RELIC_RARITY_WEIGHTS` 里。Boss 遗物恰恰全是 `Boss` 档，走那条路会
    /// 得到空池（`RunId::EMPTY`），于是"三选一"安静地变成"没得选"。
    pub fn offer_boss_relics(
        &mut self,
        relic_pool: &[PoolRelic<'_>],
    ) -> Result<(), RunError> {
        if self.boss_relic_offer_len != 0 {
            return Err(RunError::WrongPhase);
        }
        let mut candidates = [PoolRelic {
            id: "",
            rarity: Rarity::Common,
        }; MAX_POOL];
        let mut count = 0usize;
        for entry in relic_pool {
            if entry.rarity != Rarity::Boss || self.holds_relic(entry.id) {
                continue;
            }
            if count >= candidates.len() {
                return Err(RunError::Capacity);
            }
            candidates[count] = *entry;
            count += 1;
        }
        if count == 0 {
            // 没有 Boss 遗物可给（内容没配 / 全都拿过了）⇒ **不生成空的三选一**。
            return Ok(());
        }
        let mut offer = [RunId::EMPTY; BOSS_RELIC_OFFER];
        let mut len = 0usize;
        while len < BOSS_RELIC_OFFER {
            // 从"还没被选进这一手"的候选里均匀抽一个（StS 的 Boss 三选一也是均匀，不按权重）。
            let mut remaining = 0usize;
            let mut slots = [0usize; MAX_POOL];
            for (slot, entry) in candidates[..count].iter().enumerate() {
                if offer[..len].iter().any(|taken| taken.as_str() == entry.id) {
                    continue;
                }
                slots[remaining] = slot;
                remaining += 1;
            }
            if remaining == 0 {
                break;
            }
            let pick = self.rng.roll(RunStream::Chest, remaining as u32)? as usize;
            let chosen = slots[pick];
            offer[len] = RunId::new(candidates[chosen].id).map_err(|_| RunError::BadId)?;
            len += 1;
        }
        self.boss_relic_offer = offer;
        self.boss_relic_offer_len = len as u8;
        Ok(())
    }

    /// 取走三选一里的第 `slot` 个（拿到手就清空这一手）。
    pub fn take_boss_relic(
        &mut self,
        slot: u8,
        card_pool: &[PoolCard<'_>],
    ) -> Result<RunId, RunError> {
        if self.boss_relic_offer_len == 0 {
            return Err(RunError::WrongPhase);
        }
        if slot as usize >= self.boss_relic_offer_len as usize {
            return Err(RunError::BadSlot);
        }
        let relic = self.boss_relic_offer[slot as usize];
        // ⚠️ 先入腰带再清空：`push_relic` 失败时（不认识的遗物/容量满）这一手**原样保留**，
        // 玩家还能再选 —— 与"拒绝 ⇒ 一个字节都不改"同一条纪律。
        self.push_relic(relic.as_str(), card_pool)?;
        self.boss_relic_offer = [RunId::EMPTY; BOSS_RELIC_OFFER];
        self.boss_relic_offer_len = 0;
        Ok(relic)
    }

    pub fn push_relic(
        &mut self,
        relic_id: &str,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''',
    ),
])

# ── 5. 指纹 ─────────────────────────────────────────────────────────────────
patch(HASH, [
    (
        'hash offer',
        '''    writer.str("potions=").u32(state.potions().len() as u32).str("\\n");''',
        '''    writer
        .str("boss_relic_offer=")
        .u32(state.boss_relic_offer().len() as u32)
        .str("\\n");
    for relic in state.boss_relic_offer() {
        writer.str("bo=").str(relic.as_str()).str("\\n");
    }
    writer.str("potions=").u32(state.potions().len() as u32).str("\\n");''',
    ),
])
print('done')

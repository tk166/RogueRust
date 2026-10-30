"""§155: `roll_reward` must filter the relic pool exactly like the chest does.

The chest and the shop call the **private** `relic_candidates`, which skips relics the player already
holds. A fight's relic has to obey the same rule -- otherwise an elite can hand out a second copy of
the relic you started with (the exact bug §145 fixed for chests).

So `roll_reward` filters the pool itself, with the same helper, instead of trusting the caller.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

OLD = """        let relic = if matches!(kind, FightKind::Elite | FightKind::Boss) && !relic_pool.is_empty() {
            let index = self.rng.roll(RunStream::Reward, relic_pool.len() as u32)? as usize;
            RunId::new(relic_pool[index]).map_err(|_| RunError::BadId)?
        } else {
            RunId::EMPTY
        };"""

NEW = """        let mut relic = RunId::EMPTY;
        if matches!(kind, FightKind::Elite | FightKind::Boss) {
            // Same filter as the chest and the shop (§145): never a second copy of a held relic.
            let mut candidates = [0usize; MAX_POOL];
            let count = self.relic_candidates(relic_pool, &mut candidates);
            if count > 0 {
                let pick = self.rng.roll(RunStream::Reward, count as u32)? as usize;
                let Some(cell) = candidates.get(pick).copied() else {
                    return Err(RunError::BadId);
                };
                let Some(id) = relic_pool.get(cell) else {
                    return Err(RunError::BadId);
                };
                relic = RunId::new(id).map_err(|_| RunError::BadId)?;
            }
        }"""

if OLD not in source:
    raise SystemExit("relic pick block missing")
source = source.replace(OLD, NEW, 1)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("roll_reward now filters held relics")

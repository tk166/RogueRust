"""§411：**分裂/召唤之后打不中、意图不变** —— 槽位→战斗员的映射用了开战时的静态名单。

## 玩家报的

1. "恐惧药水选目标的功能不能用卡住了"；
2. "史莱姆老大分裂以后对它们打击不造成伤害了，而且他们的行为在往后每一轮都不变了"。

## 根因：**同一个静态表被三处当成"活的名单"**

`Session::plan`（`rd-wasm`）是**开战时**的遭遇敌人列表（`Box::leak` 的固定表）。
而分裂/召唤之后，场上的战斗员是**新造的**（`acid_slime_l#000001`），根本不在那张表里。

三处都按 `plan.enemies[slot]` 找目标：

| 位置 | 后果 |
|---|---|
| `step_play`（出牌的目标） | 槽位 ≥ 表长 ⇒ `target = None` ⇒ **卡打空、不掉血** |
| `rd_env_use_potion` 的 `combat_damage` / `combat_status` | 同上 ⇒ 药水**没有目标** ⇒ 界面停在"选目标"里 ⇒ "卡住了" |
| `refresh_intents`（意图显示） | 走 `locate_enemy`（遭遇内联记录）⇒ 新造的战斗员"不在名单里" ⇒ 意图**永远是未知** ⇒ "行为每一轮都不变" |

而**执行**那一侧（`action_for`）其实有兜底（`summoned_actions`：按定义 id 扫遭遇找动作表），
所以分裂出来的史莱姆**真的会打你**，但你看不到它的意图、也打不到它 —— 玩家体验就是
"打不动它，它却在打我，直到我死"。

## 修法

1. **一个** helper：`Session::combatant_at_slot(slot)` —— 槽位 → **活的**战斗员（`enemy_roster()`，
   它就是观察向量与动作表用的同一个顺序）。出牌与药水都改用它。
   `plan` 只保留"开战时的蓝图"这一个用途（建战斗、日志）。
2. `refresh_intents` 与 `action_for` **共用**一个 `intent_action(actor)`：先走 `select_action`
   （遭遇记录），拿不到再走 `summoned_actions`（定义 id 兜底）。这样"显示"与"执行"不可能分叉
   —— 而这正是本 bug 的教训：**同一个事实在两处各写一遍，一处有兜底一处没有**。
"""

import io


def patch(path, pairs, label):
    t = io.open(path, encoding='utf-8').read()
    for old, new in pairs:
        assert t.count(old) == 1, '%s: %r (%d)' % (label, old[:60], t.count(old))
        t = t.replace(old, new)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t)
    print('patched', label)


# ── 1. Session::combatant_at_slot + intent_action（lib.rs）──────────────────
patch(
    'kernel/rd-wasm/src/lib.rs',
    [
        (
            '''    fn alive_enemy_slots(&self) -> Vec<usize> {''',
            '''    /// 墙位槽 → **活的**战斗员（§411）。
    ///
    /// ⚠️ 这是"槽位 → 战斗员"的**唯一**入口。以前三处（出牌目标、药水目标、意图显示）各自
    /// 用 `plan.enemies[slot]`（开战时的静态表），而分裂/召唤出来的战斗员不在那张表里：
    /// 出牌 ⇒ 目标 `None`（打不中）、药水 ⇒ 没有目标（界面卡在选目标）、意图 ⇒ 永远"未知"。
    ///
    /// `enemy_roster()` 的顺序**就是**观察向量与动作表用的顺序，所以它才是"槽位"的定义。
    fn combatant_at_slot(&self, slot: i32) -> Option<CombatantId> {
        if slot < 0 {
            return None;
        }
        self.enemy_roster().get(slot as usize).copied()
    }

    fn alive_enemy_slots(&self) -> Vec<usize> {''',
        ),
        (
            '''    fn action_for(&self, actor: &CombatantId) -> Result<Option<&'static str>, String> {
        if let Some(at) = locate_enemy(self.content, self.encounter, actor)
            .map_err(|error| format!("locate_enemy: {}", detail(&error)))?
        {
            let choice =
                select_action(&self.state, self.content, at, actor, self.state.current_round)
                    .map_err(|error| format!("select_action: {}", detail(&error)))?;
            return Ok(choice.map(|choice| choice.action_id));
        }
        let actions = self.summoned_actions(actor)?;
        if actions.is_empty() {
            return Ok(None);
        }
        let round = self.state.current_round.max(1) as usize;
        Ok(actions.get((round - 1) % actions.len()).copied())
    }''',
            '''    /// 这一回合这个敌人**要打的招**：`(动作 id, EACT 行号, 意图种类)`（§411）。
    ///
    /// **执行与显示共用这一个函数**（`action_for` / `refresh_intents`）。第一版把两条路分开写：
    /// 执行有"按定义 id 兜底"（`summoned_actions`），显示没有 ⇒ 分裂出来的史莱姆"意图永远未知
    /// 但照样打你"。**同一个事实写两遍，就会有一处漏掉兜底。**
    fn intent_action(
        &self,
        actor: &CombatantId,
    ) -> Result<Option<(&'static str, u32, Option<rd_core::intent::IntentKind>)>, String> {
        if let Some(at) = locate_enemy(self.content, self.encounter, actor)
            .map_err(|error| format!("locate_enemy: {}", detail(&error)))?
        {
            let choice =
                select_action(&self.state, self.content, at, actor, self.state.current_round)
                    .map_err(|error| format!("select_action: {}", detail(&error)))?;
            return Ok(choice.map(|choice| (choice.action_id, choice.action_row, choice.intent_kind)));
        }
        // 召唤/分裂出来的战斗员：遭遇记录里没有它，按**定义 id** 找它的动作表（轮转）。
        let actions = self.summoned_actions(actor)?;
        if actions.is_empty() {
            return Ok(None);
        }
        let round = self.state.current_round.max(1) as usize;
        let Some(action_id) = actions.get((round - 1) % actions.len()).copied() else {
            return Ok(None);
        };
        let row = self
            .content
            .lookup_in(action_id, rd_core::content::EK_EACTION)
            .map(|entry| u32::from(entry.index));
        let kind = row.and_then(|row| {
            self.content
                .row(rd_core::content::Table::EnemyAction, row)
                .and_then(|row| rd_core::intent::intent_kind_of(self.content, row).ok().flatten())
        });
        Ok(Some((action_id, row.unwrap_or(u32::MAX), kind)))
    }

    fn action_for(&self, actor: &CombatantId) -> Result<Option<&'static str>, String> {
        Ok(self.intent_action(actor)?.map(|(action_id, _, _)| action_id))
    }''',
        ),
        # refresh_intents：走同一个 intent_action
        (
            '''            let choice: Result<Option<ActionChoice<'static>>, _> =
                match locate_enemy(content, self.encounter, &id) {
                    Ok(Some(at)) => select_action(&self.state, content, at, &id, round),
                    Ok(None) => {
                        intents.push(Intent::unknown("不在这条遭遇的敌人名单里"));
                        continue;
                    }
                    Err(error) => Err(error),
                };
            let intent = match choice {
                Ok(Some(choice)) => {
                    // §386：带状态求值 —— 掷骰伤害（`roll.bite`）才显示得出来。
                    let damage =
                        program_damage_with_state(content, choice.action_row, &self.state, &id);
                    let kind = intent_kind_code(choice.intent_kind);
                    let mut text = choice.action_id.to_string();''',
            '''            let _ = round;
            // §411：与**执行**共用 `intent_action`（含"按定义 id 兜底"）——
            // 第一版这里只走 `locate_enemy`，于是分裂/召唤出来的敌人意图永远是"未知"。
            let choice = self.intent_action(&id);
            let intent = match choice {
                Ok(Some((action_id, action_row, intent_kind))) => {
                    // §386：带状态求值 —— 掷骰伤害（`roll.bite`）才显示得出来。
                    let damage = program_damage_with_state(content, action_row, &self.state, &id);
                    let kind = intent_kind_code(intent_kind);
                    let mut text = action_id.to_string();''',
        ),
        (
            '''                Ok(None) => Intent::unknown("没有 authored 动作"),
                Err(error) => Intent::unknown(&format!("intent 读不出来: {}", detail(&error))),''',
            '''                Ok(None) => Intent::unknown("没有 authored 动作"),
                Err(error) => Intent::unknown(&format!("intent 读不出来: {}", error)),''',
        ),
        # step_play：目标用活的名单
        (
            '''        let target: Option<&'static str> = if target_slot < 0 {
            None
        } else {
            self.plan
                .enemies
                .get(target_slot as usize)
                .map(|enemy| &*Box::leak(enemy.id.to_string().into_boxed_str()))
        };''',
            '''        // §411：目标从**活的**名单取（`combatant_at_slot`），不是开战时的 `plan.enemies`。
        // 旧写法在分裂/召唤之后 `plan.enemies.get(slot)` 是 `None` ⇒ 卡打空、不掉血。
        let target: Option<&'static str> = self
            .combatant_at_slot(target_slot)
            .map(|id| &*Box::leak(id.as_str().to_string().into_boxed_str()));''',
        ),
    ],
    'lib.rs',
)

# ── 2. 药水的两个原子：目标也用活的名单（run.rs）──────────────────────────
patch(
    'kernel/rd-wasm/src/run.rs',
    [
        (
            '''            let slot_index = if target >= 0 {
                target as usize
            } else {
                (0..session.plan.enemies.len())
                    .find(|index| {
                        let id = session.plan.enemies[*index].id;
                        rd_core::state::CombatantId::new(id)
                            .ok()
                            .and_then(|cid| session.state.combatant(&cid))
                            .is_some_and(|c| c.health_current > 0)
                    })
                    .unwrap_or(usize::MAX)
            };
            let Some(plan_enemy) = session.plan.enemies.get(slot_index) else {
                return refuse("药水没有目标：这一侧没有活着的敌人");
            };
            let Ok(target_id) = rd_core::state::CombatantId::new(plan_enemy.id) else {
                return refuse("敌人的战斗员 id 不合法");
            };''',
            '''            // §411：目标槽 → **活的**战斗员（`combatant_at_slot`）。旧写法查 `plan.enemies`
            // （开战时的静态表），分裂/召唤之后槽位越界 ⇒ 药水"没有目标" ⇒ 界面卡在选目标。
            let target_id = if target >= 0 {
                session.combatant_at_slot(target)
            } else {
                let roster = session.enemy_roster();
                roster
                    .iter()
                    .find(|cid| {
                        session
                            .state
                            .combatant(cid)
                            .is_some_and(|c| c.health_current > 0)
                    })
                    .copied()
            };
            let Some(target_id) = target_id else {
                return refuse("药水没有目标：这一侧没有活着的敌人");
            };''',
        ),
        (
            '''                let Some(plan_enemy) = session.plan.enemies.get(slot_index) else {
                    return refuse("药水没有目标：这一侧没有活着的敌人");
                };
                match rd_core::state::CombatantId::new(plan_enemy.id) {''',
            '''                // §411：同上 —— 目标从活的名单取。
                let Some(target_id) = (if target >= 0 {
                    session.combatant_at_slot(target)
                } else {
                    let roster = session.enemy_roster();
                    roster
                        .iter()
                        .find(|cid| {
                            session
                                .state
                                .combatant(cid)
                                .is_some_and(|c| c.health_current > 0)
                        })
                        .copied()
                }) else {
                    return refuse("药水没有目标：这一侧没有活着的敌人");
                };
                match Ok::<_, ()>(target_id) {''',
        ),
    ],
    'run.rs potions',
)

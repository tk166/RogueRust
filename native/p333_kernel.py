"""§333：给"下一回合多抽 / 多能量"补上**一次性**的那一半。

## 分析结论（这一节的主要产出）

文档里那条 `Draw / Energized（下一回合多抽 / 多能量）` 写的"需要：内核（回合开始的发牌/能量）"
**是过时的**：两条管线都在，而且都有真实消费者 ——

| 管线 | 读它的时刻 | 现在的消费者 |
|---|---|---|
| `TurnStartDraw` | 回合开始第 **6** 步（抽牌） | `standard.draw_reduction`（每层 −1）、`standard.ring_of_the_serpent`（+1 flat） |
| `TurnStartEnergy` | 回合开始第 **2** 步（补能） | `berserk`、`philosophers_stone`、`art_of_war`、`mark_of_pain`、`slavers_collar`、`busted_crown`、`ectoplasm`、`sozu`、`cursed_key`、`velvet_choker`、`runic_dome` |

真正缺的是**一次性**的那一半：wiki 的 `Energized` / `Draw Card` 是"**只**下一回合"，而上面的
消费者全是"每回合"。内容能表达"一次性"的路子有两条，各差一点：

* 自己 `TurnStarted` 触发器里摘掉自己 —— 对**能量**成立（补能在第 2 步，触发器在第 4 步），
  对**抽牌**不成立（抽牌在第 6 步，触发器在第 4 步就把自己摘了 ⇒ 加成丢了）；
* 用 `pending_turns` 延后一层 —— 但"哪一回合该失效"仍然要在**抽牌之后**才能判。

所以缺的是**一个时刻**：抽牌之后。内容够不到它（既不是 `TurnStarted` 也不是 `TurnEnded`），
与 §197 `Blur` 的"撑过一次就摘掉"是同一类问题，而那里已经有先例
（`consume_one_shot_block_retainers`）。

## 这一节做的

1. 标签 `one_shot_turn_start`（内容 `STAT.Tags` 里写）；
2. `Host::expire_one_shot_turn_start` —— 与 `consume_one_shot_block_retainers` 同形：
   摘掉身上**所有**带该标签的状态；
3. `turn.rs` 在**抽牌之后**调一次（那时两条管线都已经读过它们了）；
4. 内容加两个状态：`standard.energized`（`TurnStartEnergy/AddPerStack 1`）、
   `standard.draw_card_next_turn`（`TurnStartDraw/AddPerStack 1`），都带这个标签。

`TurnHost` 的新方法给一个**默认空实现**：只有 `Host` 有内容，测试宿主没有内容，
对它们"什么都不做"就是正确答案（这与 `turn_start_draw_count` 的默认实现同一条理由）。
"""

import io

HOST = 'kernel/rd-core/src/host.rs'
TURN = 'kernel/rd-core/src/turn.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ══ 1. host.rs：标签 + 方法 ═══════════════════════════════════════════════════
h = io.open(HOST, encoding='utf-8').read()

h = sub(h, """pub const TAG_RETAIN_BLOCK_ONCE: &str = "retain_block_once";""",
        """pub const TAG_RETAIN_BLOCK_ONCE: &str = "retain_block_once";

/// §333：`one_shot_turn_start` —— "这一回合开始结算完就摘掉"。
///
/// 用它的状态是 wiki 的 `Energized` / `Draw Card`（"**只**下一回合 +X 能量 / +X 抽牌"）：
/// 它们的修饰器在回合开始被 `TurnStartEnergy`（第 2 步）与 `TurnStartDraw`（第 6 步）读，
/// 读完就该消失。**抽牌在第 6 步、`TurnStarted` 触发器在第 4 步**，所以内容自己摘不掉
/// （见 [`Host::expire_one_shot_turn_start`]）。
pub const TAG_ONE_SHOT_TURN_START: &str = "one_shot_turn_start";""",
        'tag')

h = sub(h, """    pub fn consume_one_shot_block_retainers(&mut self, state: &mut CombatState, actor: &CombatantId) {""",
        """    /// §333：摘掉 `one_shot_turn_start` 的状态（`Energized` / `Draw Card`）。
    ///
    /// 调用点在 `turn.rs` 的**抽牌之后**：那时 `TurnStartEnergy`（第 2 步）与
    /// `TurnStartDraw`（第 6 步）都已经把它们算进去了。
    ///
    /// 与 [`Self::consume_one_shot_block_retainers`] 同形（先收集定义再摘，避免在遍历
    /// 状态表时改它），也同一条纪律：**只摘"活的"**（pending 的那些还没生效，不该被摘）。
    pub fn expire_one_shot_turn_start(&mut self, state: &mut CombatState, actor: &CombatantId) {
        let mut definitions = [crate::state::StatusDefinitionId::EMPTY; 8];
        let mut count = 0usize;
        {
            let Some(combatant) = state.combatant(actor) else {
                return;
            };
            for instance in combatant.statuses() {
                if count == definitions.len() || !is_active(instance) || instance.stacks <= 0 {
                    continue;
                }
                let Ok(true) = status_bind::has_tag(
                    self.content,
                    instance.definition_id.as_str(),
                    TAG_ONE_SHOT_TURN_START,
                ) else {
                    continue;
                };
                definitions[count] = instance.definition_id;
                count += 1;
            }
        }
        for definition in definitions.iter().take(count) {
            let _ = self.modify_status_stacks(state, actor, definition, -99);
        }
    }

    pub fn consume_one_shot_block_retainers(&mut self, state: &mut CombatState, actor: &CombatantId) {""",
        'host method')

# TurnHost 实现里转发（照 consume_one_shot_block_retainers 那一行的形状）
h = sub(h, """    fn consume_one_shot_block_retainers(&mut self, state: &mut CombatState, actor: &CombatantId) {
        Host::consume_one_shot_block_retainers(self, state, actor);
    }""",
        """    fn consume_one_shot_block_retainers(&mut self, state: &mut CombatState, actor: &CombatantId) {
        Host::consume_one_shot_block_retainers(self, state, actor);
    }

    fn expire_one_shot_turn_start(&mut self, state: &mut CombatState, actor: &CombatantId) {
        Host::expire_one_shot_turn_start(self, state, actor);
    }""",
        'trait impl')
io.open(HOST, 'w', encoding='utf-8', newline='\n').write(h)
print('host.rs: tag + expire method')

# ══ 2. turn.rs：trait 默认实现 + 抽牌之后调用 ═════════════════════════════════
t = io.open(TURN, encoding='utf-8').read()

t = sub(t, """    /// §199：回合开始**补给多少能量**（`TurnStartEnergy` 管线之后的数）。默认 `base`。""",
        """    /// §333：摘掉 `one_shot_turn_start` 的状态（`Energized` / `Draw Card`）。
    ///
    /// 默认**什么都不做**：只有 `Host` 有内容，而"哪些状态带那个标签"只能从内容读。
    /// 与 [`Self::turn_start_draw_count`] 的默认实现同一条理由 —— 测试宿主没有内容，
    /// 对它们"不做"就是正确答案。
    fn expire_one_shot_turn_start(&mut self, state: &mut CombatState, actor: &CombatantId) {
        let _ = (state, actor);
    }

    /// §199：回合开始**补给多少能量**（`TurnStartEnergy` 管线之后的数）。默认 `base`。""",
        'trait default')

t = sub(t, """    // 7. 清 Block。它在队列解析**之后** —— 所以第 5 步里排队的 `gainBlock` 会被这一次清空抹掉，""",
        """    // 6b. §333：`one_shot_turn_start` 的状态在这里过期。
    //     位置是**语义**：`TurnStartEnergy` 在第 2 步、`TurnStartDraw` 在第 6 步都已经读过它们，
    //     所以"读完就摘"必须落在这两步之后。放在第 4 步（`TurnStarted` 触发器）会把**抽牌**那份
    //     加成提前摘掉 —— 而那正是这条机制此前做不到的原因。
    host.expire_one_shot_turn_start(state, &actor);
    if stopped(state) {
        return Ok(());
    }

    // 7. 清 Block。它在队列解析**之后** —— 所以第 5 步里排队的 `gainBlock` 会被这一次清空抹掉，""",
        'call site')
io.open(TURN, 'w', encoding='utf-8', newline='\n').write(t)
print('turn.rs: default + call after draw')

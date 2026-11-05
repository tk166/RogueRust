"""§226 (part 2): 把 §225 那条"已知语义差"的断言改成**正确语义**的断言。

`Second Wind` / `Fiend Fire` 现在用 `event.bool: card.isResolving` 把正在结算的那张牌排除掉
（StS 的形状：打出的牌在结算时已经不在手牌）。所以：
* Second Wind：1 张打击 + 1 张防御 + 自己（skill）⇒ 只消耗防御、只给 5 格挡（原来 10）；
* Fiend Fire：2 张（打击 + 防御）× 7 = 14（原来 3 × 7 = 21）。
"""
import io

HOST = 'kernel/rd-core/src/host.rs'

src = io.open(HOST, encoding='utf-8').read()

old_doc = '''    /// §225：`Second Wind` / `Fiend Fire` —— 整手牌逐张消耗，每张换一份效果。
    ///
    /// 这两张牌同时钉住三件事：
    /// ① `forEachCardInZone` 的快照语义（循环体搬走卡不影响这一趟）；
    /// ② 迭代卡的 **tag 位**被填进 `event_flags`（§225 A），否则"**非攻击**牌"会把攻击牌也算进去；
    /// ③ 消耗走 `moveCardToZone` ⇒ `move_card_for` ⇒ `LifecyclePrograms[Exhausted]`（§220 那条路）。'''
new_doc = '''    /// §225/§226：`Second Wind` / `Fiend Fire` —— 整手牌逐张消耗，每张换一份效果。
    ///
    /// 这两张牌同时钉住四件事：
    /// ① `forEachCardInZone` 的快照语义（循环体搬走卡不影响这一趟）；
    /// ② 迭代卡的 **tag 位**被填进 `event_flags`（§225 A），否则"**非攻击**牌会把攻击牌也算进去"；
    /// ③ §226：迭代的牌**是不是正在结算的那一张**（`event.bool: card.isResolving`）——
    ///    打出的牌在参考里要到终态回调才离开手牌，所以循环看得见它，StS 的语义里它**不算**
    ///    "手牌里的一张"。内容的 `not(card.isResolving)` 把这条差补上；
    /// ④ 消耗走 `moveCardToZone` ⇒ `move_card_for` ⇒ `LifecyclePrograms[Exhausted]`（§220 那条路）。'''
assert src.count(old_doc) == 1
src = src.replace(old_doc, new_doc)

old = '''        // ⚠️ **已知语义差（§225 记录）**：参考实现里打出的牌在节目期间**仍在手牌里**
        // （`onTerminal` 才落区，`play::tests` 与 `CARD_DIFF` 的 `archive_the_evidence` 都钉着
        // 这条）。所以这个循环把 `Second Wind` 自己也算进去 ⇒ 5×2 = 10，而 wiki 是 5。
        // 改它要动参考的落区时机（哈希契约），因此这里如实断言我们的数字，差异写进
        // `sts-wiki-gap.md` §G.2。
        assert_eq!(
            block_of(&state, "hero"),
            10,
            "5 for the Skill + 5 for the Second Wind itself (declared deviation); exhausted: {:?}",
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
        );'''
new = '''        // 参考里打出的牌在节目期间**仍在手牌里**（`onTerminal` 才落区 —— `play::tests` 与
        // `CARD_DIFF` 的 `archive_the_evidence` 都钉着这条，所以内核**不动**快照）。
        // §226 让内容自己认得出"这一趟就是我"：`not(event.bool: card.isResolving)`。
        // ⇒ 只给防御那 5 点，Second Wind 自己那份**不再算**。
        assert_eq!(
            block_of(&state, "hero"),
            5,
            "5 for the Skill only -- the card being played is not \\"a card in your hand\\"; \
             exhausted: {:?}",
            zone_definitions(&state, "hero", CardZone::ExhaustPile)
        );'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''        // 同理：三张牌（打击 / 防御 / Fiend Fire 自己）× 7 = 21 ⇒ 20 血的敌人归零。
        assert_eq!(
            health(&state, "enemy_a"),
            0,
            "3 x 7 = 21 (the played card counts itself -- the same declared deviation)"
        );'''
new = '''        // 同理：两张牌（打击 / 防御）× 7 = 14 ⇒ 20 血的敌人剩 6。Fiend Fire 自己不算
        // （否则是 21，一场"多打了一张"的胜利）。
        assert_eq!(
            health(&state, "enemy_a"),
            6,
            "2 x 7 = 14, not 3 x 7 = 21: the played card is not \\"in your hand\\""
        );'''
assert src.count(old) == 1
src = src.replace(old, new)

io.open(HOST, 'w', encoding='utf-8', newline='\n').write(src)
print('ok')

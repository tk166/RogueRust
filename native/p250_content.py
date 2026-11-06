"""§250（内容）：B/C/D/F 四组共 14 张牌 / 18 行。

牌面数字全部来自 wiki 正文（两处来源核对过）：

| 牌 | 正文 | 载体 |
|---|---|---|
| `ritual_dagger` | 1 费，15 伤害；**If Fatal, 本牌伤害永久 +3（升级 +5）**；Exhaust | `dealDamageAndIfFatal` + `card.counter` |
| `hand_of_greed` | 2 费，20/25 伤害；**If Fatal, 20/25 金币** | `dealDamageAndIfFatal` + `gainGold` |
| `discovery` | 1 费，三选一加进手牌、**这次 0 费**；**基础 Exhaust，升级不 Exhaust** | `offerRandomCards` |
| `forethought` | 0 费；放到抽牌堆**底**、0 费直到打出；**升级后"任意张"** | `ChoiceThen::ToDrawPileBottomFree` |
| 诅咒 10 张 | 见各行 `DescriptionKey` | 生命周期键 / 出牌上限 / `createCardCopy` |

⚠️ 三处**写明了的偏差**（`port-plan.md` §250 有同一份记录）：
1. `ritual_dagger` 的成长是**这场战斗内**（每副本 mark counter 跟着实例走），StS 是**跨场永久**；
   我们的运行层不会把战斗实例的计数器写回牌组。同样记在 §248 的每副本价格那一条旁边。
2. `discovery` 的候选池是"排除无色/诅咒/状态/垃圾/X 费后的**基础牌**"，StS 是"你职业的牌池"
   —— 我们的内容没有职业 tag。
3. `parasite` 的效果在**牌组移除**那一刻（run 层），本轮没有"卡牌 run 钩子"，
   所以它在这里只是一张**不可打出的惰性诅咒**。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
# 攻击牌打**这一张牌选中的目标**（与 `strike` 逐字相同：`sel.eventTarget`）。
TARGET = {"kind": "sel.eventTarget",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}
RESOLVING = {"kind": "cardInstance.resolving", "value": {}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def handle():
    return {"value": "(unnamed)"}


def program(root):
    return {"Id": handle(), "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def seq(*children):
    return node("node.sequence", Children=list(children))


def add(left, right):
    return {"kind": "add", "value": {"Left": left, "Right": right}}


def multiply(left, right):
    return {"kind": "multiply", "value": {"Left": left, "Right": right}}


def card_counter(key):
    return {"kind": "card.counter", "value": {"CounterId": {"value": key}}}


def add_card_counter(key, delta):
    return node("node.addCardCounter", CardExpression=RESOLVING, OwnerSelector=SELF,
                CounterId={"value": key}, Delta=const(delta))


def deal_damage(amount, selector=TARGET):
    return node("node.dealDamage", TargetSelector=selector, Amount=amount,
                IgnoresBlock=False, Element=None)


def deal_damage_and_if_fatal(amount, body):
    return node("node.dealDamageAndIfFatal", TargetSelector=TARGET, Amount=amount,
                IgnoresBlock=False, Element=None, Program=body)


def gain_gold(amount):
    return node("node.gainGold", Amount=const(amount))


def lose_hp(amount):
    return node("node.loseHp", TargetSelector=SELF, Amount=amount)


def apply_status(status_id, stacks):
    return node("node.applyStatus", TargetSelector=SELF,
                StatusDefinitionId={"value": status_id}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def create_card_copy(zone, placement=None, definition=None):
    kwargs = {"ToZone": zone}
    if placement:
        kwargs["Placement"] = placement
    if definition:
        # 生命周期节目里没有"当前这张牌"（§220 的偏离 #2）⇒ 由内容指明定义 id。
        kwargs["CardDefinitionId"] = definition
    return node("node.createCardCopy", **kwargs)


def set_counter(key, amount):
    return node("node.setCombatantCounter", TargetSelector=SELF,
                CounterId={"value": key}, Amount=const(amount), Relative=False)


def zone_count(zone_name):
    return {"kind": "combatantZoneCount",
            "value": {"Selector": SELF, "Zone": zone_name}}


def offer_cards(count):
    # `Count`/`Min`/`Max` 都是**普通整数字段**（不是表达式）—— 与 `chooseCards` 的 `Min`/`Max` 同形。
    return node("node.offerRandomCards", Count=count, Min=1, Max=1)


def choose_from_hand(then, min_cards, max_cards):
    return node("node.chooseCards", OwnerSelector=SELF, FromZone="Hand",
                Min=min_cards, Max=max_cards, Then=then)


def then_to_draw_pile_bottom_free():
    # `Then` 是**裸字符串**（与 `warcry` 的 `"Then": "ToDrawPileTop"` 同一个形状）——
    # 它不是 IR 节点，所以没有 `{kind, value}` 包装。
    return "ToDrawPileBottomFree"


# ---------------------------------------------------------------------------
# 卡表
# ---------------------------------------------------------------------------
def card(card_id, cost, rarity, tags, text, root, *, exhaust=False, lifecycle=None,
         turn_end_zone="DiscardPile"):
    return dict(id=card_id, cost=cost, rarity=rarity, tags=tags, text=text, root=root,
                exhaust=exhaust, lifecycle=lifecycle or {}, turn_end_zone=turn_end_zone)


RITUAL = "standard.ritual_dagger_bonus"

CARDS = [
    # ---- B：ritual_dagger（每副本伤害记账 + If Fatal）----
    card('ritual_dagger', 1, 'Special', ['attack', 'colorless'],
         "Deal 15 damage. If Fatal, permanently increase this card's damage by 3. Exhaust.",
         deal_damage_and_if_fatal(add(const(15), multiply(card_counter(RITUAL), const(3))),
                                  seq(add_card_counter(RITUAL, 3))),
         exhaust=True),
    card('ritual_dagger+', 1, 'Special', ['attack', 'colorless'],
         "Deal 15 damage. If Fatal, permanently increase this card's damage by 5. Exhaust.",
         deal_damage_and_if_fatal(add(const(15), multiply(card_counter(RITUAL), const(5))),
                                  seq(add_card_counter(RITUAL, 5))),
         exhaust=True),
    # ---- F：hand_of_greed（战斗里赚金币）----
    card('hand_of_greed', 2, 'Rare', ['attack', 'colorless'],
         "Deal 20 damage. If Fatal, gain 20 Gold.",
         deal_damage_and_if_fatal(const(20), seq(gain_gold(20)))),
    card('hand_of_greed+', 2, 'Rare', ['attack', 'colorless'],
         "Deal 25 damage. If Fatal, gain 25 Gold.",
         deal_damage_and_if_fatal(const(25), seq(gain_gold(25)))),
    # ---- C：discovery（三选一，进手牌且免费）----
    card('discovery', 1, 'Uncommon', ['skill', 'colorless'],
         "Choose 1 of 3 random cards to add into your hand. It costs 0 this turn. Exhaust.",
         seq(offer_cards(3)), exhaust=True),
    # 升级**不再 Exhaust**（wiki：「Upgrading Discovery causes it to no longer Exhaust」）。
    card('discovery+', 1, 'Uncommon', ['skill', 'colorless'],
         "Choose 1 of 3 random cards to add into your hand. It costs 0 this turn.",
         seq(offer_cards(3))),
    # ---- C：forethought（放抽牌堆底 + 免费）----
    card('forethought', 0, 'Uncommon', ['skill', 'colorless'],
         "Put a card from your hand to the bottom of your draw pile. It costs 0 until played.",
         seq(choose_from_hand(then_to_draw_pile_bottom_free(), 1, 1))),
    # 升级 = "任意张"。上限用 10（StS 的手牌上限），不是"手牌数" —— `Min`/`Max` 是**字面整数**。
    card('forethought+', 0, 'Uncommon', ['skill', 'colorless'],
         "Put any number of cards from your hand to the bottom of your draw pile. "
         "They cost 0 until played.",
         seq(choose_from_hand(then_to_draw_pile_bottom_free(), 0, 10))),
    # ---- D：10 张诅咒 ----
    card('clumsy', 1, 'Curse', ['curse', 'unplayable', 'ethereal'],
         "Unplayable. Ethereal.", seq(), turn_end_zone="ExhaustPile"),
    card('curse_of_the_bell', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. Cannot be removed from your deck.", seq()),
    card('decay', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. At the end of your turn, take 2 damage.", seq(),
         lifecycle={"TurnEndInHand": program(seq(deal_damage(const(2), SELF)))}),
    card('necronomicurse', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. When Exhausted, a new copy appears in your hand.", seq(),
         lifecycle={"Exhausted": program(
             seq(create_card_copy("Hand", definition="necronomicurse")))}),
    # 上限走**计数器**（`play.rs` 的 `card_play_cap`）：`Drawn` 设 3，`TurnEndInHand` 清 0。
    # 计数器是覆盖写 ⇒ 每回合抽到再设一次不会翻倍（用状态层数就会，那会把"3 张"变成 6 张）。
    card('normality', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. You cannot play more than 3 cards this turn.", seq(),
         lifecycle={"Drawn": program(seq(set_counter("card_play_cap", 3))),
                    "TurnEndInHand": program(seq(set_counter("card_play_cap", 0)))}),
    # `pain`：`CardPlayedInHand` 是 §250 新加的生命周期键。
    card('pain', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. While in hand, lose 1 HP when other cards are played.", seq(),
         lifecycle={"CardPlayedInHand": program(seq(lose_hp(const(1))))}),
    card('parasite', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. If transformed or removed from your deck, lose 3 Max HP.", seq()),
    # `pride` 是**可打出**的（wiki：「Unlike all other Curses, it can naturally be played」），
    # 打出后 Exhaust，所以它没有 `unplayable` tag，`PlayedCardDestinationZone` 是消耗堆。
    card('pride', 1, 'Curse', ['curse', 'innate'],
         "Innate. At the end of your turn, put a copy of this card on top of your draw pile. "
         "Exhaust.", seq(), exhaust=True,
         lifecycle={"TurnEndInHand": program(
             seq(create_card_copy("DrawPile", "Top", definition="pride")))}),
    card('regret', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. At the end of your turn, lose HP equal to the number of cards in your hand.",
         seq(), lifecycle={"TurnEndInHand": program(
             seq(lose_hp(zone_count("Hand"))))}),
    card('shame', 1, 'Curse', ['curse', 'unplayable'],
         "Unplayable. At the end of your turn, gain 1 Frail.", seq(),
         lifecycle={"TurnEndInHand": program(seq(apply_status("standard.frail", 1)))}),
]


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in doc['Cards']}
    added = 0
    for spec in CARDS:
        if spec['id'] in have:
            continue
        row = {
            'Id': spec['id'],
            'PackageId': 'sts',
            'NameKey': spec['id'],
            'DescriptionKey': spec['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': spec['cost']}],
            'Tags': [{'value': tag} for tag in spec['tags']],
            'Rarity': spec['rarity'],
            'Program': program(spec['root']),
            'LifecyclePrograms': spec['lifecycle'],
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': spec['turn_end_zone'],
            'PlayedCardDestinationZone': 'ExhaustPile' if spec['exhaust'] else 'DiscardPile',
        }
        doc['Cards'].append(row)
        added += 1
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('added %d card row(s); total %d' % (added, len(doc['Cards'])))


main()

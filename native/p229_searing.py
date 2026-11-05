"""§229 (part 4): `Searing Blow` —— "Can be Upgraded any number of times"。

先说清楚**为什么可以不加模型**：本内容的"升级"是**另一行 CARD**（`strike` → `strike+`）。"任意次"
需要的只是**能连续加 `+`**（`searing_blow` → `+` → `++` → …），而现行实现里卡住它的是两处
**猜**而不是查：

1. `state::upgraded_id` 见到以 `+` 结尾的 id 直接返回 `None`（防 `strike+` → `strike++`）。但真正
   该问的是"内容里有没有那一行" —— `exec::upgradable_definition` 一直在问，这里没问。
2. `rd_run::upgrade_at`（事件/祝福的"升级一张牌"）同样以 `ends_with('+')` 判定"已经升级过"。
   它的调用方 `apply_deck_change` **手里就有 `pool`**，只是没往下传 —— 于是它没法查表，只能猜。

两处都改成**查表**：`+` 能加几次由内容里有多少行决定，`strike++` 不存在 ⇒ `strike+` 依然升不了。
于是 `searing_blow` 只要把行写够就成立，内核与运行层都不用认识这张牌。
"""
import io

STATE = 'kernel/rd-core/src/state.rs'
RUN = 'kernel/rd-run/src/state.rs'
CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'
INV = 'native/card_wiki_inventory.py'

# ── 1) 内核：允许"再加一个 +"，行是否存在由调用方查内容 ────────────────────────
src = io.open(STATE, encoding='utf-8').read()
old = '''/// 返回 `None` 的两种情形都是**拒绝**、不是"随便给个值"：
/// * id 已经以 `+` 结尾（升级过的不再升级）；
/// * `+` 之后超出 [`ID_CAP`]（装不下就会被截断成一个**别的** id，那是撞名）。
#[must_use]
pub fn upgraded_id(definition: &str) -> Option<CardDefinitionId> {
    let bytes = definition.as_bytes();
    if bytes.last() == Some(&b'+') || bytes.len() + 1 > ID_CAP {
        return None;
    }'''
new = '''/// 返回 `None` 只有一种情形：`+` 之后超出 [`ID_CAP`]（装不下就会被截断成一个**别的** id，那是撞名）。
///
/// §229：**这里不再拒绝"已经以 `+` 结尾"**。那条规则是"防 `strike+` 变成 `strike++`"，而它真正该问
/// 的是"内容里有没有 `strike++` 这一行" —— 那个问题只有拿得到内容的人能回答，所以它归
/// `exec::upgradable_definition`（以及 `rd_run::upgrade_at` 的查表）。把"能加几次"写在**内容**里，
/// `Searing Blow` 的 "Can be Upgraded any number of times" 就不需要任何新模型：
/// 行写到哪儿，就能升到哪儿。
#[must_use]
pub fn upgraded_id(definition: &str) -> Option<CardDefinitionId> {
    let bytes = definition.as_bytes();
    if bytes.len() + 1 > ID_CAP {
        return None;
    }'''
assert src.count(old) == 1
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))

# ── 2) 运行层：`upgrade_at` 拿到牌池，改成查表 ────────────────────────────────
src = io.open(RUN, encoding='utf-8').read()
old = '''            DeckChange::Upgrade => self.upgrade_at(index)?,'''
new = '''            // §229: the pool is already in hand here -- passing it down is what lets `upgrade_at`
            // **look up** the next row instead of guessing from a `+` suffix.
            DeckChange::Upgrade => self.upgrade_at(index, pool)?,'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''    /// Append the upgrade marker (`strike` → `strike+`).
    ///
    /// Already upgraded is **not** an error: the blessing (or the event) simply has nothing to do.
    /// That is the reference's behaviour too -- StS lets you upgrade a card you already upgraded and
    /// nothing happens.
    fn upgrade_at(&mut self, index: usize) -> Result<(), RunError> {
        let id = self.deck[index].as_str();
        if id.ends_with('+') {
            return Ok(());
        }
        let mut buffer = [0u8; 64];
        let mut len = 0usize;
        for byte in id.as_bytes() {
            if len < buffer.len() - 1 {
                buffer[len] = *byte;
                len += 1;
            }
        }
        buffer[len] = b'+';
        len += 1;
        let upgraded = core::str::from_utf8(&buffer[..len]).map_err(|_| RunError::BadId)?;'''
new = '''    /// Replace the deck card with its upgraded row (`strike` → `strike+`), **looked up in the pool**.
    ///
    /// Already upgraded is **not** an error: the blessing (or the event) simply has nothing to do.
    /// That is the reference's behaviour too -- StS lets you upgrade a card you already upgraded and
    /// nothing happens.
    ///
    /// §229: "nothing to do" is decided by **the content**, not by a `+` suffix. `upgraded_id` asks the
    /// pool whether `<id>+` exists, so `Searing Blow` (whose id keeps growing `+`) upgrades again and
    /// `strike+` (no `strike++` row) still does nothing -- one rule for every card, and the run layer
    /// still owns no content.
    fn upgrade_at(&mut self, index: usize, pool: &[PoolCard<'_>]) -> Result<(), RunError> {
        let id = self.deck[index].as_str();
        let Some(upgraded) = upgraded_id(pool, id) else {
            return Ok(());
        };'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(src)

# ── 3) 内容：8 行（12/16/20/…/40） ───────────────────────────────────────────
SEL_EVENT_TARGET = {
    "kind": "sel.eventTarget",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"},
}


def row(cid, name, damage, upgradable):
    text = ("Deal %d damage. Can be upgraded any number of times." % damage) if not upgradable \
        else ("Deal %d damage." % damage)
    return {
        "Id": cid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": text,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": 2}],
        "Tags": [{"value": "attack"}],
        "Rarity": "Uncommon",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": {
                "kind": "node.dealDamage",
                "value": {
                    "TargetSelector": SEL_EVENT_TARGET,
                    "Amount": {"kind": "const", "value": {"Value": damage}},
                    "ResultKey": None,
                    "IgnoresBlock": False,
                    "Element": None,
                },
            },
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": "DiscardPile",
        "PlayedCardDestinationZone": "DiscardPile",
    }


raw = io.open(CONTENT, encoding='utf-8').read()
import json
data = json.loads(raw)
have = {r['Id'] for r in data['Cards']}
assert not any(i.startswith('searing_blow') for i in have)

LEVELS = 8  # 基础 + 7 次升级：12/16/20/24/28/32/36/40
for level in range(LEVELS):
    cid = 'searing_blow' + '+' * level
    name = 'Searing Blow' + '+' * level
    data['Cards'].append(row(cid, name, 12 + 4 * level, level + 1 < LEVELS))

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── 4) 检查器 + wiki 清单 ────────────────────────────────────────────────────
src = io.open(CHECK, encoding='utf-8').read()
rows = []
for level in range(LEVELS):
    cid = 'searing_blow' + '+' * level
    rows.append('    "%s": {"Cost": 2, "Tags": ["attack"],\n%*s"Facts": [("damage", %d, "event")]},'
                % (cid, len(cid) + 4, '', 12 + 4 * level))
old = '''    # ---- §229：随机双击（§228 载体的第二个用户）/ 每副本计数器 ------------------------------'''
new = '''    # ---- §229：可无限升级（内容把行写够） ---------------------------------------------------
    # 八行 = 基础 + 7 次升级（12/16/20/…/40）。`+` 能叠几次**由行数决定**，内核不认识这张牌。
''' + '\n'.join(rows) + '''
    # ---- §229：随机双击（§228 载体的第二个用户）/ 每副本计数器 ------------------------------'''
assert src.count(old) == 1
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))

src = io.open(INV, encoding='utf-8').read()
old = """    # 没有数字的牌：纯关键字/状态牌。"""
new = """    # §229：`Deal (12;16) damage. Can be Upgraded any number of times.` —— 每档 +4，`plus` 是**第一档**。
    'searing_blow': ([('damage', 12, 'event')], [('damage', 16, 'event')]),
    # 没有数字的牌：纯关键字/状态牌。"""
assert src.count(old) == 1
io.open(INV, 'w', encoding='utf-8', newline='\n').write(src.replace(old, new))
print('ok searing blow')

"""给**每一个**会改状态的 RunStore 动作插入统一冻结检查（`canMutate`）。

按**行**定位（不能用 `[^{]*\\{`：`enterNode` 的返回类型 `{ ok: boolean; ... }` 自带花括号）。
每个插入都断言"签名恰好一次"，插完再按同样的方式扫一遍确认没有漏 —— 漏一个就是冻结有洞。
"""

import io
import re

P = 'web-next/src/run/RunStore.ts'
src = io.open(P, encoding='utf-8').read()

# 方法名 → (日志里的动作名, 失败返回值；None = void)
GUARDS = {
    'chooseBlessing': ('选择祝福', None),
    'enterNode': ('走路', 'return { ok: false, why: this.frozenReason ?? "已冻结" };'),
    'beginNode': ('结算节点', 'return -1;'),
    'fightBegin': ('开战', 'return -1;'),
    'fightEnd': ('战斗结算', 'return -1;'),
    'takeRewardCard': ('拿奖励牌', 'return -1;'),
    'skipReward': ('跳过奖励', 'return -1;'),
    'takeRewardPotion': ('拿奖励药水', 'return -1;'),
    'takeRewardRelic': ('拿奖励遗物', 'return -1;'),
    'settleDefault': ('用默认动作通过', 'return false;'),
    'endAct': ('幕间推进', 'return -1;'),
    'buy': ('买东西', 'return -1;'),
    'removeFromDeck': ('删牌', 'return -1;'),
    'leave': ('离开', 'return -1;'),
    'rest': ('休息', 'return -1;'),
    'smith': ('锻造', 'return -1;'),
    'toke': ('抽烟斗', 'return -1;'),
    'lift': ('举重', 'return -1;'),
    'dig': ('挖宝', 'return -1;'),
    'recall': ('回忆', 'return -1;'),
    'openChest': ('开宝箱', 'return -1;'),
    'chooseEvent': ('事件选项', 'return -1;'),
    'takeEventOffer': ('拿事件候选', 'return -1;'),
    'pickEventCard': ('事件选牌', 'return -1;'),
    'pickBlessingCard': ('祝福选牌', 'return -1;'),
    'pickupPickCard': ('欠账改牌', 'return -1;'),
    'pickupAddCard': ('欠账加牌', 'return -1;'),
    'pickupSkip': ('欠账跳过', 'return -1;'),
    'pickupMaxHp': ('欠账换上限', 'return -1;'),
    'usePotion': ('喝药水', 'return -1;'),
    'dropPotion': ('扔药水', 'return -1;'),
}


def body_line(lines, name):
    """返回该方法**函数体第一行**的下标（签名行之后第一个以 `{` 结尾的行 +1）。"""
    heads = [i for i, line in enumerate(lines) if re.match(r'^  ' + re.escape(name) + r'\(', line)]
    assert len(heads) == 1, '%s: 签名命中 %d 次' % (name, len(heads))
    index = heads[0]
    while index < len(lines) and not lines[index].rstrip().endswith('{'):
        index += 1
    assert index < len(lines), '%s: 找不到函数体' % name
    return index + 1


lines = src.split('\n')
# 从后往前插，避免下标漂移。
targets = []
for name, (label, fail) in GUARDS.items():
    at = body_line(lines, name)
    assert 'canMutate' not in lines[at], '%s: 已经插过了' % name
    targets.append((at, name, label, fail))

for at, name, label, fail in sorted(targets, reverse=True):
    lines.insert(at, '    if (!this.canMutate("%s")) %s' % (label, fail if fail else 'return;'))

# 复核：每个方法的函数体第一行都必须是 canMutate
missing = [name for name, _ in GUARDS.items() if 'canMutate' not in lines[body_line(lines, name)]]
assert not missing, '漏了: %s' % missing

io.open(P, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
print('guarded %d actions' % len(targets))

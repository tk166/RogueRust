"""把 `STATUS_ZH` 从"只有名字"升级成 `(名字, 中文说明)`（§393）。

说明都是**一句话**：这个状态做什么。来源是官方中文本地化的措辞习惯（数值按内容包里的写法）。
⚠️ 只作显示，不进任何规则判定。
"""

import io
import re

PATH = 'native/build_zh_i18n.py'
t = io.open(PATH, encoding='utf-8').read()

TABLE = {
    'standard.artifact': ('神器', '抵消接下来 N 个负面效果。'),
    'standard.cap_cost_at': ('费用上限', '这张牌的费用被限制在一个上限。'),
    'standard.confusion': ('混乱', '抽到的牌费用随机化。'),
    'standard.constricted': ('紧束', '每回合结束时失去 N 点生命。'),
    'standard.curiosity': ('好奇', '每当你打出一张能力牌，它获得 N 点力量。'),
    'standard.curl_up': ('蜷缩', '第一次受到攻击伤害时，获得 N 点格挡。'),
    'standard.double_damage': ('双倍伤害', '下一张攻击牌打出两次。'),
    'standard.draw_reduction': ('抽牌减少', '每回合少抽 N 张牌。'),
    'standard.enrage': ('激怒', '每当你打出一张技能牌，它获得 N 点力量。'),
    'standard.entangle_ready': ('缠绕就绪', '下一回合缠绕你。'),
    'standard.entangled': ('缠绕', '本回合不能打出攻击牌。'),
    'standard.fading': ('消逝', 'N 回合后消失。'),
    'standard.flying': ('飞行', '受到的攻击伤害减半；被击中 N 次后落地。'),
    'standard.hex': ('诅咒', '每当你打出一张非攻击牌，获得 1 张虚空。'),
    'standard.intangible': ('无形', '受到的伤害降为 1。回合结束时减 1 层。'),
    'standard.lagavulin_asleep': ('沉睡', '沉睡中：N 回合内不行动、也不受伤害。'),
    'standard.lose_dexterity': ('失去敏捷', '回合结束时失去 N 点敏捷。'),
    'standard.lose_strength': ('失去力量', '回合结束时失去 N 点力量。'),
    'standard.malleable': ('可塑', '受到攻击伤害时获得格挡，格挡量逐次增加。'),
    'standard.mode_shift': ('模式转换', '再受到 N 点伤害就切换形态。'),
    'standard.nightmare_pending': ('噩梦待发', '下回合把选中的牌各复制 N 张。'),
    'standard.no_block_from_cards': ('卡牌不提供格挡', '牌给的格挡无效。'),
    'standard.no_draw': ('无法抽牌', '回合开始时不再抽牌。'),
    'standard.omega': ('欧米伽', 'N 回合结束时，对所有敌人造成 50 点伤害。'),
    'standard.painful_stabs': ('痛苦刺击', '每次攻击造成未被格挡的伤害时，塞 1 张伤口。'),
    'standard.phantom_veil': ('幻影面纱', '本回合受到的伤害降为 1。'),
    'standard.phase_split': ('分裂（相位）', '生命降到 50% 以下时，分裂成 1 只大型酸液史莱姆和 1 只大型尖刺史莱姆（各带当前生命）。'),
    'standard.plated_armor': ('镀甲', '回合结束时获得 N 点格挡；受到未被格挡的攻击伤害时减 1 层。'),
    'standard.poison': ('中毒', '回合开始时失去 N 点生命，然后层数减 1。'),
    'standard.regain_strength': ('恢复力量', '回合结束时恢复 N 点力量。'),
    'standard.regen': ('再生', '回合结束时回复 N 点生命，然后层数减 1。'),
    'standard.sharp_hide': ('尖刺外壳', '被攻击时对攻击者造成 N 点伤害。'),
    'standard.slow': ('迟缓', '本回合每打出一张牌，受到的伤害 +10%。'),
    'standard.split': ('分裂', '死亡时分裂成两只更小的史莱姆。'),
    'standard.split_acid_l': ('分裂：大型酸液', '死亡时分裂成两只中型酸液史莱姆。'),
    'standard.split_spike_l': ('分裂：大型尖刺', '死亡时分裂成两只中型尖刺史莱姆。'),
    'standard.spore_cloud': ('孢子云', '死亡时给凶手 2 层虚弱。'),
    'standard.stasis': ('停滞', '把你的 1 张牌扣住，之后归还。'),
    'standard.stasis_ready': ('停滞就绪', '下一次停滞会扣住你的牌。'),
    'standard.the_bomb_damage': ('炸弹伤害', 'N 回合后爆炸，造成 40 点伤害。'),
    'standard.time_warp': ('时间扭曲', '本回合每打出 12 张牌，你失去一个回合。'),
    'standard.unawakened': ('未觉醒', '第一次死亡后复活。'),
    'standard.fairy_in_a_bottle': ('瓶中精灵', '死亡时回复 30% 生命并复活（一次性）。'),
    'standard.duplication': ('复制', '下一张打出的牌打出两次。'),
    'standard.the_boot': ('靴子', '小于等于 4 点的攻击伤害提升到 5 点。'),
    'standard.paper_phrog': ('纸蛙', '易伤的层数不会在回合结束时减少。'),
    'standard.paper_krane': ('纸鹤', '虚弱的层数不会在回合结束时减少。'),
    'standard.snecko_skull': ('蛇骷髅', '每场战斗第一次抽到诅咒时，抽 1 张牌。'),
    'standard.duality': ('双重', '每打出一张攻击牌，获得 1 点敏捷。'),
    'standard.energized': ('充能', '获得 N 点额外能量。'),
    'standard.draw_card_next_turn': ('下回合抽牌', '下回合多抽 N 张牌。'),
}

# 找到 STATUS_ZH 块并整体替换（块以 `STATUS_ZH = {` 开始、以单独一行 `}` 结束）。
start = t.index('STATUS_ZH = {')
end = t.index('\n}\n', start) + len('\n}\n')
lines = ['STATUS_ZH = {']
for key, (name, text) in TABLE.items():
    lines.append("    '%s': (%r, %r)," % (key, name, text))
lines.append('}')
lines.append('')
new_block = '\n'.join(lines)

# 顺带把类型注释改掉（现在每一条是二元组）。
t = t[:start] + new_block + t[end:]
t = t.replace(
    '#: 只在状态里出现的词 → 中文（§388 第 ③ 层）。',
    '#: 只在状态里出现的词 → `(中文名, 中文说明)`（§388 第 ③ 层 + §393）。',
)
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('STATUS_ZH 升级为 (name, text)，共 %d 条' % len(TABLE))

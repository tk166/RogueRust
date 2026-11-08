"""审阅报告 §5 的**证据路径**对不对：`orange_pellets` 到底写在哪一层。

报告说"这是可以由 JSON `node.applyStatus(strength=3)` 直接证实的行为错误"。
我们这份内容的遗物行 `RunPrograms` / `CombatRules` 全是 null —— 遗物行为分两处：
  * `rd-run/state.rs` 的 `relic_effect()`（名字 → `RelicEffect`）
  * `rd-core/host.rs` 的 §299 段（`CombatRules` 解释器）
真正"数三种牌类型"的程序挂在**状态** `standard.orange_pellets` 上。这份脚本把状态行打出来，
于是"报告的证据路径对不对"有据可查。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def walk(node, out, depth=0):
    if isinstance(node, dict):
        if 'Op' in node or 'Effect' in node or 'Then' in node:
            out.append(json.dumps(node, ensure_ascii=False))
            return
        for key, value in node.items():
            walk(value, out, depth + 1)
    elif isinstance(node, list):
        for item in node:
            walk(item, out, depth + 1)


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    for status in doc['Statuses']:
        if status['Id'] in ('standard.orange_pellets', 'standard.dead_branch'):
            print('=' * 72)
            print(json.dumps({k: v for k, v in status.items() if k != 'Id'},
                             ensure_ascii=False, indent=1)[:2000])
            print('-- flat --')
            ops = []
            walk(status, ops)
            for line in ops[:14]:
                print('  ', line[:200])


main()

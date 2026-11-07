"""§278：把 `UnknownRooms` 的事件迁移成 **节点表**（`EV` 入口 + `EVND` 段）。

迁移是**机械的**：每个旧事件 = 一个入口 + 一个节点，节点的两个选项 = 原来的两个选项，
`Next` 为空（这一段就是终点）。所以迁移前后**行为必须逐字节相同** —— 脚本自己在迁移
前后各抓一份"语义快照"并比对，否则"迁移做错了"会和"内容本来就这样"长得一模一样。

幂等：已经迁移过的行（有 `Entry`、没有 `Label0`）直接跳过。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def snapshot(doc):
    """每个事件的**语义**（不看存储形状）：id、正文、以及每个选项的标签/效果/A15。"""
    out = {}
    nodes = {n['Id']: n for n in (doc.get('EventNodes') or [])}
    for room in doc['UnknownRooms']:
        if 'Entry' in room:
            node = nodes[room['Entry']]
            options = node['Options']
            out[room['Id']] = (
                room.get('NameKey'),
                node.get('TextKey'),
                tuple(
                    (option.get('Label'),
                     tuple((e.get('Effect'), e.get('Amount')) for e in (option.get('Effects') or [])),
                     tuple((e.get('Effect'), e.get('Amount')) for e in (option.get('EffectsAsc') or [])),
                     option.get('Next') or '')
                    for option in options
                ),
            )
        else:
            out[room['Id']] = (
                room.get('NameKey'),
                room.get('DescriptionKey'),
                tuple(
                    (room.get('Label%d' % slot),
                     tuple((e.get('Effect'), e.get('Amount')) for e in (room.get('Effects%d' % slot) or [])),
                     tuple((e.get('Effect'), e.get('Amount')) for e in (room.get('Effects%dAsc' % slot) or [])),
                     '')
                    for slot in (0, 1)
                ),
            )
    return out


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))
    before = snapshot(doc)
    nodes = doc.setdefault('EventNodes', [])
    known_nodes = {node['Id'] for node in nodes}
    migrated = 0
    for room in doc['UnknownRooms']:
        if 'Entry' in room:
            continue
        node_id = room['Id']
        if node_id in known_nodes:
            raise SystemExit('node id %r already exists -- refusing to overwrite' % node_id)
        options = []
        for slot in (0, 1):
            label = room.pop('Label%d' % slot, '')
            effects = room.pop('Effects%d' % slot, None) or []
            asc = room.pop('Effects%dAsc' % slot, None) or []
            option = {'Label': label, 'Effects': effects, 'Next': ''}
            if asc:
                option['EffectsAsc'] = asc
            options.append(option)
        node = {'Id': node_id, 'TextKey': room.pop('DescriptionKey', ''), 'Options': options}
        nodes.append(node)
        room['Entry'] = node_id
        migrated += 1
    after = snapshot(doc)
    assert before == after, (
        'migration changed semantics: %s'
        % [k for k in before if before[k] != after.get(k)]
    )
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('§278 migration: %d room(s) rewritten, %d node(s) total, semantics identical'
          % (migrated, len(nodes)))


main()

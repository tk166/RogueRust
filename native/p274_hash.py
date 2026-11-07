"""§274 第三批：`DeckChange::TransformAndUpgrade` 的三处映射 + 拾取队列进指纹 + 存档 v7。

⚠️ 本文件用 raw string：`\\n` 必须是 Rust 源码里的两个字符。heredoc 会把它们吃掉（FACTS §161.5）。
"""
import io

HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'
ARCH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


HASH_FOLLOW_OLD = r'''        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Transform)) => {
            "transform"
        }
    }
}'''

HASH_FOLLOW_NEW = r'''        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Transform)) => {
            "transform"
        }
        // §274：`astrolabe` 用得到它（恩惠里目前不用，但映射要穷尽 —— 这是编译器的闸门）。
        Some(crate::state::BlessingFollowUp::Deck(
            crate::state::DeckChange::TransformAndUpgrade,
        )) => "transform_and_upgrade",
    }
}'''

HASH_CHANGE_OLD = '''        Some(crate::state::DeckChange::Transform) => "transform",
    }
}'''

HASH_CHANGE_NEW = '''        Some(crate::state::DeckChange::Transform) => "transform",
        Some(crate::state::DeckChange::TransformAndUpgrade) => "transform_and_upgrade",
    }
}'''

PICKUP_OLD = r'''    writer
        .str("tiny_chest=")
        .u32(u32::from(state.tiny_chest_rooms()))
        .str("\n");'''

PICKUP_NEW = r'''    writer
        .str("tiny_chest=")
        .u32(u32::from(state.tiny_chest_rooms()))
        .str("\n");
    // §274：拾取时欠着的牌组编辑（`empty_cage` / `astrolabe`）。不进指纹的话，
    // "还欠 2 次"与"还欠 1 次"会哈希相同 —— 而那正是这两件遗物的全部区别。
    writer
        .str("pickup=")
        .str(deck_change_code(state.pickup_change()))
        .str("/")
        .u32(u32::from(state.pickup_picks()))
        .str("\n");'''


def main():
    h = io.open(HASH, encoding='utf-8').read()
    h = patch(h, HASH_FOLLOW_OLD, HASH_FOLLOW_NEW, 'hash follow code')
    h = patch(h, HASH_CHANGE_OLD, HASH_CHANGE_NEW, 'hash deck change code')
    h = patch(h, PICKUP_OLD, PICKUP_NEW, 'hash pickup')
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(h)

    a = io.open(ARCH, encoding='utf-8').read()
    a = patch(a, '''        DeckChange::Transform => 3,
    }''', '''        DeckChange::Transform => 3,
        // §274
        DeckChange::TransformAndUpgrade => 4,
    }''', 'archive to_u8')
    a = patch(a, '''        3 => DeckChange::Transform,
        _ => return Err(ArchiveError::BadField("deck_change")),''',
              '''        3 => DeckChange::Transform,
        // §274
        4 => DeckChange::TransformAndUpgrade,
        _ => return Err(ArchiveError::BadField("deck_change")),''', 'archive from_u8')
    a = patch(a, '/// §272：5 → 6（`unknown_room` + `tiny_chest_rooms`）。',
              '/// §274：6 → 7（`pickup_change` + `pickup_picks`）。\n'
              '/// §272：5 → 6（`unknown_room` + `tiny_chest_rooms`）。', 'version doc')
    a = patch(a, 'const VERSION: u8 = 6;', 'const VERSION: u8 = 7;', 'version')
    a = patch(a, '    let tiny_chest_rooms = reader.byte()?;',
              '''    let tiny_chest_rooms = reader.byte()?;
    // §274
    let pickup_change = reader.byte()?;
    let pickup_picks = reader.byte()?;''', 'archive read')
    a = patch(a, '    writer.byte(state.tiny_chest_rooms)?;',
              '''    writer.byte(state.tiny_chest_rooms)?;
    // §274：哪一种编辑（0 = 不欠）+ 还欠几次。
    writer.byte(match state.pickup_change() {
        None => 0u8,
        Some(change) => deck_change_to_u8(change),
    })?;
    writer.byte(state.pickup_picks())?;''', 'archive write')
    a = patch(a, '    restored.tiny_chest_rooms = tiny_chest_rooms;',
              '''    restored.tiny_chest_rooms = tiny_chest_rooms;
    // §274：0 = 不欠；其余必须与 `deck_change_to_u8` 对得上（读到 5 是**存档坏了**）。
    restored.pickup_change = if pickup_change == 0 {
        None
    } else {
        Some(deck_change_from_u8(pickup_change)?)
    };
    restored.pickup_picks = pickup_picks;''', 'archive restore')
    io.open(ARCH, 'w', encoding='utf-8', newline='\n').write(a)
    print('hash + archive v7')


main()

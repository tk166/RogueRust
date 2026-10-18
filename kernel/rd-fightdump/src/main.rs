//! `rd-fightdump` —— 让内核**第一次真的跑完一局战斗**，并把它的一步一步打出来。
//!
//! # 它是什么 / 不是什么
//!
//! 它**不是**测试（测试在 `rd-core/src/battle.rs` 里，那些才是闸门）；它是**诊断**：
//! 用真实内容镜像建一局真战斗，按写死的脚本跑完，把每一步的
//! `(round, turn, problems)` 与**每一步之后的 `write_hash_input` SHA-256** 打出来。
//!
//! 它的两个用途，正好对应规格书 `docs/spec/fight-driver.md` §4 的两阶段：
//!
//! 1. **自证**（阶段 1）：同一份输出跑两遍必须逐字节相同；换 seed 必须改变哈希序列。
//! 2. **对拍**（阶段 2）：以后 C# oracle 按同一张卡 author 同一局，把两边的
//!    `step=… hash=…` 行喂给同一个 python 脚本按 key 比对。所以格式是**一行一个键值**，
//!    键名固定、顺序固定、不打印任何人类专供的排版。
//!
//! # 输出格式（固定，别改成好看的）
//!
//! ```text
//! image=<路径> bytes=<n> cards=<n> enemy_actions=<n> encounters=<n>
//! gaps=<四条已知偏差，见 battle.rs 的 FROZEN_GAP_*>
//! scenario=<名字> combat=<id> seed=<n> shuffle=<true|false> hero=<id>/<hp> enemies=<id>/<hp>,…
//!                 deck=<卡:id>,… energy=<当前>/<上限>
//! step=<i> round=<r> turn=<t> problems=<n> kinds=<A,B|none> hero_hp=<n> enemy_hp=<n,…>
//!       chain=<n> exec=<n> hash=<64 hex>
//! …
//! final result=<Ongoing|Victory|Defeat|Draw|Aborted> steps=<n> round=<r> turn=<t> random_step=<n>
//!       hero_hp=<n> energy=<n> hand=<n> draw=<n> discard=<n> exhaust=<n>
//! ```
//!
//! `--cards` 把场景表换成**逐卡**表：镜像里每一张 `CARD` 一局固定形状的短战斗（牌组里只有它，
//! 脚本只有"打出它"），头行的键名换成 `card=<卡 id> index=<行号>`，其余逐字节相同。
//! 一条卡一行、一张都不跳过。它的对拍目标不是整局语义，而是**每张卡自己的效果**
//! （`native/fight_diff.py` 的 `CARD_DIFF`）。
//!
//! `--cards-multi` 是同一张表的**跨回合**版本：每张卡两个变体、每个变体 4 步
//! （`cardmulti=<卡 id> index=<行号> variant=<0|1>`）。它管的是"打一步"照不到的那一半语义：
//! 回合结束弃手牌、下回合抽回来、抽牌堆空时重洗（`random_step` 会前进一格）、回合开始的补能、
//! 以及敌人真的出手。头行的 `deck` / `energy` 与 `CARD_MULTI_*` 常量一一对应。
//!
//! `--enemies` 把场景表换成**逐敌人动作**表：镜像里 394 条 `EACT` 各一局（该动作所属敌人 + 英雄，
//! 牌组为空），头行键名 `enemy=<动作 id> index=<行号>`。动作的归属敌人取 id 前缀
//! （`<敌人>.<动作>`）—— 前缀是不是真的敌人、与 `ENCT` 的 `Actions` 是否一致，由
//! `native/fight_diff.py` 的闸门从镜像核对。
//!
//! `--one-turn` 把场景表换成**多敌人 / 一步一回合**的小表（头行键名 `oneturn=<场景名>`）。
//! 它专门演示 `Step::EndOneTurn`（"只结束一个回合，让下一个存活战斗员上场"）：
//! 两个敌人时一步只能让**一个**敌人出手。⚠️ 这一层**没有 C# 对拍物**（参考实现的三个脚本步
//! 都带着目标，没有"只推一步"这种步），所以它是**自证层**：跑两遍必须逐字节相同。
//! 它也因此**不**进默认场景表 —— 默认表由 `native/fight_diff.py` 的 `FIGHT_DIFF` 逐键比对，
//! 多一个 C# 侧没有的场景名会让那条闸门整体红。
//!
//! `round`/`turn` 是**执行前**的值（`ScenarioRunner.cs:106,140,164,203`）；
//! `hash` 是**执行后**的状态指纹。两者一起才能定位"是哪一步把状态推歪了"。
//!
//! # 一行一步为什么是每步单独调一次 `run_fight`
//!
//! `FightOutcome` 没有游标字段，所以"每步之后立刻取指纹"只能一步一喂。这**不改变语义**：
//! 外壳每一步都重新读 `state.result` 与英雄状态（`ScenarioRunner.cs:40-51`），
//! 所以 N 次 1 步调用与 1 次 N 步调用给出逐字节相同的状态。
//!
//! # 退出码
//!
//! * `0` —— 所有场景都跑完；
//! * `1` —— 有场景**真的坏了**（`BattleError`；不是 `Problem`，那些是观测）；
//! * `2` —— 镜像读不到 / 解析不了（打印路径与生成命令）。

use std::env;
use std::fs;
use std::process::ExitCode;

use rd_core::battle::{
    build_fight, run_fight, standard_turn_config, DeckEntry, FightOutcome, FightPlan,
    PlanCombatant, Step, DEVIATIONS,
};
use rd_core::content::{Content, Table};
use rd_core::hash::{sha256, to_hex_lower};
use rd_core::host::Host;
use rd_core::snapshot;
use rd_core::state::{CardZone, CombatId, CombatResult, CombatState, CombatantId, ResourceId};
use rd_core::writer::TextWriter;

/// 指纹缓冲。状态 171 KB，规范文本实测 ~3 KB；1 MiB 是"怎么都不会撞上"的余量。
/// 溢出**必须**响亮 —— 一个被截断的指纹看起来仍然像一个指纹。
const HASH_BUFFER: usize = 1 << 20;

/// 镜像的默认位置（`env!` 定在编译期，跟 `exec.rs` 的 `core_image()` 同一个取法）。
fn default_image_path() -> String {
    let root = env!("CARGO_MANIFEST_DIR");
    std::path::Path::new(root)
        .join("../../tools/contentc/out/content.core.rdcf")
        .display()
        .to_string()
}

fn main() -> ExitCode {
    // 参数：`rd-fightdump [镜像路径] [--cards|--cards-multi|--enemies|--one-turn] [--text]`。
    // 四种模式**互斥**（一次只跑一种）：它们的输出是给 `native/fight_diff.py` 的不同闸门按不同
    // 块键（`card=` / `cardmulti=` / `enemy=` / `oneturn=`）分块解析的，混跑只会让解析器更脆。
    let mut raw: Vec<String> = env::args().skip(1).collect();
    let cards_mode = raw.iter().any(|arg| arg == "--cards");
    let cards_multi_mode = raw.iter().any(|arg| arg == "--cards-multi");
    let enemies_mode = raw.iter().any(|arg| arg == "--enemies");
    let one_turn_mode = raw.iter().any(|arg| arg == "--one-turn");
    let text_mode = raw.iter().any(|arg| arg == "--text");
    raw.retain(|arg| {
        arg != "--cards"
            && arg != "--cards-multi"
            && arg != "--enemies"
            && arg != "--one-turn"
            && arg != "--text"
    });
    let path = raw.first().cloned().unwrap_or_else(default_image_path);
    if [cards_mode, cards_multi_mode, enemies_mode, one_turn_mode]
        .iter()
        .filter(|on| **on)
        .count()
        > 1
    {
        eprintln!(
            "--cards / --cards-multi / --enemies / --one-turn 一次只能给一个：它们是四种不同的场景表"
        );
        return ExitCode::from(2);
    }

    let blob = match fs::read(&path) {
        Ok(blob) => blob,
        Err(e) => {
            eprintln!(
                "RDCF 镜像缺失或读不到：{path}\n  {e}\n  \
                 它是 tools/contentc 的构建产物，生成命令：\n    \
                 python tools/contentc/compile.py\n  \
                 （同时写出 tools/contentc/out/content.rdcf 与 content.core.rdcf）"
            );
            return ExitCode::from(2);
        }
    };
    let content = match Content::parse(&blob) {
        Ok(content) => content,
        Err(e) => {
            eprintln!("RDCF 镜像解析失败：{path}\n  {e:?}");
            return ExitCode::from(2);
        }
    };
    // 打出来的是规范化路径（`..` 折叠掉）；折叠不了就原样打 —— 两个都对，只是好看一点。
    // Windows 的 `canonicalize` 会加 `\\?\` 前缀，去掉它（那是 API 细节，不是路径的一部分）。
    let shown = fs::canonicalize(&path).unwrap_or_else(|_| std::path::PathBuf::from(&path));
    let shown = shown.display().to_string();
    let shown = shown.strip_prefix(r"\\?\").unwrap_or(&shown);

    println!(
        "image={shown} bytes={} cards={} enemy_actions={} encounters={}",
        blob.len(),
        content.rows(Table::Card).remaining(),
        content.rows(Table::EnemyAction).remaining(),
        content.rows(Table::Encounter).remaining(),
    );
    // 仍在的偏差先打出来：读输出的人第一眼就该知道"这份输出是在什么偏差下产生的"。
    println!("deviations={}", DEVIATIONS.join(","));

    let table = if cards_mode {
        match card_scenarios(&content) {
            Ok(table) => table,
            Err(why) => {
                eprintln!("逐卡场景表建不起来：{why}");
                return ExitCode::from(2);
            }
        }
    } else if cards_multi_mode {
        match card_multi_scenarios(&content) {
            Ok(table) => table,
            Err(why) => {
                eprintln!("逐卡多层场景表建不起来：{why}");
                return ExitCode::from(2);
            }
        }
    } else if enemies_mode {
        match enemy_scenarios(&content) {
            Ok(table) => table,
            Err(why) => {
                eprintln!("逐敌人动作场景表建不起来：{why}");
                return ExitCode::from(2);
            }
        }
    } else if one_turn_mode {
        one_turn_scenarios()
    } else {
        scenarios()
    };
    for spec in &table {
        if let Err(why) = run_scenario(&content, spec, text_mode) {
            eprintln!("{} {} 失败：{why}", spec.label, spec.name);
            return ExitCode::from(1);
        }
    }
    ExitCode::SUCCESS
}

/// 一个写死的场景（蓝图 + 脚本）。
///
/// `label` 是那一行的键名：整局场景是 `scenario=`，逐卡场景是 `card=`。两种都走同一个
/// [`run_scenario`]，因为"蓝图 + 脚本 + 一步一步取指纹"这件事对两者完全一样 ——
/// 多一条并行的执行路径就多一处会悄悄不一致的地方。
struct Scenario<'a> {
    label: &'static str,
    /// 场景名（整局）/ 卡定义 id（逐卡、逐卡多层）/ 敌人动作 id（逐敌人动作）。
    name: &'a str,
    /// 镜像表的行号（`CARD` / `EACT`）：闸门用它把三边的顺序钉在一起。整局场景没有行号。
    row_index: Option<u32>,
    /// 只给逐卡多层：变体号。头行会多打一格 `variant=<n>`。
    variant: Option<u32>,
    combat: &'a str,
    seed: i32,
    hero: PlanCombatant<'a>,
    enemies: Vec<PlanCombatant<'a>>,
    deck: Vec<DeckEntry<'a>>,
    shuffle: bool,
    /// 英雄的开局资源 `(当前, 上限)`：整局场景是 3/3，逐卡场景给到 10/10
    /// （逐卡考的是卡本身，不该被费用挡住；镜像里最贵的卡是 2）。
    energy: (i32, i32),
    steps: Vec<Step<'a>>,
}

/// 逐卡场景的固定形状。**C# oracle 的 `rd_oracle_card_run` 必须 author 同一份**，
/// 两边的 `card=` 头行由 `native/fight_diff.py` 逐键比对，所以这里的数字不是"随手取的"。
const CARD_COMBAT: &str = "card_diff";
const CARD_SEED: i32 = 1;
const CARD_HERO: &str = "hero";
const CARD_HERO_HP: i32 = 70;
const CARD_ENEMY: &str = "queue_imp";
/// 高到一张卡打不死（镜像里单张卡的最大输出是 `dealDamage 24` 与
/// `paperwork stacks × 5`，都没有 500 的零头）：逐卡考的是"这张卡做了什么"，
/// 不是"敌人死没死"。真正考终局的那一局是整局场景里的 `finish`/`dot_kill`。
const CARD_ENEMY_HP: i32 = 500;
const CARD_ENERGY: i32 = 10;
/// 标准包的补能幅度（`StandardCombatPackage.cs:124`）。逐卡场景只打一步、不跨回合，
/// 所以它今天不生效；写在这里是为了与 C# 侧"只装标准包、不另注册补能"完全对齐。
const CARD_ENERGY_REFILL: i32 = 3;

/// 逐卡场景表：镜像里**每一张**卡一局，牌组里只有它自己，脚本只有"打出它"。
///
/// 卡的程序**不进哈希**（进哈希的是卡定义 id），所以两侧必须打同一张卡、同一段程序 ——
/// Rust 侧的程序来自镜像本身，C# 侧按 `native/card_specs.json` author，闸门在
/// `native/fight_diff.py` 里逐字段核对。这里不挑卡：**一张都不许跳过**。
fn card_scenarios<'a>(content: &Content<'a>) -> Result<Vec<Scenario<'a>>, String> {
    let total = content.rows(Table::Card).remaining();
    if total == 0 {
        return Err("镜像里一张卡都没有 —— 逐卡对拍无事可做（这不是『通过』）".to_string());
    }
    let mut out = Vec::with_capacity(total as usize);
    for index in 0..total {
        let card = content
            .entity_id(Table::Card, index)
            .ok_or_else(|| format!("CARD[{index}] 取不到 Id（镜像形态变了？）"))?;
        out.push(Scenario {
            label: "card",
            name: card,
            row_index: Some(index),
            variant: None,
            combat: CARD_COMBAT,
            seed: CARD_SEED,
            hero: PlanCombatant {
                id: CARD_HERO,
                max_health: CARD_HERO_HP,
            },
            enemies: vec![PlanCombatant {
                id: CARD_ENEMY,
                max_health: CARD_ENEMY_HP,
            }],
            deck: vec![DeckEntry { card, count: 1 }],
            shuffle: false,
            energy: (CARD_ENERGY, CARD_ENERGY),
            steps: vec![Step::HeroPlays {
                card,
                target: Some(CARD_ENEMY),
            }],
        });
    }
    Ok(out)
}

/// 逐卡多层场景的固定形状（`CARD_MULTI`）。三份常量（Rust / C# / `native/fight_diff.py`）
/// 描述同一局战斗，改一处另外两处就红。
///
/// 为什么与逐卡那层不同形：
/// * 能量 **3/3**（不是 10/10）—— 跨回合才会**补能**，而 10/10 的池子补到 10 是恒等，
///   那个机制就永远是绿的；镜像里最贵的卡是 2，所以 3 还是够付。
/// * 牌组给 **2 张**（变体 A）/ **1 张**（变体 B）—— 一张卡一张牌组，第二回合抽牌时
///   抽牌堆必然空、弃牌堆非空 ⇒ 真的走一次重洗（`random_step` 前进一格）。
const CARD_MULTI_COMBAT: &str = "card_multi";
const CARD_MULTI_SEED: i32 = 1;
const CARD_MULTI_HERO: &str = "hero";
const CARD_MULTI_HERO_HP: i32 = 70;
const CARD_MULTI_ENEMY: &str = "queue_imp";
const CARD_MULTI_ENEMY_HP: i32 = 500;
const CARD_MULTI_ENERGY: i32 = 3;
/// 逐卡多层用的敌人动作：让"敌人真的出手"这一格有内容（镜像里它就是对英雄 8 点）。
const CARD_MULTI_ACTION: &str = "queue_imp.desk_jab";

/// 变体 A：打出它 → 结束回合 → 转过一整轮 → 再打出它（4 步）。
const MULTI_VARIANT_PLAY_AGAIN: u32 = 0;
/// 变体 B：打出它 → 结束回合 → 敌人动作 → 转回英雄回合（4 步）。
const MULTI_VARIANT_ENEMY_THEN_WRAP: u32 = 1;
const MULTI_VARIANTS: u32 = 2;

/// 逐卡多层：镜像里**每一张**卡 × 2 个变体，每个变体 4 步，跨过至少一个回合边界。
///
/// 与 `--cards` 那张表的关系：那一层问"这张卡做了什么"（1 步），这一层问"跨回合之后两侧
/// 还一样吗"（丢弃手牌 / 抽回来 / 重洗 / 补能 / 敌人出手 / DoT tick）。一张卡都不许跳过。
fn card_multi_scenarios<'a>(content: &Content<'a>) -> Result<Vec<Scenario<'a>>, String> {
    let total = content.rows(Table::Card).remaining();
    if total == 0 {
        return Err("镜像里一张卡都没有 —— 逐卡多层对拍无事可做（这不是『通过』）".to_string());
    }
    let mut out = Vec::with_capacity(total as usize * MULTI_VARIANTS as usize);
    for index in 0..total {
        let card = content
            .entity_id(Table::Card, index)
            .ok_or_else(|| format!("CARD[{index}] 取不到 Id（镜像形态变了？）"))?;
        for variant in 0..MULTI_VARIANTS {
            let play = Step::HeroPlays {
                card,
                target: Some(CARD_MULTI_ENEMY),
            };
            let (deck, steps) = match variant {
                MULTI_VARIANT_PLAY_AGAIN => (
                    // 两张：第一回合抽到两张、打掉一张，第二回合重洗后还能再打一张。
                    vec![DeckEntry { card, count: 2 }],
                    vec![play, Step::HeroEndsTurn, Step::NextRound, play],
                ),
                MULTI_VARIANT_ENEMY_THEN_WRAP => (
                    // 一张：第二回合的重洗**取决于这张卡落在哪个区**（弃牌堆 ⇒ 重洗，
                    // 消耗堆 ⇒ 不重洗）。镜像里 48 张弃牌堆 / 14 张消耗堆，这条分岔真的有内容。
                    vec![DeckEntry { card, count: 1 }],
                    vec![
                        play,
                        Step::HeroEndsTurn,
                        Step::EnemyActs {
                            enemy: CARD_MULTI_ENEMY,
                            action: CARD_MULTI_ACTION,
                            target: Some(CARD_MULTI_HERO),
                        },
                        Step::NextRound,
                    ],
                ),
                _ => return Err(format!("未知的逐卡多层变体号 {variant}（0..{MULTI_VARIANTS} 之外）")),
            };
            out.push(Scenario {
                label: "cardmulti",
                name: card,
                row_index: Some(index),
                variant: Some(variant),
                combat: CARD_MULTI_COMBAT,
                seed: CARD_MULTI_SEED,
                hero: PlanCombatant {
                    id: CARD_MULTI_HERO,
                    max_health: CARD_MULTI_HERO_HP,
                },
                enemies: vec![PlanCombatant {
                    id: CARD_MULTI_ENEMY,
                    max_health: CARD_MULTI_ENEMY_HP,
                }],
                deck,
                shuffle: false,
                energy: (CARD_MULTI_ENERGY, CARD_MULTI_ENERGY),
                steps,
            });
        }
    }
    Ok(out)
}

/// 逐敌人动作场景的固定形状（`ENEMY_DIFF`）。
///
/// 牌组**为空**：这一层问的是"这条动作做了什么"，英雄有没有牌无关；空牌组也让 C# 侧不必
/// author 任何一张卡。能量 3/3 与英雄 70 点沿用整局那层的数字。
const ENEMY_COMBAT: &str = "enemy_diff";
const ENEMY_SEED: i32 = 1;
const ENEMY_HERO: &str = "hero";
const ENEMY_HERO_HP: i32 = 70;
/// 敌人在这一层是"靶子也是施法者"：够高到不吃一条动作的自伤就死（镜像里最高单次 24）。
const ENEMY_HP: i32 = 60;
const ENEMY_ENERGY: i32 = 3;

/// 逐敌人动作：镜像里**每一条** `EACT` 一局。
///
/// 脚本两步：结束英雄回合（把行动位让出去）+ 让它执行这条动作。归属敌人取动作 id 的前缀
/// `<敌人>.<动作>` —— 内核只有扁平的 `EACT` 表，读不到 `ENCT` 里嵌套的敌人记录；
/// 前缀到底是不是真的敌人、与 `ENCT` 的 `Actions` 是否一致，由 `native/fight_diff.py`
/// 的闸门从镜像核对（核不上就整体红，而不是让这一层安静地打错敌人）。
fn enemy_scenarios<'a>(content: &Content<'a>) -> Result<Vec<Scenario<'a>>, String> {
    let total = content.rows(Table::EnemyAction).remaining();
    if total == 0 {
        return Err("镜像里一条敌人动作都没有 —— 这一层无事可做（这不是『通过』）".to_string());
    }
    let mut out = Vec::with_capacity(total as usize);
    for index in 0..total {
        let action = content
            .entity_id(Table::EnemyAction, index)
            .ok_or_else(|| format!("EACT[{index}] 取不到 Id（镜像形态变了？）"))?;
        let (enemy, _) = action
            .split_once('.')
            .ok_or_else(|| format!("敌人动作 `{action}` 的 id 里没有 `.`，推不出归属敌人"))?;
        out.push(Scenario {
            label: "enemy",
            name: action,
            row_index: Some(index),
            variant: None,
            combat: ENEMY_COMBAT,
            seed: ENEMY_SEED,
            hero: PlanCombatant {
                id: ENEMY_HERO,
                max_health: ENEMY_HERO_HP,
            },
            enemies: vec![PlanCombatant {
                id: enemy,
                max_health: ENEMY_HP,
            }],
            deck: Vec::new(),
            shuffle: false,
            energy: (ENEMY_ENERGY, ENEMY_ENERGY),
            steps: vec![
                Step::HeroEndsTurn,
                Step::EnemyActs {
                    enemy,
                    action,
                    target: Some(ENEMY_HERO),
                },
            ],
        });
    }
    Ok(out)
}

/// `--one-turn` 那一层的场景表：**多敌人 / 一步一回合**（`Step::EndOneTurn` 的演示与回归）。
///
/// 为什么单独一张表而不是塞进默认表：
/// * 默认表的每个场景名都要在 C# oracle 的场景表里存在（`native/fight_diff.py` 的
///   `collect()` 找不到就 `GateFailure`），而参考实现的三个脚本步都得带目标，
///   没有"只结束一个回合"这种步 ⇒ **这一层永远不可能有 C# 对拍物**；
/// * 所以它是**自证层**：同一份输出跑两遍必须逐字节相同（终局语义由
///   `battle.rs` 的 `one_end_one_turn_step_puts_exactly_one_combatant_on_stage` 钉住）。
///
/// 两个场景：
/// * `two_enemies` —— 一步只让**一个**敌人上场：`EndOneTurn` → `queue_imp` 出手 8 点 →
///   `EndOneTurn` → `stamp_goblin` 出手 5 点。如果 `EndOneTurn` 退化成 `NextRound`，
///   第二次 `EndOneTurn` 会绕过 goblin 直接回到英雄（第 3 步的 `round`/`turn`/`hero_hp` 全变）。
/// * `dot_kill` —— 推进到"下一个战斗员的回合开场"时战斗就结束：停在那一格，不继续推。
fn one_turn_scenarios() -> Vec<Scenario<'static>> {
    let hero = PlanCombatant {
        id: "hero",
        max_health: 70,
    };
    let imp = PlanCombatant {
        id: "queue_imp",
        max_health: 22,
    };
    let goblin = PlanCombatant {
        id: "stamp_goblin",
        max_health: 22,
    };
    vec![
        Scenario {
            label: "oneturn",
            name: "two_enemies",
            row_index: None,
            variant: None,
            combat: "one_turn_two_enemies",
            seed: 1,
            hero,
            enemies: vec![imp, goblin],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 2,
            }],
            shuffle: false,
            energy: (3, 3),
            // 4 步 ⇒ 行动位走 英雄 → imp → goblin（`turn` 1/2/3）。
            steps: vec![
                Step::EndOneTurn,
                Step::EnemyActs {
                    enemy: "queue_imp",
                    action: "queue_imp.desk_jab",
                    target: Some("hero"),
                },
                Step::EndOneTurn,
                Step::EnemyActs {
                    enemy: "stamp_goblin",
                    action: "stamp_goblin.rubber_stamp_rush",
                    target: Some("hero"),
                },
            ],
        },
        Scenario {
            label: "oneturn",
            name: "dot_kill",
            row_index: None,
            variant: None,
            combat: "one_turn_dot_kill",
            seed: 1,
            hero,
            // 5 血 + `permit_a38` 的 5 层 `paperwork`（带 `damage_over_time`）⇒
            // 它的回合**一开始**就被 DoT 打死，而它是最后一个敌人 ⇒ `Victory`。
            enemies: vec![PlanCombatant {
                id: "queue_imp",
                max_health: 5,
            }],
            deck: vec![DeckEntry {
                card: "permit_a38",
                count: 5,
            }],
            shuffle: false,
            energy: (3, 3),
            steps: vec![
                Step::HeroPlays {
                    card: "permit_a38",
                    target: Some("queue_imp"),
                },
                Step::EndOneTurn,
            ],
        },
    ]
}

/// 写死的场景表。
///
/// 用的卡/敌人/动作都是镜像里真有的（`paper_cut` / `permit_a38` / `queue_imp` /
/// `queue_imp.desk_jab`），血量与牌组是这里 authored 的（参考的蓝图也这么写）。
fn scenarios() -> Vec<Scenario<'static>> {
    let hero = PlanCombatant {
        id: "hero",
        max_health: 70,
    };
    let imp = PlanCombatant {
        id: "queue_imp",
        max_health: 22,
    };
    let play = Step::HeroPlays {
        card: "paper_cut",
        target: Some("queue_imp"),
    };
    vec![
        // ① 打到终局：3 张纸片（18）+ 过一轮 + 1 张（24 ≥ 22）⇒ 敌人死。
        Scenario {
            label: "scenario",
            name: "finish",
            row_index: None,
            variant: None,
            combat: "city_easy_01",
            seed: 7,
            hero,
            enemies: vec![imp],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 12,
            }],
            shuffle: true,
            energy: (3, 3),
            steps: vec![play, play, play, Step::NextRound, play],
        },
        // ② 敌人真的出手：`queue_imp.desk_jab` = `dealDamage 8 → sel.eventTarget`。
        Scenario {
            label: "scenario",
            name: "enemy_hits",
            row_index: None,
            variant: None,
            combat: "enemy_hits",
            seed: 1,
            hero,
            enemies: vec![imp],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 2,
            }],
            shuffle: false,
            energy: (3, 3),
            steps: vec![
                Step::HeroEndsTurn,
                Step::EnemyActs {
                    enemy: "queue_imp",
                    action: "queue_imp.desk_jab",
                    target: Some("hero"),
                },
            ],
        },
        // ③ 观测面：不在手里的卡 / 打出去了 / 轮到英雄时叫敌人出手（两条塌成一个类别）。
        Scenario {
            label: "scenario",
            name: "refusals",
            row_index: None,
            variant: None,
            combat: "refusals",
            seed: 1,
            hero,
            enemies: vec![imp],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 2,
            }],
            shuffle: false,
            energy: (3, 3),
            steps: vec![
                Step::HeroPlays {
                    card: "strong_binder",
                    target: Some("queue_imp"),
                },
                play,
                play,
                Step::EnemyActs {
                    enemy: "queue_imp",
                    action: "queue_imp.desk_jab",
                    target: Some("hero"),
                },
            ],
        },
        // ④ DoT 在敌人自己的回合里把它打死 ⇒ 下一步 `EnemyNotAlive`（英雄一滴血不掉）。
        Scenario {
            label: "scenario",
            name: "dot_kill",
            row_index: None,
            variant: None,
            combat: "dot_kill",
            seed: 1,
            hero,
            enemies: vec![
                PlanCombatant {
                    id: "queue_imp",
                    max_health: 5,
                },
                PlanCombatant {
                    id: "stamp_goblin",
                    max_health: 22,
                },
            ],
            deck: vec![DeckEntry {
                card: "permit_a38",
                count: 5,
            }],
            shuffle: false,
            energy: (3, 3),
            steps: vec![
                Step::HeroPlays {
                    card: "permit_a38",
                    target: Some("queue_imp"),
                },
                Step::HeroEndsTurn,
                Step::EnemyActs {
                    enemy: "queue_imp",
                    action: "queue_imp.desk_jab",
                    target: Some("hero"),
                },
            ],
        },
    ]
}

fn run_scenario(content: &Content<'_>, spec: &Scenario<'_>, text_mode: bool) -> Result<(), String> {
    let hero_id = CombatantId::new(spec.hero.id).map_err(|e| format!("{e}"))?;
    let energy = ResourceId::new("standard.energy").map_err(|e| format!("{e}"))?;
    let (energy_current, energy_max) = spec.energy;
    let resources = [(energy, energy_current, Some(energy_max))];
    let refills = [(energy, CARD_ENERGY_REFILL)];
    // 蓝图里的抽牌数从驱动的标准配置里取（**不是**在 CLI 里再写一遍 5）——
    // 2026-10-18 的裁决 1 之后这个字段是真的会生效的，写死在这里就等于绕过它。
    let standard = standard_turn_config().map_err(|e| format!("{e:?}"))?;
    let plan = FightPlan {
        combat_id: spec.combat,
        seed: spec.seed,
        hero: spec.hero,
        enemies: &spec.enemies,
        deck: &spec.deck,
        cards_drawn_per_turn: standard.draw_per_turn,
        shuffle_draw_pile_on_start: spec.shuffle,
        resources: &resources,
        turn_start_refills: &refills,
    };

    let mut state = CombatState::new(
        CombatId::new(spec.combat).map_err(|e| format!("{e}"))?,
        spec.seed,
    );
    let mut host = Host::new(content);
    build_fight(&mut state, content, &plan).map_err(|e| format!("build_fight: {e:?}"))?;

    // ── 场景头（一行全是 key=value：这一局的蓝图长什么样）
    let mut plan_line = format!(
        "{}={} ",
        spec.label, spec.name
    );
    if let Some(index) = spec.row_index {
        plan_line.push_str(&format!("index={index} "));
    }
    if let Some(variant) = spec.variant {
        plan_line.push_str(&format!("variant={variant} "));
    }
    plan_line.push_str(&format!(
        "combat={} seed={} shuffle={} hero={}/{} enemies=",
        spec.combat, spec.seed, spec.shuffle, spec.hero.id, spec.hero.max_health
    ));
    for (index, enemy) in spec.enemies.iter().enumerate() {
        if index > 0 {
            plan_line.push(',');
        }
        plan_line.push_str(&format!("{}/{}", enemy.id, enemy.max_health));
    }
    plan_line.push_str(" deck=");
    for (index, entry) in spec.deck.iter().enumerate() {
        if index > 0 {
            plan_line.push(',');
        }
        plan_line.push_str(&format!("{}:{}", entry.card, entry.count));
    }
    plan_line.push_str(&format!(" energy={}:{energy_current}/{energy_max}", energy.as_str()));
    println!("{plan_line}");

    // ── 一步一步：一步一喂，好在每步之后取指纹
    for (index, step) in spec.steps.iter().enumerate() {
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            content,
            &plan,
            std::slice::from_ref(step),
            &mut host,
            &mut out,
        )
        .map_err(|e| format!("run_fight(step {index}): {e:?}"))?;
        let Some(outcome) = out.step(0) else {
            return Err(format!("step {index} 没有产出观测"));
        };

        let kinds = if out.problems_of(0).is_empty() {
            "none".to_string()
        } else {
            out.problems_of(0)
                .iter()
                .map(|p| p.wire_name())
                .collect::<Vec<_>>()
                .join(",")
        };
        let enemies = spec
            .enemies
            .iter()
            .map(|enemy| format!("{}", health(&state, enemy.id)))
            .collect::<Vec<_>>()
            .join(",");
        println!(
            "step={index} round={} turn={} problems={} kinds={} hero_hp={} enemy_hp={} chain={} exec={} hash={}",
            outcome.round,
            outcome.turn,
            outcome.problems,
            kinds,
            health(&state, spec.hero.id),
            enemies,
            state.next_effect_chain_number,
            state.next_program_execution_id,
            state_hash(&state)?,
        );
    }

    // ── 终局：12 个观测量（规格书 §4 阶段 2 的 (b) 那条路要的就是它们）
    println!(
        "final result={} steps={} round={} turn={} random_step={} hero_hp={} energy={} \
         hand={} draw={} discard={} exhaust={}",
        result_name(state.result),
        spec.steps.len(),
        state.current_round,
        state.current_turn,
        state.random_step,
        health(&state, spec.hero.id),
        energy_of(&state, &hero_id),
        zone_count(&state, &hero_id, CardZone::Hand),
        zone_count(&state, &hero_id, CardZone::DrawPile),
        zone_count(&state, &hero_id, CardZone::DiscardPile),
        zone_count(&state, &hero_id, CardZone::ExhaustPile),
    );
    // ── `--text`：规范文本一行一行打（每行加 `text=` 前缀，这样它仍然是 key=value 形状，
    //    解析器不必为它开一个"裸行"后门）。`text-end` 收尾，空文本也要打得出来。
    if text_mode {
        let canonical = hash_input_text(&state)?;
        for line in canonical.split('\n') {
            if !line.is_empty() {
                println!("text={line}");
            }
        }
        println!("text-end");
    }
    Ok(())
}

fn health(state: &CombatState, who: &str) -> i32 {
    CombatantId::new(who)
        .ok()
        .and_then(|id| state.combatant(&id).map(|c| c.health_current))
        .unwrap_or(-1)
}

fn energy_of(state: &CombatState, who: &CombatantId) -> i32 {
    state
        .combatant(who)
        .and_then(|c| {
            c.resources()
                .iter()
                .find(|p| p.key.as_str() == "standard.energy")
                .map(|p| p.pool.current)
        })
        .unwrap_or(-1)
}

fn zone_count(state: &CombatState, who: &CombatantId, zone: CardZone) -> usize {
    state.card_zones(who).map_or(0, |z| z.count(zone))
}

/// 状态的逐字节指纹（`snapshot::write_hash_input` 的文本 → SHA-256 → 小写 hex）。
fn state_hash(state: &CombatState) -> Result<String, String> {
    let text = hash_input_text(state)?;
    let mut hex = [0u8; 64];
    to_hex_lower(&mut hex, &sha256(text.as_bytes()));
    Ok(String::from_utf8(hex.to_vec()).expect("hex 一定是 ASCII"))
}

/// `snapshot::write_hash_input` 的规范文本（哈希喂的就是它）。
///
/// `--text` 模式把它一行一行打出来（`text=<行>`）。哈希不同时，把两侧的这段文本逐行对差，
/// 红的位置就从"64 个 hex 字符不一样"变成"`chain_num` 差 1"。
fn hash_input_text(state: &CombatState) -> Result<String, String> {
    let mut buf = vec![0u8; HASH_BUFFER];
    let mut w = TextWriter::new(&mut buf);
    snapshot::write_hash_input(&mut w, state);
    if w.overflowed() {
        return Err(format!("指纹缓冲 {HASH_BUFFER} B 不够"));
    }
    if w.is_empty() {
        return Err("指纹是空的".to_string());
    }
    Ok(w.as_str().to_string())
}

/// `CombatResult` 的名字（哈希用的是整数，这里只是给人/给 python 看的）。
fn result_name(result: CombatResult) -> &'static str {
    match result {
        CombatResult::Ongoing => "Ongoing",
        CombatResult::Victory => "Victory",
        CombatResult::Defeat => "Defeat",
        CombatResult::Draw => "Draw",
        CombatResult::Aborted => "Aborted",
    }
}

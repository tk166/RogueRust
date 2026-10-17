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
//! step=<i> round=<r> turn=<t> problems=<n> kinds=<A,B|none> hero_hp=<n> enemy_hp=<n,…> hash=<64 hex>
//! …
//! final result=<Ongoing|Victory|Defeat|Draw|Aborted> steps=<n> round=<r> turn=<t> random_step=<n>
//!       hero_hp=<n> energy=<n> hand=<n> draw=<n> discard=<n> exhaust=<n>
//! ```
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
    build_fight, run_fight, DeckEntry, FightOutcome, FightPlan, PlanCombatant, Step,
    FROZEN_GAP_HERO_ID, FROZEN_GAP_PROBLEM, FROZEN_GAP_RESULT, FROZEN_GAP_TURN_CONFIG,
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
    let args: Vec<String> = env::args().skip(1).collect();
    let path = args.first().cloned().unwrap_or_else(default_image_path);

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
    // 四条已知偏差先打出来：读输出的人第一眼就该知道"这份输出是在什么偏差下产生的"。
    println!(
        "gaps={FROZEN_GAP_TURN_CONFIG},{FROZEN_GAP_HERO_ID},{FROZEN_GAP_RESULT},{FROZEN_GAP_PROBLEM}"
    );

    for spec in scenarios() {
        if let Err(why) = run_scenario(&content, &spec) {
            eprintln!("scenario {} 失败：{why}", spec.name);
            return ExitCode::from(1);
        }
    }
    ExitCode::SUCCESS
}

/// 一个写死的场景（蓝图 + 脚本）。
struct Scenario {
    name: &'static str,
    combat: &'static str,
    seed: i32,
    hero: PlanCombatant<'static>,
    enemies: Vec<PlanCombatant<'static>>,
    deck: Vec<DeckEntry<'static>>,
    shuffle: bool,
    steps: Vec<Step<'static>>,
}

/// 写死的场景表。
///
/// 用的卡/敌人/动作都是镜像里真有的（`paper_cut` / `permit_a38` / `queue_imp` /
/// `queue_imp.desk_jab`），血量与牌组是这里 authored 的（参考的蓝图也这么写）。
fn scenarios() -> Vec<Scenario> {
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
            name: "finish",
            combat: "city_easy_01",
            seed: 7,
            hero,
            enemies: vec![imp],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 12,
            }],
            shuffle: true,
            steps: vec![play, play, play, Step::NextRound, play],
        },
        // ② 敌人真的出手：`queue_imp.desk_jab` = `dealDamage 8 → sel.eventTarget`。
        Scenario {
            name: "enemy_hits",
            combat: "enemy_hits",
            seed: 1,
            hero,
            enemies: vec![imp],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 2,
            }],
            shuffle: false,
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
            name: "refusals",
            combat: "refusals",
            seed: 1,
            hero,
            enemies: vec![imp],
            deck: vec![DeckEntry {
                card: "paper_cut",
                count: 2,
            }],
            shuffle: false,
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
            name: "dot_kill",
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

fn run_scenario(content: &Content<'_>, spec: &Scenario) -> Result<(), String> {
    let hero_id = CombatantId::new(spec.hero.id).map_err(|e| format!("{e}"))?;
    let energy = ResourceId::new("standard.energy").map_err(|e| format!("{e}"))?;
    let resources = [(energy, 3, Some(3))];
    let refills = [(energy, 3)];
    // 蓝图里这两个旋钮必须与驱动层会给的一致（`battle.rs` 的 `FROZEN_GAP_TURN_CONFIG`）：
    // 直接从驱动的标准配置里取，而不是在这里再写一遍 3 和 5。
    let standard = rd_core::battle::standard_turn_config().map_err(|e| format!("{e:?}"))?;
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
        "scenario={} combat={} seed={} shuffle={} hero={}/{} enemies=",
        spec.name, spec.combat, spec.seed, spec.shuffle, spec.hero.id, spec.hero.max_health
    );
    for (index, enemy) in spec.enemies.iter().enumerate() {
        if index > 0 {
            plan_line.push(',');
        }
        plan_line.push_str(&format!("{}/{}", enemy.id, enemy.max_health));
    }
    println!("{plan_line}");

    // ── 一步一步：一步一喂，好在每步之后取指纹
    for (index, step) in spec.steps.iter().enumerate() {
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            content,
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
            "step={index} round={} turn={} problems={} kinds={} hero_hp={} enemy_hp={} hash={}",
            outcome.round,
            outcome.turn,
            outcome.problems,
            kinds,
            health(&state, spec.hero.id),
            enemies,
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
    let mut buf = vec![0u8; HASH_BUFFER];
    let digest = {
        let mut w = TextWriter::new(&mut buf);
        snapshot::write_hash_input(&mut w, state);
        if w.overflowed() {
            return Err(format!("指纹缓冲 {HASH_BUFFER} B 不够"));
        }
        if w.is_empty() {
            return Err("指纹是空的".to_string());
        }
        sha256(w.as_str().as_bytes())
    };
    let mut hex = [0u8; 64];
    to_hex_lower(&mut hex, &digest);
    Ok(String::from_utf8(hex.to_vec()).expect("hex 一定是 ASCII"))
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

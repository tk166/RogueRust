"""§277 遭遇**组合槽**：一条遭遇记录可以是"从这里随机挑一只"。

## 为什么需要它

wiki 的 Act 1 硬池里有两条遭遇不是固定组合，而是**加权随机组合**：

* `Exordium Thugs`：第一个敌人 = Louse（任色）**或** Medium Slime（任型）；
  第二个 = Slaver（任色）**或** Cultist **或** Looter。
* `Exordium Wildlife`：第一个 = Fungi Beast 或 Jaw Worm；第二个 = Louse 或 Medium Slime。

枚举所有组合会变成 20 + 8 条遭遇（而且每条都要重写 HP/AI 队列）；旧内容的做法是"钉一种组合"
（`enc_small_slimes` / `enc_two_louses` 都是这么写的，并注明是偏差）。这一节把那条路补成机制：

## 形状

`ENCT.Enemies[]` 的每一条记录可以多一个可选键 `Candidates`（`F_TERMLIST` 的**对象列表**）：

```json
{"Candidates": [
  {"Id": "louse_red",    "Weight": 1, "MaxHealth": 10, "MaxHealthAsc": [{"AscensionMin": 7, "MaxHealth": 11}]},
  {"Id": "acid_slime_m", "Weight": 1, "MaxHealth": 28, "MaxHealthAsc": [{"AscensionMin": 7, "MaxHealth": 29}]}
], "Position": 0}
```

* 元素与 `Enemies` 的元素**同形** ⇒ 读的时候可以复用 `EnemySpec` 的 `id()/max_health()/
  max_health_asc()/spawn()/owner()`，不写第二套访问器；
* **HP 跟着候选走**：镜像里没有 `MON` 段（`Monsters` 只是建内容时的 roster），所以候选必须自带；
* `Weight` 是相对权重（整数，>0）。

## 掷骰放哪

建战斗时（`build_session_at_with`）用**这一场战斗的 `seed`** 派生：遭遇本身已经在
`RunStream::Combat` 上滚过一次，组合是"把这场战斗搭出来"的一部分（`Rolls` 初始化计数器也在这层），
所以它不开新流 —— 新开一条只会让 `run_hash` 的随机流计数多一格，而那一格不影响任何运行层状态。
判据是"同一个 seed 永远同一场"。
"""
import io

CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'


def patch(src, old, new, what, count=1):
    got = src.count(old)
    assert got == count, '%s: %d matches (want %d)' % (what, got, count)
    return src.replace(old, new)


CORE_ADD = '''    /// §277：这一条记录是不是**组合槽** —— `Candidates` 是一个加权候选表（对象列表），
    /// 建战斗时挑一个。缺键 / 空列表都表示"不是组合槽"（固定记录）。
    ///
    /// 元素的形状与 `Enemies` 的元素**相同**（`Id` + `MaxHealth` + `MaxHealthAsc` + `Weight`），
    /// 所以调用方可以用 [`Self::from_term`] 把一个候选当成一条普通记录来读。
    pub fn candidates(&self) -> Result<SlotList<'a>, EncounterError> {
        match self.list_any("Candidates") {
            Err(EncounterError::MissingField("Candidates"))
            | Err(EncounterError::WrongFieldKind("Candidates")) => Ok(SlotList {
                content: self.content,
                start: 0,
                count: 0,
                kind: F_TERMLIST,
            }),
            other => other,
        }
    }

    /// §277：把一个**列表元素**当成一条敌人记录。
    ///
    /// 存在的理由只有一个：`Candidates` 的元素与 `Enemies` 的元素同形，所以 `id()` /
    /// `max_health()` / `max_health_asc()` / `spawn()` / `owner()` 全部可以复用 —— 不写第二套
    /// 访问器（写两套就会漂，比如一边认 `MaxHealthAsc`、另一边忘了）。
    #[must_use]
    pub const fn from_term(content: &'a Content<'a>, term: u16) -> Self {
        Self { content, term }
    }

    /// §277：候选的相对权重（`Candidates` 元素的 `Weight`）。缺席 ⇒ `None`（调用方按 1 处理）。
    pub fn weight(&self) -> Result<Option<i32>, EncounterError> {
        match self.field_at("Weight") {
            Err(EncounterError::MissingField("Weight")) => Ok(None),
            Err(EncounterError::WrongFieldKind("Weight")) => {
                Err(EncounterError::WrongFieldKind("Weight"))
            }
            Ok((kind, at)) => {
                if kind != F_INT {
                    return Err(EncounterError::WrongFieldKind("Weight"));
                }
                match self.slot(at)? {
                    ABSENT_INT | NULL_INT => Ok(None),
                    other => Ok(Some(i32::from(other as i16))),
                }
            }
        }
    }

'''


def main():
    core = io.open(CORE, encoding='utf-8').read()
    anchor = '''    /// §208: `StartingBlock`（`F_INT`）—— 开局就挂在敌人身上的格挡。'''
    assert core.count(anchor) == 1
    core = core.replace(anchor, CORE_ADD + anchor)
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(core)
    print('rd-core: EnemySpec::{candidates, from_term, weight}')


main()

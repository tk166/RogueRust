// HUD：用 `@react-three/uikit`（plan P1 明确要求），**不碰 DOM**。
//
// ⚠️ 已知限制（P1 的实测结论之一）：uikit 的默认字体是 Inter，**没有中文字形**。所以这一层
// 只放**数字与拉丁字母**（HP、能量、回合），中文标签放在 DOM 覆盖层。
// 这不是偷懒：它正是"3D 文字要中文字形图集"这条结论的直接证据 —— 详见 `docs/ui-next-p1.md`。

import { Container, Fullscreen, Text } from "@react-three/uikit";

export interface HudProps {
  hp: number;
  maxHp: number;
  block: number;
  energy: number;
  maxEnergy: number;
  turn: number;
  phase: string;
  onEndTurn: () => void;
  onOpenModal: () => void;
}

export function Hud({
  hp,
  maxHp,
  block,
  energy,
  maxEnergy,
  turn,
  phase,
  onEndTurn,
  onOpenModal,
}: HudProps) {
  return (
    <Fullscreen flexDirection="column" justifyContent="space-between" padding={12}>
      {/* 顶栏：HP / 格挡 / 能量 / 回合 */}
      <Container flexDirection="row" gap={10} alignItems="center">
        <Container backgroundColor="#101820" borderRadius={8} paddingX={12} paddingY={8}>
          <Text fontSize={18} color="#ff9d8a" fontWeight="bold">
            {`HP ${hp}/${maxHp}`}
          </Text>
        </Container>
        <Container backgroundColor="#101820" borderRadius={8} paddingX={12} paddingY={8}>
          <Text fontSize={18} color="#8ac6ff" fontWeight="bold">
            {`BLK ${block}`}
          </Text>
        </Container>
        <Container backgroundColor="#101820" borderRadius={8} paddingX={12} paddingY={8}>
          <Text fontSize={18} color="#ffd166" fontWeight="bold">
            {`EN ${energy}/${maxEnergy}`}
          </Text>
        </Container>
        <Container backgroundColor="#101820" borderRadius={8} paddingX={12} paddingY={8}>
          <Text fontSize={16} color="#b8c7d6">
            {`TURN ${turn}`}
          </Text>
        </Container>
      </Container>

      {/* 底栏：结束回合 + 设置。phase 显示在这里，方便肉眼确认状态机在哪一档。 */}
      <Container flexDirection="row" gap={10} justifyContent="flex-end" alignItems="center">
        <Container backgroundColor="#0d141b" borderRadius={8} paddingX={10} paddingY={6}>
          <Text fontSize={13} color="#6f8ba8">
            {`phase: ${phase}`}
          </Text>
        </Container>
        <Container
          backgroundColor="#1b2733"
          borderRadius={8}
          paddingX={14}
          paddingY={8}
          onClick={onOpenModal}
          hover={{ backgroundColor: "#243543" }}
        >
          <Text fontSize={16} color="#cfe0ef" fontWeight="bold">
            SETTINGS
          </Text>
        </Container>
        <Container
          backgroundColor="#2b3a24"
          borderRadius={8}
          paddingX={14}
          paddingY={8}
          onClick={onEndTurn}
          hover={{ backgroundColor: "#3b5230" }}
        >
          <Text fontSize={16} color="#d6f5c8" fontWeight="bold">
            END TURN
          </Text>
        </Container>
      </Container>
    </Fullscreen>
  );
}

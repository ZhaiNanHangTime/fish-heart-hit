# 咸鱼突刺素材接入说明

这次只做一件事：把新的 `xianyu` 素材接入现有逻辑，不改你原来的心率算法结构。

## 已接入的帧
- idle
- alert_low
- alert_mid
- tense
- high
- charge
- burst
- recover

## 当前映射逻辑
常态按平滑后的紧张强度 `flush` 分段：
- `< 0.18` → idle
- `0.18 ~ 0.34` → alert_low
- `0.34 ~ 0.52` → alert_mid
- `0.52 ~ 0.68` → tense
- `0.68 ~ 0.84` → high
- `>= 0.84` → charge

事件帧优先：
- `burst > 0.42` → burst
- `0.08 < burst <= 0.42` → recover

## 这次顺手收掉的点
- 保留图片素材本身，不再额外开红色脉冲光
- 保留代码里的轻度红温染色和心跳弹动
- `effects.html` 同步支持新状态名
- 新素材统一放在 `web/assets/skins/xianyu/`

## 部署
直接覆盖原项目即可。

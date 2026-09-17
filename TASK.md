# 实验任务

## ITU-T P.1321 Annex B：Block building

来源：Recommendation ITU-T P.1321 (10/2025), Annex B "Communication task: Block building"，
原型是 ITU-T P.920 的 2D 视频会议版本。

**任务**
- 两个角色。指导者拿着完整 3D 图形的表示（图片），搭建者只有散件，按口头指令搭出同样的图形。
- 图形是 8–9 块大颗粒积木的小造型（图 B.2a：红黄橙三色，动物/机器人一类），难度靠积木数量和造型复杂度调。
- 目的是逼出音视频交互：搭建者要看、要问、要确认，指导者要看结果、要纠正。

**角色**
- 最少一名指导者 + 一名搭建者，可多名搭建者。
- 指导者建议由实验员/演员（confederate）担任：搭建者对刺激更敏感，把指导者固定下来能控制每个搭建者收到的指令。

**时长与结构**
- 一个 8–9 块的图形约 5 分钟；每个测试条件搭 1–3 个图形，一个条件约 25 分钟。
- 整场（筛查 → 前测问卷 → 训练 → 条件 → 条件后问卷 → 休息 → … → 后测问卷）不超过 90 分钟。
- 训练用不同于正式的图形，避免学习效应。正式前先做小规模 pilot 调协议。

**测量**
- 任务表现：每个条件下正确搭完一个图形的平均时间；可加成功率、错误率（9.1）。
- 条件示例明确包括音视频传输的变化（网络、压缩）。
- 系统侧同时监控并随时间报告吞吐、延迟、能耗等（9.5.1）。
- 主观量表、模拟器晕动、认知负荷等按第 9 节选用。

**设置与既有版本（B.4 / B.6.1）**
- 3DoF：搭建者坐在桌前，桌上搭，只能转头；6DoF：在虚拟环境里走动，积木是虚拟的。
- 已有实施：P.920 原版（2D 视频会议）；[b-Cortes2] 单人、无交流，只借了积木模型，测的是透视画面的自视延迟；
  [b-Cortes] 双人体积视频版，测通信延迟对协作的影响；[b-Ferrarotti] 一人 VR 一人 2D 屏；[b-Gutierrez] 双人 VR。

**文献要点（docs/papers）**
- Cortés 2024 (TOMM)，双人 + 通信延迟，最贴我们：5 个图形（Mazinger、Rocket、Bird、Dog、TRex）各 7 块大颗粒；
  延迟 300（本底）/600/900/1200/1500 ms，pilot 10 人先定档；每对被试 5 个任务，希腊拉丁方平衡图形×延迟，顺序随机；
  训练先搭最好和最差两档，休息 10 分钟再正式；60 人。
  客观：完成时间（Unity 日志）+ 双声道录音算每人说话时长和发言次数（P.1305，静音 >200 ms 切分）。
  主观 11 题 5 级：全局质量、系统烦扰、延迟感知、打断难度（P.920/P.1305）；投入、适应、完成信心（存在感）；
  社交存在、理解、配合、信息有用（Gupta）。
  结果：主观在 ≥900–1200 ms 显著下降，建议端到端不超 900 ms；完成时间 160 s → 190 s（1500 ms）不显著，
  人靠多说几轮来适应；搭建者比指导者对延迟更敏感，作者建议以后用固定的 confederate 指导者、只分析搭建者。
- Ferrarotti 2024 (IMX demo)，非对称：搭建者戴 Quest 3 在 VR 里用虚拟积木（带磁吸）搭，指导者在 PC 上看参考图、
  用 MATLAB 面板控制；WebRTC 点对点。图形 5/10/15 块三档；条件是通道组合（双向音视频 / 单向视频 / 只音频，共 4 种）。
  只有 demo，无结果；关注点是"传的信息类型决定交互质量和数量"。是 VQEG-IMG 的工作，6DoF 那张图就是他们的。
- Cortés 2022 (ICIP)，单人自视延迟：4 个模型各 65–90 s，190–597 ms 八档，450 ms 以上主观崩、完成时间基本不变。

## 我们的变体

讨论中，未定稿。

**有倾向的**
- 骨架照 P.920 / Cortés 2024：两角色，指导者拿参考、搭建者拿散件、自由交流搭出图形。指导者由 agent 担任，
  即 Cortés 建议的固定 confederate；只分析搭建者。
- 搭建者要有视觉参考。眼镜屏幕显示参考图：一个图形备几张不同角度的图，交流中 agent 看情况一次展示一张，
  搭建者也可要求换角度。图经网络下发，但是一次性素材，不算被测通道；切换时晚到算进语音延迟。
- 被测通道两条：语音双向，眼镜相机上行给 agent。
- 网络变量：丢包，可能再交叉一个变量，共 6 或 9 个任务。丢包对两路作用不同：语音（Opus，有 FEC/PLC）低丢包几乎
  听不出、高丢包断续；视频丢包是卡帧花屏，直接影响 agent 看到什么。档位靠 pilot 试到"听得出、看得出"，不照文献数字。
  丢包率、抖动、码率在 LiveKit 侧可观测，和 reply_ms 一起记（P.1321 9.5.1 的系统侧监控）。
- 积木：手头只有乐高小颗粒，先用。图形设计偏大件（2×4、2×2）和高对比色，少用 1×N 薄片和白色，agent 和用户都看得清；
  小颗粒的好处是能拿到镜头前给 agent 看。形状待定。
- 图形数 = 条件数（拉丁方），6 或 9 个难度相当、互不相同的图形，另备 1–2 个训练用；难度差要在 pilot 里验。
- 时长流程沿用 Cortés：一个图形约 2–3 分钟；训练先给最好和最差条件；条件×图形拉丁方、顺序随机；每任务后填问卷，
  11 题裁一版。9 个任务约 45 分钟 + 训练休息，接近 90 分钟上限；6 个宽松。

**待定**
- 完成检验：Cortés 靠双方共识，没有客观核查。我们做不做、怎么做。
- 交叉的第二个变量是什么：纯网络（延迟/带宽）还是交互设计（有无参考图、agent 主动/被动），两者回答的问题不同。
- 本底：agent 响应本身 2–5 s，已超 Cortés 最差档。先在好网络下量基线，再看劣化叠加多少；pilot 要做这个。
- 任务时间上限要不要加（真人不会卡死，agent 会）。
- 每个被试跑几个任务、被试人数。

**Future work**
- 下行视觉做成实时：agent 控制 3D 模型旋转、以视频流下发，让下行视觉也成为被测通道，与 Cortés 的设定对齐。

## 参考文献（P.1321 书目）

- [b-Cortes2] Cortés, C., Gutiérrez, J., Pérez, P., Viola, I., César, P., García, N. (2022). Impact of self-view latency on quality of experience: Analysis of natural interaction in XR environments. IEEE ICIP 2022, 3131–3135.
- [b-Cortes] Cortés, C., Viola, I., Gutiérrez, J., Jansen, J., Subramanyam, S., Alexiou, E., César, P. (2024). Delay threshold for social interaction in volumetric eXtended Reality communication. ACM TOMM 20(7), 1–22.
- [b-Ferrarotti] Ferrarotti, A., Baldoni, S., Carli, M., Battisti, F. (2024). Interaction goes virtual: towards collaborative XR. ACM IMX 2024, 443–446.
- [b-Gutierrez] Gutiérrez, J., Pérez, P. (2024). IMG Test plan on Immersive communication systems. VQEG Plenary Meeting, Klagenfurt (presentation 118).
- ITU-T P.920: 原版 block building 任务（2D 视频会议）。

# LEGO 任务跟进笔记：与"全双工语音模型 + 确定性视觉传感器 + 头戴相机"相近的现有工作

**结论先行：目前没有哪个公开项目同时具备眼镜头戴相机、全双工云端语音模型、确定性步骤状态传感器，并且做过网络损伤下的用户研究。** 最接近的是 2025–2026 年的小型 GitHub 项目，以 GlassKit（Rokid 眼镜 + WebRTC + OpenAI Realtime + RF-DETR 检测器）为代表。可靠性和网络 QoE 的证据，目前几乎全部来自 2015–2023 年 CMU Gabriel LEGO 这一系工作（非 LLM）。

## TL;DR

- **最接近的系统**：GlassKit 的 IKEA 装配助手和饮品教练示例、TFS_RokidDemo（压板机工作流）、MIT/CMU 的"实时多模态 LM + 视觉工具"机器人方案（arXiv 2602.04157）。三者都把状态判定交给检测器或状态机，语音模型只负责对话。只有机器人方案报告了延迟（OpenAI Realtime 690±389 ms，Gemini Live 739±593 ms）和工具调用准确率。眼镜类开源项目基本都没有可靠性数据。【证据薄弱】
- **LEGO 板面识别**：唯一现成、针对"板上每格是什么颜色"的代码是 CMU gabriel-lego。它支持标准 LEGO（非 Duplo），但要求一块带黑色边框和黑点的专用打印底板。代码为 Python 2 + OpenCV 2.4.9.1，另有一个 Python 3 移植版，均基本停更。DuploTrack 用的是 Kinect 深度相机。没找到 2019 年以后能直接复用的单相机网格颜色读取开源项目。通用 VLM 在 LEGO 状态检测上 F1 最高只有 40.54%（LEGO Co-builder，GPT-4o）。
- **网络 QoE 与视觉接入**：没找到对全双工语音代理注入丢包或限带宽并做用户评测的研究，这是一个真实空白。最可用的方法学先例是 CMU/KTH 的 LEGO 延迟研究：紧界 600 ms、松界 2.7 s，延迟会引起用户"节奏同化"。视觉接入方面，多个独立项目收敛到同一组做法：说话时约 1 fps、空闲时约 0.33 fps 推帧；每轮用户发言附带最新一帧；或者由独立检测器或状态机产出文本事件，再注入语音模型上下文。

---

## 问题 1：最接近的现有系统（2023 年起）

### 关键发现

| 项目 / 工作 | 形态 | 感知怎么做 | 可靠性 / 延迟 | 开源 |
|---|---|---|---|---|
| **GlassKit**（RealComputer，GitHub，持续更新至 2026，172 星，MIT）https://github.com/RealComputer/GlassKit | Rokid 眼镜（Android），摄像头和麦克风经 WebRTC 送到后端，再接 OpenAI Realtime；带单色 HUD\[1\] | 三种做法并存：①"IKEA assembly assistant"直接把麦克风和摄像头流给 OpenAI Realtime；②同一示例的 RF-DETR 变体用后端目标检测"增强"实时模型；③"Drink-making coach"把 Overshoot 视频推理、配方状态（recipe state）和 OpenAI Realtime 组合起来，主动逐步指导。文档里有"Proactive perception pattern""backend-gated turns for vision/tool/speech workflows""sideband events"等模式页\[1\]\[2\] | README 没有给出延迟或准确率数字【证据薄弱】。提供 GlassKit Eval CLI 做视觉回归测试\[1\] | 是 |
| **TFS_RokidDemo**（kw-iteria，GitHub）https://github.com/kw-iteria/TFS_RokidDemo | Rokid RV101 眼镜，CameraX 采 JPEG，经 WebSocket 送到 Mac 上的服务器；HUD 加 TTS\[3\] | 按工作流状态机推进（待机→找压板机→"请关闭压板机"→10 s 倒计时）。`vision.ts` 对单帧做结构化分类（可选 Gemini、OpenAI Responses、OpenAI Realtime 等）。`agent.ts` 是对话助手，"sees the frame + state, calls workflow tools"。可以通过对话"use this as the closed reference"现场采集参考图\[3\] | 延迟设计：gpt-realtime-mini 跑在一条长连接 WebSocket 上，"every frame is an out-of-band response"，省掉每次请求的 TLS/HTTP 开销。没有给出数字【证据薄弱】\[3\] | 是 |
| **MIT/CMU 机器人方案**：Lee et al., "A Modern System Recipe for Situated Embodied Human–Robot Conversation with Real-Time Multimodal LLMs and Tool-Calling"，arXiv\[4\] 2602.04157（2026）https://arxiv.org/abs/2602.04157 | Jibo / Reachy Mini 机器人的第一人称相机；OpenAI Realtime 或 Gemini Live 负责对话和 VAD\[4\] | 实时 LM 当对话管理器，通过 5 个工具（look_at_person、look_at_object、look_around、look_for、use_vision）主动感知。本地跑 YOLO11-pose（49.3 ms）和 SAM3（161.7 ms）做跟踪。use_vision 按需把最新帧发进会话，而不是持续推流\[4\] | 端到端延迟 OpenAI 690±389 ms，Gemini 739±593 ms。单次交互成本 0.047 美元对 0.018 美元。工具决策宏准确率 0.72 对 0.77。use_vision 精确率 1.00、召回约 0.60，即"该看时不看"。样本小：作者 Dong Won Lee 等（CMU/MIT）只评测了 6 个场景（姿势指导、白板辅导、台灯摆放、植物诊断、穿搭检查、找失物）× 4 个系统变体，2 名标注者 | 未见代码链接【证据薄弱】 |
| **ARGUS / TIM**（NYU，DARPA PTG），arXiv 2308.06246（IEEE VIS 2023）https://arxiv.org/abs/2308.06246 | HoloLens 2，做烹饪等任务指导 | 感知流负责识别物体，推理流负责识别动作；ARGUS\[5\] 是给开发者用的可视化调试工具\[6\] | 两条流"about 100 ms"完成一次更新。ARGUS 的串流延迟约 300 ms，Windows Device Portal 约 1.3 s。不是\[5\] LLM 语音对话架构 | 是（GitHub VIDA-NYU）\[6\] |
| **Meta Ray-Ban 系开源 App**：OpenVision（FelixSteindorff）https://github.com/FelixSteindorff/OpenVision ；VisionClaw / Vision-Bot（WaltLuv）https://github.com/WaltLuv/Vision-Bot ；meta-glasses-ios-openai（kirill-markin，见 https://github.com/topics/meta-glasses ） | Meta DAT SDK 取眼镜相机，接 Gemini Live 或 OpenAI Realtime\[7\] | 通用"看到什么就聊什么"，没有任务状态跟踪。OpenVision 同时提供"按需拍照（GPT-4o）"和"实时视频（gpt-realtime / Gemini Live 1fps）"两种模式；VisionClaw\[7\]\[8\] 以约 1 fps 推 JPEG\[9\] | 没有可靠性数据 | 是 |
| **Snap Spectacles OpenAIConnector**（GitHub）https://github.com/Oluwatosin-Ogunyebi/OpenAIConnector-Spectacles | Spectacles 眼镜 | 捏合手势触发拍一帧，连同 prompt 发到 Chat Completions，不走实时语音\[10\] | 无 | 是 |
| **Augmented Assembly**，arXiv 2601.11535（2026）https://arxiv.org/html/2601.11535 | HoloLens 2 上的 LEGO 装配 AR 指导\[11\] | 物体识别（2D 框）加手部跟踪\[11\] | AR 指导用时 12:39，对照组分拣零件 25:54、未分拣 32:11。不含语音\[11\] LLM | 未确认 |

### 解读

- 2025–2026 年的眼镜小项目普遍有一个分层：**检测器或状态机掌握"事实"，实时语音模型掌握"说话"**。GlassKit 的 RF-DETR 变体和饮品教练、TFS_RokidDemo 的 `vision.ts` 加状态机都是这样。这和你们"判定器只是传感器"的决定一致，说明这不是孤立的设计选择。
- 纯 VLM 判定步骤状态并不可靠。LEGO Co-builder（arXiv 2507.05515，2025）报告 GPT-4o 在状态检测上 F1 最高 40.54%。Epoch\[12\] AI 的家具装配基准报告（Aiden Ament、Greg Burnham，2026-09-23）显示，GPT-6 Astra 以 80% 居首（2025 年 11 月最佳成绩为 Claude Opus 4.5 的 28%），但每张照片中位耗时 3 分钟，测试集为三种 IKEA 家具共 60 张图；"尚不够快、不能用于实时装配指导"的说法来自 The Decoder 的转述，报告原文中未见。
- **没有任何一个项目报告网络条件对用户体验的影响**。这正是你们研究可以占据的位置。

---

## 问题 2：从相机读取 LEGO/Duplo 板面状态

### 关键发现

**CMU Gabriel LEGO 助手**：唯一直接相关、直接输出"格子→颜色"矩阵的系统。
- 资料：Chen et al., "Early Implementation Experience with Wearable Cognitive Assistance Applications", WearSys 2015；Zhuo\[13\] Chen 博士论文 CMU-CS-18-104（2018）https://elijah.cs.cmu.edu/DOCS/CMU-CS-18-104.pdf \[14\] ；代码 https://github.com/cmusatyalab/gabriel-lego （Python 2）和 https://github.com/cmusatyalab/gabriel-lego-py3 （Python 3，Apache-2.0，155 次提交，0 星）。\[15\]
- **流程**（WearSys 2015 原文摘录）：
  1. 用"distinctive black border and black dot pattern"找到底板，经"robust black detector"定位四角后做透视变换；\[16\]
  2. 提取模型区域，用颜色检测补上透视下看到的砖块侧面；\[16\]
  3. 用 grey world 颜色归一化应对光照；\[16\]
  4. 每格按"weighted majority vote of colors"量化成离散颜色，品红色表示"不确定"；\[16\]
  5. 输出二维矩阵，例如 `[[0, 2, 1, 1], [0, 2, 1, 6], [2, 2, 2, 2]]`，0 表示空。\[14\]\[17\]
  任务是 **2D**（竖立的单层平面图案），客户端会先丢弃模糊帧（early discard）。\[16\]\[18\]
- **标准 LEGO，不是 Duplo**：README 写"Any standard lego bricks would work. However, these bricks need to be placed on this particular lego board … Print the board on a piece of paper would also work."参考套装为 LEGO 6000207。\[19\]
- **分辨率 / 距离**：论文中可远程把相机设为 1280×720（"set the camera resolution to 720P"），微基准用"a pre-recorded 360p video"。没取到工作距离和逐帧准确率【证据薄弱】。Ajalon\[14\] 论文（Pham et al., Software: Practice and Experience 2021）表中列出视频带宽"480p: 3.6 / 7.0，720p: 6.8 / 9.9（Average / Peak, Mbps）"。这组数字是否专指\[17\] LEGO 应用，我未能从摘录中确认【证据薄弱】。
- **代码状态**：README 明确写"OpenCV: 2.4.9.1 (not working with more recent version)"，numpy 1.11.1，有 Docker 镜像，最近 release 是"Legacy Gabriel version"（2019-11-22）。作者也承认"the code to implement it reliably was challenging (especially with flexible user actions and under different lighting conditions)"。py3\[19\] 版本可作为起点，但都应视为**停更**状态【推测：基于星数和 release 日期】。

**DuploTrack**：Gupta, Fox, Curless, Cohen, UIST 2012, https://dl.acm.org/doi/10.1145/2380116.2380167
- 用 Kinect 的颜色加深度做实时 3D 跟踪，推断每一步的 Duplo 搭建过程；可以创作新模型、指导他人复现，并检测错误。\[20\]\[21\]
- 用户研究显示，相比说明书插图，它出错更少、搭建更快。\[22\]
- 依赖深度传感器，只针对 Duplo；未见开源代码【证据薄弱】。

**Miller et al., "Interactive 3D Model Acquisition and Tracking of Building Block Structures"**（同期工作，见 https://www.researchgate.net/publication/221688639 ）
- 假设模型底座始终贴在桌面上，从而把跟踪降为 3 自由度（平面平移 2 个 + 平面旋转 1 个），同样针对 Duplo。这一假设和你们"固定底板在桌上"的设定完全对应。\[23\]

**更新的相关工作**（都不是现成的"单相机读底板网格颜色"方案）：
- **LEGO 底板作为人工地标做位姿估计**，IEEE 会议论文（2023）https://ieeexplore.ieee.org/document/10260305/ 。利用网格、圆形螺柱和文字图案，"can recover more than 95% stud centers as feature points"。这说明**普通\[24\] LEGO 底板本身就可以作为单应性 / 位姿标定物**，可能不需要 Gabriel 那种黑边打印板【推测：论文目标是位姿，不是砖块占用】。
- **BRICKxAR**，arXiv 1907.12549（2019）：基于标记和模型注册的 LEGO AR，平均注册误差小于 1 mm；跟踪的是步骤，不是逐格颜色。\[25\]
- **Kleinbeck et al.**（ASDF，arXiv 2403.16400 引用）：YOLOv5 加合成数据做积木装配指导，指导步骤在 HoloLens 上渲染；可能对应 Constantin Kleinbeck（TUM）的 IEEE VR 论文"ARTFM"，据搜索摘要其用 BlenderProc + Unity Perception 生成 44 类砖块的合成数据；代码是否公开未核实【证据薄弱】。
- **"Photos and rendered images of LEGO bricks"**，Scientific Data 2023，https://www.nature.com/articles/s41597-023-02682-2 ：Boiński（Gdańsk University of Technology）发布约 15.5 万张照片、近 150 万张渲染图，配 YOLOv5 检测器，按形状分类白桌面上的散件，不针对底板。
- **SCANet**，arXiv 2403.18195（2024）：纠正 LEGO 装配错误，面向机器人和 3D 位姿，不是头戴单目。
- **马赛克类仓库**（cmadisons/lego-pic、myrtleTree33/lego-mosaic〔Python/OpenCV〕、ryantimpe/brickr〔R〕）：方向相反，是"图像→砖块颜色方案"。可复用的只有\[26\]\[27\]\[28\] LEGO 调色板量化。

### 解读

- 能直接借用的思路仍是 Gabriel 的"找板→透视校正→逐格颜色投票"。它在 2015 年 Google Glass 第一人称视角下就能跑，而且用的就是标准 LEGO。主要风险在光照和手部遮挡，作者自己也这样说。
- 2D 竖板任务（Gabriel）和水平底板上的 3D 堆叠不同：后者从头戴斜视角看，会有侧面遮挡和高度歧义。Miller 等的"底座贴桌、3 自由度"假设和 DuploTrack 的深度数据是解决这类问题的先例，但都依赖 Duplo 的大尺寸或深度相机。
- **Duplo 和标准 LEGO**：除 Gabriel 外，所有实时跟踪工作（DuploTrack、Miller 等）都选了 Duplo。【推测】原因是 1×1 Duplo 单元的边长约为标准 LEGO 的 2 倍，在 Kinect 时代的分辨率下更易分割。1080p 广角头戴相机在 40–60 cm 距离看标准 8 mm 螺柱，每格大约只有十几到二十几个像素，可行但余量不大。这是估算，未见实测文献。

---

## 问题 3：网络损伤下实时语音代理的 QoE

### 关键发现

**直接相关的研究：没有找到。** 我没找到任何学术或业界研究，对全双工语音助手或 WebRTC 语音加视频 AI 管线注入延迟、丢包或带宽限制，并测量用户主观体验。【证据薄弱：这是检索结论，不排除存在未公开的内部研究】

**最接近、可直接借用方法学的工作（LEGO 加可穿戴认知助手）：**
- **Chen et al., "An Empirical Study of Latency in an Emerging Class of Edge Computing Applications for Wearable Cognitive Assistance"**，ACM/IEEE SEC 2017，https://www.cs.cmu.edu/~zhuoc/papers/latency2017.pdf 。用 Wizard-of-Oz 方式测延迟容忍度，给 LEGO、Draw、Sandwich 等逐步指导类应用定出**紧界 600 ms、松界 2.7 s**。紧界以下用户感知不到改进；超过松界，"user\[29\]\[30\] experience and performance is significantly impacted"。\[31\]\[32\]
- **Olguín Muñoz et al., "Impact of delayed response on wearable cognitive assistance"**，PLOS ONE 2021，https://pmc.ncbi.nlm.nih.gov/articles/PMC7987160/ \[33\] ，数据集 Zenodo 4489266。
  - 方法：用 LEGO 助手注入 7 档固定延迟（0、0.6、1.125、1.65、2.175、2.7、3.0 s），任务长度\[30\] 4/8/12 步。\[34\]
  - 为了排除网络抖动，**刻意改成本地运行**，所以没有研究丢包和抖动。\[30\]\[35\]
  - 结论：用户出现"pacing effect"，即系统变慢时用户自己也变慢；原因是认知计划被打断，而不是情绪唤起。\[30\]\[33\]
- **Klatzky & Satyanarayanan, "Psychological Science Meets Wearable Cognitive Assistance"**，Current Directions in Psychological Science 2023，https://journals.sagepub.com/doi/full/10.1177/09637214231187912 。最差与最好条件相比，执行一条指令的时间"nearly doubled"。用户在等待时会晃动 LEGO 结构，导致系统重置，进一步拖慢下一条指令。这是"延迟\[36\] × 视觉判定器"耦合失败的真实案例。
- **"Realistic Modeling of Human Timings for Wearable Cognitive Assistance"**，arXiv 2212.06100：在上述数据基础上建了用户时序模型，可用于在仿真中做网络实验。\[37\]

**语音代理的延迟感知研究（只测延迟，不测丢包）：**
- **τ-Voice**，arXiv 2603.13686（2026）：全双工语音代理基准。OpenAI 响应延迟 0.90 s、打断率 14%，但"selectivity"仅 6%，几乎对所有附和语都作出回应；Google 延迟 1.14 s；xAI 延迟 1.15 s，打断率 84%。\[38\]
- **"Quantifying Latencies: A Conversation Analysis Approach to Human-Agent Interactions in Virtual Reality"**，CHI 2026，https://dl.acm.org/doi/10.1145/3772318.3790947 ：代理响应中位数 4.1 s，人类 1.2 s；指出代理存在启动延迟和"wind-down latency"（被打断后停不下来）。\[39\]
- **"Mitigating Response Delays in Free-Form Conversations with LLM-powered Intelligent Virtual Agents"**，CUI 2025，arXiv 2507.22352：VR 中注入响应延迟，测试对话填充词的缓解作用。\[40\]
- **"Understanding User Perceptions of Response Delays in …"**，ACM（CSCW），https://dl.acm.org/doi/pdf/10.1145/3555765 ：比较 2/4/8/16 s 延迟，8 s 尚可容忍，16 s 显著更差。场景是文字聊天机器人，可比性有限。\[41\]
- **"The Impact of Response Latency and Task Type on Human-LLM Interaction and Perception"**，arXiv 2604.06183（2026）：延迟与任务类型的交互效应。我只看到参考文献片段，未读正文【证据薄弱】。
- **Full-Duplex-Bench**，arXiv 2503.04721（2025）：全双工模型轮次交接能力的基准，可借用其指标定义。

**业界博客（工程经验，质量参差）：**
- **Agora**，"The Impact of Latency in Speech-Driven Conversational AI Applications"：https://www.agora.io/en/blog/the-impact-of-latency-in-speech-driven-conversational-ai-applications/ 。按 ITU-T G.114，口到耳延迟 275 ms 以内用户满意，275–385 ms 部分用户不满，再往上体验差。逐项拆分了编码、抖动缓冲（>60 ms）、播放（160–250 ms）等延迟。有厂商立场。\[42\]
- **Hamming AI**，WebRTC 语音代理测试指南：https://hamming.ai/resources/webrtc-call-quality-testing-voice-agents 。持续丢包 >1% 视为警告，>3% 阻断发布。另一篇称"2%\[43\] packet loss … causes 10-15% ASR word error rate increases"，但没给出数据来源【证据薄弱：厂商断言】。\[44\]
- **Spheron** 博客称 Opus PLC 能"transparently"处理 10–15% 丢包，FEC 增加 15–20% 带宽【证据薄弱：厂商断言，与上一条存在张力】。\[45\]

### 解读

- 方法学上，最成熟的模板是 Olguín Muñoz 2021：固定延迟档位、步骤级计时、生理信号、Zenodo 公开数据。但它恰好**排除**了网络随机性。你们的研究等于把这个实验搬回真实网络，再加上全双工语音层。
- 语音层和视觉层的延迟预算差别很大：语音轮次交接在几百毫秒量级（G.114 275 ms；τ-Voice 约 0.9–1.15 s），步骤判定的容忍区间在 0.6–2.7 s。【推测】网络损伤很可能先在语音层被察觉（打断、抢话、卡顿），然后才轮到"判定器慢了"。所以两层应分别打点计时。\[34\]\[38\]\[42\]
- 丢包对 ASR 或语音模型理解的影响，目前只有厂商经验数字，彼此矛盾，缺乏受控研究。

---

## 问题 4：人们如何把视觉接到实时语音模型上

### 平台层事实

- **OpenAI gpt-realtime**（"Introducing gpt-realtime and Realtime API updates"，OpenAI 博客，2025-08）https://openai.com/index/introducing-gpt-realtime/ ：图像通过 `conversation.item.create` 以 `input_image` 内容项加入会话。官方原话是"Instead of treating an image like a live video stream, the system treats it more like adding a picture into the conversation."\[46\]
- **OpenAI GPT-Live**（LiveKit 插件文档）https://docs.livekit.io/agents/models/realtime/plugins/gpt-live/ ：由服务器驱动，客户端不能创建、取消或截断响应；是否被打断由模型自己决定；推理和工具调用委托给后端 Responses 模型；语音模型和后端模型各有一套指令。文档提示"Use the OpenAI Realtime API, which supports video input"。【推测】这意味着\[47\] GPT-Live 插件目前不直接收视频帧，视觉信息需要走工具或后端模型。OpenAI 工程博客"How we built a realtime system for responsive voice AI in six months"（2026-08-03）https://openai.com/index/continuous-voice-interaction-with-gpt-live/ 说明了它从轮次制转向连续流，并通过委托处理推理。\[48\]
- **Gemini Live API**（Vertex 和 ai.google.dev 文档）：视频按 **1 FPS** 处理，"unsuitable for … fast-changing video"；帧以单张 JPEG/PNG 发送，推荐 768×768；音频加视频会话限 2 分钟（不压缩上下文时）；每帧 66 或 258 token，取决于 media_resolution。\[49\]\[50\]\[51\]\[52\]

### 各项目的接入形态与节奏

| 形态 | 项目 / 来源 | 节奏 | 报告的行为 |
|---|---|---|---|
| **A. 持续推帧（模拟视频）** | LiveKit Agents `video_input=True`：OpenAI Realtime 把"each frame as an image message"，Gemini 原生流式 https://docs.livekit.io/agents/models/realtime/plugins/openai/ \[53\]\[54\] | 默认**用户说话时 1 fps、其余时间每 3 秒 1 帧**，可用 `video_sampler` 调整\[54\]\[55\] | 每帧都消耗 token，帧率越高成本越高；如果模型只支持音频，帧会被**静默忽略**，不报错\[53\] |
| | livekit-examples/vision-demo（Gemini Live，iOS）https://github.com/livekit-examples/vision-demo \[56\] | 说话时 1 fps，否则 0.3 fps\[56\] | 已标注为过时，被官方 starter 取代\[56\] |
| | Pipecat 26c-gemini-multimodal-live-video 示例（issue #979）https://github.com/pipecat-ai/pipecat/issues/979 | `framerate=1`\[57\] | 有 Tavus 头像时会把两路视频都喂给模型。另有\[57\] expo-gemini-live 仓库 https://github.com/kiarashplusplus/expo-gemini-live 报告 Pipecat 0.0.94 中 Gemini 的视频帧处理是 no-op，"Daily camera frames never reach Gemini"，属于静默失效\[58\] |
| | VisionClaw、OpenVision（Meta Ray-Ban） | 约 1 fps JPEG\[9\] | 无行为报告 |
| **B. 每轮附最新帧** | LiveKit Vision Agent Quickstart 和 Video 文档（STT-LLM-TTS 管线）https://docs.livekit.io/agents/multimodality/vision/video/ \[53\]\[59\] | **每个用户轮次**在 LLM 生成前注入最新一帧\[53\]\[59\] | 官方给出的理由是"without overwhelming the model or requiring it to process multiple sequential frames"，"Keeps the context clean"\[53\]\[59\] |
| **C. "看"工具 / 按需快照** | MIT/CMU 机器人方案的 `use_vision`（arXiv 2602.04157） | 模型调用工具时才发一帧\[4\] | 明确说持续推流"can be costly as image tokens accumulate"。实测**精确率 1.00、召回约 0.60**：模型在该看的时候常常不看，作者称之为"not looking is itself an error"\[4\] |
| | OpenVision"Photo on request"；Spectacles 捏合拍照；Gemini-CLI\[7\]\[10\] Vision Extension `/vision:capture`\[60\] | 用户请求或手势触发 | 无行为报告 |
| **D. 独立视觉模型或检测器产出文本或事件，注入语音模型** | GlassKit RF-DETR 变体，"realtime model augmentation"；饮品教练（Overshoot 视频推理 + 配方状态 + Realtime）；文档中的"backend-gated turns"\[1\]\[2\] | 检测事件驱动 | README 未报告行为【证据薄弱】 |
| | TFS_RokidDemo：每帧结构化分类，状态机驱动 HUD；对话助手看"frame + state"并调用工作流工具\[3\] | 每帧做 out-of-band 分类，对话按需 | 无数字 |
| | Pipecat MoondreamService（本地 VLM 把图像转成文字）https://docs.pipecat.ai/server/services/vision/moondream \[61\] | 按管线配置 | 无 |
| | GPT-Live 的委托架构本身：语音模型→后端 Responses 模型→工具\[47\] | 按需 | 官方架构，见上文 |

### 收敛模式（多个独立来源）

1. **帧率上限约 1 fps，空闲时降频**：Gemini 平台硬限 1 FPS；LiveKit 对 OpenAI 和 Gemini 的默认值都是说话时 1 fps、空闲时 1/3 fps；vision-demo、Pipecat\[49\]\[54\]\[55\]\[56\] 示例和 Meta Ray-Ban 开源 App 都用约 1 fps。至少\[9\]\[56\]\[57\] 4 个独立来源一致。
2. **不要把视频当视频，而当"往对话里放图"**：OpenAI 官方措辞、LiveKit 的"每轮最新帧"、机器人方案的 `use_vision` 背后是同一个理由：图像 token 累积带来成本和上下文污染。
3. **任务状态由模型之外的组件持有**：GlassKit（RF-DETR、配方状态）、TFS_RokidDemo（状态机）、机器人方案（本地 YOLO 和 SAM 跟踪，只把紧凑目标交给控制器）、GPT-Live\[4\] 委托架构。这是和你们设计最相关的收敛点。
4. **静默失效是共同的坑**：LiveKit 文档（音频模型会静默忽略视频）和 expo-gemini-live（Pipecat 版本中帧未送达）各自独立记录了"以为模型看到了，其实没看到"。\[58\]

### 关于"主动解说 / 连贯性 / 困惑"

- **公开资料中几乎没有关于"模型在持续推帧时会不会主动解说摄像头画面"的系统报告。**【证据薄弱】
- 相关迹象有三条：
  - LiveKit 的 Gemini Live 视觉配方显式开启了"proactivity"，说明主动发言要专门配置，不是默认行为；\[62\]
  - τ-Voice 发现 OpenAI 模型几乎对所有附和语和非指向性语音都作出回应（selectivity 6%）。【推测】如果推送的视觉事件措辞像用户发言，也可能诱发不必要的回应；\[38\]
  - 机器人方案的主要失败是"该看时没看"（召回低），而不是"乱看乱说"（精确率高）。\[4\]
- 对话连贯性方面，机器人方案在 6 个场景中"Convo. Quality"评分为 4.65±0.15（满分 5），且各变体之间没有明显差异。说明加入视觉工具没有破坏语言连贯性；但样本只有\[4\] 2 名标注者【证据薄弱】。

---

## 注意事项

- 本笔记中的 2026 年资料（GlassKit、TFS_RokidDemo、arXiv 2602.04157、τ-Voice、GPT-Live 文档）大多是预印本或 README，没有经过同行评审，数字可能随版本变化。
- Gabriel LEGO 的分辨率、距离和逐帧准确率等关键指标没能从原文取到（WearSys PDF 无法访问，博士论文相关章节在抓取时被截断），需要自行查阅论文 §3.1.6 和 §3.3。
- 厂商博客（Hamming、Spheron、Agora、forasoft）中的丢包和延迟阈值属于工程经验或营销内容，不能当作实验结论。

## 最值得先看的项目/资料

1. **GlassKit**（https://github.com/RealComputer/GlassKit ）：最接近你们形态的开源实现（眼镜 + WebRTC + OpenAI Realtime + 检测器 + 逐步指导）。重点看 `rokid-openai-realtime-rfdetr` 和饮品教练示例，以及文档中的"OpenAI Realtime / backend-gated turns""Proactive perception pattern"两页。
2. **arXiv 2602.04157**（实时多模态 LM + 视觉工具）：唯一同时给出延迟、成本和"何时看"准确率的公开评测，可借用评测协议。
3. **cmusatyalab/gabriel-lego(-py3)** 和 WearSys 2015 论文：唯一现成的"板面→颜色矩阵"实现，使用标准 LEGO。
4. **Olguín Muñoz et al., PLOS ONE 2021**，加 Chen et al. SEC 2017：网络 QoE 实验设计的直接模板（延迟档位、紧界和松界、节奏同化），数据公开。
5. **LiveKit Agents Video 文档**：推帧节奏默认值、每轮最新帧注入，以及静默忽略视频这一坑。
6. **TFS_RokidDemo**：在 Realtime 长连接上做 out-of-band 单帧分类、用状态机推进步骤的小型参考实现。
7. **IEEE 10260305（LEGO 底板位姿估计）**：可以考虑用普通底板本身的螺柱网格代替专用黑边打印板做单应性校正。

## Sources

1. [GitHub - RealComputer/GlassKit: 😎 Toolkit for building AI apps that see, hear, and guide through smart glasses](https://github.com/RealComputer/GlassKit)
2. [Skills](https://skills.lc/RealComputer/GlassKit/realcomputer-glasskit-skills-glasskit-skill-md)
3. [GitHub - kw-iteria/TFS\_RokidDemo · GitHub](https://github.com/kw-iteria/TFS_RokidDemo)
4. [arxiv.org](https://arxiv.org/pdf/2602.04157)
5. [\\systemname: \\revisionVisualization of AI-Assisted Task Guidance in AR](https://arxiv.org/html/2308.06246)
6. [NYU Tandon researchers unveil tool to help developers create augmented reality task assistants](https://engineering.nyu.edu/news/nyu-tandon-researchers-unveil-tool-help-developers-create-augmented-reality-task-assistants)
7. [GitHub - FelixSteindorff/OpenVision: Open-source iOS app connecting Meta Ray-Ban smart glasses to AI — 5 backends (on-device MLX models, Apple Intelligence, OpenAI, Gemini Live, OpenClaw), on-device neural voice, face recognition & live web search. Private and offline-capable.](https://github.com/FelixSteindorff/OpenVision)
8. [GitHub - automacuniao-sudo/OpenVision: Open-source iOS app connecting Meta Ray-Ban smart glasses to AI — 5 backends (on-device MLX models, Apple Intelligence, OpenAI, Gemini Live, OpenClaw), on-device neural voice, face recognition & live web search. Private and offline-capable.](https://github.com/automacuniao-sudo/OpenVision)
9. [GitHub - WaltLuv/Vision-Bot: VisionBot — Real-Time Multimodal Voice & Vision Field Assistant (Gemini Live + LiveKit WebRTC + PropControl & VisionOps Bridge)](https://github.com/WaltLuv/Vision-Bot)
10. [GitHub - Oluwatosin-Ogunyebi/OpenAIConnector-Spectacles: An open source Lens Studio project that bridges Snap Spectacles and OpenAI. It uses the Spectacles CameraModule to capture frames from the device camera and sends them to OpenAI's vision API — displaying the response as AR text overlaid in your field of view.](https://github.com/Oluwatosin-Ogunyebi/OpenAIConnector-Spectacles)
11. [Augmented Assembly: Object Recognition and Hand Tracking forAdaptive Assembly Instructions in Augmented Reality](https://arxiv.org/html/2601.11535)
12. [LEGO Co-builder: Exploring Fine-Grained Vision-Language Modeling for Multimodal LEGO Assembly Assistants](https://arxiv.org/html/2507.05515v2)
13. [Impact of delayed response on wearable cognitive assistance - PubMed](https://pubmed.ncbi.nlm.nih.gov/33755667/)
14. <https://elijah.cs.cmu.edu/DOCS/CMU-CS-18-104.pdf>
15. [GitHub - cmusatyalab/gabriel-lego-py3: Python 3 implementation of Lego wearable cognitive assistant](https://github.com/cmusatyalab/gabriel-lego-py3)
16. [Early Implementation Experience with Wearable Cognitive Assistance Applications](http://krha.kr/data/pubs/zhuo-wearsys.pdf)
17. [Ajalon: Simplifying the authoring of wearable cognitive assistants - Pham - 2021 - Software: Practice and Experience - Wiley Online Library](https://onlinelibrary.wiley.com/doi/full/10.1002/spe.2987)
18. [Carnegie Mellon University](https://www.cmu.edu/scs/edgecomputing/software/wca-apps.html)
19. [GitHub - cmusatyalab/gabriel-lego](https://github.com/cmusatyalab/gabriel-lego)
20. [(PDF) DuploTrack: A real-time system for authoring and guiding duplo block assembly](https://www.researchgate.net/publication/261855441_DuploTrack_A_real-time_system_for_authoring_and_guiding_duplo_block_assembly)
21. [\[PDF\] DuploTrack: a real-time system for authoring and guiding duplo block assembly](https://www.semanticscholar.org/paper/DuploTrack:-a-real-time-system-for-authoring-and-Gupta-Fox/563c01818b54ca85ed5970dc12c5ca379f146f7f)
22. [DuploTrack](https://dl.acm.org/doi/10.1145/2380116.2380167)
23. [Interactive 3D Model Acquisition and Tracking of Building Block Structures](https://www.researchgate.net/publication/221688639_Interactive_3D_Model_Acquisition_and_Tracking_of_Building_Block_Structures)
24. [Vision-Based Camera/Robot Pose Estimation Using Both Semantic and Geometric Features on LEGO Baseplates](https://ieeexplore.ieee.org/document/10260305/)
25. [Augmented Reality Applied to LEGO Construction: AR-based Building Instructions with High Accuracy & Precision and Realistic Object-Hand Occlusions](https://www.researchgate.net/publication/334759504_Augmented_Reality_Applied_to_LEGO_Construction_AR-based_Building_Instructions_with_High_Accuracy_Precision_and_Realistic_Object-Hand_Occlusions)
26. [GitHub - cmadisons/lego-pic: Turn any photo into a LEGO mosaic — pick a baseplate size and get the brick colors you'd need.](https://github.com/cmadisons/lego-pic)
27. [GitHub - myrtleTree33/lego-mosaic: Convert any image to a Lego-palette compatible mosaic!!! · GitHub](https://github.com/myrtleTree33/lego-mosaic)
28. [GitHub - ryantimpe/brickr: 3D LEGO models and mosaics from images using R and #tidyverse · GitHub](https://github.com/ryantimpe/brickr)
29. [(PDF) An empirical study of latency in an emerging class of edge computing applications for wearable cognitive assistance](https://www.researchgate.net/publication/320836425_An_empirical_study_of_latency_in_an_emerging_class_of_edge_computing_applications_for_wearable_cognitive_assistance)
30. [Impact of delayed response on wearable cognitive assistance - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7987160/)
31. [Offload Shaping for Wearable Cognitive Assistance](https://doi.org/10.3390/electronics13204083)
32. [An Empirical Study of Latency in an Emerging Class of Edge Computing](https://www.cs.cmu.edu/~zhuoc/papers/latency2017.pdf)
33. [Impact of delayed response on wearable cognitive assistance](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7987160/)
34. [Impact of delayed response on wearable cognitive assistance](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0248690)
35. [Impact of delayed response on Wearable Cognitive Assistance](https://arxiv.org/pdf/2011.02555)
36. [Psychological Science Meets Wearable Cognitive Assistance - Roberta L. Klatzky, Mahadev Satyanarayanan, 2023](https://journals.sagepub.com/doi/full/10.1177/09637214231187912)
37. [Realistic Modeling of Human Timings for Wearable Cognitive Assistance](https://arxiv.org/pdf/2212.06100)
38. [𝜏-Voice: Benchmarking Full-Duplex Voice Agents on Real-World Domains](https://arxiv.org/html/2603.13686v1)
39. [Quantifying Latencies: A Conversation Analysis Approach to Human-Agent Interactions in Virtual Reality](https://dl.acm.org/doi/10.1145/3772318.3790947)
40. [Mitigating Response Delays in Free-Form Conversations with](https://arxiv.org/pdf/2507.22352)
41. [345 Understanding User Perceptions of Response Delays in](https://dl.acm.org/doi/pdf/10.1145/3555765)
42. [The Impact of Latency in Speech-Driven Conversational AI Applications](https://www.agora.io/en/blog/the-impact-of-latency-in-speech-driven-conversational-ai-applications/)
43. [WebRTC Call Quality Testing for Voice Agents](https://hamming.ai/resources/webrtc-call-quality-testing-voice-agents)
44. [Voice Agent Troubleshooting: Complete Diagnostic Checklist](https://hamming.ai/resources/voice-agent-troubleshooting)
45. [WebRTC LLM Streaming: Real-Time Voice Agent Infrastructure on GPU Cloud](https://www.spheron.network/blog/webrtc-llm-streaming-voice-agent-gpu-cloud/)
46. [Introducing gpt-realtime and Realtime API updates for production voice agents](https://openai.com/index/introducing-gpt-realtime/)
47. [OpenAI GPT-Live plugin guide](https://docs.livekit.io/agents/models/realtime/plugins/gpt-live/)
48. [How we built a realtime system for responsive voice AI in six months](https://openai.com/index/continuous-voice-interaction-with-gpt-live/)
49. [Gemini Live API reference](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/model-reference/multimodal-live)
50. [Limits and specifications of the Live API](https://firebase.google.com/docs/ai-logic/live-api/limits-and-specs)
51. [Live API capabilities guide](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
52. [Video understanding](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding)
53. [Video](https://docs.livekit.io/agents/multimodality/vision/video/)
54. [OpenAI Realtime API plugin guide](https://docs.livekit.io/agents/models/realtime/plugins/openai/)
55. [Gemini Live API plugin](https://docs.livekit.io/agents/models/realtime/plugins/gemini/)
56. [GitHub - livekit-examples/vision-demo: Open-source voice + video AI assistant built on LiveKit · GitHub](https://github.com/livekit-examples/vision-demo)
57. [Issues in combining 26c-gemini-multimodal-live-video.py and 21-tavus-layer.py · Issue #979 · pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat/issues/979)
58. [GitHub - kiarashplusplus/expo-gemini-live: Pipecat Gemini Live Demo End-to-end starter kit for building a realtime Pipecat experience that pairs a FastAPI backend with an Expo/React Native client. · GitHub](https://github.com/kiarashplusplus/expo-gemini-live)
59. [Vision Agent Quickstart](https://docs.livekit.io/agents/quickstarts/vision/)
60. [GitHub - automateyournetwork/GeminiCLI\_Vision\_Extension: An Extension for Gemini-CLI that enables Webcam access including single frame capture and American Sign Language (ASL) modes · GitHub](https://github.com/automateyournetwork/GeminiCLI_Vision_Extension)
61. [Moondream Vision - Pipecat](https://docs.pipecat.ai/server/services/vision/moondream)
62. [Gemini Realtime Agent with Live Vision](https://docs.livekit.io/recipes/gemini_live_vision/)

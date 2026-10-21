# TODO

## 实验设计

- [ ] 基线：好网络下跑两条架构，量判定准确率和每段延迟（委托 → 大脑 → 开口 → 眼镜播出）。误判和本底延迟要低到实验里测的是网络不是模型，这是进实验的门槛。
- [ ] 丢包档位：主变量是丢包，打在语音双向和眼镜上行视频上，可能再交叉延迟。档位要靠 pilot 定：最低一档刚好听得出、看得出，最高一档任务还能完成。Cortés 2024 的延迟档是 300 / 600 / 900 / 1200 / 1500 ms，10 人 pilot 定的。
- [ ] 任务和顺序：任务数等于条件数，每个被试每个任务搭一次、每个条件经历一次，任务 × 条件按拉丁方平衡，顺序随机；另备一个训练任务，不进正式。13 个 5 步任务的难度是否相近、一个 trial 要几分钟，pilot 里验。
- [ ] 眼镜上留什么：现在是状态条 + 步骤列表 + 双方字幕，没有参考图。正式实验前裁到参考图 + 当前步，屏幕上信息越少，被试越依赖被测的语音链路。参考图怎么出（图片、几个角度）没定。
- [ ] 主观量表：Cortés 2024 每个条件后问 11 题、5 级。全局质量、系统烦扰、延迟感知、打断难度（P.920 / P.1305）；投入、适应、完成信心（存在感）；社交存在、理解、配合、信息有用（Gupta）。他们是人对人，我们是人对助手，社交存在、配合这类题要换或删，剩下的留。
- [ ] 流程：筛查 → 前测问卷 → 训练 → 每个条件一个 trial + 条件后问卷 → 后测问卷，整场不超 90 分钟（P.1321）。按条件数算一场多长。

## 系统

### 重要

- [ ] **最重要**：延迟打点重做（2026-10-20 定）。要量的是不管有没有委托，佩戴者说完最后一个字到 Live 开口的沉默，再切成上行、模型、下行三段。现在的量法不对：report.py 的分段以 delegation.created 为终点，只覆盖委托回合；起点用眼镜日志 `wearer sound stops`，其阈值 1000 比真实尾音高，边沿早 0.2–1.5 s，2026-10-19 四次运行据此算出的"讲完到委托 3.2 s"实为约 2.7 s，直接回答的回合按录音量是约 1 s。GPT-Live 不发 VAD 事件，能用的只有 `input_transcript.delta` 的 end_ms、`delegation.created` 的 offset_ms（同一时间轴，原点未明，对墙钟三分钟漂 1.5 s）和第一块 `output_audio.delta` 的到达时刻。
  - 四个点，每个回合一行，全部 wall clock，眼镜的经 clock.json 对到服务端轴：T1 眼镜麦克风轨最后一个响帧（SpeechEdgeLog，阈值降到约 500，hangover 提到 800 ms，和插件一致）；T2 agent 端输入音频转安静的时刻（插件已算 quiet_ms，记最后一个响帧）；T3 该回合第一块 output_audio.delta 到达 agent 的时刻；T4 眼镜 agent 音轨第一个响帧（现有阈值 500，已对录音验证准）。T4−T1 是佩戴者经历的沉默，T2−T1 上行，T3−T2 GPT-Live，T4−T3 下行。
  - 眼镜的两个点是主量，agent 的两个点是拆分：netem 整形的是眼镜到 livekit-server 这一跳，agent 侧的 T3−T2 在任何网络条件下都不变，只靠它看不到网络的影响。两端用同一套判定（RMS 阈值加 hangover），差值才干净地等于网络加抖动缓冲。句中停顿把一句切成几段不影响，取 Live 开口前最后一个停止边沿即可。
  - 另记 delegation.created 给回合打标签，input_transcript.delta 的 end_ms 和 delegation 的 offset_ms 作模型内部时间的参考。report.py 对每个回合而不只是委托算一行，有录音时用录音校验，正式实验不录音。
  - visual frame age 拆两段：agent 持有（帧到 FrameTap 到 look_sent，已有）；眼镜到 agent 不逐帧量，Python SDK 的 timestamp_us 是接收侧时间，用眼镜每 5 s 的 rtt 和编码器状态加 agent 端接收统计的 jitterBufferDelay 估，netem 加的延迟是已知量。逐帧精确只能靠录音的 video.csv。
- [x] Gemini 路径真机跑通（2026-10-13 实验室四次运行，见下节）
- [ ] 系统性测试：Gemini Live 一体化 vs GPT-Live 配合不同后端模型，看整体的响应时间和效果，50% pre 时展示

### GPT 路径（大脑）

- [x] 主动观察（watch）：没有委托时大脑一张接一张看，最少间隔 BRAIN_WATCH_EVERY=2 s，768 不思考；工具 note（记进大脑的时间线，to_voice 时以 thinking 给 Live）、say（下一次 watch 也调 say 才以 commentary 让 Live 说）、set_progress；不调工具就什么都不留。委托来时取消正在跑的 watch。2026-10-19 实验室跑了三轮，用户认为弥补了之前的问题
- [ ] 保留意见：委托来时如果 watch 发出不到 1 s，不取消，让它的结论带上委托 id 当回答（watch 不知道问题，可能答不上）
- [ ] 端到端延迟的最后一段：记录里已有委托 → 大脑回复 → Live 开口，还缺眼镜播出，要在眼镜本地按真实声音计时
- [ ] 对比模型和图片尺寸对延迟的影响

### Realtime 路径（PoC）

2026-10-19 加的第三条路：gpt-realtime-2.1 自己听、看、说，用 set_progress 推进度；说话时每秒一帧、不说话约 3 s 一帧，帧是底部正方形 1080。

- [ ] 真机跑一次乐高：判对率、set_progress 是否该调就调、调完会不会重复播报、每帧多少 image token、上下文随帧怎么涨、回复延迟

### Gemini 路径

2026-10-13 实验室四次运行的结论：Live API 给一帧最多 280 token（MEDIA_RESOLUTION_HIGH），模型认得出颜色和大件形状，数不清颗粒，2x6 近看读成 1x6 或 2x4；乐高任务留给 GPT 路径。2026-10-16 起 Gemini 路径去掉了乐高任务和 set_progress，是不带任务的通用助手：中间正方形 768x768，提示词、音色 Kore、MEDIA_RESOLUTION_LOW、默认滑动窗口和不先开口都照 rayneo-x3-pro-gemini-live；拿来做什么任务，没定。

- [ ] 待定：Gemini 路径是否换一个 P.1321 任务。看过的候选是 Annex D 寻宝（多人非对称，B 在真实房间找线索，A 持清单和密码表解码），模型只需认大件物品和对话，符号可以由 B 念给它查表。只是候选，没有决定做
- 工具跟着话触发、工具返回后重复（set_progress 的两个问题）随乐高任务一起去掉了；以后再给 Gemini 加工具时还会碰到，届时试 tool_response_scheduling=SILENT
- [ ] extended thinking 搁置：gemini-3.8-live-extended-thinking 用 interaction_status 协议（IN_PROGRESS / REQUIRES_ACTION / IDLE），锁定的 google-genai 2.18.1 不认 IDLE，plugin 1.8.3 不读该字段，模型"查看中"17 s 后报系统错误、工具调用没发出。等 livekit-agents 和 google-genai 跟上再试；GEMINI_THINKING_LEVEL 留在 config.py

### 眼镜

- [ ] UI用户自己说的话可以就留一行，一直更新，而不是顶掉上面，这样可以更多保留agent说的话
- [ ] 显示当前步要找的砖和它的摆放位置，降低任务难度和时间消耗
- [ ] 音量：通话流扬声器只有 1/15，通话中按音量键调；不够再在 agent 加增益
- [ ] 功耗：电量日志，跑一次完整通话看续航
- [ ] 实验结束后 `glasses.ps1 -RestoreSleep`

### 部署

- [ ] 正式实验前关掉 livekit-server 的 ICE-TCP（`deploy/livekit.lab.yaml` 的 `tcp_port: 7881`，2026-10-20 定）。netem 整形的是眼镜到服务器这一跳，丢包大到 ICE 判 UDP 断了时会悄悄切到 TCP，测到的就成了 TCP 重传而不是丢包，日志里也不显眼。眼镜 SDK 没限制传输类型，UDP 和 TCP 候选都出。关掉后 UDP 不通就直接断，当一次失败的 trial。没有 TURN 和 TLS，不用动。
- [ ] 丢包注入由网络侧软件做并自带记录，本系统对它是黑箱；眼镜端每 5 s 记链路实测（RTT、丢包、编码器状态、下行 jitter buffer）和语音起止的 wall clock，pull_run.py 拉成 glasses.log，并经 adb 和 ssh 量出眼镜对服务器的时钟偏移写进 clock.json
- [ ] 结束后 app 偶尔自动重连开新会话（疑似误触），留意

### 搁置

- 任务由另一个 app 经 websocket 和眼镜通信来选（现在是眼镜上的列表）

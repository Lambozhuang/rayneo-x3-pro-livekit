# TODO

## 实验设计

- [ ] 基线：好网络下跑两条架构，量判定准确率和每段延迟（委托 → 大脑 → 开口 → 眼镜播出）。误判和本底延迟要低到实验里测的是网络不是模型，这是进实验的门槛。
- [ ] 丢包档位：主变量是丢包，打在语音双向和眼镜上行视频上，可能再交叉延迟。档位要靠 pilot 定：最低一档刚好听得出、看得出，最高一档任务还能完成。Cortés 2024 的延迟档是 300 / 600 / 900 / 1200 / 1500 ms，10 人 pilot 定的。
- [x] 任务和顺序：由控制台定，这边不管。眼镜收到 start_task 就按号开积木，收到 end_task 或双击就结束，结束后交日志；训练任务是任务表的前三个（ladder、flag、crane，2026-11-03 定），正式任务是其余十个，控制台按阶段内编号来叫，眼镜换算成表上的号（Lab.TRAINING_TASKS）。拉丁方、任务配条件、每场几个 trial 都是控制台的设计器里配的，不是这个系统要实现的。
- [ ] 眼镜上留什么：2026-10-28 起是状态条 + 步骤列表 + 双方字幕 + 相机底部正方形的预览，步骤图只在佩戴者要求或接受提议时出现（Anders 10-27 的反馈：图不能一直给，要促进佩戴者和助手的沟通；预览让佩戴者知道助手看得见什么）。正式实验前还要定字幕留不留，屏幕上信息越少，被试越依赖被测的语音链路。
- [ ] 主观量表：Cortés 2024 每个条件后问 11 题、5 级。全局质量、系统烦扰、延迟感知、打断难度（P.920 / P.1305）；投入、适应、完成信心（存在感）；社交存在、理解、配合、信息有用（Gupta）。他们是人对人，我们是人对助手，社交存在、配合这类题要换或删，剩下的留。
- [ ] 流程：筛查 → 前测问卷 → 训练 → 每个条件一个 trial + 条件后问卷 → 后测问卷，整场不超 90 分钟（P.1321）。按条件数算一场多长。

## 系统

### 重要

- [ ] **最重要**：延迟打点重做（2026-10-20 定）。要量的是不管有没有委托，佩戴者说完最后一个字到 Live 开口的沉默，再切成上行、模型、下行三段。现在的量法不对：report.py 的分段以 delegation.created 为终点，只覆盖委托回合；起点用眼镜日志 `wearer sound stops`，其阈值 1000 比真实尾音高，边沿早 0.2–1.5 s，2026-10-19 四次运行据此算出的"讲完到委托 3.2 s"实为约 2.7 s，直接回答的回合按录音量是约 1 s。GPT-Live 不发 VAD 事件，能用的只有 `input_transcript.delta` 的 end_ms、`delegation.created` 的 offset_ms（同一时间轴，原点未明，对墙钟三分钟漂 1.5 s）和第一块 `output_audio.delta` 的到达时刻。
  - 四个点，每个回合一行，全部 wall clock，眼镜的经 clock.json 对到服务端轴：T1 眼镜麦克风轨最后一个响帧（SpeechEdgeLog，阈值降到约 500，hangover 提到 800 ms，和插件一致）；T2 agent 端输入音频转安静的时刻（插件已算 quiet_ms，记最后一个响帧）；T3 该回合第一块 output_audio.delta 到达 agent 的时刻；T4 眼镜 agent 音轨第一个响帧（现有阈值 500，已对录音验证准）。T4−T1 是佩戴者经历的沉默，T2−T1 上行，T3−T2 GPT-Live，T4−T3 下行。
  - 眼镜的两个点是主量，agent 的两个点是拆分：netem 整形的是眼镜到 livekit-server 这一跳，agent 侧的 T3−T2 在任何网络条件下都不变，只靠它看不到网络的影响。两端用同一套判定（RMS 阈值加 hangover），差值才干净地等于网络加抖动缓冲。句中停顿把一句切成几段不影响，取 Live 开口前最后一个停止边沿即可。
  - 另记 delegation.created 给回合打标签，input_transcript.delta 的 end_ms 和 delegation 的 offset_ms 作模型内部时间的参考。report.py 对每个回合而不只是委托算一行，有录音时用录音校验，正式实验不录音。
  - visual frame age 拆两段：agent 持有（帧到 FrameTap 到 look_sent，已有）；眼镜到 agent 不逐帧量，Python SDK 的 timestamp_us 是接收侧时间，用眼镜每 5 s 的 rtt 和编码器状态加 agent 端接收统计的 jitterBufferDelay 估，netem 加的延迟是已知量。逐帧精确只能靠录音的 video.csv。
- [ ] 系统性测试：Gemini Live 一体化 vs GPT-Live 配合不同后端模型，看整体的响应时间和效果，50% pre 时展示
- [ ] H.265 迁移上机（2026-11-03 定，编码不是实验因子）：眼镜改发 H.265，agent 在 lab PC 的 RTX 2080 Ti 上用 NVDEC 解，libwebrtc 没有 H.265 软解，agent 从此只能跑在有 NVIDIA 卡的机器上（家里的机器先不管）。代码已改、未上机。顺序：lab PC 装 nvidia-container-toolkit；用一次性容器连本地 livekit-server 看 agent 日志出现 NvidiaVideoDecoderFactory；上机一次看 rayneo-link 的 encoder 是 c2.qti.hevc.encoder、记录的 decoder 事件是 NVIDIA H265 Decoder 且有帧、大脑照片正常。依据：eval/brain-frame-codec 的 0.1 Mbps 行，H.265 撑到 0.25 Mbps、0.1 垮，H.264 撑到 0.5、0.25 垮。

### GPT 路径（大脑）

- [ ] **2026-11-04 晚的新结构上机**（在家改的，lab PC 连不上，三件在 eval/agent-sim 上用 16:44 和 10-28 两场的录像联调过，没上真机）：眼睛是 Decisions API（gpt/eyes.py，gpt-6-luna，每帧两个请求七个问题，0.3 到 0.4 s，手在动 0.7 s 一看、静止 2 s、用户开口立刻看），状态机按两次一致出事实行；voice 按 OpenAI 的 Prompting GPT-Live 模板是视频通话里的指导者，从事实行组织语言；terra 只在需要文字时被叫一句（gpt/consult.py：放了但没放对、用户问眼前的事或不同意、说放好了但 2.5 s 内快眼没判定），无对话无缓存。lab PC 的 .env 要加 BRAIN_TRANSPORT=ws、BRAIN_QUICK_MODEL=gpt-6-luna、BRAIN_QUICK_DETAIL=low、BRAIN_QUICK_EVERY=2、BRAIN_CONSULT=on，少一个 agent 不起；BRAIN_WATCH_EVERY 不再读。BRAIN_CONSULT=off 是方案 D：只有快眼判对错，放错只说 not quite 加复述位置加提议看图，问眼前的事按快眼读数答；真机上两种各跑一轮比一比。真机要听：拿起砖到 "yep, that's the one" 几秒、手离开到 "that's step N" 几秒、放错时 "not quite" 和 terra 那句之间隔多久、放对了有没有被误报 not quite（quick 事件里 right 的值和 step 事件的 basis）、voice 一回合多长、误委派几次（delegation）、Decisions 的 503 几次（quick_failed）。不行回 tag instructor-a（2026-11-04 晚的上一版：terra 每 2 s 看加快眼）或 pilot2-agent。
- [ ] 语音重复说同一件事（2026-11-02 第四场 logs/20261102-132502-glasses-ef10b896，111 到 132 s）。brain-v4 暂时接受，用户决定先不改。看到的：(1) 规则 3 的 tell 和规则 4 的 say 单子重叠，"一步放对或放错"两边都命中，大脑同一轮既 tell 又 say（w42），"放对"又和 Progress 重复（w10）；(2) GPT-Live 会念 tell，又不去重 commentary，所以同一事实两条通道各念一遍；(3) 助手的话在一段结束时才进 history，这一段拖了 20 s，大脑 say 时看不见助手正在说什么；(4) 语音说话占这场 71% 的时间，若 watch 等它说完再发，盲区太大；只在上一轮 tell/say 后才等的变体抓不住反应延迟。可选的改法按简单到复杂：tell 和 say 的单子分开，拿错砖归 say，放对不 tell，已 tell/say 过的不再 say；接 GPT-Live 的 output_transcript.delta 让大脑看见正在说的话；定向等待。缓存已验证：未缓存部分稳定在约 1450 token 一轮
- [ ] 第二次 pilot 的 agent 侧改动上机（2026-11-04 下午改，user-study/pilot-2/issues.md A1 到 A5；重放和替身检查过）：大脑不再要姿势、手里只认颜色、看不清就说没看到什么；camera.py 每 5 s 记 stream 事件（kbps、fps、weak），弱时每分钟告诉大脑一次让 voice 说画面糊；（门和待定步骤 2026-11-04 下午上机两场后拆掉了：voice 一回合说 5 到 12 s，每句都等到过时，比积压连念更糟。）真机看：弱网下有没有 turn/closer 这类话、画面糊那句一场几次、voice 还有没有连念旧话和抢话、step 事件前有没有 progress_pending。A7 系统下拉菜单和语音助手误触还没做。
- [ ] 大脑按变化说话 + say 分 news/waiting 限频（2026-11-04 上午，重放过，真机上听 0.25 Mbps 下的话量和语气，看 say_held 的数量；开场白多了一句能力说明，voice-script 上听过 46 词 11 s，长了可以再砍）。
- [ ] watch-only 上机验证（2026-11-03 第一次 pilot 的反馈，docs/pilot/2026-11-03-feedback.md；17:00 上机一场后 voice 的提示词又改了三处，晚上在 eval/voice-script 上离线过了剧本，下次上机听真机）：look 整个去掉，voice 的提示词不再转交、按 helper 说过的事实答，需要眼睛的话说一句等 helper 的下一行；大脑拿对颗粒就 say（之前只 tell，被试觉得太沉默）、放错一次就提议看图（之前两次）、用户问眼前的事用 say 答。GPT-Live 的 session 没有不带 delegation 的选项，所以它自己转交时 brain.on_delegation 立刻用一句 commentary 关掉，不拍照；记录里 delegation 事件数就是提示词没管住的次数，上机要听 voice 被关掉后怎么接。跟着要清的：眼镜的 Thinking 状态没人设了（Phase.kt 读 rayneo.brain.looking），下次改眼镜时去掉；docs/diagrams/gpt-live-agent.png 还画着委托，要重画；report.py 的 hand-over 等待图从此为空，归到下面记录与分析的整理里。
- [x] 保留意见：委托来时如果 watch 发出不到 1 s，不取消，让它的结论带上委托 id 当回答。2026-11-03 look 整个去掉了，不再适用。
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

- [ ] lab 模式给被试的改动（2026-11-03 深夜，模拟器上看过，真机上要跑一场）：任务自己结束（大脑记完最后一步、voice 说完并静 2 s，agent 发 rayneo.call.over，眼镜等本地 agent 声音静 1 s 再挂断，ended_by=finished，gpt/agent.py `_end_when_finished`），lab 模式下双击无效、三连击是实验员的（结束这场或退回菜单，模拟器上试过），lab 屏幕只剩给被试的一句话（Lab.stage），带 -Lab 启动直接进 lab 屏幕，通话中标题行右端显示剩余时间。真机要看：完成后几秒挂断、voice 的最后一句有没有被切掉、报告里 ended_by 和 completed、控制台怎么收这个结束。glasses.ps1 默认 -Exposure 现在是 -2（2026-11-04 定，-6 把黄看成橙），看一眼 rayneo-call 的 exposure 行。Thinking 状态和 rayneo.brain.looking 已从眼镜端删掉。
- [ ] UI用户自己说的话可以就留一行，一直更新，而不是顶掉上面，这样可以更多保留agent说的话
- [ ] 相机预览在加法显示上亮不亮、要不要压暗；两个眼各一个渲染器的功耗。按需步骤图的行为本身已验（2026-10-28 两场、2026-11-02 四场：要图或答应提议后 0.4 到 2.6 s 到眼镜）
- [ ] 步骤图在 netem 丢包下晚到时的体验，以及是否要让语音知道图可能未到。好网络下的到达延迟已验：属性公布到眼镜显示 50 到 100 ms（2026-10-28 和 2026-11-02 的 glasses.log）
- [ ] 音量：通话流扬声器只有 1/15，通话中按音量键调；不够再在 agent 加增益
- [ ] 功耗：电量日志，跑一次完整通话看续航
- [ ] 实验结束后 `glasses.ps1 -RestoreSleep`
- [ ] lab 模式 2026-11-02 上机一轮行为对了：控制台 start_task 开通话、双击结束、眼镜和 agent 的两份上报都到（agent 的一份原来晚 20 s，等 livekit-server 关房间，已改成 session 一关就结束 job）。同日按 QoE Lab 那边 agent 的审查改的几处还没再上机：控制台主动关 socket（onClosing）和 replaced 不再重连、start_task 时开不了通话立刻上报、任务表加载完才连 socket、agent 先走时上报最后一次公布的进度、pending 文件两个进程抢

### 记录与分析

- [ ] 给 QoE Lab 的两份上报 2026-11-03 过了一遍：agent 的 log（整份 events.jsonl 加 brain.txt、voice.txt、brain-tools.json 和 build 终态，照片不传）不缺，时间都是相对 call 开始的 t，不改；眼镜的 log 原来只有总结 {room, task, task_number, steps_done, steps_total, completed, ended_by}，同日加了 events（CallLog.kt：链路统计、agent 声音到达解码器的起止、图片到达和上屏、通话边界，每条 t_ms 相对任务开始），佩戴者侧的麦克风阈值边沿不进上报（噪声多，以服务端 state 事件为准），logcat 行和 pull_run.py 不变。还没上机。待定：服务器时钟和控制台时钟之间没有偏移测量（控制台只测眼镜的），实验室里仍靠 pull_run.py 的 clock.json，要不要进上报
- [ ] 日志记录结构和分析脚本要整理（2026-11-02 用户提出，混乱）。现状：runlog 的 events.jsonl 一种事件一种字段（watch_sent/look_sent 带 lines 和 looks，旧记录带 said；say/tell/picture 事件按 w 或 n 挂到 look 上；voice_started 和 voice_joined 两种时序事件），report.py 兼容三代记录格式，分析每次都是临时 python 脚本（本次 session 的时间线、token 增长、thinking 对照都是一次性写的）。要定的：事件和字段的一套命名，一个命令出每场的常规分析（进度轨迹、tell/say/picture、每次 look 的 in/cached/ms、委托到开口的延迟），旧格式要不要再兼容

### 部署

- [ ] 正式实验前关掉 livekit-server 的 ICE-TCP（`deploy/livekit.lab.yaml` 的 `tcp_port: 7881`，2026-10-20 定）。netem 整形的是眼镜到服务器这一跳，丢包大到 ICE 判 UDP 断了时会悄悄切到 TCP，测到的就成了 TCP 重传而不是丢包，日志里也不显眼。眼镜 SDK 没限制传输类型，UDP 和 TCP 候选都出。关掉后 UDP 不通就直接断，当一次失败的 trial。没有 TURN 和 TLS，不用动。
- [ ] 丢包注入由网络侧软件做并自带记录，本系统对它是黑箱；眼镜端每 5 s 记链路实测（RTT、丢包、编码器状态、下行 jitter buffer）和语音起止的 wall clock，pull_run.py 拉成 glasses.log，并经 adb 和 ssh 量出眼镜对服务器的时钟偏移写进 clock.json
- [ ] 结束后 app 偶尔自动重连开新会话（疑似误触），留意


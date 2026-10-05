# 判定器离线评测：结果记录

本文件由 `python eval/results_table.py` 生成：下面的文字来自 `eval/results_notes.md`，表格来自
`eval/truck/results/` 里的原始记录。看完这一页应该不需要再问"当时测的是什么"。

## 一句话

在录好的一次搭建（13 步、3 处可测的故意错误）上，**gpt-6-sol、不开推理、关系式 prompt（terse2）、服务器端裁板**
是目前的判定器配置：原始画质 29 问全对，通话流画质 28/29，单次约 2 s（TTFT 约 1.1 s）。整条
"门控 → 判定 → 状态机"回放在原始画质下 13 步全部 1 s 内跟上、3 个错都报、零误报；通话流画质下第 5 步
（两条并排白砖）判定不稳，状态机要求连续两帧才确认时会卡死，单帧确认则跟得上但多一个误报。

## 测的是什么

**素材**：`truck/run1/` 三段录像，眼镜自带相机，2432×1824、HEVC、30 fps、约 18 Mbps，竖幅。按 1 fps 抽帧共 148 帧
（part1 62、part2_p1 61、part2_p2 25），帧号 = 秒 + 1。真值在 `truck/events.json`：每步"砖到位且手离开"的秒数、
3 处故意放错的区间、2 段看别处。

**两种帧源**
- 原始帧：上面的 2432×1824。裁板后底板约 820 px 宽，一格约 45 px。
- 1080p15 派生帧：同一段视频用 ffmpeg 转成 1080×1440、15 fps、H.264、4 Mbps（`-preset veryfast -tune zerolatency`），
  模拟 app 发给 LiveKit 的通话流规格（app 实际是 1920×1080 15 fps 4 Mbps 横幅，底板像素占比还没用真实流核对）。
  裁板后约 480 px 宽，一格约 27 px。

**送进模型的东西**（每问一次独立调用）
- 系统提示（固定）+ 一段按步生成的用户文本 + 一张照片。照片 = 服务器端裁出的底板（绿色掩码 → 闭运算 → 最大连通块
  → 加 10% 边距），JPEG q90，OpenAI 侧 detail=high。这叫 C 路线；最早一轮的 B 路线发整帧 768×1024，之后没再用。
- 用户文本来自 `truck/layout.json` 每步的 `name`（已放的砖）、`where`（本步加什么、放哪）、`checks`（3–4 条可核对的关系），
  例如第 6 步：

  ```
  Already on the plate from earlier steps: red slope 3x4; purple 2x4 cab; green 1x2 exhaust; white 1x6 top; white 1x6 middle.
  Step 6 adds the blue 1x4 brick lying flat directly under the lower white brick, its left end touching the purple brick, ...
  Facts to check:
  1. the blue brick's left end touches the purple brick
  2. it sits directly under the lower white brick with no gap
  3. its right end is two studs short of the white bricks' right end
  ```
- 模型先用一句话描述看到了什么，再逐条答 y / n / ?，最后给四选一：correct / wrong / not_placed / cannot_see，JSON。
- 每个结果目录里 `prompt.txt` 是当次的系统提示和参数；jsonl 每行的 `question` 是当次发出的用户文本原文，`raw` 是模型原始回复；
  同目录 `*_photo.jpg` 是发出的照片字节。**措辞改过多版（见下），同名配置两次结果可能用的不是同一版文字，以 jsonl 为准。**

**prompt 版本**（`judge_eval.py --prompt`）
- `grid`：带行列编号的目标图 + "第 N 步在列 a–b 行 c–d"，四选一。模型复述坐标不看图，废弃。
- `relational`：人话事实，先描述再逐条 y/n，完整输出。
- `terse`：同上，输出压到一句描述 + 字母串。
- `terse2`：terse 的 seen 从"这步的砖在不在、什么样"改成"该位置上有什么、几排凸点、挨着什么"。**当前默认。**
- `checks`：不描述只答 y/n。`image`：不给文字事实，只给无编号目标图 + 一句问。两者都更差，只试过一轮。

**模型与参数**（都从 .env 读）
- gpt-6-luna：推理 none / low / 默认。gpt-6-sol：推理 none（sol 不支持 temperature）。
- qwen3.8-27b（OpenRouter）：不开思考 / 开思考；自由路由、钉 DekaLLM；钉 Cerebras fp16 上游 429，三次都没跑成。
- claude-sonnet-5.5（OpenRouter，azure/global 端点，reasoning minimal）。

**题集**
- `rest.json` 29 问：每个"手离开、板静止"的状态挑一帧。13 个刚放好（期望 对）、3 个放错（期望 错）、13 个下一块还没放（期望 未放）。
  第 8 步的故意错误全程手在板上，静止判定器按设计看不到，不在题集里。
- `rest6.json`：3 个放错 + 各自修正后的帧（Q8 Q9 Q13 Q14 Q22 Q23），用来快速比模型和推理设置。
- `rest_disc.json`（Q22 Q23）、`rest_fix.json`、`rest_hands.json`：针对单个问题的小集，见"其他探索"。

**延迟**：从发出请求到收完回复，流式；TTFT = 到第一个输出 token。在公司笔记本上量，含网络。

## 结论

- 坐标和图对比都不行，人话事实行。网格 prompt 3 个错全漏（luna 24/29）；纯两图 3/6；关系式事实能把 3 个错都捉到。
- 事实的措辞决定误报。踩过的坑：`standing upright` 被当成 3D 立起（改成"长边前后向"）；"中高度"、"到板边"、"排气管在正上方"、
  "底边齐平"、"和斜坡同宽对齐"都会在正确帧上误报；两条并排同色砖说成"第二条砖"会被答"只有一条"。
- 不开推理时 sol 比 luna 稳：luna none 四次 3–5/6 随机，sol none 三次都 5/6（只漏后轮偏 2 格）。luna low 6/6 但 4–5 s。
- 换模型没有更好：Qwen 不开思考 3–5/6 且路由抖动大，开思考 5/6 但 4–115 s；Sonnet minimal 在 1080p 上 27/29（两问因自我纠正
  写了两个 JSON 被记成无效，实际答对），漏的和 sol 一样。
- 延迟 ≈ 输出 token ÷ 约 70 tok/s，TTFT 1–1.5 s 是看图的固定成本；1 s 以内任何 VLM 都做不到。
- 分辩率是真瓶颈：同一配置原始帧 29/29，1080p 派生帧 26–28/29；两条并排白砖在 1080p 下合成一块（Q11），后轮偏 2 格看不出（Q22）。
  眼镜端裁切不做（用户决定）；提高通话流分辩率是可选项，没动。
- 回放证明流水线结构成立；1080p 下第 5 步那块砖的判定每帧约 1/3 概率答对，"连续两帧确认"会卡死，单帧确认能过。确认策略待接
  GPT-Live 后按误报接受度定，不在这里定。

## 措辞版本（按时间）

1. 初版 13 步 where/checks。
2. 删第 4 步"排气管在左端正上方"、第 6 步"底边和红紫砖齐平"（在正确帧上误报）。
3. 第 10 步改为"车尾门正下方是裸板 / 右缘在浅绿砖右端左侧 / 两盘间隙比一个盘窄"，随后删间隙条；"tail door"换成"车身右端的白色 1×4"。
4. 第 1/2/3/5/8/13 步：`standing upright` → 长边前后向；"中高度" → 上下都有空凸点；"到板边" → 该行右边没有空凸点；第 5 步加"白色区域两格深"。
   → `rest_C_gpt-6-sol_high_none_terse_v2` 29/29 用的是这一版。
5. 第 5 步改成"白色区域变成两排凸点深的 2×6 白块"，不提"第二条砖"。→ 所有 `terse2` 结果和回放用的是这一版。

## 29 问是哪些

帧号 = 片段内秒数 + 1；下表用秒。每问只问当前步，期望答案由真值（events.json）给出。

| 编号 | 片段 / 秒 | 问第几步 | 那块砖 | 期望答案 | 画面里是什么 |
|---|---|---|---|---|---|
| Q1 | part1 2 s | 1 | red slope 3x4 | 未放 | empty plate at rest |
| Q2 | part1 9 s | 1 | red slope 3x4 | 对 | red slope just placed, hands off |
| Q3 | part1 11 s | 2 | purple 2x4 cab | 未放 | same state, a bit later |
| Q4 | part1 15 s | 2 | purple 2x4 cab | 对 | purple placed |
| Q5 | part1 17 s | 3 | green 1x2 exhaust | 未放 |  |
| Q6 | part1 23 s | 3 | green 1x2 exhaust | 对 | lime exhaust placed |
| Q7 | part1 24 s | 4 | white 1x6 top | 未放 |  |
| Q8 | part1 28 s | 4 | white 1x6 top | 错 | tan 1x6 on row 6 instead of white |
| Q9 | part1 34 s | 4 | white 1x6 top | 对 | white top after the fix |
| Q10 | part1 35 s | 5 | white 1x6 middle | 未放 |  |
| Q11 | part1 41 s | 5 | white 1x6 middle | 对 | white middle placed |
| Q12 | part1 42 s | 6 | blue 1x4 lower-left | 未放 |  |
| Q13 | part1 45 s | 6 | blue 1x4 lower-left | 错 | blue 1x4 shifted right (~cols 9-12) |
| Q14 | part1 51 s | 6 | blue 1x4 lower-left | 对 | blue after the fix |
| Q15 | part1 52 s | 7 | green 1x2 lower-right | 未放 |  |
| Q16 | part1 58 s | 7 | green 1x2 lower-right | 对 | lime lower-right placed |
| Q17 | part1 60 s | 8 | white 1x4 at the right end of the body, long side front to back | 未放 |  |
| Q18 | part2_p1 10 s | 8 | white 1x4 at the right end of the body, long side front to back | 对 | tail door after the fix |
| Q19 | part2_p1 24 s | 9 | red disc front wheel | 未放 | after the distraction, no disc yet |
| Q20 | part2_p1 30 s | 9 | red disc front wheel | 对 | front disc placed |
| Q21 | part2_p1 30 s | 10 | red disc rear wheel | 未放 | same frame, next step |
| Q22 | part2_p1 38 s | 10 | red disc rear wheel | 错 | rear disc too far right, under the tail door |
| Q23 | part2_p1 48 s | 10 | red disc rear wheel | 对 | rear disc after the fix |
| Q24 | part2_p1 50 s | 11 | tan 1x6 ground left | 未放 |  |
| Q25 | part2_p1 55 s | 11 | tan 1x6 ground left | 对 | tan 1x6 placed |
| Q26 | part2_p1 55 s | 12 | white 1x6 ground mid | 未放 | same frame, next step |
| Q27 | part2_p1 59 s | 12 | white 1x6 ground mid | 对 | white 1x6 ground placed |
| Q28 | part2_p1 59 s | 13 | yellow 1x4 ground right | 未放 | same frame, next step |
| Q29 | part2_p2 2 s | 13 | yellow 1x4 ground right | 对 | yellow 1x4 placed; all done |

## 29 问各配置结果

| 结果文件（模型_图detail_推理_prompt_其他） | prompt | 路线 | 帧源 | 对/总 | 答错的问题（期望→答） | 延迟中位 / p90 s | TTFT 中位 s | token 输入 / 输出 |
|---|---|---|---|---|---|---|---|---|
| `rest_C_gpt-6-luna_high_low_terse_1080p15` | terse | C | 1080p15 派生，裁后 480 px | 25/29 | Q11 对→未放；Q15 未放→错；Q20 对→错；Q23 对→错 | 3.6 / 4.5 | 3.1 | 769 / 256 |
| `rest_C_gpt-6-sol_high_none_terse` | terse | C | 原始 2432×1824，裁后 816 px | 25/29 | Q2 对→错；Q4 对→错；Q11 对→未放；Q29 对→错 | 2.0 / 2.5 | 1.1 | 1215 / 50 |
| `rest_C_gpt-6-sol_high_none_terse2_1080p15` | terse2 | C | 1080p15 派生，裁后 480 px | 28/29 | Q22 错→对 | 2.0 / 2.7 | 1.1 | 750 / 52 |
| `rest_C_gpt-6-sol_high_none_terse2_nohist_1080p15` | terse2 | C | 1080p15 派生，裁后 480 px | 26/29 | Q15 未放→错；Q20 对→错；Q22 错→对 | 2.2 / 3.9 | 1.1 | 696 / 53 |
| `rest_C_gpt-6-sol_high_none_terse_1080p15` | terse | C | 1080p15 派生，裁后 480 px | 26/29 | Q11 对→未放；Q20 对→错；Q22 错→对 | 1.9 / 2.6 | 1.1 | 769 / 48 |
| `rest_C_gpt-6-sol_high_none_terse_1080p15_r2` | terse | C | 1080p15 派生，裁后 480 px | 26/29 | Q11 对→未放；Q20 对→错；Q22 错→对 | 1.9 / 2.5 | 1.1 | 769 / 49 |
| `rest_C_gpt-6-sol_high_none_terse_v2` | terse | C | 原始 2432×1824，裁后 816 px | 29/29 | — | 1.9 / 2.6 | 1.1 | 1222 / 50 |
| `rest_C_or-anthropic_claude-sonnet-5.5_high_minimal_azure-global_terse2_1080p15` | terse2 | C | 1080p15 派生，裁后 480 px | 25/29 | Q9 对→无效；Q13 错→无效；Q20 对→错；Q22 错→对 | 2.0 / 3.0 | 1.3 | 961 / 105 |

| 结果文件（模型_图detail_推理_prompt_其他） | prompt | 路线 | 帧源 | 对/总 | 答错的问题（期望→答） | 延迟中位 / p90 s | TTFT 中位 s | token 输入 / 输出 |
|---|---|---|---|---|---|---|---|---|
| `rest_B_gpt-6-luna_high` | ? | B | 原始 2432×1824，裁后 768 px | 24/29 | Q2 对→错；Q8 错→对；Q10 未放→对；Q13 错→对；Q22 错→对 | 4.1 / 6.9 | 未记 | 1434 / 258 |

## 6 问（Q8 Q9 Q13 Q14 Q22 Q23：3 个错 + 各自修正后的帧）各配置结果

| 结果文件（模型_图detail_推理_prompt_其他） | prompt | 路线 | 帧源 | 对/总 | 答错的问题（期望→答） | 延迟中位 / p90 s | TTFT 中位 s | token 输入 / 输出 |
|---|---|---|---|---|---|---|---|---|
| `rest6_C_gpt-6-luna_high_low_checks` | checks | C | 原始 2432×1824，裁后 825 px | 4/6 | Q9 对→错；Q14 对→错 | 6.3 / 7.7 | 未记 | 1174 / 342 |
| `rest6_C_gpt-6-luna_high_low_rel` | relational | C | 原始 2432×1824，裁后 825 px | 5/6 | Q14 对→错 | 8.3 / 11.0 | 未记 | 1272 / 466 |
| `rest6_C_gpt-6-luna_high_low_terse` | terse | C | 原始 2432×1824，裁后 825 px | 6/6 | — | 5.5 / 6.6 | 未记 | 1282 / 307 |
| `rest6_C_gpt-6-luna_high_low_terse_r2` | terse | C | 原始 2432×1824，裁后 825 px | 6/6 | — | 4.2 / 6.7 | 未记 | 1273 / 281 |
| `rest6_C_gpt-6-luna_high_none_rel` | relational | C | 原始 2432×1824，裁后 825 px | 4/6 | Q13 错→对；Q22 错→对 | 3.1 / 4.5 | 未记 | 1272 / 164 |
| `rest6_C_gpt-6-luna_high_none_terse` | terse | C | 原始 2432×1824，裁后 825 px | 3/6 | Q13 错→对；Q22 错→对；Q23 对→错 | 1.7 / 2.7 | 未记 | 1273 / 54 |
| `rest6_C_gpt-6-luna_high_none_terse_factsv1` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q9 对→错 | 1.9 / 2.7 | 未记 | 1282 / 54 |
| `rest6_C_gpt-6-luna_high_none_terse_r2` | terse | C | 原始 2432×1824，裁后 825 px | 4/6 | Q13 错→对；Q22 错→对 | 1.7 / 2.6 | 未记 | 1273 / 56 |
| `rest6_C_gpt-6-luna_high_none_terse_r3` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q13 错→对 | 1.8 / 2.5 | 未记 | 1273 / 58 |
| `rest6_C_gpt-6-luna_high_rel` | relational | C | 原始 2432×1824，裁后 825 px | 6/6 | — | 6.2 / 18.0 | 未记 | 1272 / 754 |
| `rest6_C_gpt-6-luna_low_low_terse` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q14 对→错 | 5.2 / 8.3 | 未记 | 802 / 314 |
| `rest6_C_gpt-6-sol_high_none_img` | image | C | 原始 2432×1824，裁后 825 px | 3/6 | Q8 错→对；Q14 对→错；Q22 错→对 | 2.1 / 3.2 | 1.4 | 1352 / 49 |
| `rest6_C_gpt-6-sol_high_none_terse_r1` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q22 错→对 | 2.4 / 4.2 | 未记 | 1273 / 54 |
| `rest6_C_gpt-6-sol_high_none_terse_r2` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q22 错→对 | 2.4 / 2.9 | 未记 | 1273 / 58 |
| `rest6_C_gpt-6-sol_high_none_terse_r3` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q22 错→对 | 2.2 / 2.9 | 1.4 | 1273 / 53 |
| `rest6_C_or-qwen_qwen3.8-27b_high_none_dekallm_terse_r1` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q22 错→对 | 2.3 / 3.0 | 1.2 | 1146 / 72 |
| `rest6_C_or-qwen_qwen3.8-27b_high_none_terse_r1` | terse | C | 原始 2432×1824，裁后 825 px | 3/6 | Q13 错→对；Q22 错→对；Q23 对→错 | 2.8 / 7.6 | 2.1 | 1146 / 66 |
| `rest6_C_or-qwen_qwen3.8-27b_high_none_terse_r2` | terse | C | 原始 2432×1824，裁后 825 px | 4/6 | Q22 错→对；Q23 对→错 | 7.1 / 19.9 | 3.1 | 1146 / 63 |
| `rest6_C_or-qwen_qwen3.8-27b_high_terse_r1` | terse | C | 原始 2432×1824，裁后 825 px | 5/6 | Q22 错→对 | 29.6 / 114.8 | 29.0 | 1182 / 2112 |

## 回放


**`replay_frames_1080p15_c1`：1080p15 派生帧，连续确认 1 次，gpt-6-sol_high_none_terse2，判定调用 75 次 / 148 帧**

| 步 | 真值完成（第几帧） | 系统推进（第几帧） | 差（秒） | 错误窗口（帧） | 报错时刻（帧） |
|---|---|---|---|---|---|
| 1 | 8 | 8 | 0 |  |  |
| 2 | 14 | 14 | 0 |  |  |
| 3 | 23 | 21 | -2 |  |  |
| 4 | 33 | 33 | 0 | 27–30 | 27 |
| 5 | 40 | 39 | -1 |  |  |
| 6 | 51 | 50 | -1 | 44–47 | 44 |
| 7 | 57 | 57 | 0 |  |  |
| 8 | 71 | 71 | 0 | 63–69 | 漏 |
| 9 | 92 | 91 | -1 |  |  |
| 10 | 109 | 94 | -15 | 99–103 | 漏 |
| 11 | 117 | 115 | -2 |  |  |
| 12 | 121 | 120 | -1 |  |  |
| 13 | 123 | 123 | 0 |  |  |

误报：第 13 步 @ 帧 122（placement differs）

**`replay_frames_1080p15_c2`：1080p15 派生帧，连续确认 2 次，gpt-6-sol_high_none_terse2，判定调用 94 次 / 148 帧**

| 步 | 真值完成（第几帧） | 系统推进（第几帧） | 差（秒） | 错误窗口（帧） | 报错时刻（帧） |
|---|---|---|---|---|---|
| 1 | 8 | 9 | 1 |  |  |
| 2 | 14 | 15 | 1 |  |  |
| 3 | 23 | 22 | -1 |  |  |
| 4 | 33 | 34 | 1 | 27–30 | 28 |
| 5 | 40 | 147 | 107 |  |  |
| 6 | 51 | 没推进 |  | 44–47 | 漏 |
| 7 | 57 | 没推进 |  |  |  |
| 8 | 71 | 没推进 |  | 63–69 | 漏 |
| 9 | 92 | 没推进 |  |  |  |
| 10 | 109 | 没推进 |  | 99–103 | 漏 |
| 11 | 117 | 没推进 |  |  |  |
| 12 | 121 | 没推进 |  |  |  |
| 13 | 123 | 没推进 |  |  |  |

误报：第 5 步 @ 帧 72（the white area's left end touches the purple brick）；第 5 步 @ 帧 85（the white area's right end is straight: both rows end at the same place）；第 5 步 @ 帧 109（the white area's right end is straight: both rows end at the same place）；第 5 步 @ 帧 124（the white area's left end touches the purple brick）；第 5 步 @ 帧 127（the white area's left end touches the purple brick）；第 5 步 @ 帧 141（the white area's right end is straight: both rows end at the same place）；第 5 步 @ 帧 145（the white area's right end is straight: both rows end at the same place）

**`replay_frames_c1`：原始 2432×1824帧，连续确认 1 次，gpt-6-sol_high_none_terse2，判定调用 72 次 / 148 帧**

| 步 | 真值完成（第几帧） | 系统推进（第几帧） | 差（秒） | 错误窗口（帧） | 报错时刻（帧） |
|---|---|---|---|---|---|
| 1 | 8 | 8 | 0 |  |  |
| 2 | 14 | 14 | 0 |  |  |
| 3 | 23 | 21 | -2 |  |  |
| 4 | 33 | 33 | 0 | 27–30 | 27 |
| 5 | 40 | 39 | -1 |  |  |
| 6 | 51 | 50 | -1 | 44–47 | 41, 44 |
| 7 | 57 | 57 | 0 |  |  |
| 8 | 71 | 61 | -10 | 63–69 | 漏 |
| 9 | 92 | 91 | -1 |  |  |
| 10 | 109 | 109 | 0 | 99–103 | 99 |
| 11 | 117 | 115 | -2 |  |  |
| 12 | 121 | 120 | -1 |  |  |
| 13 | 123 | 122 | -1 |  |  |

误报：无

**`replay_frames_c2`：原始 2432×1824帧，连续确认 2 次，gpt-6-sol_high_none_terse2，判定调用 73 次 / 148 帧**

| 步 | 真值完成（第几帧） | 系统推进（第几帧） | 差（秒） | 错误窗口（帧） | 报错时刻（帧） |
|---|---|---|---|---|---|
| 1 | 8 | 9 | 1 |  |  |
| 2 | 14 | 15 | 1 |  |  |
| 3 | 23 | 22 | -1 |  |  |
| 4 | 33 | 34 | 1 | 27–30 | 28 |
| 5 | 40 | 40 | 0 |  |  |
| 6 | 51 | 51 | 0 | 44–47 | 45 |
| 7 | 57 | 58 | 1 |  |  |
| 8 | 71 | 72 | 1 | 63–69 | 漏 |
| 9 | 92 | 92 | 0 |  |  |
| 10 | 109 | 110 | 1 | 99–103 | 100 |
| 11 | 117 | 116 | -1 |  |  |
| 12 | 121 | 121 | 0 |  |  |
| 13 | 123 | 123 | 0 |  |  |

误报：无


### 怎么读回放表

回放 = 148 帧按时间顺序过"门控 → 判定（问状态机当前步）→ 状态机"。门控放行才调判定器；判定答 correct 连续 N 次 → 本步完成、
推进到下一步；答 wrong 连续 N 次 → 产生一条"第几步哪条事实不对"的事实；其他 → 计数清零。"差"是系统推进帧减真值帧，
真值是肉眼标的，±1 s 内都算同时。"报错时刻"落在错误窗口内算捉到；第 8 步手没离开，按设计漏。
1080p、单帧确认那张表里第 10 步在帧 94 推进（真值 109）是**提前误推进**：后轮还没放就被判 correct 了一次。

## 门控（`gate_eval.py`，本地，无模型）

- 信号：底板找到且整块在画面里（紧框不贴画面边、短边 ≥ 画面宽 23%、长宽比 0.7–1.45）；板框内肤色占比 ≥ 15% 算有手。
- 对我手标的 145 帧（`truck/gate_labels.json`）：70 个静止可问帧全放过；75 个不该问的帧拦住 55，漏 20（手在板边或板上）。
- 更细的肤色规则（血块大小、贴边、形状）试过都放弃：米色砖、紫砖边、红砖阴影都在肤色窗里，会误拦静止帧。
- 漏的 20 帧里挑 8 个直接问判定器，8 个都答得合理（砖在手里 → 未放，被挡 → 看不见，手扶板放错 → 错）。所以门控只管板完整 + 没有大片手。
- 帧差在 1 fps 下主要量到头动，没用；实机 15 fps 可以加"静止一秒"。

## 其他探索

- 第 5 步两条白砖在 1080p 下：单独一句"紫砖右边的白色区域有几排凸点，1 还是 2"，3 帧 × 3 种问法 9/9 答 2；放进完整步骤语境
  （不论原措辞、改"两排深"、terse2、还是选择题"1 还是 2 [期望 2]"）每帧只有约 1/3 答对，隔帧翻转。语境里一说"这步加了一条白砖"
  它就按砖数。
- 门名字实验：把"tail door"换成直白描述后，sol 两帧都对，luna / Qwen 仍在放错帧上说"门正下方是裸板"。名字不是主因。
- 眼镜端先裁再编码的模拟（原分辩率裁板 → H.264 crf 23）：1080p 下错的三问救回两问（Q11、Q22），说明丢的是像素；但用户决定裁切只在服务器做。
- luna 开 low 在 1080p 上 25/29，比 sol none 差且慢一倍。

## 文件索引

- `truck/results/rest_*.jsonl` + 同名目录：29 问各次运行；`rest6_*`、`rest_disc_*`、`rest_fix_*`、`rest_hands_*`：小集。
- `truck/results/replay_*_c*.json`：回放时间线与事实；`replay_cache.jsonl`：回放用到的所有判定答案。
- `truck/results/gate_signals.jsonl`、`truck/gate_labels.json`、`truck/run1/sheets/gate_sheet.jpg`：门控。
- `truck/run1/sheets/`：看片用的拼图（rest_sheet、crops_all、各次调试图）。

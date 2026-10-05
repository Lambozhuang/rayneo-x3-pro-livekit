# eval/ — 判定器评测素材

录像来自眼镜自带相机（`deploy/record.ps1`），HEVC 2432×1824 30 fps，旋转元数据 −90°（竖幅）。
视频、抽帧、拼图不入库（.gitignore），布局、真值、参考图入库。

## truck/ — 2D 卡车，16×16 底板，13 步

- `plan.html`：搭建方案示意（行列坐标：列左→右 1–16，行上→下 1–16）
- `layout.json`：13 步，按实际搭建顺序；每步颜色和占用格 `[col0,row0,col1,row1]`
- `refs/ref_stepNN.png`：第 N 步完成后的俯视参考图（带行列号），`ref_sheet.png` 全部拼图
- `events.json`：真值时间线。每步 `done` = 砖到位且手离开的 (片段, 秒)；`wrong` = 故意放错的区间和内容；
  `distractions` = 看别处的区间
- `run1/`：三段视频（part1 61.8 s；part2_p1 61.6 s；part2_p2 25.6 s）。part1→part2 之间约 7 分钟没动板子；
  p1→p2 之间约 2 s 空白（相机 60 s 单段上限），第 13 步落在空白里
  - `frames/<clip>/NNN.jpg`：1 fps 全分辩率抽帧，NNN = 秒 + 1。重建：
    `ffmpeg -i <clip>.mp4 -vf fps=1 -q:v 2 frames/<clip>/%03d.jpg`
  - `sheets/`：看片用的拼图（整帧 / 按绿色裁板 / 四处错误放大）

run1 里的故意错误：第 4 步错色（米色代白）、第 6 步错位（右偏约 2 格）、第 8 步错向加错位（手未离开）、
第 10 步错位（后轮右偏）。工作距离下底板约 750 px 宽，一格约 45 px。

## 判定器评测（路线 B / C）

`eval/judge_eval.py`，模型只从 `backend/.env` 读：`OPENAI_CHECK_MODEL`（+ `OPENAI_CHECK_DETAIL`、`OPENAI_CHECK_EFFORT`）、`GEMINI_CHECK_MODEL`。

```
python eval/judge_eval.py labels                                  # 真值表 truck/results/labels.{jsonl,txt}、样例图，不调 API
python eval/judge_eval.py run --route C --provider openai         # 全集 276 问；--subset truck/subset_small.json 跑 18 问小集；--limit N
python eval/judge_eval.py summarize truck/results/C_<model>.jsonl  # 三类准确率、4 处错误检出、误报、延迟、token
```

先跑 `--questions truck/rest.json`：29 个静止状态各一问（13 对、3 错、13 未放），每问独立：系统提示 + 一句步骤问题 + layout 渲染的第 N 步目标图（新砖黄框，detail=low）+ 照片（B 整帧 768×1024 detail=high；C 为绿色掩码裁出的底板）。第 8 步的错放全程手在板上，静止判定器按设计不会看到这种帧，所以不在 rest 集里。不带 `--questions` 则用 events.json 推出的 276 个逐帧问题（当前步 N 和上一步 N−1），留给门控和逐帧统计。结果按 (clip, frame, step) 追加写入，中断可续跑；每次调用发出的图和原始回复都落在 `results/<run>/`。

### 结果到目前（rest 集，模型来自 .env，原始记录在 `truck/results/`）

- 网格 prompt（编号目标图 + 行列号，四选一）：luna 整帧 B 29 问 24/29，3 个错全漏；裁板 C 只多捉到蓝砖。理由在复述题目，不在看图。分辨率不是瓶颈。
- 关系 prompt（人话描述 + 3–4 条可核对的关系，先描述再逐条 y/n，不给图不给坐标；`layout.json` 的 `where`/`checks`），C 路线，6 问 = 3 错 + 3 修正：

  | 模型 / 推理 / 输出 | 6 问 | 延迟中位 | 备注 |
  |---|---|---|---|
  | luna 默认推理，完整输出 | 6/6 | 6.2 s（最大 18） | 输出 750 token |
  | luna low，terse | 6/6 ×2 | 4.2–5.5 s | 均衡之选 |
  | luna none，terse | 3–5/6 ×4 | 1.7 s | 位置错随机漏，偶有误报 |
  | sol none，terse | 5/6 ×2 | 2.4 s | 稳定；后轮偏 2 格看不出 |
  | luna low，只答 y/n 不描述 | 4/6 | 6.3 s | 更差不更快 |
  | luna low，terse，图 detail=low | 5/6 | 5.2 s | 省 token 不省时间 |
  | sol none，terse（流式，第 3 次） | 5/6 | 2.2 s，TTFT 1.4 s | 同上 |
  | qwen3.8-27b（OpenRouter）none，terse | 3/6、4/6 | 2.0–10 s，TTFT 0.8–16 s | 对的后轮两次说错，偏的后轮两次说对；路由到的提供商不同，时延抖动大 |
  | qwen3.8-27b（OpenRouter）开思考，terse | 5/6 | 4.5–115 s，TTFT 即思考时长 | 还是看不出后轮偏；思考长到不可用。钉死 Cerebras（provider.only, no fallbacks）：OpenRouter 共享额度被上游限流 429，三次都没跑起来，要用得自带 Cerebras key |
  | qwen3.8-27b 钉 DekaLLM，none，terse | 5/6 | 1.8–3.0 s，TTFT 0.9–1.9 s | 和 sol 同一结果同一漏，一样快；一轮样本 |

- 后轮偏 2 格这题，把事实改成局部二选一（"车尾门正下方是裸板还是圆盘"、"圆盘右缘在浅绿砖右端左侧"、"两盘间隙比一个盘窄"）再跑 2 帧 × sol / Qwen@DekaLLM / luna 各两遍（不开推理）：放错帧上 luna、Qwen 四次都把前两条答 yes，sol 靠"间隙"那条碰对；"间隙比一个盘窄"（3 格 vs 4 格）在正确帧上又被三家判 no。结论：不开推理的模型看不出圆盘差 2 格，措辞救不了；间隙那条已删，第 10 步留 3 条。 把"tail door"这个名字换成直白的"竖立在车身右端的白砖"后再跑一遍：sol 两帧都对（放错帧靠"右缘超出浅绿砖"那条），luna、Qwen 仍在放错帧上把"白砖正下方是裸板"答 yes，luna 还在正确帧上答反。名字不是主因，是看不出。
- 选型：要稳就 luna + low + terse（约 4–5 s）；要快就 sol + none + terse（约 2.4 s，最细的位置错看不到）。延迟 ≈ 输出 token ÷ 约 70 tok/s，1 s 以内 VLM 做不到。
- 事实的写法决定误报：用"贴着 / 有缝 / 颜色 / 横放竖放 / 在某砖的左边或下面"，不用"齐平""正上方"（第 4、6 步因此各删一条）。
- 待试：Gemini Flash。OpenRouter 的 Qwen 不如 sol，TTFT 也不稳。

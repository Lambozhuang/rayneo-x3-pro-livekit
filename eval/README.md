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

每帧问当前步 N（期望 未放/错/对）和上一步 N−1（期望 对），两图输入：layout 渲染的第 N 步目标图（新砖黄框）+ 现场照片。B 发整帧（长边 1024），C 发绿色掩码裁出的底板（闭运算 + 最大连通块，手、屏幕、浅绿砖不再干扰；8 帧找不到底板直接答"看不见"）。错误窗口到完成之间的帧标 `moving`，干扰窗口单独统计，都不计分。结果按 (clip, frame, step) 追加写入，中断可续跑。

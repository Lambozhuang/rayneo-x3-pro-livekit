# 面向VLM逐步验证的LEGO式搭建任务设计：文献调研笔记

结论先行：按目前的设计，"在手中搭建、含斜顶、用无状态VLM评判"很难做到"网络良好时几乎零误判"。LEGO Co-builder（arXiv 2025）报告GPT-4o在LEGO装配状态检测上最高仅40.54% F1，DORI朝向基准也显示通用VLM的物体朝向判断接近随机水平。因此建议改做"固定底板+二维布局+颜色/位置可判定"的任务，并以经典CV或混合判定为主评判器，VLM只作辅助或备份。另外，每2–3 s采样一帧，本身就给系统引入了约1–1.5 s的平均附加延迟，这可能掩盖你们想测量的网络延迟效应，需要一并重新设计。

## TL;DR

- **当前方法的核心假设（VLM能近乎完美地逐步判定）得不到文献支持**：GPT-4o在LEGO装配状态检测上仅得40.54% F1（LEGO Co-builder, 2025）；朝向基准DORI上最好的模型在粗粒度朝向判断上也只有约54–64%。你们观察到的"斜顶朝向不可靠""手持旋转后参考系歧义""长提示中漏检"，都与文献方向一致。
- **推荐的任务形态**：固定、带标记的底板；只用哑光的2×2/2×4砖；每步只放一块、只改变"颜色×格位"；朝向无关（旋转对称）；确定性CV网格判定为主，VLM作二次确认。这正是CMU Gabriel LEGO助手和Funk等人Duplo基准所采用的简化思路。
- **网络QoE定位**：与你们最接近的先例是CMU的可穿戴认知助手（LEGO任务的时延容忍上下界为600–2700 ms）和PLOS ONE 2021（Olguín Muñoz等）的LEGO助手延迟实验：注入0–3 s延迟后，长时间延迟使用户显著放慢，且这一效应在系统恢复响应后仍持续一段时间，作者将其归因于认知规划受损。Maslych等（CUI 2025）发现LLM语音代理延迟超过4 s后体验明显下降。你们的实验应把"系统基线延迟"压到远低于这些阈值，网络操纵才有检测力。

---

## 一、第一人称（头戴）视频中的装配步骤验证：数据集、定义、精度与失败模式

### 1.1 "步骤完成"的两种定义：动作式 vs 状态式

- **动作式（action-based）**：大多数数据集（Assembly101、MECCANO、IKEA ASM、EgoPER、HoloAssist）标注的是"动作片段"及其是否为错误或纠正，问的是"做了什么"，而非"装配体是否已处于正确状态"。
- **状态式（state-based）**：IndustReal（Schoonbeek等，WACV 2024）在摘要中指出，程序性任务的动作识别存在"根本缺陷"：没有为动作提供任何成功度量。为此它提出程序步骤识别（Procedure Step Recognition, PSR）任务：只有当"与该步骤相关的部件被正确安装"时，步骤才算完成；装配状态用每个组件的1/0/-1编码表示（正确安装/未装/错误安装）。来源：IndustReal: A Dataset for Procedure Step Recognition Handling Execution Errors in Egocentric Videos in an Industrial-Like Setting，WACV 2024，https://arxiv.org/abs/2310.17323
- **对你们的含义**：你们的需求（"有几步可见地完成、有没有放错"）本质上属于状态式验证，与IndustReal的PSR/ASD最接近，与Assembly101类动作式基准关系较远。

### 1.2 关键数据集与报告的精度

| 数据集/工作 | 设置 | 步骤定义 | 报告精度（摘要） | 记录的失败模式 |
|---|---|---|---|---|
| IndustReal（WACV 2024） | HoloLens 2第一人称，27名参与者，36种3D打印零件的玩具车；白色桌面、白色背景、光照一致 | 状态式（PSR+ASD） | ASD（YOLOv8-m）mAP：带框帧0.838，整段视频0.641；PSR最佳基线POS 0.797/F1 0.883，但在含错误的录像上降到0.731/0.816 | 整段视频评测时性能下降27%，主因是"细粒度视觉差异状态"的误报；错误状态的误报率达65%、AP仅0.23；例：销钉朝向错误被误判为"销钉缺失"，用螺母代替螺钉未被识别 |
| Assembly101 / Assembly101-O（CVPR 2022；PREGO CVPR 2024） | 玩具车拆装，8个静态+4个第一人称相机 | 动作式；"错误/纠正"片段 | PREGO在Assembly101-O上平均F1约32.5；DTGL约53.5（NeurIPS 2024） | PROVIA（arXiv 2026）指出该协议只测第一次错误之前的部分，且仅凭位置先验即可达平均F1 0.50，与DTGL相当；训练/测试集参与者不互斥（47人中有35人重叠） |
| HoloAssist（ICCV 2023） | HoloLens 2，350对指导者–执行者，20类任务，166小时 | 动作式细粒度错误 | 错误检测F-score：仅RGB 35.11，仅手部姿态40.19（据二手综述整理）【证据薄弱：未核对原文表格】 | 约6%的动作被标为错误；类别极不平衡 |
| EgoPER（CVPR 2024） | 第一人称烹饪5个任务 | "任何偏离任务图的行为"都算错误 | 以EDA/AUC报告；仅用无错训练视频做单类检测 | 需要主动物体检测与手–物关系特征 |
| EgoOops（ICCVW 2025） | 第一人称，含电路/积木等领域，参考程序文本 | 动作是否违背文本 | 在Assembly101上训练的模型迁移后不如均匀采样基线；Qwen2-VL-7B的"错误"类召回超过有监督MLP，但识别"纠正"很差 | 跨域迁移差；MLLM难以判断"这是不是纠正" |

来源：
- PREGO: online mistake detection in PRocedural EGOcentric videos，CVPR 2024，https://arxiv.org/html/2404.01933v1
- Differentiable Task Graph Learning（DTGL），NeurIPS 2024，https://arxiv.org/pdf/2406.01486
- Task Graph Maximum Likelihood Estimation（扩展版，含DO 53.5 vs PREGO 32.5），arXiv 2025，https://arxiv.org/pdf/2502.17753
- PROVIA: Procedure State Tracking for Online Mistake Detection in Egocentric Videos，arXiv 2026，https://arxiv.org/html/2609.20638
- HoloAssist，ICCV 2023，https://openaccess.thecvf.com/content/ICCV2023/html/Wang_HoloAssist_an_Egocentric_Human_Interaction_Dataset_for_Interactive_AI_Assistants_ICCV_2023_paper.html
- Error Detection in Egocentric Procedural Task Videos（EgoPER），CVPR 2024，https://openaccess.thecvf.com/content/CVPR2024/papers/Lee_Error_Detection_in_Egocentric_Procedural_Task_Videos_CVPR_2024_paper.pdf
- EgoOops，ICCV 2025 Workshop，https://arxiv.org/pdf/2410.05343

### 1.3 文献中与你们最相关的"简化措施"

- **让手离开装配体**：IndustReal明确要求参与者"完成一步后把手从装配体上移开，以保证对装配状态的遮挡最少"。这说明即使是专门的状态检测基准，也要靠协议消除手部遮挡。
- **控制背景与光照**：IndustReal在白桌、白背景、一致光照下录制，零件用少数几种颜色的PLA打印。
- **状态数爆炸**：IndustReal指出，早期ASD工作的复杂度被限制在"5或6个零件"，因为状态数随零件数呈组合增长；利用程序知识（限定下一步只能是哪些状态）能显著提升PSR（B3优于B2）。**这直接支持"判定器应有状态/先验"，而不是每帧无状态地从零判断。**
- **6D位姿融合**：ASDF（ISMAR 2024）把6D位姿估计与状态检测做后期融合来提升ASD。这说明学界处理朝向问题时借助了显式位姿，而不是依赖通用VLM。来源：ASDF: Assembly State Detection Utilizing Late Fusion by Integrating 6D Pose Estimation，ISMAR 2024，https://arxiv.org/pdf/2403.16400

---

## 二、基于VLM的进度追踪/错误检测（2024年以后）

### 2.1 有效的做法及其前提

- **ZeProM（arXiv 2026）**：单个预训练视频VLM零样本完成时序分割+错误检测，在EgoPER上EDA比最强有监督方法高4.4点。成功要素：①程序只写成简单的编号步骤列表（作者发现写出完整依赖图反而"让模型困惑"）；②让模型先分割再判错（相当于强制推理）；③结构化JSON输出。**注意**：这是离线、整段视频输入、烹饪类大动作任务，与"单帧、小零件、在线"的场景差距很大。来源：The Unreasonable Effectiveness of VLMs for Zero-shot Procedural Mistake Detection，arXiv 2026，https://arxiv.org/pdf/2606.21579
- **TI-PREGO（arXiv 2024）**：用LLM的上下文学习加思维链做下一步预测，检测"程序性"（顺序）错误。VLM/LLM在这里处理的是符号序列，而非像素级状态。来源：https://arxiv.org/pdf/2411.02570
- **共同规律**：VLM在"顺序/遗漏/大动作"类错误上有效，在"执行错误"（零件装错位置或朝向）上证据薄弱。

### 2.2 明确报告的局限（与你们直接相关）

- **LEGO Co-builder（2025）**：基于65本官方LEGO说明书合成场景。状态检测任务（T3）中，负样本是把待装零件随机平移至少5%。结果"所有被评估VLM的F1-State都低于50%"，GPT-4o最高也只有40.54%（FPR 43.06%），Gemini-2.5-flash为28.81%，GLM-4.1-thinking为39.61%。作者的解释是模型难以把图像中的位置信息与文本对齐。**这是与你们任务最接近的直接证据**：即使是合成的干净图像、只考察位置偏移（尚未涉及朝向），GPT-4o也做不到可靠。来源：LEGO Co-builder: Exploring Fine-Grained Vision-Language Modeling for Multimodal LEGO Assembly Assistants，arXiv 2025，https://arxiv.org/html/2507.05515
- **IKEA-Bench（arXiv 2026）**：评估"说明书图示↔视频"的跨描绘对齐，发现准确率低，且在专有大模型上"难以靠规模解决"，瓶颈在视频理解而非说明书理解。来源：Benchmarking and Mechanistic Analysis of Vision-Language Models for Cross-Depiction Assembly Instruction Alignment，https://arxiv.org/html/2604.00913 。**这与你们"渲染参考图 vs 真实相机帧"的做法高度相关**：渲染图与照片之间同样存在跨描绘差异。
- **朝向（DORI，2025）**：评测了24–26个模型，"在通用空间基准上表现好的模型，在以物体为中心的朝向任务上仍接近随机"。最佳模型粗粒度约54.2%（另一版本为64.2%），细粒度约42.9–45%，下降最大的是复合旋转和"物体间参考系转换"。来源：Seeing Isn't Orienting: A Cognitively Grounded Benchmark Reveals Systematic Orientation Failures in MLLMs，arXiv 2505.21649，https://arxiv.org/html/2505.21649v7 （【注意】不同版本数字不一致，原因是模型集合有更新）
- **低层视觉（VLMs are blind，ACCV 2024）**：VLM能数清彼此分离、间距较大的形状，但对重叠或嵌套的形状计数困难，而且"数不清网格的行数或列数"。四个前沿VLM的平均准确率约56–58%。来源：Vision language models are blind，ACCV 2024，https://openaccess.thecvf.com/content/ACCV2024/html/Rahmanzadehgervi_Vision_language_models_are_blind_ACCV_2024_paper.html
- **提示/文本干扰**：多篇工作显示，无关或误导性文本会让视觉任务性能"崩塌"；无关上下文会导致答案整体偏向否定，被表述成"可能与图像相关"时影响更强。来源：Diagnosing and Mitigating Modality Interference in MLLMs，arXiv 2505.19616，https://arxiv.org/html/2505.19616 ；When Irrelevant Text Matters: Affine Margin Shifts in MLLMs，arXiv 2026，https://arxiv.org/pdf/2608.19208 ；On the robustness of multimodal language model towards distractions，arXiv 2502.09818，https://arxiv.org/pdf/2502.09818

### 2.3 逐条核对你们的五项观察

| 你们的观察 | 文献判断 | 依据与说明 |
|---|---|---|
| (a) 平铺俯视下颜色和凸点计数效果好 | **部分支持，但有隐患** | 分离的物体计数可靠（VLMs are blind）；但"网格行/列计数"和相邻重叠基元是已知弱点，相邻凸点正属于此类。建议不要让评判依赖"数凸点"，而改为"哪个格位是什么颜色"，并由CV完成 |
| (b) 小零件3D朝向（斜顶朝向）不可靠 | **支持** | DORI的朝向判断接近随机；IndustReal中连专用检测器也把"销钉朝向错误"误判为"缺失"；LEGO Co-builder里仅平移扰动就已低于50% F1 |
| (c) 手中转动后"沿哪一排/哪一端"出现歧义 | **支持** | DORI中下降最大的是"物体间参考系转换"；Funk基准、Gabriel、IndustReal都把装配体放在固定底板或桌面上，没有一个在手中搭建 |
| (d) 光面砖的镜面反射让蓝色被读成白色 | **未知/证据薄弱** | 本次检索未找到专门研究VLM颜色判定受镜面高光影响的论文。IndustReal通过控制光照和背景回避了这一问题。【推测】这是经典的颜色恒常/高光饱和问题，偏振或漫射光、哑光零件、避开高饱和相近色（蓝/白）可缓解 |
| (e) 提示启动效应：单独问能看到L形砖，嵌入完整检查提示后漏检 | **间接支持** | 模态干扰和无关文本导致"否定偏移"的研究，与"长提示里漏检（偏向回答'未完成'）"方向一致；ZeProM也发现更复杂的程序描述反而更差。但没有找到针对"LEGO步骤检查提示"的直接实验【证据薄弱】 |

---

## 三、以LEGO/积木搭建为任务的AR/HCI用户研究

### 3.1 代表性研究

- **Funk et al., A Benchmark for Interactive Augmented Reality Instructions for Assembly Tasks，MUM 2015**：https://thomaskosch.com/wp-content/papercite-data/pdf/funk2015gatm.pdf
  - 设置：26×26绿色Duplo底板固定放在工位上，8个拣料盒（2×4排列），8种砖（2×2的橙、黄、蓝、红、白、青柠色，以及2×4的黄、绿色）。
  - 步数：4/8/16/32步（重复测量，以步数为唯一自变量，按平衡拉丁方排序）。
  - 度量：按"一般装配任务模型"（GATM）把每步时间拆成t_locate part、t_pick、t_locate pos、t_assemble；错误数和时间都按步数归一化；另测NASA-TLX。纸质基线下，Duplo任务每步的t_locate part约2.14 s、t_assemble约1.04 s；错误很少（4步0.17个，32步0.5个）。
  - 选择理由：Duplo任务"便宜、易复现、有代表性、易扩展"，而且pick-and-place任务的时间主要花在"定位零件/定位位置"上，最能反映指令质量。**这恰好对应你们的需求：想让网络效应体现在"信息传递"而非"动手操作"上。**
- **Funk et al., Interactive worker assistance: comparing in-situ projection, HMD, tablet, and paper instructions，UbiComp 2016**：https://dl.acm.org/doi/10.1145/2971648.2971706 。同样采用抽象的Duplo任务。原位投影装配更快，HMD在"定位位置"上显著更慢；原位投影比HMD错误更少、认知负荷更低。
- **Blattgerste et al., Comparing Conventional and AR Instructions for Manual Assembly Tasks，PETRA 2017**：https://www.semanticscholar.org/paper/b2e0ebd35c4fb20d87fda1de22e658515c0275b4 。对比HoloLens、Epson Moverio BT-200、手机和纸质说明，任务为标准化Duplo搭建：纸质最快，HoloLens错误最少；作者还提出了时间分段的操作化定义。续作PETRA 2018（In-Situ Instructions Exceed Side-by-Side Instructions）发现原位指令在错误数、完成时间和任务负荷上都优于并排指令。
- **Kosch博士论文（Workload-Aware Systems…，arXiv 2010.07703）**：沿用Funk的任务，每个条件24块Duplo砖。来源：https://arxiv.org/pdf/2010.07703
- **DuploTrack（Gupta et al., UIST 2012）**：用Kinect深度相机实时推断并追踪Duplo装配过程，能检测错误并给出纠正反馈；用户研究显示比图示手册错误更少、搭建更快。**这是"非VLM、几何/深度驱动"的实时LEGO状态验证先例。**来源：https://dl.acm.org/doi/10.1145/2380116.2380167
- **远程协作中的LEGO任务**：HandsInTouch研究（J. Visual Communication and Image Representation, 2018）把LEGO装配作为"简单任务"、笔记本维修作为"复杂任务"；加入草图线索只在复杂任务上缩短时间。来源：https://www.sciencedirect.com/science/article/abs/pii/S1047320318303365 。**含义**：LEGO任务太简单时，操纵变量（此处是交互线索，你们则是网络条件）的效应可能测不出来，任务难度需要足够。

### 3.2 从这些研究中提炼的设计共性

- 装配体几乎总是放在**固定的底板/工位**上，而不是拿在手里。
- 使用**Duplo或大颗粒砖**，颜色种类有限且彼此差异大（Funk：6–8种）。
- 错误一般计为"放错位置/放错砖"的块数，时间按步数归一化；**没有一项研究把"朝向"作为计分项**，因为2×2、2×4砖本身旋转对称或近似对称。【推测：这正是它们回避朝向问题的方式】
- 步数从4到32可调，常见24步左右。

---

## 四、在你们约束下的任务设计推理

### 4.1 约束逐项分析

1. **1080p广角头戴相机**：广角意味着桌面上一块2×2砖只占很少像素。"Augmented Reality Applied to LEGO Construction"指出，LEGO单位尺寸只有1.6 mm量级，对识别很不利。来源：https://arxiv.org/pdf/1907.12549 。→ 优先用**Duplo（各维度加倍）**或更大的砖。
2. **每2–3 s一帧**：Funk基准中每步总时间约5 s（定位零件约2.1 s + 拣取约0.9 s + 定位位置约1.2 s + 装配约1.0 s）。按2–3 s的采样间隔，一步只能采到约2帧，而且完成时刻到被采样之间平均有1–1.5 s的量化延迟。→ 这与下文第五节的LEGO时延容忍区间（600–2700 ms）同一量级，**会显著稀释网络延迟操纵的效应**。【推测，但基于算术】
3. **手在画面里**：IndustReal通过协议让手离开。→ 建议采用"放好后手离开底板/或做一个确认手势"的交互协议，或者只在检测到画面稳定、没有手时才调用判定器。
4. **光面砖**：没有VLM层面的文献（见2.3(d)）。→ 用哑光砖（或哑光3D打印件，如IndustReal的PLA）、漫射照明，避开蓝/白、黄/白这类在高光下易混淆的颜色组合。
5. **无状态VLM+渲染参考图**：IndustReal B3表明"限制下一步可能的状态"有显著收益；IKEA-Bench表明渲染/图示与真实视频之间的跨描绘对齐很弱。→ 判定器应**有状态**（服务器维护当前状态，每次只问"期望的那一块到位了吗"），参考图最好用**同一相机、同一机位拍的真实照片**，而非渲染图。
6. **5–10分钟会话，需要暴露延迟效应**：按Funk的每步约5 s计，10–20步约1–2分钟，就算加上指导语和纠错也不到10分钟。→ 可以设计2–3个等长的变体（如各12–16步），在被试内轮换网络条件。

### 4.2 整个方法是否错了？

**部分错了。** "用通用VLM作为近乎完美的逐步评判器"这一前提，在文献中没有任何支持：最接近的LEGO基准上GPT-4o只有40.54% F1；工业ASD专用检测器在错误状态上的误报率也达65%。问题不在提示工程，而在任务本身把"细粒度3D状态+无固定参考系"交给了模型。如果研究目标是网络QoE，判定器的误差就是干扰变量，应当**从实验设计上把它消除**，而不是寄希望于模型进步。可行的三条路是：①把任务改成CV可确定判定的形式；②VLM作辅助，经典CV作主判；③"绿野仙踪"（Wizard-of-Oz）或半自动判定，让被试端体验到的仍是"AI助手"，但判定真值来自人工或确定性规则。

---

## 五、AI助手/对话代理/AR引导的网络QoE研究

### 5.1 最接近你们的先例：可穿戴认知助手（LEGO任务）

- **Chen et al., An Empirical Study of Latency in an Emerging Class of Edge Computing Applications for Wearable Cognitive Assistance，ACM/IEEE SEC 2017**：https://www.cs.cmu.edu/~zhuoc/papers/latency2017.pdf 。Gabriel系统把Glass、HoloLens或手机上的640×360、15 fps视频流推送到cloudlet或云端。作者为每类任务定义了端到端时延的"紧界/松界"：低于紧界，用户对改进不敏感；超过松界，体验和表现受到显著影响。**LEGO等逐步指导任务为600–2700 ms**（台球95–105 ms，乒乓150–230 ms，人脸370–1000 ms，数字引自Pham et al. 2021的汇总表）。上云时"Ping-pong、Draw和Lego达不到紧界"。**这是你们的实验最直接的对标文献。**
- **Olguín Muñoz et al., Impact of delayed response on Wearable Cognitive Assistance，PLOS ONE 2021**：https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0248690 。N=40，LEGO助手，注入0、0.6、1.125、1.65、2.175、2.7、3.0 s的延迟。结论："长时间的系统延迟使用户相应地（且显著地）放慢执行速度，这种效应在系统恢复响应后仍会持续一段时间"，并与神经质人格特质相关。**注意**：该研究去掉了真实网络，在本地用缓冲注入延迟。这正好留给你们一个空白：在真实WebRTC链路上操纵丢包、带宽和抖动。

### 5.2 语音/LLM对话代理的响应延迟

- **Maslych et al., Mitigating Response Delays in Free-Form Conversations with LLM-powered Intelligent Virtual Agents，ACM CUI 2025**：https://arxiv.org/pdf/2507.22352 。ASR→LLM→TTS代理，延迟设为1.5 / 4.0 / 6.5 s。延迟显著降低感知响应时间、参与度、印象、能力评价和再次使用意愿；"超过4秒后体验下降"。自然填充语（"让我想想"加手势）能缓解，人工等待指示（图标+音效）无显著作用。57.41%的参与者最喜欢低延迟代理，61.11%最不喜欢高延迟代理。
- **Peng et al., CHI 2020 LBW**（N=94）："用户最多可容忍4 s延迟，但在8 s延迟时满意度下降。"（据子代理检索，DOI 10.1145/3334480.3382792）
- **众包对话系统延迟研究，PACM HCI/CSCW 2022**（N=478）：超过8 s后评价明显变差，16 s引起烦躁；2–4 s反而被认为"像机器人、快得不真实"（该场景下用户预期对面是真人在打字）。来源：https://dl.acm.org/doi/10.1145/3555765
- **车载对话代理，AutomotiveUI 2020**：过长的正延迟使用户以为"出错了"，负延迟（抢话）则被认为粗鲁。来源：https://dl.acm.org/doi/10.1145/3409120.3410651
- 【注意来源质量】网上流传的"700 ms魔法阈值""斯坦福研究称满意度高73%"等说法来自厂商博客，没有可核查的出处，不应引用。

### 5.3 AR/XR与远程引导中的网络损伤

- **Wang et al., Understanding How Network Performance Affects User Experience of Remote Guidance，Springer 2014**：远程移动辅助系统，5种网络场景，同时测时延、抖动、带宽和丢包；结论是"丢包率是QoE下降的最大贡献者"。来源：https://link.springer.com/chapter/10.1007/978-3-319-10166-8_1 。**这提示你们：丢包对视频上行（VLM看到的帧质量）和语音下行的影响可能比纯时延更大。**
- **Mitra et al., QoE Assessment of Cloud-based Social XR over Heterogeneous Access Networks，IEEE CCNC 2025**（N=28，20种条件）：RTT在77 ms以内对QoE无显著影响；RTT≥77 ms且丢包>2%时显著下降；抖动超过约52 ms也会显著下降。来源：http://karanmitra.me/wp-content/uploads/2024/12/SocialXR_CCNC_2pages_Preprint.pdf
- **Delay Threshold for Social Interaction in Volumetric XR Communication，ACM TOMM 2024**：远程双人积木搭建任务，端到端延迟300–1500 ms；社交临场感受延迟影响明显，而任务时长差异不显著。来源：https://dl.acm.org/doi/10.1145/3651164 。**含义**：主观评分往往比任务时间对延迟更敏感，你们应同时采集两者。
- **协作VR中的延迟与突发丢包，Scientific Reports 2021**：大延迟显著影响QoE但不影响任务表现，突发丢包则对两者影响都更大。来源：https://www.nature.com/articles/s41598-021-02567-7
- **TPIFM（arXiv 2026）**：远程AR协作，端到端延迟100–3000 ms共8档，按ITU-T P.910的ACR五级量表评分，并指出"不同任务类型的JND不同"。来源：https://arxiv.org/pdf/2603.09264 （未能获取结果数据【证据薄弱】）

### 5.4 标准

- **ITU-T G.114**：2000版规定单向时延0–150 ms"对大多数应用可接受"，150–400 ms在知情前提下可接受，超过400 ms"对一般网络规划不可接受"。现行2003版保留400 ms作为规划上限，并指出高交互任务在低于100 ms时就可能受影响。来源：https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-G.114-200305-I!!PDF-E
- **ITU-T G.1036（2022）**：AR服务的QoE影响因素，包括传输时延和"AR服务的响应性能"。来源：https://www.itu.int/rec/T-REC-G.1036/en
- **ITU-T P.1320（2022）/ P.1321（2025）**：XR会议的QoE评估，以及交互式主观测试方法；P.1321的标准任务中包含"积木搭建"（Block Building）。来源：https://www.itu.int/rec/T-REC-P.1320
- **ITU-T G.1051（2023）**：真实应用流量模式下的时延测量与交互性评分。
- 【证据薄弱】本次没有找到专门针对云端语音助手/AI助手QoE的ITU-T建议书；最接近的是P.852（文本聊天机器人的主观质量评估）。

### 5.5 定位你们的实验

现有文献要么在本地注入延迟（PLOS ONE 2021），要么研究的是人–人远程协作或社交XR（CCNC 2025、TOMM 2024）。**"真实WebRTC链路+云端VLM判定+语音反馈"的AI任务助手在丢包、带宽受限下的QoE，基本是空白**，这是你们的贡献点。但要让效应可测，系统自身的基线延迟（采样间隔+VLM推理+TTS）必须明显低于LEGO任务约2.7 s的松界，否则网络操纵会被基线淹没。【推测：基于Chen 2017的界限与你们2–3 s采样+GPT类调用的时延估算】

---

## 推荐任务设计

### 方案A（首选）："固定Duplo底板+二维颜色格位"任务，经典CV主判+VLM复核

- **形态**：Duplo底板固定在桌面，四角贴ArUco/AprilTag标记；只用2×2和2×4哑光Duplo砖，4–5种高区分度颜色（如红、黄、绿、蓝、黑，避免白色）；每步只放一块，只在底板上放一层或最多两层；目标是12–16步的平面马赛克或矮墙。
- **判定**：用标记做单应性矫正，把画面变成俯视网格，对每格做颜色分类（HSV加少量标定），与期望状态差分。只有"画面稳定且手不在底板上"时才判定。VLM只负责生成自然语言纠错说明，或在CV置信度低时复核。
- **优点**：确定性，可达到接近100%的准确率，可独立验证；与Funk基准、Gabriel LEGO助手、DuploTrack同属一类思路，可比性强；判定延迟可降到百毫秒级，网络效应不会被淹没。
- **缺点**：不再是"VLM助手"的纯粹形态；需要标定和照明控制；二维任务对被试来说可能偏简单（参考HandsInTouch的教训），需要通过步数和干扰砖提高难度。

### 方案B：保留VLM为主判，但把问题降维成"单一二元问题"

- **形态**：同方案A的底板和砖。服务器维护状态；每帧只问VLM一个问题，例如："格位(3,5)是否有一块红色2×2砖？是/否"。同时提供标记矫正后的裁剪图，以及同机位拍摄的"期望状态真实照片"（而非渲染图）。
- **优点**：仍是VLM驱动；利用程序先验（IndustReal B3的思路）规避长提示干扰（观察e）；不涉及朝向（观察b、c）。
- **缺点**：没有文献证明这样能达到"近乎完美"；LEGO Co-builder中连位置判断都低于50% F1【推测：降维加矫正后会显著改善，但必须用自己的数据预先测出准确率上限】；VLM调用延迟本身仍有数秒。

### 方案C：Wizard-of-Oz/半自动判定

- **形态**：被试面对的是完整的"AI语音助手"；判定由实验者在监控端按键完成（或由方案A的CV自动完成、实验者兜底），网络条件照常作用于上行视频和下行语音。
- **优点**：完全消除模型误差，干净地隔离网络效应；HCI中常用。
- **缺点**：生态效度问题；人工判定的反应时间本身带来方差；如果研究问题包括"网络损伤如何通过降低帧质量影响AI判定"，这一路径会被切断。

### 方案D（不推荐，除非研究目标改变）：保留在手中搭建和斜顶等朝向零件

- 只有当研究问题改为"VLM判定误差与网络损伤的交互"时才有意义。文献（DORI、LEGO Co-builder、IndustReal）一致预测，在这种形态下判定误差会主导结果。

### 通用建议

- **把采样改为事件驱动或≥2 fps**，并测量、报告"完成动作→语音反馈"的端到端基线延迟；目标是远低于600 ms–2.7 s的LEGO容忍区间。
- **网络条件的设计**：参考Olguín Muñoz的0–3 s延迟梯度，以及Wang 2014"丢包影响最大"的结论，至少覆盖"时延"和"丢包"两个维度。
- **同时测主观与客观指标**：ACR/MOS（P.910/P.1321）、NASA-TLX、每步时间（GATM分段）、错误数、纠错次数，以及延迟恢复后的"滞后放慢"。
- **正式实验前**，先用自己的数据在理想网络下测判定准确率（按步、按错误类型），把它作为纳入实验的门槛。

---

## 优先阅读论文清单（按相关性排序）

1. Olguín Muñoz et al., Impact of delayed response on Wearable Cognitive Assistance，PLOS ONE 2021，https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0248690 ：LEGO助手加注入延迟，与你们的实验最接近。
2. Chen et al., An Empirical Study of Latency in … Wearable Cognitive Assistance，ACM/IEEE SEC 2017，https://www.cs.cmu.edu/~zhuoc/papers/latency2017.pdf ：LEGO任务的时延容忍界限与系统架构。
3. Schoonbeek et al., IndustReal，WACV 2024，https://arxiv.org/abs/2310.17323 ：状态式步骤完成的定义、协议简化和失败模式。
4. Huang/Pei et al., LEGO Co-builder，arXiv 2025，https://arxiv.org/html/2507.05515 ：GPT-4o在LEGO状态检测上的上限。
5. Funk et al., A Benchmark for Interactive AR Instructions for Assembly Tasks，MUM 2015，https://thomaskosch.com/wp-content/papercite-data/pdf/funk2015gatm.pdf ：可直接复用的Duplo任务与GATM度量。
6. Tasnim et al., Seeing Isn't Orienting（DORI），arXiv 2025，https://arxiv.org/html/2505.21649v7 ：VLM朝向判断的系统性失败。
7. Maslych et al., Mitigating Response Delays … LLM-powered IVAs，CUI 2025，https://arxiv.org/pdf/2507.22352 ：LLM语音代理的延迟阈值与填充语策略。
8. Gupta et al., DuploTrack，UIST 2012，https://dl.acm.org/doi/10.1145/2380116.2380167 ：非VLM的实时Duplo状态追踪。
9. Blattgerste et al., Comparing Conventional and AR Instructions for Manual Assembly Tasks，PETRA 2017，https://www.semanticscholar.org/paper/b2e0ebd35c4fb20d87fda1de22e658515c0275b4
10. Rahmanzadehgervi et al., Vision language models are blind，ACCV 2024，https://openaccess.thecvf.com/content/ACCV2024/html/Rahmanzadehgervi_Vision_language_models_are_blind_ACCV_2024_paper.html
11. Wang et al., Understanding How Network Performance Affects User Experience of Remote Guidance，2014，https://link.springer.com/chapter/10.1007/978-3-319-10166-8_1
12. Ozsoy/Doorenbos et al., ZeProM，arXiv 2026，https://arxiv.org/pdf/2606.21579 ：VLM零样本错误检测的有效条件。
13. PROVIA，arXiv 2026，https://arxiv.org/html/2609.20638 ：对现有在线错误检测评测协议的批评，读Assembly101类数字前必读。

---

## 注意事项与证据局限

- **镜面反射（观察d）**：没有找到VLM层面的直接研究，相关建议基于经典视觉常识【推测】。
- **HoloAssist的F-score**来自二手综述，未核对原文表格【证据薄弱】。
- **DORI的数字**因版本不同而不同（54.2%/64.2%粗粒度），引用时需注明版本。
- **Chen 2017的界限**来自任务分析和文献推导，并非大样本MOS研究；PLOS ONE 2021在本地注入延迟，未涉及真实网络。
- **语音代理的延迟阈值**（约1–2 s偏好、约4 s明显下降、约8 s强烈下降）来自应用层注入延迟，而非网络仿真。
- 几篇2026年arXiv预印本（ZeProM、PROVIA、IKEA-Bench、TPIFM）尚未经过同行评审。
- 本次检索未覆盖"lost in the middle"式的多模态长上下文研究，以及Ego-Exo4D的keystep精度数字；如有需要可补查。
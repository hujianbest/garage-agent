---
title: "一文读懂 Harness"
date: 2026-05-12
tags: [AI, Harness Engineering, Coding Agent, 软件工程]
draft: true
---

这篇文章，我前一版写得太像讲义了。

资料都对，逻辑也没啥大问题，但读起来不像我自己会写出来的东西。像什么呢？像一个很认真但有点端着的 AI，在给大家做 Harness Engineering 科普。

这就有点尴尬了。

咱们聊 Harness，本来就是为了让 AI 别端着、别乱跑、别写一堆看起来正确但没人想读的东西。结果我自己先写成了那样。

所以这一版重新来。

这两天我主要看了三篇原文：OpenAI 的《Harness engineering: leveraging Codex in an agent-first world》，Anthropic 的《Effective harnesses for long-running agents》，还有《Harness design for long-running application development》。不绕弯子，先说结论：

Harness 不是更高级的 prompt。

它是模型外面的那套工程现场。

agent 开工前读什么，做到一半怎么交接，做完凭什么算数，搞坏了怎么发现，下次会话怎么接着干，这些东西加起来，才是 Harness。

![一文读懂 Harness 封面](images/harness_blog_cover.png)

# 1. 充了钱，然后呢？

说实话，我一开始对 AI Coding 的期待很朴素。

我都花钱买会员了，模型也越来越强了，那总该能少受点罪吧？

现实经常是另一回事。

你让 agent 做一个功能，它动作很快。读文件、改代码、跑命令，屏幕刷得飞起。十分钟以后，它告诉你：完成了。

你一试。

按钮没反应，页面状态不刷新，测试没跑全，某个边界 case 直接炸。然后你让它修，它也很积极，修完这个地方，另一个地方又冒烟。来来回回折腾几轮，前面省下来的时间，全在后面擦屁股的时候吃回去了……

这时候咱们很容易骂模型。

是不是 Claude 不够强？是不是 GPT 还差一代？是不是上下文窗口再大点就好了？

以前我也这么想。

但 OpenAI 和 Anthropic 这几篇文章给我的刺激是：很多时候，不是模型不会写代码，是工作现场太乱。

Anthropic 做过一个挺狠的对照。让同一个模型做一个 2D 复古游戏编辑器。裸跑，20 分钟，花 9 美元，核心玩法没跑起来。加上 planner、generator、evaluator 这套完整 harness，跑 6 小时，花 200 美元，游戏可以正常玩。

模型没换。

prompt 也不是突然开光。

变的是工作方式。

OpenAI 那边更夸张。他们用 Codex 从空仓库开始做内部产品，坚持 0 行人工手写代码。五个月后，仓库大约百万行代码，三位工程师驱动 Codex 合并了大约 1500 个 PR，平均每人每天 3.5 个 PR。

这数字看着很爽，但重点不是「AI 可以替人写百万行代码」。

重点是人类工程师在干什么。

他们不再把主要精力花在敲代码上，而是在设计环境、表达意图、建立反馈循环、让 agent 能自己验证、自己修、自己交接。

也就是说，人的价值不是没了，是上移了。

以前咱们写代码，现在咱们搭工作现场。

# 2. Harness 到底是个啥？

如果只用一句话讲：

Harness 是给 AI agent 干活用的工程环境。

别急着把它理解成某个工具、某个框架、某个目录结构。它更像一整套现场纪律：谁先看图纸，谁拿工具，做到哪要签字，出门前谁验收，现场乱了谁清理。

咱们以前做软件工程，其实一直在干这个。

需求要写清楚，架构要有边界，任务要拆小，测试要跑，代码要 review，发布要留回滚方案。只不过以前这些纪律主要长在人脑子里，靠团队文化、会议、文档和老工程师的唠叨来维持。

AI Coding 之后，这套东西必须变成 agent 看得见、读得懂、执行得了的文件和命令。

我把 Harness 拆成五块。

![Harness 五个子系统](images/harness_five_subsystems.png)

## 2.1 指令，别写成说明书坟场

很多人第一次给 agent 加规则，会干一件事：把所有东西塞进 `AGENTS.md`。

项目背景、代码规范、架构原则、测试命令、发布流程、踩坑记录，全写进去。看起来很负责，实际上很容易把 agent 淹死。

OpenAI 也踩过这个坑。

他们试过一个巨大的 `AGENTS.md`，结论很直接：失败得很可预测。

上下文是稀缺资源。你把根指令文件写成小说，真正跟任务有关的代码、文档、日志就被挤掉了。更麻烦的是，当每句话都写得像「很重要」，agent 就不知道哪句真的重要。

后来他们的做法很朴素：`AGENTS.md` 当目录。

大概 100 行，告诉 agent 先读什么、遇到什么问题去哪找、哪些规则不能碰。真正详细的内容放到结构化的 `docs/` 里，比如架构、产品规格、质量评分、可靠性要求。

这就像带新人。

你不会第一天丢给他一本 1000 页手册，然后说「都很重要」。你会先告诉他，地图在这，当前任务在这，出了问题看这几份文档。

给地图，别给百科。

## 2.2 状态，别让下一轮从失忆开始

agent 有一个特别像新人的地方：这轮聊得热火朝天，下一轮一开，又像刚入职。

Anthropic 的 long-running agents 文章就是围绕这个问题展开的。长任务不可能都塞进一个 context window，每个新会话默认又不知道前面发生了什么。你不留交接，它就只能考古。

所以 harness 里要有外置记忆。

`feature_list.json` 记录哪些功能没开始、哪些正在做、哪些真的通过了。

`progress.md` 或 `claude-progress.txt` 记录每轮做了什么、跑了什么验证、还有什么没确认。

`session-handoff.md` 负责长任务中断时告诉下一轮：别瞎猜，从这里接。

git history 也很重要。它让 agent 能看到最近发生了什么，必要时还能回退到一个干净状态。

Anthropic 的做法是，第一轮 initializer agent 先把环境搭起来：`init.sh`、进度文件、feature list、初始 commit。后续 coding agent 每轮开工先读这些东西，再选一个没完成的功能推进。

这不复杂。

但很管用。

人类团队交接班也是这样。你不能指望夜班工程师靠灵感知道白班修到哪了。

## 2.3 验证，别听它说「应该可以」

AI 最烦人的地方，不是会犯错。

是它犯错以后还挺自信。

它会说「实现完成」「测试通过」「逻辑应该没问题」。听着很稳，实际一跑，可能页面都打不开。

所以 Harness 里最硬的一块，就是验证。

完成不能靠 agent 自己说。完成要靠命令、日志、截图、端到端路径、浏览器自动化、构建结果、测试输出。

Anthropic 提到一个很真实的现象：Claude 会写单测，也会用 `curl` 打开发服务器，但如果你不明确要求它像用户一样做端到端测试，它可能根本不知道功能没跑通。

OpenAI 做得更彻底。他们让 Codex 能启动每个 git worktree 对应的应用实例，能通过 Chrome DevTools Protocol 看 DOM、截图、导航，还能查询 logs、metrics、traces。

这就很关键了。

以前咱们让 AI「检查一下」，它可能就是读读代码，安慰你一句看起来没问题。

现在你让它检查，它能真的打开应用、点按钮、看日志、查指标。

这才叫验证。

不是让 AI 更自信，是让 AI 看见事实。

## 2.4 范围，一次只端一个盘子

Agent 很容易太热心。

你让它修一个筛选 Bug，它顺手重构状态管理。你让它加一个按钮，它顺手改了路由、样式、数据层，还附赠一堆你没让它碰的「优化」。

看起来干了很多。

到头来真正能验收的没几个。

Anthropic 的解法特别土：一次只做一个 feature。

而且 feature 不能写成「优化聊天体验」这种空气话。要写成端到端行为，比如用户点击 New Chat 后，新会话被创建，聊天区显示欢迎状态，侧边栏出现新会话。

一开始全部是 failing。

只有真的跑过验证，才能改成 passing。

这就是约束。

但约束不是压制 AI。约束是给 AI 装轨道。没有轨道，它跑得越快，冲出去越远。

## 2.5 生命周期，开工和收工都要有规矩

很多 agent 失败，不是在写代码时失败，而是在开头和结尾失败。

开头没确认环境是不是坏的，就开始叠新功能。

结尾没更新进度、没清临时代码、没记录没验证的边界，下一轮进来先数字考古半小时。

所以一个 agent session 应该像一个小事务。

开工时：确认目录，读 `AGENTS.md`，读进度，读 feature list，看 git log，跑 `./init.sh`，先确认 baseline 是绿的。

收工时：跑验证，更新进度，更新功能状态，记录风险，清理临时东西，只在可以恢复时 commit。

![Agent 会话生命周期](images/harness_session_lifecycle.png)

这套流程一点都不新。

甚至有点老派。

但 AI Coding 之后，老派的东西突然又值钱了。

# 3. Prompt、Context、Harness，别混在一起

我一开始也容易把这几个词混着用。

Prompt Engineering，是把一句话说清楚。

Context Engineering，是给这一轮对话选对材料。

Harness Engineering，是设计整个工作现场。

还是用摄影打个比方。

Prompt 是你对摄影师说：帮我拍一张傍晚海边的人像，暖色调，有电影感。

Context 是你给他看样片、场地照片、模特资料、器材清单。

Harness 是整间摄影棚：灯怎么布，器材谁管，选片标准是什么，修图怎么验收，下次拍摄怎么延续风格。

三者都重要。

但咱们一旦进入真实工程任务，单次 prompt 再漂亮，也挡不住会话断片、范围乱飞、验证缺失、状态漂移这些老问题。

这就是 Harness 的位置。

它解决的不是「这一句怎么说」，而是「这个系统怎么长期稳定干活」。

# 4. 三篇原文真正给我的启发

OpenAI 那篇文章，表面上是在讲 Codex 写了百万行代码。

但我读下来，最重要的不是百万行。

是他们把仓库变成了 agent 能读懂的系统。

`AGENTS.md` 是目录。`docs/` 是知识库。架构约束靠 linter 和结构测试执行。日志、指标、trace、UI 都要对 agent 可见。人的 taste 不能只停在 review 评论里，要沉淀成文档或工具。

这句话很关键：agent 看不到的东西，对它来说就不存在。

你在 Slack 里讨论过的架构原则，你脑子里默认的产品判断，你们团队口口相传的禁忌，如果没有进入仓库，对 agent 来说就是空气。

Anthropic 第一篇文章，给的是最小可行版本。

initializer agent 先搭环境，coding agent 后续一轮一轮推进。每轮只做一个 feature，做完要更新 progress，要 commit，要留下干净状态。

这套东西不花哨，但特别适合咱们今天就抄回自己的项目。

Anthropic 第二篇文章，讲的是更复杂的多 agent 结构。

planner 把一句话需求扩成产品规格，generator 负责实现，evaluator 用 Playwright MCP 像用户一样操作应用，再按 rubric 打分。

这里最让我有共鸣的是 evaluator 校准。

作者说，Claude 开箱做 QA 并不好。它会发现真实问题，然后把自己说服到通过。这个画面太熟了。像不像有些人写完代码之后自测一下，发现一个小问题，然后心里默念「应该不影响主流程」？

AI 也会这样。

所以 evaluator 也要训练，也要看日志，也要把它和人类判断不一致的地方一点点改回来。

这就回到了软件工程的老道理：评审不是形式，评审也需要标准。

# 5. 如果今天就想落地，先别搞复杂

别一上来就 planner、generator、evaluator 全家桶。

先从四个文件开始。

## 5.1 `AGENTS.md`

写短一点。

只写开工流程、工作规则、完成定义。

根文件不要超过一两百行。详细背景放到 `docs/ARCHITECTURE.md`、`docs/PRODUCT.md`、`docs/QUALITY.md` 里。

它是地图，不是小说。

## 5.2 `feature_list.json`

不要只写 TODO。

每个功能至少要有描述、状态、验证方式、证据和依赖。

最关键的是，状态不能靠嘴改。只有验证跑过、有证据，才允许从 `in_progress` 变成 `passing` 或 `done`。

功能清单不是 backlog。

它是 agent 的边界线。

## 5.3 `init.sh`

给项目一个统一入口。

安装依赖、类型检查、测试、构建、启动开发服务器，能放进去的就放进去。

然后在 `AGENTS.md` 里写死一条规矩：如果 `./init.sh` 一开始就失败，先修 baseline，不要加新功能。

这条很土。

但坏地基上盖楼，盖得越快越吓人。

## 5.4 `progress.md`

每轮结束前，让 agent 写清楚：本轮目标、改了哪些文件、跑了哪些验证、哪些地方没验证、下一轮第一步干什么。

不要写散文。

写给下一个 agent 看，越具体越好。

「继续优化体验」等于没写。

「下一步先运行 `npm test -- qa-service`，如果引用为空，检查 `IndexingService.chunkDocument` 的 >1000 字符路径」才有用。

# 6. 几个坑，提前避一下

第一个坑，根指令写成巨型小说。

越写越长，越没人读。agent 也一样。根文件做路由，细节放专题文档。

第二个坑，功能清单和进度日志各写各的。

`feature_list.json` 说 done，`progress.md` 说还有问题。你猜 agent 信谁？它可能信那个对自己最有利的。

第三个坑，只跑局部测试。

AI 很爱跑最快的测试，因为快，也因为容易绿。但真实 Bug 经常藏在组件边界。前端状态、IPC、持久化、索引、引用链路，只跑一个服务层单测看不出来。

第四个坑，让同一个 agent 又写又评。

自我评审当然有用，但别迷信。generator 写，evaluator 按 rubric 挑问题，必要时 planner 先写规格或 sprint contract。角色拆开，很多问题才会浮出来。

第五个坑，结束时不清场。

OpenAI 文章里提到，他们一开始每周五要花 20% 的工作时间清理 AI slop。后来把 golden principles 编码进仓库，用后台 Codex 任务持续扫描偏差、更新质量评分、开重构 PR。

这其实就是垃圾回收。

清洁不是洁癖。

清洁是给下一轮留命。

# 7. 绕了一圈，还是软件工程

读完这三篇文章，我反而没那么焦虑了。

因为 Harness Engineering 说到底，不是什么玄学新概念。

它是把老软件工程里的纪律，翻译成 AI agent 能执行的东西。

需求要清楚，边界要明确，状态要持久，验证要可靠，交接要干净。

咱们以前就知道这些。

只是以前靠人记，靠人盯，靠老工程师在 review 里碎碎念。

现在 AI 把执行力放大了，纪律也必须被放大。否则放大的不是生产力，是混乱。

所以真正重要的能力，可能不是会背多少 prompt 技巧。

而是你能不能把自己的工程判断写进系统里。

你怎么定义完成？

你怎么限制范围？

你怎么让下一轮知道上一轮做了什么？

你怎么让 AI 看到真实运行结果，而不是只看代码脑补？

这些问题，才是 AI Coding 进入真实工程之后绕不开的东西。

# 8. 别急着追新模型

我不是说模型不重要。

模型当然重要。更强的模型会让很多 harness 设计变简单，甚至让一部分旧约束变得多余。

Anthropic 第二篇文章里就讲了这个变化。Sonnet 4.5 上，context anxiety 很明显，所以 context reset 和结构化 handoff 是关键设计。到了 Opus 4.5/4.6，模型长任务能力和自我检查能力变强，有些 sprint 拆分和 evaluator 频率就可以重新评估。

这点很重要。

Harness 不是越复杂越好。

它应该像脚手架。施工时承重，楼盖好后能拆就拆。留下来的，应该是那些真正在保护质量、延续状态、减少返工的结构。

所以如果你现在已经在用 AI Coding，我建议别一上来研究 20 条神奇 prompt。

先问自己几个土问题：

- 我的 agent 开工前知道读什么吗？
- 它知道上次做到哪吗？
- 它一次只做一个清晰功能吗？
- 它完成时有可运行证据吗？
- 它结束时给下一轮留下干净现场吗？

这五个问题答不上来，再强的模型也可能只是跑得更快的野马。

Harness 做的事，就是把缰绳、跑道、检查点和马厩都修好。

听起来不酷。

但工程里很多真正有用的东西，本来就不酷。

能稳定交付，才酷。

---

## 资料来源

- [OpenAI: Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)
- [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Anthropic: Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps)

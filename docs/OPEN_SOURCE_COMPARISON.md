# SceneForge 开源项目适配对比

> 调研快照：2026-10-31。
> 结论基于各项目官方仓库、论文与官方文档；未做本地跑分，不引用未经核实的效果数值。
> 许可与权重条款只代表调研当时的公开信息，正式引入前必须再次审阅。

## 1. 调研目的

回答三个问题：

1. 是否存在一个开源项目，可以直接完成“单张/多张照片 → 可编辑 Blender 场景”？
2. 对建筑（含布达拉宫这类复杂地标）、产品道具、植物自然环境，各自应该用哪一段能力？
3. 哪些项目看起来相关，但不能作为核心依赖？

## 2. 核心结论

**不存在能端到端满足要求的单一项目。**

开源生态的现状是分段的：

| 能力段 | 代表项目 | 能给出什么 | 给不出什么 |
| --- | --- | --- | --- |
| 图像语义理解 | VLM、Grounding DINO、SAM 2 | 物体/部件框与 mask、开放词汇标签 | 三维几何、真实尺度、跨图实体身份 |
| 单图深度先验 | Depth Anything V2 | 相对深度、前后遮挡线索 | 米制尺寸、被遮挡结构 |
| 多视角几何 | COLMAP、OpenMVS、Meshroom | 相机位姿、稀疏/稠密点云、纹理网格 | 语义对象树、可编辑建筑构件 |
| 神经几何前端 | VGGT、DUSt3R/MASt3R | 学习式相机/深度/点图，可导出 COLMAP 格式 | 直接可交付的纹理网格；单图不是测量 |
| 单物体资产生成 | TRELLIS、TripoSR、Hunyuan3D、InstantMesh | 一个物体的网格与纹理 | 整个场景；真实地标被遮挡部分的恢复 |
| 程序化场景 | Infinigen、Geometry Nodes | 植物、地形、规则化构件与实例化 | 凭参考图忠实还原指定地标 |
| 渲染与数据管线 | BlenderProc | 批量渲染、相机灯光、回归基线 | 图片重建 |
| 地理上下文 | Blender GIS、OSM2World、Blosm | 地形、城市体块、道路水系 | 地理数据里不存在的建筑细节 |

因此 SceneForge 的定位是**编排与契约层**：把视觉证据、几何证据、语义结构和参数化生成器串成一条可追溯、可回滚的工程流水线。

### 2.1 对布达拉宫的直接含义

- 单张照片无法完成可靠测量重建：缺少视差，背面、进深与被遮挡结构不可观测。
- DUSt3R/VGGT 的单图输出属于学习先验推断，不是真实结构恢复。
- TRELLIS/TripoSR/Hunyuan3D/InstantMesh 生成的是“合理资产”，会补全不存在的结构，不能标为真实地标。
- 正确路线：**已有测绘/CAD/授权模型 > 有尺度控制的多角度采集 > 人工确认的参数化重建 > 单图概念模型**。
- 单图结果只能作为 `concept` 或 `proxy` 交付，不能标注为 `accurate`。

## 3. 适配矩阵

图例：✅ 可承担该角色；⚠️ 有条件可用；❌ 不应承担。

| 项目 | 主要角色 | 语义理解 | 多视角几何 | 可编辑对象 | 直接进 Blender | 建筑地标 | 产品道具 | 植物自然 | 许可关注点 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| COLMAP | 相机与几何 | ❌ | ✅ | ❌ | ⚠️ 需网格化 | ⚠️ 有覆盖才行 | ✅（多图小物体） | ✅（地形岩石） | New BSD，第三方依赖单独核查 |
| OpenMVS | 稠密重建/纹理化 | ❌ | ✅ | ❌ | ⚠️ OBJ/GLB 后仍需清理 | ⚠️ | ✅ | ✅ | **AGPL-3.0**，服务化需评估义务 |
| Meshroom | 摄影测量一体化 | ❌ | ✅ | ❌ | ⚠️ 导出网格后导入 | ⚠️ | ✅ | ✅ | MPL-2.0，含 AliceVision/Qt 等依赖 |
| VGGT | 神经几何前端 | ❌ | ⚠️ 学习式 | ❌ | ❌ 需转 COLMAP/网格化 | ⚠️ 试验性 | ⚠️ | ⚠️ | 自定义许可，仅 Commercial 权重可商用 |
| DUSt3R | 点图与全局对齐 | ❌ | ⚠️ 学习式 | ❌ | ❌ 需网格化 | ❌ 不适合交付 | ⚠️ | ⚠️ | **CC BY-NC-SA 4.0 非商业** |
| MASt3R | 匹配与位姿前端 | ❌ | ⚠️ 学习式 | ❌ | ❌ | ⚠️ | ⚠️ | ⚠️ | **CC BY-NC-SA 4.0 非商业** |
| TRELLIS | 单物体资产 | ❌ | ❌（多图是条件） | ⚠️ 单资产 | ✅ GLB | ❌ | ✅ | ⚠️ 单株 | MIT 为主，子模块另查 |
| TripoSR | 轻量单图资产基线 | ❌ | ❌（多文件是批处理） | ❌ | ✅ | ❌ | ⚠️ 简单物体 | ❌ | MIT |
| Hunyuan3D 2.x | 单物体形状 + PBR | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ 对照 | ⚠️ | 自定义社区许可（地域/MAU/托管限制） |
| InstantMesh | 单图资产生成 | ❌ | ❌（合成视图非观测） | ❌ | ✅ | ❌ | ⚠️ | ❌ | Apache-2.0，权重另核 |
| Grounding DINO | 开放词汇检测 | ✅ | ❌ | ❌ | ❌ | ✅ 部件候选 | ✅ | ✅ | Apache-2.0 |
| SAM 2 | 提示式分割/视频传播 | ⚠️ 无标签 | ❌ | ❌ | ❌ | ✅ 立面/屋面 mask | ✅ | ✅ | Apache-2.0（代码与权重） |
| Depth Anything V2 | 单图深度 | ❌ | ❌ | ❌ | ❌ | ⚠️ 仅先验 | ⚠️ | ⚠️ | 代码 Apache-2.0；**Base/Large 权重 CC-BY-NC-4.0** |
| OpenSeeD | 语义/全景分割 | ✅ | ❌ | ❌ | ❌ | ✅ 山体/天空/墙面 | ⚠️ | ✅ | Apache-2.0，依赖较旧 |
| Infinigen | 程序化自然场景 | ❌ | ❌ | ✅ 参数化 | ⚠️ 需封装 | ⚠️ 建筑有限 | ⚠️ | ✅ | BSD-3-Clause |
| Geometry Nodes | 参数化生成底座 | ❌ | ❌ | ✅ | ✅ 原生 | ✅ 构件级 | ✅ | ✅ | Blender 为 GPL，`.blend` 产物归用户 |
| BlenderProc | 渲染与合成数据 | ❌ | ❌ | ⚠️ | ✅ | ❌ | ❌ | ❌ | GPL-3.0 |
| Blender GIS | 地理数据导入 | ❌ | ❌ | ✅ 地形网格 | ✅ | ❌ | ❌ | ✅ 地形基底 | GPL-3.0，在线服务条款另查 |
| OSM2World | OSM → 3D | ❌ | ❌ | ⚠️ 体块 | ✅ GLB/OBJ | ⚠️ 仅标签内信息 | ❌ | ⚠️ | MIT；OSM 数据为 ODbL，需署名 |
| Blosm | 城市与地形导入 | ❌ | ❌ | ✅ 体块 | ✅ | ⚠️ 体块级 | ❌ | ✅ | GPL-3.0，Base/Pro 功能分开评估 |
| Archipack | 参数化建筑构件 | ❌ | ❌ | ✅ | ✅ | ⚠️ 仅常规构件 | ❌ | ❌ | GPL-3.0 旧仓库，**维护停滞** |
| Sverchok | 高级节点参数化 | ❌ | ❌ | ✅ | ✅ | ✅ 需自研节点图 | ⚠️ | ✅ | GPL-3.0 |

## 4. 关键项目说明

### 4.1 多视角几何

**COLMAP**：经典 SfM + MVS。输入是有重叠的多张图像，输出相机、稀疏/稠密点云，可导出网格。它解决“真实存在但需要测量”的部分，但没有语义拆分。无控制点时通常只能恢复到相似变换尺度。

**OpenMVS**：常作为 COLMAP 之后的稠密重建与纹理化阶段，可输出 PLY/OBJ/glTF/GLB。许可为 AGPL-3.0；如果把重建作为对外服务，需要单独评估网络服务义务。

**Meshroom**：AliceVision 的节点式摄影测量工具，一体化程度高，适合无头批处理，但输出仍是融合网格，需要人工清理与对象化。

**VGGT**：一次前向可给相机、深度、点图，并支持 COLMAP 导出，适合作为神经几何前端，再交给 COLMAP/OpenMVS 做后续。官方明确其单图能力不是专门的训练目标，不能当测量工具用。权重许可需要区分原权重与 Commercial 权重。

**DUSt3R/MASt3R**：研究价值高，但官方代码为 CC BY-NC-SA 4.0 非商业许可，且不直接交付纹理网格。不适合作为默认商业依赖。

### 4.2 图像语义理解

**Grounding DINO**：文本提示 → 候选框与短语，适合开放词汇检测，但没有 mask、层级和深度，也不做跨图实体关联。

**SAM / SAM 2**：提示式分割，SAM 2 增加视频流式记忆。静态照片主线用 SAM 2 图像预测器即可；视频/连拍序列才需要跟踪分支。SAM 2 的 track 只适合连续帧，不等于宽基线多图的实体关联。

**Depth Anything V2**：输出相对深度；另有室内/室外微调的米制模型，但域外地标场景不保证真实尺寸。Small 权重 Apache-2.0，Base/Large/Giant 为 CC-BY-NC-4.0。

**OpenSeeD**：可同时处理 thing 与 stuff（山体、天空、墙面），适合作为建筑背景与自然区域的补充。依赖较旧，建议独立环境。

### 4.3 单物体资产生成

**TRELLIS**：单图/文本/多图条件生成 mesh、radiance field、3D Gaussian，可导出纹理 GLB。多图是生成条件，不是相机测量；也没有语义对象树。适合作为“独立道具生成器”。

**TripoSR**：轻量、MIT、接入简单。CLI 多文件是逐图独立批处理，不能误认为联合多图重建。

**Hunyuan3D-2.1**：增加 PBR 纹理流程，2.0 有官方 API Server 与 Blender addon。许可为自定义社区许可，含地域、MAU、Hosted Service 限制，不能按 MIT/Apache 理解。

**InstantMesh**：内部用 Zero123++ 合成多视图，再进稀疏视图 LRM。合成视图不是真实观测，因此不具备真实多视角几何能力。

### 4.4 程序化与地理

**Infinigen**：数学规则与参数驱动的自然/室内场景生成器，BSD-3-Clause，活跃维护。适合植物、地形与自然场景的 Builder，但只能生成其生成器覆盖的类别。

**Geometry Nodes**：Blender 原生非破坏式参数化系统，是 SceneForge 的首选生成底座。它提供表达能力，不提供图像理解，地标仍需专用节点逻辑。

**BlenderProc**：批量渲染、相机灯光控制与合成数据管线，适合做回归测试与多视角渲染，不是重建工具。

**Blender GIS / OSM2World / Blosm**：地理上下文来源。OSM2World 当前仓库为 MIT（旧资料中的 LGPL 已过时），Blender GIS 与 Blosm 为 GPL-3.0。OSM 数据本身是 ODbL，需要署名与相同方式共享约束。

## 5. 不建议作为核心依赖的项目

| 项目 | 原因 |
| --- | --- |
| DUSt3R / MASt3R | 非商业许可，且需要额外网格化与纹理化 |
| YOLO-World | GPL-3.0，闭源集成需评估 copyleft 或商业许可 |
| Archipack（开源旧版） | 维护停滞，旧版面向 Blender 2.79；2.x 为付费获取 |
| 3D-GPT | 发布不完整且仓库未见明确许可，仅适合作 Agent 原型参考 |
| SceneCraft（论文项目） | 未找到作者官方公开实现，论文许可不等于代码许可 |
| Holodeck | Apache-2.0 但输出路径是 AI2-THOR/Unity，不适合作 Blender Builder |
| Semantic-SAM | 多粒度 mask 不等于正确的父子树，且许可未核实 |

同名警示：`OrangeSodahub/SceneCraft` 是另一个做布局条件扩散的项目，不是论文中的 LLM+Blender Agent。

## 6. 推荐组合

### 6.1 默认栈（首期）

```text
云端 VLM（场景理解与结构化建议）
  + Grounding DINO：开放词汇检测
  + SAM 2（图像预测器）：部件与物体 mask
  + Depth Anything V2 Small：单图深度先验
  + COLMAP：多图相机与几何证据
              ↓
   scene.json（唯一真源，记录观测、实体、关系、保真度）
              ↓
   Blender Python + Geometry Nodes Builders
              ↓
   多视角渲染对照 + 质量门禁
```

### 6.2 可选栈（按需启用）

| 需求 | 启用 |
| --- | --- |
| 需要纹理网格代理 | Meshroom 或 COLMAP→OpenMVS |
| 神经几何初始化试验 | VGGT（许可审查后） |
| 独立道具复杂网格 | TRELLIS（首选）/ TripoSR（基线）/ Hunyuan3D（PBR 对照） |
| 植物与自然环境 | Infinigen 封装 + Geometry Nodes 散布 |
| 真实地形与城市轮廓 | Blender GIS / OSM2World / Blosm |
| 批量渲染与回归 | BlenderProc |

### 6.3 选型原则

1. 一方只承担一个角色，避免“一个模型包打天下”的误用。
2. 所有外部能力通过适配器接入，核心契约不绑定供应商。
3. 模型版本、权重哈希、输入尺寸与后处理必须固定并可追溯。
4. 许可风险高的项目不进入默认链路；确需使用时单独评审。

## 7. 引入前复核清单

- [ ] 仓库 LICENSE 与权重许可分别确认，不只查代码许可。
- [ ] 训练数据与checkpoint条款是否允许目标使用方式。
- [ ] 服务化/托管是否触发 AGPL 或自定义许可义务。
- [ ] 依赖版本、CUDA 与 Python 版本可固定。
- [ ] 与目标 Blender 版本完成兼容性验证。
- [ ] 关键能力用自建 golden set 自测，不引用第三方宣传数值。
- [ ] 外部数据（OSM/DEM/卫星/底图）记录来源、许可与获取日期。

## 8. 来源

- COLMAP：https://github.com/colmap/colmap ；https://colmap.github.io/tutorial.html
- OpenMVS：https://github.com/cdcseacave/openMVS
- Meshroom：https://github.com/alicevision/Meshroom
- VGGT：https://github.com/facebookresearch/vggt
- DUSt3R：https://github.com/naver/dust3r
- MASt3R：https://github.com/naver/mast3r
- TRELLIS：https://github.com/microsoft/TRELLIS
- TripoSR：https://github.com/VAST-AI-Research/TripoSR
- Hunyuan3D-2.1：https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- InstantMesh：https://github.com/TencentARC/InstantMesh
- Grounding DINO：https://github.com/IDEA-Research/GroundingDINO
- SAM 2：https://github.com/facebookresearch/sam2
- Depth Anything V2：https://github.com/DepthAnything/Depth-Anything-V2
- OpenSeeD：https://github.com/IDEA-Research/OpenSeeD
- Infinigen：https://github.com/princeton-vl/infinigen
- BlenderProc：https://github.com/DLR-RM/BlenderProc
- Blender GIS：https://github.com/domlysz/BlenderGIS
- OSM2World：https://github.com/tordanik/OSM2World
- Blosm：https://github.com/vvoovv/blosm
- Archipack：https://github.com/s-leger/archipack
- Sverchok：https://github.com/nortikin/sverchok
- Blender Geometry Nodes：https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/introduction.html
- Blender 许可：https://www.blender.org/about/license/
- OpenStreetMap 许可：https://www.openstreetmap.org/copyright

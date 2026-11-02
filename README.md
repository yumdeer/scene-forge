# SceneForge

将单张或多张风景照片重建为**可追溯、可编辑、可分级发布**的 3D 场景工程。

- 整个风景分层重建：地形、建筑、植被、水面、天空与光照。
- 支持多图几何重建，也支持单图结合地理数据与参考资料补全。
- 高精度 Blender 母版与 three.js 发布档分离，按需生成多级 LOD。
- 所有事实、外部数据、假设与人工确认统一记录在 `scene.json`。

## 首期范围与口径

- 对象：建筑/场景、产品与静态道具、植物与自然环境；暂不包含人物与生物。
- 目标：**可编辑优先**。输出保留语义对象树与参数，不接受只能整体变形的“外壳模型”。
- 输入：单图快速生成，多图补全进深、遮挡与材质；复杂地标以**主视图高一致、其他视角合理**为验收口径。
- 运行：云端视觉模型负责理解，本地 Blender 负责确定性建模与导出。

## 文档

- [项目计划书](docs/PROJECT_PLAN.md)：目标、边界、场景分层、验收与实施阶段。
- [技术方案](docs/TECHNICAL_DESIGN.md)：详细设计，含证据层、场景契约、Blender 生成层与质量门禁。
- [开源项目适配对比](docs/OPEN_SOURCE_COMPARISON.md)：候选项目能力、许可与推荐组合。
- [实施路线](docs/IMPLEMENTATION_ROADMAP.md)：阶段交付、出口门禁与测试策略。
- [布达拉宫建模复盘](docs/POTALA_CASE_STUDY.md)：既有模型失真原因与专项重建流程。

## 快速开始

```bash
# 依赖（版本固定）
python3 -m pip install -r requirements.txt

# 校验场景 / 勘察文档
python3 pipeline/schema_validate.py scene examples/minimal-scene.json
python3 pipeline/schema_validate.py survey examples/minimal-survey.json

# 由勘察数据生成人读报告（唯一数据源，禁止手工维护第二份结论）
python3 pipeline/render_survey.py examples/minimal-survey.json --out /tmp/survey-report.md

# 契约与渲染测试
python3 -m unittest discover -s tests -v
```

报告模板见 [templates/survey-report.md](templates/survey-report.md)，由 `survey.json` 渲染生成，测试会校验其与渲染结果一致。

## 当前状态

阶段 1：工程契约与勘察基线。

- 已完成：`scene.json` / `survey.json` Schema、最小完整示例、校验 CLI、勘察报告渲染器、正负向契约测试。
- 进行中：`scene.json` v1.1 提案（`observations`、`relations`、`fidelity`、`geometryConstraints`、`cameras[].solvedFrom`）落 Schema。
- 待启动：阶段 2 单图最小闭环（视觉证据适配器、建筑 Builder、灰模主视图对照）。

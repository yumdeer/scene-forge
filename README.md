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

## 体量闭环（P1）

以布达拉宫为例，完整链路是“契约 → 覆盖 → 相机拟合 → 投影配准 → 灰模渲染”，每一步都有可执行脚本与机器可读报告：

```bash
SCENE=scenes/potala-palace-lhasa/scene.json
SURVEY=examples/potala-survey.json

# 1) 结构覆盖门禁：照片里可见的结构类别必须在场景里有元素承接
python3 pipeline/coverage_check.py --survey $SURVEY --scene $SCENE

# 2) 相机拟合：目标点 + 环绕方位/俯仰/距离 + fov；正视图锁死方位
python3 pipeline/fit_camera.py --survey $SURVEY --scene $SCENE \
  --photo photo_front --camera camera_front --lock-azimuth --elevation-limit 2 --write

# 3) 配准门禁：相机投影包围盒 vs 照片地标，输出 derived/registration-report.json 与叠加图
python3 pipeline/registration_check.py --survey $SURVEY --scene $SCENE

# 4) 灰模渲染（Blender 4.5 headless，Cycles CPU；缺 libSM 时补 LD_LIBRARY_PATH）
CAMERA_ID=camera_front RENDER_NAME=p1-massing-front.png \
  blender -b -P generators/architecture/potala_massing.py
```

要点：

- 相机水平位置只能由方位角与距离推出，禁止独立横移；否则求解器会用平移吸收几何比例误差。
- 照片只约束宽高比，绝对尺度必须写在场景根级 `scaleAnchor`，缺省的均匀缩放对成像不可观测。
- 地标 `scope` 区分“宫殿主体”与“含外围延伸墙的建筑群剪影”，两类不能混用一个包围盒。
- 生成器只消费 `scene.json` 的 `reconstruction.generator.parameters`，参数由 `pipeline/massing_params.py` 展开（支持重复阵列与坡面剪切）。

## 当前状态

阶段 1 已完成，阶段 2 的体量闭环（P1）已在布达拉宫专项跑通。

- 已完成：`scene.json` / `survey.json` Schema、最小完整示例、校验 CLI、勘察报告渲染器、正负向契约测试。
- 已完成：体量参数展开、结构覆盖门禁、相机拟合、投影配准门禁、Blender 灰模生成器，以及布达拉宫两视角相机。
- 已完成：`scaleAnchor` 尺度锚与地标 `scope`（主体 / 建筑群）契约字段。
- 进行中：布达拉宫 P1 体量收敛——配准门禁 2/4，正视图仍受红宫偏窄与东侧墙脚随地形下探约束，详见[技术方案 8.2](docs/TECHNICAL_DESIGN.md) 与[专项复盘](docs/POTALA_CASE_STUDY.md)。
- 待启动：阶段 2 的视觉证据适配器与立面细节（P3~P5）；`scene.json` v1.1 提案（`observations`、`relations`、`fidelity`、`geometryConstraints`、`cameras[].solvedFrom`）。

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

## 工作流

```text
照片 / 参考资料
   → survey.json      勘察：观测、区域、地标、尺度来源与假设
   → scene.json       契约：场景唯一真源，元素、相机、生成参数、验收关卡
   → 体量构建与渲染   确定性参数展开 + Blender headless 灰模
   → 质量门禁         覆盖、相机拟合、投影配准、轮廓对照
   → 分级发布         母版 / LOD / 预览 / 报告
```

各环节对应 `pipeline/` 下的独立脚本，输入输出都是契约文件与机器可读报告：

```bash
SCENE=<scene.json> SURVEY=<survey.json>

# 结构覆盖：照片中可见的结构类别必须在场景里有元素承接
python3 pipeline/coverage_check.py --survey $SURVEY --scene $SCENE

# 相机拟合：目标点 + 环绕方位/俯仰/距离 + fov，写回 scene.json 的 orbit 字段
python3 pipeline/fit_camera.py --survey $SURVEY --scene $SCENE \
  --photo <photoRef> --camera <cameraId> --lock-azimuth --write

# 投影配准：相机投影包围盒对照照片地标，输出报告与叠加图
python3 pipeline/registration_check.py --survey $SURVEY --scene $SCENE

# 灰模渲染：读取 scene.json 的生成参数、相机与光照
CAMERA_ID=<cameraId> blender -b -P generators/architecture/<builder>.py
```

约束：

- 相机水平位置只能由方位角与距离推出，不允许独立横移，否则求解器会用平移吸收几何比例误差；正视图必须锁死方位角。
- 照片只约束宽高比，绝对尺度必须写在场景根级 `scaleAnchor`，均匀缩放对成像不可观测。
- 照片地标用 `scope` 区分主体与建筑群剪影，两类不共用同一包围盒。
- 生成器只消费 `scene.json` 的 `reconstruction.generator.parameters`，禁止在脚本内写死坐标。

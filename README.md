# FiguHair - Blender 插件

一个 Blender 插件，用于从曲线创建管道（管状网格），支持**逐点自定义横截面形状**。每个曲线控制点的横截面都可以通过拖动顶点来自由编辑形状，非常适合制作头发、触须、藤蔓等造型。

## 核心功能

- 每个曲线控制点拥有独立的横截面形状
- 横截面由多个顶点组成，每个顶点的 X/Y 位置可单独调整
- 相邻控制点之间的横截面自动平滑插值过渡
- NURBS / Path 曲线会按平滑曲线采样生成管线，少量控制点也能得到柔和弯曲效果
- Poly 曲线保持折线生成，适合需要硬边路径的情况
- 支持添加/删除横截面顶点，自由塑造任意截面形状
- 内置圆形重置、线性渐细预设
- 将某个点的横截面复制到所有点
- 自动更新：编辑参数后管道实时重新生成

## 安装方法

1. 将 `hair_curve_pipe` 文件夹复制到 Blender 插件目录：
   - Windows: `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\`
   - macOS: `~/Library/Application Support/Blender/<version>/scripts/addons/`
   - Linux: `~/.config/blender/<version>/scripts/addons/`
2. 打开 Blender → `Edit > Preferences > Add-ons`
3. 搜索 "FiguHair"，勾选启用

## 使用方法

### 基本流程

1. 创建一条曲线（Bezier / Poly / NURBS）
2. 选中曲线，在 3D 视图右侧边栏找到 **FiguHair** 标签
3. 点击 **Sync Point Settings** 同步控制点
4. 在 **Curve Points** 子面板选择要编辑的控制点
5. 在 **Cross-Section Editor** 中调整横截面顶点位置
6. 点击 **Generate Hair Pipe** 生成管道网格

### Cross-Section Editor 说明

选中某个曲线控制点后，面板会显示该点的横截面：
- 横截面是一个由多个顶点围成的闭合轮廓（默认是圆形）
- 每个顶点显示 X / Y 坐标，直接修改数值即可改变形状
- **Add Vertex**：在当前顶点和下一个顶点之间插入新顶点
- **Remove Vertex**：删除当前选中的顶点（最少保留 3 个）
- **Reset to Circle**：将当前点的横截面恢复为圆形
- **Copy to All Points**：将当前横截面形状应用到所有控制点
- **Scale**：整体缩放横截面
- **Rotation**：整体旋转横截面

### 典型工作流：制作一根头发

1. 添加 Bezier 曲线，编辑模式下调整形状
2. 回到物体模式，Hair Pipe 面板 → Sync Point Settings
3. 点击 Linear Taper 应用渐细效果
4. 选择某个特定的点，手动拖动横截面顶点做出扁平或不规则形状
5. Generate Hair Pipe 生成最终网格

## 兼容性

- Blender 3.6+
- 支持 Bezier、Poly、NURBS 曲线
- 支持环形（Cyclic）曲线

## 文件结构

```
hair_curve_pipe/
├── __init__.py      # 插件入口
├── properties.py    # 属性（横截面顶点、逐点设置、全局设置）
├── operators.py     # 核心算法与操作符
├── panel.py         # UI 面板
├── handler.py       # 自动更新处理器
└── README.md
```

# FiguHair GitHub 上传说明

本说明用于以后把 FiguHair 插件更新并上传到 GitHub。

仓库地址：

```bash
https://github.com/supokedehljs/FiguHair.git
```

## 1. 准备

确认当前目录是插件目录：

```bash
cd d:\OneDrive\cursor_workspace\blender\hair_curve_pipe
```

确认 Git 状态：

```bash
git status
```

## 2. 第一次上传

如果目录还没有初始化 Git：

```bash
git init
git branch -M main
git remote add origin https://github.com/supokedehljs/FiguHair.git
```

添加文件并提交：

```bash
git add .
git commit -m "Initial FiguHair release"
```

推送到 GitHub：

```bash
git push -u origin main
```

如果 GitHub 要求登录，请按终端提示登录，或使用 GitHub Personal Access Token。

## 3. 后续更新上传

每次修改插件后，在插件目录执行：

```bash
git status
git add .
git commit -m "Update FiguHair"
git push
```

建议把提交信息写得更具体，例如：

```bash
git commit -m "Improve sharp corner cross-section frames"
```

## 4. 如果远程仓库已经有内容

如果第一次推送时提示远程仓库已有提交，可以先拉取：

```bash
git pull --rebase origin main
```

解决可能出现的冲突后再推送：

```bash
git push -u origin main
```

## 5. 打包插件给 Blender 安装

推荐保持文件夹名为 `hair_curve_pipe`，因为 Blender 的插件模块名依赖文件夹名；插件在 Blender 里显示为 `FiguHair`。

如需打包安装，可以压缩整个 `hair_curve_pipe` 文件夹为 zip：

```bash
Compress-Archive -Path . -DestinationPath ..\FiguHair.zip -Force
```

然后在 Blender 中使用 `Edit > Preferences > Add-ons > Install...` 选择 `FiguHair.zip`。

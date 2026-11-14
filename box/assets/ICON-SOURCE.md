# AutoPlay 图标来源

CarPlay 主屏上「AutoPlay」图标（接收端把它交给 iPhone，`receiver/server/src/main/resources/autoplay-icon.png`）。

- 创建：2026-11-14，为 1.6.1 新画，车主从四个方向里选定（`docs/UI-1.6.0.md` §五）。
- 内容：一块竖的、一块横的半透明圆角面板叠在一起，是手机上的 CarPlay 放到车的屏幕上，也就是 AutoPlay 做的事。浅色底，青绿和蓝紫两块面板，叠处变深，顶部各有一层高光，下面一层柔和阴影。
- 原创：只用矩形、圆角、渐变和阴影；没有外部图片、字体、商标或第三方图标。刻意避开苹果的 CarPlay 标志（不用「播放」三角）和苹果硬件的样子（面板只是圆角矩形，没有设备的细节），也避开蓝底白「A」（像 App Store 的图标）。
- 许可：与本项目一起按 GPL-3.0 分发；`autoplay-icon.svg` 是可编辑的源文件。
- 产物：`assets/autoplay-icon.png` 和接收端资源 `autoplay-icon.png`，180 × 180、RGB PNG，满幅、不带圆角（iOS 自己裁圆角）。
- 复现：`python3 box/scripts/render-autoplay-icon.py`。由 Chromium（Python 的 playwright）按 1024 × 1024 画 SVG，再用 Pillow（Lanczos）缩到 180。PNG 的字节可能随 Chromium、Pillow、zlib 的版本变化。
- 之前（DashPlay 带来，到 1.6.0）：`scripts/generate-box-settings-icon.py` 画的青绿底、圆角框里两根滑杆，资源名 `f50-settings.png`；1.6.1 起删除，见 git 历史。
- 验证：在浏览器里按 CarPlay 主屏的大小看过圆角方形、圆形裁切和深浅两种背景；尚未在车机上看过。

# jphs-py

`jphs`（Hide & Seek 0.3，作者 Allan Latham）的纯 Python 移植。它把任意文件藏进
JPEG 的量化 DCT 系数中，并且只能用原始口令从隐写后的图片中取回：

- `jphide`：把文件嵌入一张 JPEG，写出新的 JPEG。
- `jpseek`：从隐写 JPEG 中恢复文件。

实现不依赖 libjpeg/Pillow：JPEG 解析、Huffman 与算术编码解码、Blowfish、
载体遍历和 libjpeg 8a 风格的转码输出全部用 Python 完成。输出与上游 C 版本
逐字节一致，并已通过双向交叉验证。

## 安装

```bash
pip install .
```

安装后得到与上游同名的两个命令：

```bash
jphide input.jpg output.jpg secret.bin
jpseek output.jpg recovered.bin
```

也可以不安装直接运行：

```bash
PYTHONPATH=src python -m jphs jphide input.jpg output.jpg secret.bin
PYTHONPATH=src python -m jphs jpseek output.jpg recovered.bin
```

交互提示、错误信息、退出码与上游一致：`Passphrase: `、`Re-enter  : `、
`Nothing done`、`Truncated to 120 characters`、
`Passphrases are different - try again`、`File not completely stored`、
`File not completely recovered`、`Unsuitable input jpeg file: No of components = N`。

## 库接口

```python
from pathlib import Path
from jphs.jpeg import parse_jpeg
from jphs.stego import hide, seek

cover = parse_jpeg(Path("cover.jpg").read_bytes())
stego = hide(cover, Path("secret.bin").read_bytes(), b"passphrase")
Path("stego.jpg").write_bytes(stego)

payload = seek(parse_jpeg(stego), b"passphrase")
```

异常：`NotEnoughSpaceError`（载体容量不足）、`RecoveryError`（遍历结束仍未
取完）、`StegoError`（其它错误，含分量数不为 3）。

## 兼容性与实现说明

- **输入**：支持 baseline/扩展顺序 Huffman（SOF0/SOF1）、渐进 Huffman
  （SOF2）、顺序/渐进算术编码（SOF9/SOF10），任意采样因子与重启间隔。
- **输出**：与上游一样总是写单扫描顺序 Huffman JPEG（`optimize_coding`、
  优化的 Huffman 表、边缘补块），因此输入为渐进或算术编码时输出仍是 SOF0/SOF1。
- **口令**：最长 120 字节，超长时截断（与上游一致）；空口令直接退出，
  不生成有效输出。
- **图像**：必须为 3 分量 JPEG；灰度等图像按上游原文报错。
- **已知上游限制**：极小的图片连 8 字节头部都无法承载时，`jphide` 仍会输出
  图片，但 `jpseek` 无法恢复。Python 版本的行为与上游逐字节一致。
- **有意修正**：上游 `jpseek` 用 `open(..., O_CREAT)` 时漏传 mode，生成文件的
  权限是随机的（常见为不可读写）。本移植创建普通可读文件。

## 交叉验证

上游 C 源码不纳入版本库：`upstream/` 缺失时构建脚本会自动
`git clone https://github.com/h3xx/jphs.git` 拉取。参考二进制需要 Linux/WSL + gcc：

```bash
bash tools/build_upstream_wsl.sh       # 构建 .reference/ 下的 C 参考程序
bash tools/gen_cover_refs.sh           # 生成系数 dump 与参考转码
python3 tools/xcheck_codec.py testdata/cover_420.jpg   # 编解码逐字节对比
PYTHONPATH=src python3 tools/xcheck_stego.py           # 隐写双向对比矩阵
bash tools/smoke_cli.sh                                # CLI 行为对比
```

`tools/build_upstream_wsl.sh` 还会构建带算术编码支持的 IJG `jpegtran`，
`tools/gen_arith_covers.sh` 用它生成 SOF9/SOF10 测试图片；
`tools/gen_restart_covers.sh` 生成带重启间隔（DRI）的四种编码变体。

验证范围（当前 testdata）：

- 24 张 cover：4:2:0 / 4:2:2 / 4:4:4、baseline / 渐进 / 算术编码、奇数尺寸、
  大图、灰度图，以及 Huffman/算术 × 顺序/渐进的重启间隔变体；每张都与 IJG
  参考程序的系数 dump 和转码输出逐字节一致。
- 隐写矩阵 300 个用例：覆盖 × 载荷（0/16/256/1024/4000/12000 字节）× 口令
  （含 120 字节），要求 Python 与 C 的隐藏输出逐字节相同，且 C/Python 都能
  从对方输出中恢复原始载荷（24 个用例属于上述上游“过小载体”限制，双方均
  无法恢复）。
- CLI 对照：正常隐藏/恢复、空口令、二次输入不一致、超长口令截断、参数错误、
  文件缺失、容量不足、灰度图、不可恢复图片，以及输出文本。

## 测试

```bash
python -m unittest discover -s tests -v
```

`tests/test_codec.py` 使用 `testdata/*.ref.dump` 与 `*.ref.trans.jpg`，
需要先运行 `tools/gen_cover_refs.sh`。

## 许可

上游 `jphs` 以 GNU GPL 发布；本移植沿用 GPL-2.0-or-later。

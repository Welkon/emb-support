# 没有信号源时：用 HDL 仿真造波形

分析仪只负责"采"，波形可以来自任何仿真器。本技能提供 `sim` 命令把 VCD 转成
采集目录，之后用同样的 `decode` 解码。

## 1. 装 Icarus Verilog（Icarus / 3.7k ⭐，免 sudo）

```bash
cd /tmp && mkdir -p iv && cd iv
apt-get -o Acquire::http::Proxy=http://127.0.0.1:7890 \
        -o Acquire::https::Proxy=http://127.0.0.1:7890 download iverilog
dpkg-deb -x iverilog_*.deb root
export PATH=/tmp/iv/root/usr/bin:$PATH
IVL=/tmp/iv/root/usr/lib/x86_64-linux-gnu/ivl
```

## 2. 生成波形

技能自带一个最小 I²C 主机激励 `sim/i2c_tb.v`（写 `0x50` 寄存器 `0x00`、数据 `0x53`）：

```bash
iverilog -B $IVL -o i2c.vvp sim/i2c_tb.v
vvp -M $IVL i2c.vvp          # 产出 /tmp/iv/i2c.vcd
```

## 3. 转成采集目录并解码

```bash
atkla.py sim --vcd /tmp/iv/i2c.vcd --scl scl --sda sda_line --rate 10m --out /tmp/sim_i2c
atkla.py decode /tmp/sim_i2c --protocol i2c --ch scl=0 --ch sda=1 --row packets
# 0.1000 ms  packets  0x50 WR: 00 53
```

## 4. 可用的其他仿真器

任何能导出 VCD 的工具都行：Verilator（4.1k ⭐）、Renode（3.2k ⭐）、Wokwi、
Icarus。只要有 VCD，`sim` 不需要改动。

## 边界

- 合成波形能验证解码器加载、通道映射、`--option`/`--ch` 传参、堆叠解码、CSV 导出；
- 它无法验证真实电平、毛刺、时钟拉伸和触发行为——那些只能在真机上做。

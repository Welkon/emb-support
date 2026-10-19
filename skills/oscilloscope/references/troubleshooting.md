# 排错

## 连不上（LAN）

1. `ping <ip>`；确认和电脑在同一网段。
2. 端口：多数仪器用 **5025**（Rigol/Siglent/Keysight/R&S）。VXI-11 用 111 端口做端口映射。
3. 仪器侧要开启“远程/SCPI/LAN”选项（不同品牌菜单名不同）。
4. 防火墙/路由器隔离：先用同网段有线连接排除 AP 隔离。
5. 试裸连接：

```bash
scripts/scope.py scpi --host <ip> "*IDN?" --query
scripts/scope.py doctor --host <ip>
```

6. Keysight 部分型号 socket 端口不是 5025；查手册或用 `list` 的 VXI-11 资源。

## 连不上（USB）

```bash
lsusb | grep -iE "0699|1ab1|f4ec|0957|05ff|0aad"    # Tek/Rigol/Siglent/Keysight/LeCroy/R&S
ls /dev/usbtmc*
```

- 没有 `/dev/usbtmc*`：`sudo modprobe usbtmc`，或确认仪器是 USBTMC 类设备。
- 有设备但没权限：`scripts/install_udev.sh`，然后拔插。
- WSL：必须在 Windows 侧 `usbipd attach --wsl --busid X-Y`。
- Windows：需要 VISA runtime（TekVISA / NI-VISA）或 libusb 驱动；见 `tektronix.md` 的位数问题。
- 资源字符串格式：`USB0::0x0699::0x0368::<serial>::INSTR`。序列号不对会找不到设备。

## 超时

- 默认 5s；深存储传输可能更久：`--timeout 30`。
- 查询前确保仪器完成了上一次操作：必要时先发 `*OPC?`。
- 大点数采集先降 `--points`，确认链路稳定后再加。

## 二进制块被截断/解析错

- SCPI 二进制块格式：`#<n><length><payload>`；`#0` 表示无长度、读到终止符。
- 如果返回以 `#` 开头但长度对不上，先确认仪器实际返回的是块还是文本（`--json` 看 bytes）。
- 某些仪器在块后追加 `\n`，本 skill 的解析器会按长度截取，不受影响。
- ASCII 模式（Tek）没有块头，直接是逗号/空白分隔的数字。

## 测量不支持

`measure` 先尝试仪器的 `:MEASure:*?`；不支持或报错时自动回退到波形计算
（Vpp/Vmin/Vmax/mean/RMS/freq/period/duty/rise/fall）。如果仪器不支持深存储，
先 `capture --points` 限制长度。

## 截图不支持

`shot` 只接受 PNG/JPEG magic。失败原因通常是：

- 型号没有屏幕下载命令（TBS1102B 常见）；
- 需要先 `:HARDcopy:SETUP`；
- 固件返回 BMP（可先用 `scpi` 取回原始块再自行转换）。

## 触发一直不命中

- 触发电平不在信号范围内；
- 时基太慢导致波形被压缩；
- 触发源通道被关闭/隐藏；
- 扫描模式是 AUTO（会自动触发）而不是 NORMAL/SINGLE；
- 探头衰减设置与探头实际档位不一致。

`monitor` 不命中时先 `--dry-run` 检查写入的命令，再用 `scpi` 读回
`:TRIGger:STATe?`、`:TRIGger:EDGE:LEVel?` 核对。

## Windows 特有问题

- `VI_ERROR_INV_OBJECT`：Python 与 VISA DLL 位数不匹配，见 `tektronix.md`。
- `--backend @py` 找不到 USB 设备：pyvisa-py 需要 libusb 驱动；换厂商 VISA 或装 libusb。
- 串口（ASRL）资源在某些 USB 转串口芯片上需要额外驱动。

## 安全

- 高压/浮地测量先确认差分探头与隔离；
- 不要用普通无源探头测市电；
- 修改触发/时基/通道前记录原值，结束后恢复。

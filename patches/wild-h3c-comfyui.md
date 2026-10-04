# wild-h3c-comfyui 补丁说明

上游：https://github.com/skaiy/wild-h3c-comfyui

本仓库**不包含**该节点的代码，`deploy.sh` 会 clone 上游后打上下面这一行补丁。

---

## 补丁内容

**文件**：`nodes.py`
**位置**：`io.Boolean.Input("ssd_streaming", ...)` 的默认值

~~~diff
- io.Boolean.Input("ssd_streaming", default=False, advanced=True,
+ io.Boolean.Input("ssd_streaming", default=True, advanced=True,
~~~

---

## 为什么必须改

MiniMax H3 的 DiT 全驻留需要 **37–45 GiB**，而 M1 Max 32GB 的
**Metal 单缓冲上限只有 18.7 GiB**（`recommended GPU set 25.0 GiB`）。

不加 `--ssd-streaming` 时，h3.c 会把权重一次性映射进显存 → **必然失败**。

上游默认 `False` 适用于 64GB+ 的机器。32GB 机器上如果忘了手动勾选，
每次都会白等几分钟然后报内存错误，体验很差 —— 所以在本方案里改成默认开启。

---

## 幂等处理

`deploy.sh` 打补丁前先 grep 检查：

~~~bash
if grep -q 'ssd_streaming", default=False' "$nf"; then
  sed -i '' 's/ssd_streaming", default=False/ssd_streaming", default=True/' "$nf"
fi
~~~

所以重复执行 `deploy.sh` 不会重复改，上游若改了默认值也不会冲突。

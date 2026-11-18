# system_run_lisp 返回值不可靠：表达式出错时返回上一次的结果

> 记录日期：2026-11-18
> 环境：AutoCAD 2026 `25.1s (LMS Tech)`、autocad-mcp-pro 1.8.0（上游 HEAD `9654e01`）
> 相关文档：[`AGENTS.md`](../AGENTS.md) · [`20261117-autocad-troubleshooting.md`](20261117-autocad-troubleshooting.md)

---

## 1. 现象

用 `system_run_lisp` 执行写操作或取值，`result` 有时返回的是**上一次调用**的结果，而不是本次的。表现为「返回值滞后一条」。

原文举例（当时误判为"稳定滞后"）：

```text
调用 A: (progn ... (vla-put-Height e 350.0) (vla-get-Height e))  → OK
调用 B: (progn ... 复杂的 vla-get-* ...)                          → 返回 A 的结果
```

看起来像异步竞态或缓存未刷新。

---

## 2. 根因

**不是竞态。`USERS1` 是一个跨调用持久存在的有状态变量，表达式出错时 `setvar` 根本没执行，读到的就是上一次的残留值。**

源码（`backends/com_backend.py:10322`，v1.8.0）：

```python
wrapped = f'(vl-load-com)(setvar "USERS1" (vl-princ-to-string (progn {expression})))'
self._safe_send_command(doc, wrapped)
try:
    result = doc.GetVariable("USERS1")     # 直接读，无任何成败判定
except Exception as exc:                    # optional read: the expression already ran
    log.debug("doc.GetVariable(USERS1) failed, reporting nil: %s", exc)
    result = None
return {"ok": True, "expression": expression, "result": str(result) or "nil"}
```

执行路径：

| 情况 | `setvar` 是否执行 | `USERS1` 内容 | 返回 |
|---|---|---|---|
| 表达式成功 | ✅ | 本次结果 | 正确 |
| **表达式抛错** | ❌ **未执行** | **上次成功的残留值** | **错误：返回旧值** |

AutoLISP 在 `progn` 中途出错会中止整个表达式，最外层的 `setvar` 不会运行。随后 `GetVariable("USERS1")` 读到的是上一次成功调用的残留。

`_safe_send_command` 只轮询 `CMDACTIVE` 判断命令是否结束。纯 LISP 表达式出错时 AutoCAD 立刻回到命令提示，`CMDACTIVE` 归 0，被视为「成功完成」，于是照常读 `USERS1`。

源码注释暴露了这个盲点：

```python
except Exception as exc:  # optional read: the expression already ran
```

只考虑了「读取失败」，没考虑「表达式根本没跑成功」。

---

## 3. 实验证据（三步闭环）

| 步骤 | 发送的表达式 | 实际返回 | 判定 |
|---|---|---|---|
| 1 | `"SENTINEL-A"` | `SENTINEL-A` | 正常写入 USERS1 |
| 2 | `(progn (car nil) (vla-get-Rows (vlax-ename->vla-object (handent "ZZZZZ"))) "MUST-NOT-APPEAR")` | **`SENTINEL-A`** | ❌ 本次应报错，却返回残留 |
| 3 | `(progn (setvar "USERS1" "INNER-WROTE-THIS") (vla-get-Rows ...) "NEVER")` | **`INNER-WROTE-THIS`** | ✅ 证明读取的就是 USERS1 通道 |

**第 3 步是决定性证据**：表达式内部自己写 `USERS1`，返回值立刻变成那个值。

### 反证：成功路径是对的

连续三次不同的成功表达式，返回值都正确：

```text
"AAA-111"                        → AAA-111
(strcat "B" (itoa (+ 2000 22)))  → B2022
(strcat "C" (itoa (* 333 3)))    → C999
```

**所以「稳定滞后一条」这个描述是错的**：并非每次都滞后，只在**表达式抛错**时返回旧值；成功时始终正确。这一点最初判断有误。

---

## 4. 处理

### 4.1 上游源码修复

改为 `vl-catch-all-apply` 捕获错误，并用唯一哨兵区分「没执行」：

```python
_NONCE = f"!PENDING:{token_hex(8)}"
wrapped = (
    f'(vl-load-com)'
    f'(setvar "USERS1" "{_NONCE}")'
    f'(setq *mcp-r* (vl-catch-all-apply (quote (lambda () (progn {expression})))))'
    f'(if (vl-catch-all-error-p *mcp-r*)'
    f'  (setvar "USERS1" (strcat "!ERR:" (vl-catch-all-error-message *mcp-r*)))'
    f'  (setvar "USERS1" (strcat "!OK:" (vl-princ-to-string *mcp-r*))))'
)
```

读完 `USERS1` 后：

| 读到 | 含义 | 返回 |
|---|---|---|
| `!OK:<值>` | 成功 | `ok: True, result: <值>` |
| `!ERR:<消息>` | 表达式抛错 | `ok: False, kind: lisp_runtime_error` |
| 仍是 `!PENDING:...` | 表达式连哨兵都没执行到 | `ok: False, kind: lisp_not_executed` |

### 4.2 实操对策（在修复生效前）

1. **LISP 的 `result` 只在表达式成功时可信**，不能作为唯一验证依据。
2. **用唯一标记自证**：表达式里先写标记再返回，比对标记是否出现。

   ```lisp
   (progn (setvar "USERS1" "PROBE-7f3a") (setq v ...) (list "PROBE-7f3a" v))
   ```

   返回值里没有 `PROBE-7f3a`，说明没执行到，结果不可采信。

3. **几何验证优先用不依赖 LISP 通道的工具**：ezdxf 直接读 DXF、`drawing_info`、`entity_list`、`drawing_verify_requirements`。

---

## 5. 预防

1. 任何「用 LISP 做验证」的结论，都必须确认表达式**确实执行过**（哨兵或自证标记）。
2. 看到 `result` 与预期完全不符、却与上一条调用结果相同时，第一反应应是「表达式出错读到了残留」，而不是「工具延迟」。
3. 复杂 COM 表达式（`vla-*` 链、`handent` 取不存在句柄）最容易触发，因为它们抛错概率高。
4. 写操作（`vla-put-*`）如果抛错，会让后续所有读取都拿到旧的 `USERS1`，故障会「传染」到下一次调用。

---

*2026-11-18 记录。核心更正：不是「返回值稳定滞后一条」，而是「表达式出错时返回上次残留」。已向上游提交 PR 修复。*

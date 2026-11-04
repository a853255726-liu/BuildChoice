# 核对后保存 · 本地行为示例

本目录用于演示和自动化测试核对后保存的业务行为。日常使用 BuildChoice 时，在 Codex 对话中提出开发需求即可。

模拟识别出金额、日期和类别后进入核对页面，用户可以修改、确认保存或取消。正式账本使用 localStorage。`receipt.json` 是合成数据，示例不调用相机/OCR，也不是已部署的小程序。

`manifest.json` 声明实现、测试、输入 fixture、配置和 Python 测试依赖。`tests/test_receipt.py` 使用真实浏览器点击、填写、读取 DOM 和账本；四个条件及用例 ID 在 checks/verification_helpers.py 的 criteria() 中提供，由测试辅助代码推导并绑定模拟 Hook 确认。

在仓库根目录安装核心及开发依赖，指定本机 Chrome/Edge 执行文件，然后运行：

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
$env:BUILDCHOICE_TEST_BROWSER = "C:\Program Files\Google\Chrome\Application\chrome.exe"
python checks/run_receipt_demo.py --out receipt-results.json
```

该脚本创建隔离临时工作区，执行正确实现、提前入账、忽略修改三个版本；分别应得到 passed、failed、failed。各版本都有真实用例执行记录，未使用用户浏览器配置。可用 BUILDCHOICE_CHECK_ROOT 指定临时记录父目录。负面配置只为证明测试能识别错误行为，不作为产品功能。

该示例用于测试专用采集器与验证接口。日常开发的测试和验收由 Codex 执行；接口范围见 [MCP 接口](../../docs/API.md#可选验收与验证)。

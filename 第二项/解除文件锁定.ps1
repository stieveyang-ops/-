# 一键解除文件锁定（PowerShell 版）
#
# 作用：移除本目录（含子目录）内所有文件的 Windows“网络来源”标记（Mark of the Web），
#       从而消除双击 .cmd/.bat/.ps1 时出现的“打开文件 - 安全警告：无法验证发布者”。
#
# 用法（在交付包根目录）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\解除文件锁定.ps1
#
# 说明：仅删除 Zone.Identifier 备用数据流，不修改文件内容，不改变任何 SHA256 校验结果。

$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Write-Host "正在解除锁定：" -ForegroundColor Cyan
Write-Host "  目录：$root"

$count = 0
Get-ChildItem -LiteralPath $root -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
    $zone = Get-Item -LiteralPath $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
    if ($zone) {
        Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue
        $count++
    }
}
Write-Host "  已解锁文件数：$count" -ForegroundColor Green
Write-Host "完成。若仍有单个文件被系统标记，可右键该文件 → 属性 → 勾选“解除锁定” → 确定。"

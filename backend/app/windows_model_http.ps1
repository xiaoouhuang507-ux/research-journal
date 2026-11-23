# Use the Windows HTTPS stack when the bundled Python/OpenSSL cannot negotiate
# with the provider. Credentials and research content arrive only through stdin.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    $requestData = [Console]::In.ReadToEnd() | ConvertFrom-Json
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $requestHeaders = @{ Authorization = 'Bearer ' + $requestData.key }
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes([string]$requestData.body)
    $modelResponse = Invoke-WebRequest -Uri $requestData.url -Method Post -Headers $requestHeaders -ContentType 'application/json; charset=utf-8' -Body $bodyBytes -UseBasicParsing -TimeoutSec 35
    # Windows PowerShell 5.1 decodes JSON without a charset as Latin-1.
    # Model APIs return UTF-8 JSON; read the original bytes instead of Content,
    # which has already been decoded and can silently corrupt Chinese replies.
    # Reject invalid UTF-8 rather than persisting replacement characters.
    $responseEncoding = [System.Text.UTF8Encoding]::new($false, $true)
    $responseBody = $responseEncoding.GetString($modelResponse.RawContentStream.ToArray()).TrimStart([char]0xFEFF)
    $resultData = @{ status = [int]$modelResponse.StatusCode; body = $responseBody }
} catch {
    $responseStatus = 0
    if ($_.Exception.Response) { $responseStatus = [int]$_.Exception.Response.StatusCode }
    $resultData = @{ status = $responseStatus; body = '' }
}
[Console]::Out.Write(($resultData | ConvertTo-Json -Compress -Depth 5))

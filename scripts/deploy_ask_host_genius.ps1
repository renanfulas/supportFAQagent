$ErrorActionPreference = "Stop"

# Wrapper local: copia e executa o deploy do frontend ask-host-genius no VPS.
# Por padrao faz deploy da branch main (producao). Para outra branch:
#   ./deploy_ask_host_genius.ps1 -DeployBranch alguma-branch
param(
  [string]$RemoteHost = "143.95.215.128",
  [string]$RemotePort = "22022",
  [string]$RemoteUser = "root",
  [string]$DeployBranch = "main"
)

$localRemoteScript = Join-Path $PSScriptRoot "deploy_ask_host_genius.remote.sh"
if (-not (Test-Path $localRemoteScript)) {
  throw "Script remoto nao encontrado: $localRemoteScript"
}

Write-Host "Deploy do ask-host-genius -> branch '$DeployBranch' em ${RemoteUser}@${RemoteHost}:${RemotePort}"
Write-Host "Quando pedir senha, use a senha root informada pelo time."
Write-Host "Nao cole o conteudo do .remote.sh no PowerShell local; este wrapper envia e executa remotamente."
Write-Host ""

scp -P $RemotePort -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL $localRemoteScript "${RemoteUser}@${RemoteHost}:/tmp/deploy-ask-host-genius.sh"
if ($LASTEXITCODE -ne 0) {
  throw "Falha ao copiar o script para a VPS via scp."
}

ssh -tt -p $RemotePort -o StrictHostKeyChecking=no -o UserKnownHostsFile=NUL "${RemoteUser}@${RemoteHost}" "DEPLOY_BRANCH='$DeployBranch' bash /tmp/deploy-ask-host-genius.sh; rm -f /tmp/deploy-ask-host-genius.sh"
if ($LASTEXITCODE -ne 0) {
  throw "Falha ao executar o script remoto via ssh."
}

Write-Host ""
Write-Host "Deploy OK somente se o bloco 'depois' retornou HTTP 200 e o Last-Modified dos assets passou a ser de hoje."
